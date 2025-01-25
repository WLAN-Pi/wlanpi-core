import asyncio
import base64
import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple, Union

from authlib.jose import jwt
from fastapi import HTTPException
from sqlalchemy import Integer, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from wlanpi_core.core.cache import SKeyCache, TokenCache
from wlanpi_core.core.config import settings
from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.models import SigningKey, Token
from wlanpi_core.core.repositories import TokenRepository
from wlanpi_core.services import system_service

log = get_logger(__name__)


class TokenError(Exception):
    pass


class SKeyError(Exception):
    pass


class JWTError(Exception):
    pass


@dataclass
class TokenValidationResult:
    """Result of token validation containing validation status and metadata"""

    is_valid: bool
    payload: Optional[dict] = None
    error: Optional[str] = None
    token: Optional[str] = None
    device_id: Optional[str] = None
    key_id: Optional[int] = None

    def __post_init__(self) -> None:
        """Validate required fields based on validation status"""
        if self.is_valid:
            if not self.token:
                raise ValueError("Valid tokens must have a token value")
            if not self.payload:
                raise ValueError("Valid tokens must have a payload")
            if "did" in self.payload and not self.device_id:
                self.device_id = self.payload["did"]
            if "kid" in self.payload and not self.key_id:
                self.key_id = int(self.payload["kid"])
        else:
            if not self.error:
                raise ValueError("Invalid tokens must have an error message")

    @property
    def exp(self) -> Optional[datetime]:
        """Get expiration time if payload exists"""
        if not self.payload or "exp" not in self.payload:
            return None
        try:
            return datetime.fromtimestamp(self.payload["exp"], tz=timezone.utc)
        except (TypeError, ValueError):
            return None

    @property
    def iat(self) -> Optional[datetime]:
        """Get issued-at time if payload exists"""
        if not self.payload or "iat" not in self.payload:
            return None
        try:
            return datetime.fromtimestamp(self.payload["iat"], tz=timezone.utc)
        except (TypeError, ValueError):
            return None

    @property
    def is_expired(self) -> bool:
        """Check if token is expired"""
        if not self.exp:
            return True
        return self.exp <= datetime.now(timezone.utc)

    def __str__(self) -> str:
        """Human readable representation"""
        if self.is_valid:
            return f"Valid token for device {self.device_id} (expires {self.exp})"
        return f"Invalid token: {self.error}"

    def to_dict(self) -> dict:
        """Convert to dictionary for API responses"""
        return {
            "valid": self.is_valid,
            "error": self.error if not self.is_valid else None,
            "device_id": self.device_id,
            "expires_at": self.exp.isoformat() if self.exp else None,
            "issued_at": self.iat.isoformat() if self.iat else None,
        }


