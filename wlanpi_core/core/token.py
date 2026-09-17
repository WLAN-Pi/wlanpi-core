import base64
import binascii
import json
import math
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from authlib.jose import JoseError, jwt
from sqlalchemy import Integer
from sqlalchemy import exc as sqlalchemy_exc
from sqlalchemy import func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from wlanpi_core.core.config import settings
from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.models import SigningKey, Token
from wlanpi_core.core.repositories import DeviceRepository, TokenRepository
from wlanpi_core.services import system_service

log = get_logger(__name__)

AUTH_CLOCK_NOT_SET = "AUTH_CLOCK_NOT_SET"
CLOCK_SKEW_TOLERANCE_SEC = 30


def current_boot_id() -> str:
    """Kernel boot id; changes on every reboot."""
    boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    if not boot_id:
        raise RuntimeError("Kernel boot ID is empty")
    return boot_id


def current_boottime() -> float:
    """Seconds since boot, including suspend time."""
    return time.clock_gettime(time.CLOCK_BOOTTIME)


def current_wall_time() -> float:
    return datetime.now(timezone.utc).timestamp()


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
        # if not self.exp:
        #     return True
        # return self.exp <= datetime.now(timezone.utc)
        return False

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

    def _normalize_token(self, token: Union[str, bytes]) -> str:
        """Normalize and validate JWT token format"""
        if isinstance(token, bytes):
            try:
                token = token.decode("utf-8")
            except UnicodeDecodeError as exc:
                raise JWTError("Invalid token encoding") from exc
        token = token.strip()
        if token.startswith(("b'", 'b"')) and token.endswith(token[1]):
            token = token[2:-1]

        parts = token.split(".")
        if len(parts) != 3:
            raise JWTError(f"Invalid JWT format - expected 3 parts, got {len(parts)}")

        header_b64 = parts[0].rstrip("=")
        header_b64 += "=" * ((4 - len(header_b64) % 4) % 4)
        try:
            header = json.loads(base64.urlsafe_b64decode(header_b64).decode("utf-8"))
        except (binascii.Error, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise JWTError("Header validation failed") from exc

        token_type = header.get("typ", "JWT") if isinstance(header, dict) else None
        if (
            not isinstance(token_type, str)
            or token_type.upper() != "JWT"
            or header.get("alg") != "HS256"
        ):
            raise JWTError("Invalid token header")

        return token

    async def _get_or_create_signing_key(self, session: AsyncSession) -> SigningKey:
        """
        Retrieve an existing active signing key or create a new one

        Args:
            session: Database session

        Returns:
            Active SigningKey instance
        """
        query = select(SigningKey).where(SigningKey.active == True)
        result = await session.execute(query)
        skey = result.scalar_one_or_none()

        if skey:
            log.debug("Got active signing key from database", extra={"key_id": skey.id})
            return skey

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
                # Token.expires_at > datetime.now(timezone.utc),
            )
            .values(revoked=True)
        )
        await session.execute(revoke_tokens)

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
        lifetime = expires_delta or timedelta(days=settings.ACCESS_TOKEN_EXPIRE_DAYS)
        lifetime_seconds = lifetime.total_seconds()
        wall_now = current_wall_time()
        expires = datetime.fromtimestamp(wall_now + lifetime_seconds, timezone.utc)
        boot_id = current_boot_id()
        boot_expires = current_boottime() + lifetime_seconds

        max_retries = 3
        retry_count = 0

        while retry_count < max_retries:
            async with self.app_state.db_manager.session() as session:
                try:
                    async with session.begin():
                        # Serialize active-key selection with key rotation.
                        await session.execute(text("BEGIN IMMEDIATE"))
                        device_repo = DeviceRepository(session)
                        await device_repo.get_or_create_device(device_id)
                        signing_key = await self._get_or_create_signing_key(session)

                        claims = {
                            "sub": system_service.get_hostname(),
                            "iss": "wlanpi-core",
                            "did": device_id,
                            "exp": int(expires.timestamp()),
                            "iat": int(wall_now),
                            "kid": str(signing_key.id),
                            "jti": secrets.token_hex(8),
                            "bid": boot_id,
                            "bexp": boot_expires,
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

                    log.debug(token_model)
                    log.debug(vars(token_model))

                    return jwt_token

                except sqlalchemy_exc.IntegrityError as e:
                    retry_count += 1
                    if retry_count >= max_retries:
                        log.exception(
                            "Token creation failed after retries",
                            extra={
                                "component": "auth",
                                "action": "create_token_error",
                                "device_id": device_id,
                                "error": str(e),
                                "retries": retry_count,
                            },
                        )
                        raise
                    continue
                except Exception as e:
                    log.exception(
                        "Token creation failed",
                        extra={
                            "component": "auth",
                            "action": "create_token_error",
                            "device_id": device_id,
                            "error": str(e),
                        },
                    )
                    raise

        raise RuntimeError("Token creation retry loop exited unexpectedly")

    @staticmethod
    def _numeric_claim(payload: Dict[str, Any], name: str) -> Union[int, float]:
        value = payload.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise JWTError(f"Invalid {name} claim")
        try:
            if not math.isfinite(value):
                raise JWTError(f"Invalid {name} claim")
        except OverflowError as exc:
            raise JWTError(f"Invalid {name} claim") from exc
        return value

    @classmethod
    def _validate_lifetime(cls, payload: Any) -> None:
        iat = cls._numeric_claim(payload, "iat")
        exp = cls._numeric_claim(payload, "exp")
        if exp <= iat:
            raise JWTError("Invalid token lifetime")

        has_bid = "bid" in payload
        has_bexp = "bexp" in payload
        if has_bid != has_bexp:
            raise JWTError("Invalid boot lifetime claims")

        if has_bid:
            bid = payload["bid"]
            if not isinstance(bid, str) or not bid:
                raise JWTError("Invalid bid claim")
            bexp = cls._numeric_claim(payload, "bexp")
            if bexp < 0:
                raise JWTError("Invalid bexp claim")
            if bid == current_boot_id():
                if current_boottime() >= bexp:
                    raise JWTError("Token expired")
                return

        now = current_wall_time()
        if now + CLOCK_SKEW_TOLERANCE_SEC < iat:
            raise JWTError(AUTH_CLOCK_NOT_SET)
        payload.validate_iat(now, leeway=CLOCK_SKEW_TOLERANCE_SEC)
        payload.validate_exp(now, leeway=0)
        if now >= exp:
            raise JWTError("Token expired")

    async def verify_token(self, token: str) -> TokenValidationResult:
        """Verify JWT token and return validation result"""
        masked_token = token[:20] + "..." + token[-20:] if len(token) > 40 else token
        log.debug("Verifying token: %s", masked_token)

        try:
            normalized_token = self._normalize_token(token)
        except JWTError as exc:
            return TokenValidationResult(is_valid=False, error=str(exc))

        # ponytail: verify local SQLite on every request; add a token cache only
        # if profiling shows this path is a bottleneck.
        async with self.app_state.db_manager.session() as session:
            token_model = await TokenRepository(session).get_token_by_value(
                normalized_token
            )
            if not token_model:
                return TokenValidationResult(is_valid=False, error="Token not found")
            if token_model.revoked:
                return TokenValidationResult(is_valid=False, error="Token revoked")

            signing_key = token_model.signing_key
            if not signing_key or not signing_key.active:
                return TokenValidationResult(
                    is_valid=False, error="Invalid signing key"
                )

            try:
                payload = jwt.decode(normalized_token, signing_key.key)
                for claim in ("sub", "iss", "did", "kid", "jti", "iat", "exp"):
                    if claim not in payload:
                        raise JWTError(f"Missing required claim: {claim}")
                if payload["iss"] != "wlanpi-core":
                    raise JWTError("Invalid issuer")
                if not payload["did"]:
                    raise JWTError("Invalid device ID")
                if str(payload["kid"]) != str(token_model.key_id):
                    raise JWTError("Invalid signing key claim")
                self._validate_lifetime(payload)
            except (JoseError, JWTError) as exc:
                return TokenValidationResult(is_valid=False, error=str(exc))

            return TokenValidationResult(
                is_valid=True,
                payload=payload,
                token=normalized_token,
                device_id=token_model.device_id,
                key_id=token_model.key_id,
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
                await session.commit()

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
                        # Token.expires_at > datetime.now(timezone.utc),
                    )
                    .values(revoked=True)
                )
                await session.execute(revoke_tokens)

                await session.commit()

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
                # Token.expires_at > datetime.now(timezone.utc),
            )
        )
        result = await session.execute(query)
        return result.scalar_one()

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
                        # Token.expires_at > now,
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