class TokenManager:
    def __init__(self, app_state):
        """
        Initialize TokenManager with application state

        Args:
            app_state: Application state containing database manager
        """
        self.app_state = app_state
        self.token_cache = TokenCache()
        self.skey_cache = SKeyCache()

    def _normalize_token(self, token: Union[str, bytes]) -> str:
        """Normalize and validate JWT token format"""
        # Basic normalization
        if isinstance(token, bytes):
            token = token.decode("utf-8")
        token = token.strip("b'\"")

        # Split and validate parts
        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError(f"Invalid JWT format - expected 3 parts, got {len(parts)}")

        # Pad each part
        padded_parts = []
        for part in parts:
            try:
                unpadded = part.rstrip("=")
                padding_needed = (4 - len(unpadded) % 4) % 4
                padded = unpadded + ("=" * padding_needed)
                padded_parts.append(padded)
            except Exception:
                log.exception("Base64 padding error")
                raise JWTError("Base64 padding error")

        ".".join(padded_parts)

        # Validate header
        try:
            header_b64 = padded_parts[0]
            std_b64 = header_b64.replace("-", "+").replace("_", "/")
            header_json = base64.b64decode(std_b64).decode("utf-8")
            header = json.loads(header_json)

            if not header.get("alg") or not header.get("typ", "JWT").upper() == "JWT":
                raise JWTError("Invalid token header")
        except Exception:
            raise JWTError("Header validation failed")

        return token

    async def _get_or_create_signing_key(self, session: AsyncSession) -> SigningKey:
        """
        Retrieve an existing active signing key or create a new one

        Args:
            session: Database session

        Returns:
            Active SigningKey instance
        """
        # 1. check cache
        active_key = self.skey_cache.active_key
        if active_key:
            log.debug(
                "Got active signing key from cache", extra={"key_id": active_key.id}
            )
            return active_key

        # 2. check database
        query = select(SigningKey).where(SigningKey.active == True)
        result = await session.execute(query)
        skey = result.scalar_one_or_none()

        if skey:
            self.skey_cache.cache_key(skey)
            log.debug("Got active signing key from database", extra={"key_id": skey.id})
            return skey

        # 3. not in cache? not in database?
        # Tasks:
        #  - Make sure old keys are not active
        #  - Create new key
        #  - Invalidate cache
        #  - Invalidate tokens with old keys

        deactivate_keys = (
            update(SigningKey).where(SigningKey.active == True).values(active=False)
        )
        await session.execute(deactivate_keys)

        new_key = SigningKey(
            key=base64.b64encode(secrets.token_bytes(32)).decode("utf-8"), active=True
        )
        session.add(new_key)
        await session.flush()

        revoke_tokens = (
            update(Token)
            .where(
                Token.key_id != new_key.id,
                Token.revoked == False,
                Token.expires_at > datetime.now(timezone.utc),
            )
            .values(revoked=True)
        )
        await session.execute(revoke_tokens)
        await session.commit()

        self.skey_cache.clear()
        self.token_cache.clear()

        # add key to cache
        self.skey_cache.cache_key(new_key)

        log.debug(
            "Created new signing key",
            extra={
                "component": "auth",
                "action": "create_signing_key",
                "key_id": new_key.id,
            },
        )

        return new_key

    async def create_token(
        self, device_id: str, expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create a new JWT token for a specific device

        Args:
            device_id: Device identifier
            expires_delta: Optional custom token expiration

        Returns:
            JWT token string
        """
        async with self.app_state.db_manager.session() as session:
            try:
                signing_key = await self._get_or_create_signing_key(session)

                now = datetime.now(timezone.utc)
                expires = now + (
                    expires_delta or timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
                )

                claims = {
                    "sub": system_service.get_hostname(),
                    "iss": "wlanpi-core",
                    "did": device_id,
                    "exp": int(expires.timestamp()),
                    "iat": int(now.timestamp()),
                    "kid": str(signing_key.id),
                }

                jwt_token = jwt.encode(
                    header={"alg": "HS256", "kid": str(signing_key.id)},
                    payload=claims,
                    key=signing_key.key,
                ).decode("utf-8")

                token_model = Token(
                    token=jwt_token,
                    device_id=device_id,
                    key_id=signing_key.id,
                    expires_at=expires,
                )
                session.add(token_model)
                await session.commit()

                log.debug(token_model)
                log.debug(vars(token_model))

                self.token_cache.cache_token(jwt_token, claims)

                return jwt_token

            except Exception as e:
                await session.rollback()
                log.exception(
                    "Token creation failed",
                    extra={
                        "component": "auth",
                        "action": "create_token_error",
                        "device_id": device_id,
                        "error": str(e),
                    },
                )
                raise HTTPException(status_code=500, detail=str(e))

    async def verify_token(self, token: str) -> TokenValidationResult:
        """Verify JWT token and return validation result"""
        try:
            masked_token = (
                token[:20] + "..." + token[-20:] if len(token) > 40 else token
            )
            log.debug("Verifying token: %s", masked_token)

            try:
                normalized_token = self._normalize_token(token)
            except JWTError as e:
                log.exception("Token validation failed during normalization/validation")
                return TokenValidationResult(is_valid=False, error=str(e))

            cached = self.token_cache.get_cached_token(normalized_token)
            if cached:
                log.debug("Token found in cache")
                if not self.token_cache._is_token_expired(cached):
                    return TokenValidationResult(
                        is_valid=True, payload=cached, token=normalized_token
                    )

            log.debug(
                "Cache miss - reading from database",
                extra={
                    "component": "auth",
                    "action": "db_read",
                    "operation": "token_verification",
                },
            )

            async with self.app_state.db_manager.session() as session:
                token_query = (
                    select(Token)
                    .options(selectinload(Token.signing_key))
                    .where(Token.token == normalized_token)
                )
                result = await session.execute(token_query)
                token_model = result.scalar_one_or_none()

                if not token_model:
                    return TokenValidationResult(
                        is_valid=False, error="Token not found"
                    )

                if token_model.revoked:
                    log.debug(f"Token is revoked for device {token_model.device_id}")
                    return TokenValidationResult(is_valid=False, error="Token revoked")

                signing_key = self.skey_cache.get_key(token_model.key_id)
                if not signing_key:
                    skey_query = select(SigningKey).where(
                        SigningKey.id == token_model.key_id
                    )
                    result = await session.execute(skey_query)
                    signing_key = result.scalar_one_or_none()
                    if signing_key:
                        self.skey_cache.cache_key(signing_key)
                    else:
                        return TokenValidationResult(
                            is_valid=False, error="Invalid signing key"
                        )

                try:
                    payload = jwt.decode(token, signing_key.key)
                    payload.validate()

                    self.token_cache.cache_token(token, payload)
                    return TokenValidationResult(
                        is_valid=True,
                        payload=payload,
                        token=token,
                        device_id=token_model.device_id,
                        key_id=token_model.key_id,
                    )
                except (TokenError, JWTError) as e:
                    log.exception("Token validation failed")
                    return TokenValidationResult(is_valid=False, error=str(e))

        except Exception as e:
            log.exception("Unexpected error during token verification")
            return TokenValidationResult(
                is_valid=False, error=f"Validation failed: {str(e)}"
            )

    async def revoke_token(self, token: str) -> Dict[str, Any]:
        """
        Revoke a specific token

        Args:
            token: JWT token string

        Returns:
            Revocation status dictionary
        """
        token = self._normalize_token(token)

        async with self.app_state.db_manager.session() as session:
            try:
                # Create token repository
                token_repo = TokenRepository(session)
                token_model = await token_repo.get_token_by_value(token)

                if not token_model:
                    return {"status": "warning", "message": "Token not found"}

                if token_model.revoked:
                    return {
                        "status": "info",
                        "message": "Token already revoked",
                        "device_id": token_model.device_id,
                    }

                token_model.revoked = True
                await session.flush()

                return {
                    "status": "success",
                    "message": "Token revoked",
                    "device_id": token_model.device_id,
                }

            except Exception as e:
                log.exception(
                    "Token revocation failed",
                    extra={
                        "component": "auth",
                        "action": "token_revocation_error",
                        "error": str(e),
                    },
                )
                raise

    async def purge_expired_tokens(self) -> None:
        """
        Background task to purge expired tokens
        """
        while True:
            try:
                async with self.app_state.db_manager.session() as session:
                    deleted_count = await TokenRepository(
                        session
                    ).purge_expired_tokens()

                    if deleted_count > 0:
                        log.debug(
                            f"Purged {deleted_count} expired tokens",
                            extra={"component": "auth", "action": "token_purge"},
                        )

            except Exception as e:
                log.exception(
                    "Failed to purge tokens",
                    extra={
                        "component": "auth",
                        "action": "token_purge_error",
                        "error": str(e),
                    },
                )
            finally:
                await asyncio.sleep(3600)

    async def rotate_key(self) -> Tuple[int, str]:
        """
        Rotate signing keys:
        1. Create a new active key
        2. Deactivate all previous keys
        3. Revoke tokens associated with old keys

        Returns:
            Tuple of (new key ID, base64 encoded key)
        """
        async with self.app_state.db_manager.session() as session:
            try:
                await session.begin()

                # deactivate active keys
                deactivate_keys = (
                    update(SigningKey)
                    .where(SigningKey.active == True)
                    .values(active=False)
                )
                await session.execute(deactivate_keys)

                # create new key
                new_key = SigningKey(
                    key=base64.b64encode(secrets.token_bytes(32)).decode("utf-8"),
                    active=True,
                )

                session.add(new_key)
                await session.flush()

                # revoke tokens using old keys
                revoke_tokens = (
                    update(Token)
                    .where(
                        Token.key_id != new_key.id,
                        Token.revoked == False,
                        Token.expires_at > datetime.now(timezone.utc),
                    )
                    .values(revoked=True)
                )
                await session.execute(revoke_tokens)

                await session.commit()

                self.skey_cache.clear()
                self.token_cache.clear()

                # update cache
                self.skey_cache.cache_key(new_key)

                log.debug(
                    "Rotated signing key",
                    extra={
                        "component": "auth",
                        "action": "rotate_key",
                        "new_key_id": new_key.id,
                    },
                )
                return new_key.id, new_key.key
            except Exception as e:
                await session.rollback()
                log.exception(
                    "Failed to rotate signing key",
                    extra={
                        "component": "auth",
                        "action": "key_rotation_error",
                        "error": str(e),
                    },
                )
                raise

    async def get_active_keys(self) -> List[Dict[str, Any]]:
        """
        Retrieve all signing keys with their metadata

        Returns:
            List of dictionaries containing key information
        """
        async with self.app_state.db_manager.session() as session:
            try:
                query = select(SigningKey).order_by(SigningKey.created_at.desc())
                result = await session.execute(query)
                keys = result.scalars().all()

                key_list = []
                for key in keys:
                    token_count = await self._count_tokens_for_key(session, key.id)
                    key_list.append(
                        {
                            "id": key.id,
                            "active": key.active,
                            "created_at": key.created_at.isoformat(),
                            "token_count": token_count,
                        }
                    )

                return key_list

            except Exception as e:
                log.exception(
                    "Failed to retrieve signing keys",
                    extra={
                        "component": "auth",
                        "action": "get_keys_error",
                        "error": str(e),
                    },
                )
                raise

    async def _count_tokens_for_key(self, session: AsyncSession, key_id: int) -> int:
        """
        Count the number of tokens associated with a specific signing key

        Args:
            session: Database session
            key_id: ID of the signing key

        Returns:
            Number of tokens for the key
        """
        query = (
            select(func.count())
            .select_from(Token)
            .where(
                Token.key_id == key_id,
                Token.revoked == False,
                Token.expires_at > datetime.now(timezone.utc),
            )
        )
        result = await session.execute(query)
        return result.scalar_one()

    async def verify_cache_state(self, token: Optional[str] = None) -> Dict[str, Any]:
        """
        Verify the cache state, optionally for a specific token

        Args:
            token: Optional token to check specifically

        Returns:
            dict: Cache state information
        """
        cache_info = {
            "active_key_id": self.skey_cache._active_key_id,
            "cached_keys": list(self.skey_cache._cache.keys()),
        }
        if token:
            token_state = {"in_cache": False}
            try:
                async with self.app_state.db_manager.session() as session:
                    token_repo = TokenRepository(session)
                    if token_model := await token_repo.get_token_by_value(token):
                        signing_key = self.skey_cache.get_key(token_model.key_id)
                        token_state.update(
                            {
                                "in_database": True,
                                "key_in_cache": signing_key is not None,
                                "key_id": token_model.key_id,
                                "revoked": token_model.revoked,
                                "expires_at": token_model.expires_at.isoformat(),
                            }
                        )
                    else:
                        token_state["in_database"] = False
            except Exception as e:
                token_state["error"] = str(e)
            cache_info["token_state"] = token_state
        return cache_info

    async def verify_db_state(self) -> dict:
        """
        Verify the current state of tokens in the database.

        Returns:
            dict: A dictionary containing token statistics and active tokens.
        """
        try:
            async with self.app_state.db_manager.session() as session:
                now = datetime.now(timezone.utc)

                stats_query = select(
                    func.count().label("total"),
                    func.sum(func.cast(Token.revoked, Integer)).label("revoked"),
                    func.sum(func.cast(Token.expires_at < now, Integer)).label(
                        "expired"
                    ),
                    func.min(Token.expires_at).label("earliest_expiry"),
                    func.max(Token.expires_at).label("latest_expiry"),
                )
                stats_result = await session.execute(stats_query)
                stats = stats_result.mappings().one()

                active_tokens_query = (
                    select(
                        Token.device_id,
                        Token.expires_at,
                        Token.revoked,
                    )
                    .where(
                        Token.revoked == False,
                        Token.expires_at > now,
                    )
                    .order_by(Token.expires_at.desc())
                )
                active_tokens_result = await session.execute(active_tokens_query)
                active_tokens = active_tokens_result.mappings().all()

                return {
                    "statistics": {
                        "total_tokens": stats["total"],
                        "revoked_tokens": stats["revoked"] or 0,
                        "expired_tokens": stats["expired"] or 0,
                        "earliest_expiry": (
                            stats["earliest_expiry"].isoformat()
                            if stats["earliest_expiry"]
                            else None
                        ),
                        "latest_expiry": (
                            stats["latest_expiry"].isoformat()
                            if stats["latest_expiry"]
                            else None
                        ),
                    },
                    "active_tokens": [
                        {
                            "device_id": token["device_id"],
                            "expires_at": token["expires_at"].isoformat(),
                            "revoked": token["revoked"],
                        }
                        for token in active_tokens
                    ],
                }

        except Exception as e:
            log.exception(
                "Failed to verify database state",
                extra={
                    "component": "auth",
                    "action": "db_state_verification_error",
                    "error": str(e),
                },
            )
            return {"error": str(e)}
