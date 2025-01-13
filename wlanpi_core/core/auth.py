import asyncio
import base64
import ipaddress
import json
import logging
import hmac
import hashlib
import secrets
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple, Union
from functools import lru_cache

from authlib.jose import jwt
from authlib.jose.errors import ExpiredTokenError, InvalidTokenError
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from wlanpi_core.services import system_service

log = logging.getLogger("uvicorn")

ACCESS_TOKEN_EXPIRE_DAYS = 7


class TokenError(Exception):
    pass


class KeyError(Exception):
    pass


class JWTError(Exception):
    pass


def to_timestamp(dt: Optional[Union[datetime, str, int, float]]) -> Optional[int]:
    """
    Convert various datetime formats to Unix timestamp
    
    Args:
        dt: Input datetime (can be datetime object, ISO string, or timestamp)
        
    Returns:
        int: Unix timestamp in seconds
    """
    if dt is None:
        return None
        
    try:
        if isinstance(dt, (int, float)):
            return int(dt)
        elif isinstance(dt, str):
            dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
        
        if isinstance(dt, datetime):
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return int(dt.timestamp())
            
        raise ValueError(f"Unsupported datetime format: {type(dt)}")
    except Exception as e:
        log.error(f"Failed to convert to timestamp: {e}")
        return None

def from_timestamp(ts: Optional[Union[int, float, str]]) -> Optional[datetime]:
    """
    Convert Unix timestamp to UTC datetime
    
    Args:
        ts: Unix timestamp (seconds since epoch)
        
    Returns:
        datetime: UTC datetime object
    """
    if ts is None:
        return None
        
    try:
        if isinstance(ts, str):
            ts = float(ts)
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    except Exception as e:
        log.error(f"Failed to convert from timestamp: {e}")
        return None

def pad_base64(input_str: Union[str, bytes], is_token: bool = False) -> str:
    """
    Add padding to base64/base64url encoded strings

    Args:
        input_str: The string or bytes to pad
        is_token: If True, treats input as full JWT token and handles parts separately

    Returns:
        str: Properly padded base64 string

    Raises:
        JWTError: If token format is invalid when is_token=True
    """
    try:
        input_str = normalize_token(input_str)

        if is_token:
            parts = input_str.split(".")
            if len(parts) != 3:
                raise JWTError(
                    f"Invalid JWT format - expected 3 parts, got {len(parts)}"
                )

            padded_parts = []
            for part in parts:
                try:
                    unpadded = part.rstrip("=")
                    padding_needed = (4 - len(unpadded) % 4) % 4
                    padded = unpadded + ("=" * padding_needed)
                    padded_parts.append(padded)
                except Exception as e:
                    raise JWTError(f"Failed to pad token part: {str(e)}")

            return ".".join(padded_parts)

        else:
            unpadded = input_str.rstrip("=")
            padding_needed = (4 - len(unpadded) % 4) % 4
            return unpadded + ("=" * padding_needed)
    except JWTError:
        raise
    except Exception as e:
        log.error(f"Base64 padding error: {str(e)}")
        raise JWTError(f"Base64 padding failed: {str(e)}")


def decode_jwt_part(part: str) -> dict:
    """
    Decode a single JWT part (header or payload)

    Args:
        part: Base64url encoded JWT part

    Returns:
        dict: Decoded JSON data

    Raises:
        JWTError: If decoding or JSON parsing fails
    """
    try:
        padded = pad_base64(part)

        std_b64 = padded.replace("-", "+").replace("_", "/")

        decoded_bytes = base64.b64decode(std_b64)
        decoded_str = decoded_bytes.decode("utf-8")

        return json.loads(decoded_str)

    except Exception as e:
        raise JWTError(f"Failed to decode JWT part: {str(e)}")


def validate_and_fix_token(token: Union[str, bytes]) -> str:
    """
    Validate JWT token format and fix common issues

    Args:
        token: JWT token string or bytes

    Returns:
        str: Validated and properly formatted token

    Raises:
        JWTError: If token format is invalid or unfixable
    """
    try:
        token = normalize_token(token)

        padded_token = pad_base64(token, is_token=True)

        parts = padded_token.split(".")
        if len(parts) != 3:
            raise JWTError("Invalid token structure")

        try:
            header = decode_jwt_part(parts[0])
            if not header.get("alg") or not header.get("typ", "JWT").upper() == "JWT":
                raise JWTError("Invalid token header")
        except Exception:
            raise JWTError(f"Header validation failed")

        return padded_token
    except JWTError:
        raise
    except Exception:
        raise


def normalize_token(token: Union[str, bytes]) -> str:
    """Normalize token format consistently"""
    if isinstance(token, bytes):
        token = token.decode("utf-8")
    return token.strip("b'\"")


class SingletonMeta(type):
    _instances = {}
    _lock = threading.Lock()

    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super().__call__(*args, **kwargs)
        return cls._instances[cls]


class KeyCache(metaclass=SingletonMeta):
    """
    Cache for keys
    """

    def __init__(self):
        self._active_key = None
        self._key_cache = {}

    def cache_active_key(self, key_id: int, key: str):
        """
        Cache the current active key

        Args:
            key_id: ID of the key
            key: The key itself
        """
        self._active_key = (key_id, key)
        self._key_cache[key_id] = key

    def get_cached_key(self, key_id: int) -> Optional[str]:
        """
        Retrieve a cached key

        Args:
            key_id: ID of the key to retrieve

        Returns:
            Cached key or None
        """
        return self._key_cache.get(key_id)

    @property
    def active_key(self) -> Optional[Tuple[int, str]]:
        """
        Get the currently active key

        Returns:
            Tuple of (key_id, key) or None
        """
        return self._active_key

    def clear(self):
        """
        Clear all cached keys
        """
        self._active_key = None
        self._key_cache.clear()


class TokenCache(metaclass=SingletonMeta):
    """
    Cache for tokens
    """

    def __init__(self):
        self._token_cache = {}
        self._validation_cache = {}
        self._cache_ttl = 300  # 5 minute TTL for validation results

    @lru_cache(maxsize=100)
    def _check_timestamp_expired(self, exp_timestamp: int) -> bool:
        """
        Check if a timestamp is expired.

        Args:
            exp_timestamp: Unix timestamp for expiration time

        Returns:
            bool: True if expired, False if still valid
        """
        try:
            now = int(datetime.now(timezone.utc).timestamp())
            return exp_timestamp <= now
        except (TypeError, ValueError) as e:
            log.error(f"Error checking timestamp expiry: {e}")
            return True

    def _is_token_expired(self, payload: dict) -> bool:
        """
        Check if token is expired based on payload
        """
        try:
            return self._check_timestamp_expired(payload["exp"])
        except (KeyError, TypeError) as e:
            log.error(f"Error extracting expiry from payload: {e}")
            return True

    def cache_token(self, token: str, payload: Dict[str, Any]) -> None:
        """
        Cache a token payload

        Args:
            token: Token string
            payload: Decoded token payload
        """
        token = normalize_token(token)

        if not self._is_token_expired(payload):
            self._token_cache[token] = payload
            self._validation_cache[token] = {
                "timestamp": datetime.now(timezone.utc),
                "is_valid": True,
            }
            exp = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)
            log.info(f"Cached token expiring at {exp}")

    def get_cached_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached token payload if valid

        Args:
            token: Token string to retrieve

        Returns:
            Cached token payload or None
        """
        token = normalize_token(token)
        validation = self._validation_cache.get(token)

        if validation:
            cache_age = (
                datetime.now(timezone.utc) - validation["timestamp"]
            ).total_seconds()
            if cache_age > self._cache_ttl:
                self._validation_cache.pop(token, None)
                self._token_cache.pop(token, None)
                return None

            if not validation["is_valid"]:
                return None

        payload = self._token_cache.get(token)
        if payload and not self._is_token_expired(payload):
            return payload

        self._token_cache.pop(token, None)
        self._validation_cache.pop(token, None)
        return None

    def invalidate_token(self, token: str) -> None:
        """
        Mark a token as invalid in the validation cache

        Args:
            token: Token string to invalidate
        """
        token = normalize_token(token)

        self._validation_cache[token] = {
            "timestamp": datetime.now(timezone.utc),
            "is_valid": False,
        }
        self._token_cache.pop(token, None)
        log.info("Token invalidated in cache")

    def clear_expired(self) -> None:
        """
        Remove expired entries from both caches
        """
        now = datetime.now(timezone.utc)

        expired_validations = [
            token
            for token, data in self._validation_cache.items()
            if (now - data["timestamp"]).total_seconds() > self._cache_ttl
        ]
        for token in expired_validations:
            self._validation_cache.pop(token, None)
            self._token_cache.pop(token, None)

        expired_tokens = [
            token
            for token, payload in self._token_cache.items()
            if self._is_token_expired(payload)
        ]
        for token in expired_tokens:
            self._token_cache.pop(token, None)
            self._validation_cache.pop(token, None)

        if expired_validations or expired_tokens:
            log.info(
                f"Cleared {len(expired_validations)} expired validation entries and {len(expired_tokens)} expired tokens"
            )

    def clear(self) -> None:
        """
        Clear all cached data
        """
        self._token_cache.clear()
        self._validation_cache.clear()
        self._check_timestamp_expired.cache_clear()
        log.info("Cleared caches")

    def get_cache_stats(self) -> dict:
        """
        Get statistics about the current cache state
        """
        now = datetime.now(timezone.utc)

        expired_validations = len(
            [
                token
                for token, data in self._validation_cache.items()
                if (now - data["timestamp"]).total_seconds() > self._cache_ttl
            ]
        )

        expired_tokens = len(
            [
                token
                for token, payload in self._token_cache.items()
                if self._is_token_expired(payload)
            ]
        )

        cache_info = self._check_timestamp_expired.cache_info()

        return {
            "token_cache_size": len(self._token_cache),
            "validation_cache_size": len(self._validation_cache),
            "expired_validations": expired_validations,
            "expired_tokens": expired_tokens,
            "timestamp_cache_hits": cache_info.hits,
            "timestamp_cache_misses": cache_info.misses,
            "timestamp_cache_size": cache_info.currsize,
            "validation_ttl": self._cache_ttl,
        }

    def debug_token_state(self, token: str) -> dict:
        """
        Get debug information about a specific token's cache state

        Args:
            token: The token to check

        Returns:
            dict: Token's cache state information
        """
        token = normalize_token(token)

        validation_info = self._validation_cache.get(token)
        token_info = self._token_cache.get(token)

        result = {
            "in_token_cache": token in self._token_cache,
            "in_validation_cache": token in self._validation_cache,
            "validation_status": None,
            "validation_age": None,
            "is_expired": None,
            "expiry_time": None,
        }

        if validation_info:
            cache_age = (
                datetime.now(timezone.utc) - validation_info["timestamp"]
            ).total_seconds()
            result.update(
                {
                    "validation_status": validation_info["is_valid"],
                    "validation_age": cache_age,
                    "validation_expired": cache_age > self._cache_ttl,
                }
            )

        if token_info and "exp" in token_info:
            exp_time = datetime.fromtimestamp(token_info["exp"], tz=timezone.utc)
            result.update(
                {
                    "is_expired": self._is_token_expired(token_info),
                    "expiry_time": exp_time.isoformat(),
                }
            )

        return result


class InMemoryCache(metaclass=SingletonMeta):
    """
    In-memory cache with optional timeout and maximum size
    """

    def __init__(self, maxsize: int = 128, default_timeout: int = 3600):
        """
        Initialize the cache

        Args:
            maxsize: Maximum number of items to store in cache
            default_timeout: Default timeout for cache entries in seconds
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._maxsize = maxsize
        self._default_timeout = default_timeout

    def set(self, key: str, value: Any, timeout: Optional[int] = None):
        """
        Set a value in the cache

        Args:
            key: Cache key
            value: Value to cache
            timeout: Expiration time in seconds (defaults to default_timeout)
        """
        if len(self._cache) >= self._maxsize:
            # Remove oldest item if cache is full
            self._cache.pop(next(iter(self._cache)))

        expiry = datetime.now().timestamp() + (timeout or self._default_timeout)
        self._cache[key] = {"value": value, "expiry": expiry}

    def get(self, key: str):
        """
        Get a value from the cache

        Args:
            key: Cache key

        Returns:
            Cached value or None if not found or expired
        """
        entry = self._cache.get(key)
        if not entry:
            return None

        if datetime.now().timestamp() > entry["expiry"]:
            del self._cache[key]
            return None

        return entry["value"]

    def delete(self, key: str):
        """
        Remove a key from the cache

        Args:
            key: Cache key to remove
        """
        self._cache.pop(key, None)


@dataclass
class TokenValidationResult:
    """Result of token validation containing validation status and metadata"""

    is_valid: bool
    payload: Optional[dict] = None
    error: Optional[str] = None
    token: Optional[str] = None
    device_id: Optional[str] = None
    key_id: Optional[int] = None

    def __post_init__(self):
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
        self.app_state = app_state
        self.token_cache = TokenCache()
        self.key_cache = KeyCache()

    async def _create_new_key(
        self, cursor, invalidate_old: bool = False
    ) -> Tuple[int, bytes]:
        """Helper method to create and store a new key"""
        key = secrets.token_bytes(32)
        encrypted_key = self.app_state.security_manager.encrypt(key)
        now = to_timestamp(datetime.now(timezone.utc))

        if invalidate_old:
            cursor.execute("UPDATE signing_keys SET active = FALSE")

        cursor.execute(
            "INSERT INTO signing_keys (key, active, created_at) VALUES (?, TRUE, ?)", (encrypted_key, now)
        )
        key_id = cursor.lastrowid
        return key_id, key

    async def _get_active_key_from_db(self, cursor) -> Optional[Tuple[int, bytes]]:
        """Helper method to retrieve active key from database"""
        cursor.execute(
            "SELECT id, key FROM signing_keys WHERE active = TRUE "
            "ORDER BY created_at DESC LIMIT 1"
        )
        result = cursor.fetchone()

        if result:
            key_id, encrypted_key = result
            key = self.app_state.security_manager.decrypt(encrypted_key)
            return key_id, key
        return None

    async def initialize(self) -> None:
        """Initialize signing key on application start"""
        if self.key_cache.active_key:
            log.info("Using existing cached key")
            return

        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM signing_keys")
            key_count = cursor.fetchone()[0]
            log.info(f"Current signing_keys count: {key_count}")
            
            if key_count > 0:
                cursor.execute(
                    "SELECT id, created_at, active FROM signing_keys ORDER BY created_at DESC"
                )
                keys = cursor.fetchall()
                for key in keys:
                    log.info(f"Found key: id={key[0]}, created={key[1]}, active={key[2]}")
                
            log.info("Fetching active key from database")
            cursor.execute(
                "SELECT id, key, created_at FROM signing_keys WHERE active = TRUE "
                "ORDER BY created_at DESC LIMIT 1"
            )
            result = cursor.fetchone()
        
            if result:
                key_id, encrypted_key, created_at = result[0], result[1], result[2]
                key = self.app_state.security_manager.decrypt(encrypted_key)
                self.key_cache.cache_active_key(key_id, key)
                log.info(f"Retrieved existing key_id {key_id} created at {created_at}")
                return

            log.info("No active key found, creating new key")
        
            key = secrets.token_bytes(32)
            encrypted_key = self.app_state.security_manager.encrypt(key)
            now = to_timestamp(datetime.now(timezone.utc))
            cursor.execute(
                "INSERT INTO signing_keys (key, active, created_at) VALUES (?, TRUE, ?)",
                (encrypted_key, now),
            )
            key_id = cursor.lastrowid
            
            cursor.execute("SELECT id, created_at FROM signing_keys WHERE id = ?", (key_id,))
            inserted_key = cursor.fetchone()
            if not inserted_key:
                raise KeyError(f"Failed to insert new key - no record found with id {key_id}")
                
            conn.commit()

            self.key_cache.cache_active_key(key_id, key)
            log.info(f"Created and cached new key {key_id}")
        
            cursor.execute("SELECT COUNT(*) FROM signing_keys")
            final_count = cursor.fetchone()[0]
            log.info(f"Final signing_keys count: {final_count}")
        except Exception as e:
            if conn:
                conn.rollback()
            log.exception("Failed to initialize key on start")
            raise KeyError("Failed to initialize key on start") from e
        finally:
            if conn:
                conn.close()

    async def verify_db_state(self) -> dict:
        """
        Verify the current state of tokens in the database
        """
        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()

            now = datetime.now(timezone.utc).timestamp()

            cursor.execute(
                """SELECT 
                COUNT(*) as total,
                SUM(CASE WHEN revoked = TRUE THEN 1 ELSE 0 END) as revoked,
                SUM(CASE WHEN expires_at < ? THEN 1 ELSE 0 END) as expired,
                MIN(expires_at) as earliest_expiry,
                MAX(expires_at) as latest_expiry
                FROM tokens""",
                (now,),
            )
            stats = cursor.fetchone()

            cursor.execute(
                """SELECT token, device_id, expires_at, revoked 
                FROM tokens 
                WHERE revoked = FALSE AND expires_at > ?
                ORDER BY expires_at DESC""",
                (now,),
            )
            active_tokens = cursor.fetchall()

            return {
                "statistics": {
                    "total_tokens": stats["total"],
                    "revoked_tokens": stats["revoked"],
                    "expired_tokens": stats["expired"],
                    "earliest_expiry": from_timestamp(stats["earliest_expiry"]),
                    "latest_expiry": from_timestamp(stats["latest_expiry"]),
                },
                "active_tokens": [
                    {
                        "device_id": token["device_id"],
                        "expires_at": from_timestamp(token["expires_at"]),
                        "revoked": token["revoked"],
                    }
                    for token in active_tokens
                ],
            }
        except Exception as e:
            log.exception("Failed to verify database state")
            return {"error": str(e)}
        finally:
            if conn:
                conn.close()

    async def get_key(self) -> Tuple[int, str]:
        """Get active key or create new one if none exists"""
        if self.key_cache.active_key:
            return self.key_cache.active_key

        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            key_data = await self._get_active_key_from_db(cursor)
            if key_data:
                key_id, key = key_data
                self.key_cache.cache_active_key(key_id, key)
                log.info(f"Retrieved existing key_id {key_id}")
                return key_id, key
            key_id, key = await self._create_new_key(cursor)
            conn.commit()
            self.key_cache.cache_active_key(key_id, key)
            log.info(f"Created new key {key_id}")
            return key_id, key
        except Exception as e:
            if conn:
                conn.rollback()
            log.exception(f"Failed to get/create key: {e}")
            raise KeyError(f"Key management failed: {e}")
        finally:
            if conn:
                conn.close()

    async def rotate_key(self) -> Tuple[int, str]:
        """Create new key and invalidate old ones"""

        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()

            key_id, key = await self._create_new_key(cursor, invalidate_old=True)
            conn.commit()
            cursor.execute(
                "UPDATE tokens SET revoked = TRUE WHERE key_id != ?", (key_id,)
            )
            affected_rows = cursor.rowcount
            conn.commit()
            self.key_cache.clear()
            self.token_cache.clear()
            self.key_cache.cache_active_key(key_id, key)

            log.info(f"Revoked {affected_rows} tokens")
            log.info(f"Successfully rotated to new key {key_id}")
            return key_id, key
        except Exception as e:
            if conn:
                conn.rollback()
            log.exception(f"Failed to create key: {e}")
            raise KeyError(f"Failed to create key: {e}")
        finally:
            if conn:
                conn.close()

    async def get_active_key(self) -> Optional[Tuple[int, str]]:
        """Internal only get active key"""
        if self.key_cache.active_key:
            return self.key_cache.active_key

        conn = await self.app_state.db_manager.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                "SELECT id, key FROM signing_keys WHERE active = TRUE "
                "ORDER BY created_at DESC LIMIT 1"
            )
            result = cursor.fetchone()

            if result:
                key_id, encrypted_key = result
                key = self.app_state.security_manager.decrypt(encrypted_key)
                return key_id, key

            return None
        except Exception as e:
            log.exception(f"Failed to get active key: {e}")
            raise KeyError(f"Failed to get active key: {e}")
        finally:
            conn.close()

    async def get_active_keys(self) -> Optional[Tuple[int, str]]:
        """
        List all keys with their metadata.
        Does not include the actual key material for security reasons.
        """
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT id, created_at, active 
                FROM signing_keys 
                ORDER BY created_at DESC
            """
            )
            keys = cursor.fetchall()

            return {
                "keys": [
                    {
                        "id": row[0],
                        "created_at": from_timestamp(row[1]),
                        "active": bool(row[2])
                    }
                    for row in keys
                ]
            }
        except Exception as e:
            log.exception(f"Failed to get active key: {e}")
            raise KeyError(f"Failed to get active key: {e}")
        finally:
            conn.close()

    async def _get_existing_token(
        self, device_id: str, cursor
    ) -> Optional[TokenValidationResult]:
        """Check for existing valid token for device"""
        try:
            cursor.execute(
                """SELECT t.token, t.key_id, k.key 
                FROM tokens t
                JOIN signing_keys k ON t.key_id = k.id
                WHERE t.device_id = ? AND t.revoked = FALSE""",
                (device_id,),
            )
            result = cursor.fetchone()
            if not result:
                return None

            token, key_id, encrypted_key = result
            key = self.app_state.security_manager.decrypt(encrypted_key)

            try:
                payload = jwt.decode(token, key)
                payload.validate()
                return TokenValidationResult(
                    is_valid=True, payload=payload, token=token
                )
            except (ExpiredTokenError, InvalidTokenError) as e:
                return TokenValidationResult(is_valid=False, error=str(e))
        except Exception as e:
            log.exception(f"Error checking existing token: {e}")
            return None

    async def create_token(
        self, device_id: str, expires_delta: Optional[timedelta] = None
    ) -> str:
        """
        Create and store a new JWT token for a specific device.

        Args:
            device_id (str): Device identifier.
            expires_delta (Optional[timedelta], optional):
                Custom token expiration duration.
                Defaults to ACCESS_TOKEN_EXPIRE_DAYS if not provided.

        Returns:
            str: A new or existing valid JWT token for the device.

        Raises:
            TokenError: If token creation or storage fails.

        Notes:
            - Device ID is extracted from 'did' key in the payload
            - Generates a new JWT token with embedded metadata
            - Checks for existing tokens for the same device
            - Invalidates and replaces existing tokens
            - Handles token expiration automatically
            - Caches the token to minimize database reads
        """
        log.info(f"Creating/fetching token for device {device_id}")

        if not self.key_cache.active_key:
            log.info("No active key found, initializing")
            await self.initialize()

        key_id, key = self.key_cache.active_key
        if isinstance(key, str):
            key = key.encode("utf-8")

        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()

            existing = await self._get_existing_token(device_id, cursor)
            if existing and existing.is_valid:
                log.info(f"Reusing valid token for device {device_id}")
                return existing.token

            now = datetime.now(timezone.utc)
            expire = now + (expires_delta or timedelta(days=ACCESS_TOKEN_EXPIRE_DAYS))

            claims = {
                "sub": system_service.get_hostname(),
                "iss": "wlanpi-core",
                "did": device_id,
                "exp": int(expire.timestamp()),
                "iat": int(now.timestamp()),
            }

            token = jwt.encode(
                header={"alg": "HS256", "kid": str(key_id)}, payload=claims, key=key
            )

            await self._store_token(token, device_id, cursor, claims, key_id)
            self.token_cache.cache_token(token, claims)

            log.info(f"Created new token for device {device_id}")
            return token
        except sqlite3.IntegrityError as ie:
            log.error(f"Integrity error for device {device_id}: {ie}")
            raise TokenError("Device ID conflict")
        except Exception as e:
            log.exception(f"Token creation failed: {e}")
            raise TokenError(f"Token creation failed: {str(e)}")
        finally:
            if conn:
                conn.close()

    async def revoke_token(self, token: str) -> dict:
        """
        Revoke a JWT token
        """
        log.info("Starting token revocation process")

        token = normalize_token(token)

        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()

            try:
                cursor.execute(
                    "SELECT device_id, revoked FROM tokens WHERE token = ?", (token,)
                )
                result = cursor.fetchone()

                if not result:
                    log.info("Token not found in database")
                    self.token_cache.invalidate_token(token)
                    return {"status": "warning", "message": "Token not found"}

                device_id = result["device_id"]

                if result["revoked"]:
                    log.info(f"Token for device {device_id} was already revoked")
                    self.token_cache.invalidate_token(token)
                    return {
                        "status": "info",
                        "message": "Token has already been revoked",
                        "device_id": device_id,
                    }

                cursor.execute(
                    """UPDATE tokens 
                    SET revoked = TRUE 
                    WHERE token = ?""",
                    (token,),
                )

                if cursor.rowcount == 0:
                    log.warning("Token revocation update failed")
                    return {
                        "status": "error",
                        "message": "Failed to revoke token in database",
                    }

                conn.commit()
                self.token_cache.invalidate_token(token)

                log.info(f"Successfully revoked token for device {device_id}")
                return {
                    "status": "success",
                    "message": "Token revoked",
                    "device_id": device_id,
                }
            except sqlite3.Error as e:
                log.error(f"Database error during revocation: {e}")
                return {
                    "status": "error",
                    "message": "Database error during revocation",
                }
        except Exception as e:
            if conn:
                conn.rollback()
            log.exception("Token revocation failed")
            raise HTTPException(
                status_code=500, detail=f"Failed to revoke token: {str(e)}"
            )
        finally:
            if conn:
                conn.close()

    async def _load_key_from_db(self, key_id: int) -> Optional[bytes]:
        """Load and decrypt key from database"""
        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT key FROM signing_keys WHERE id = ? AND active = TRUE", (key_id,)
            )
            result = cursor.fetchone()
            if not result:
                log.debug(f"No active key found for ID {key_id}")
                return None

            encrypted_key = result[0]
            key = self.app_state.security_manager.decrypt(encrypted_key)
            self.key_cache.cache_active_key(key_id, key)
            log.info(f"Loaded and cached key {key_id}")
            return key
        except Exception:
            log.exception(f"Failed to load key {key_id} from database")
            return None
        finally:
            if conn:
                conn.close()

    def _parse_token_header(self, token: str) -> dict:
        """Parse and validate token header"""
        try:
            header_part = token.split(".")[0]
            header = json.loads(
                base64.urlsafe_b64decode(
                    header_part + "=" * (4 - len(header_part) % 4)
                ).decode("utf-8")
            )

            if not header.get("kid"):
                raise TokenError("Missing key ID in token")
            if header.get("alg") != "HS256":
                raise TokenError("Invalid algorithm")
            return header
        except Exception as e:
            raise TokenError(f"Invalid token header: {str(e)}")

    async def _get_key_for_token(self, header: dict) -> bytes:
        """Get key for token verification"""
        key_id = header["kid"]
        try:
            key_id = int(key_id)
        except ValueError:
            raise TokenError(f"Invalid key ID format: {key_id}")
        key = self.key_cache.get_cached_key(key_id)
        if not key:
            log.info(f"Key {key_id} not in cache, attempting database load")
            key = await self._load_key_from_db(key_id)
        return key

    async def _store_token(
        self, token: str, device_id: str, cursor, claims: dict, key_id: int
    ) -> None:
        """Store token with proper transaction handling"""
        try:
            token = normalize_token(token)
            
            cursor.execute("SELECT id FROM signing_keys WHERE id = ?", (key_id,))
            if not cursor.fetchone():
                raise TokenError(f"Cannot store token - signing key {key_id} does not exist")
            
            cursor.execute("BEGIN TRANSACTION")
            
            # Delete any existing tokens for this device
            cursor.execute("DELETE FROM tokens WHERE device_id = ?", (device_id,))
            
            now = int(datetime.now(timezone.utc).timestamp())
            expires_at = to_timestamp(claims['exp'])
            
            cursor.execute(
                """INSERT INTO tokens 
                (token, device_id, expires_at, created_at, key_id) 
                VALUES (?, ?, ?, ?, ?)""",
                (token, device_id, expires_at, now, key_id),
            )
            
            cursor.execute("SELECT id FROM tokens WHERE token = ?", (token,))
            if not cursor.fetchone():
                raise TokenError("Token insert failed - no record found after insert")
                
            cursor.execute("COMMIT")
            log.info(f"Token stored for device {device_id}")
        except Exception as e:
            cursor.execute("ROLLBACK")
            log.error("Failed to store token")
            raise TokenError(f"Failed to store token: {str(e)}")

    async def verify_token(
        self, token: str, provided_conn=None
    ) -> TokenValidationResult:
        """Verify JWT token and return validation result"""
        log.info(f"Starting token verification")
        should_close = False
        conn = provided_conn
        try:
            # Log the token being verified (but mask most of it)
            masked_token = token[:20] + "..." + token[-20:] if len(token) > 40 else token
            log.debug(f"Verifying token: {masked_token}")
            
            try:
                normalized_token = normalize_token(token)
                validated_token = validate_and_fix_token(normalized_token)
            except JWTError as e:
                log.error(f"Token validation failed during normalization/validation: {e}")
                return TokenValidationResult(is_valid=False, error=str(e))

            cached = self.token_cache.get_cached_token(validated_token)
            if cached:
                log.debug("Token found in cache")
                return TokenValidationResult(is_valid=True, payload=cached, token=validated_token)
            
            if not conn:
                try:
                    conn = await self.app_state.db_manager.get_connection()
                    should_close = True
                except Exception:
                    log.error("Database connection failed")
                    return TokenValidationResult(
                        is_valid=False, error="Database unavailable"
                    )

            if conn is None:
                log.error("Database connection failed after acquiring connection")
                return TokenValidationResult(
                    is_valid=False, error="Invalid database connection"
                )

            cursor = conn.cursor()

            try:
                cursor.execute(
                    """SELECT t.revoked, t.device_id, t.key_id, t.token, t.expires_at
                    FROM tokens t 
                    WHERE t.token = ?""",
                    (validated_token,),
                )
                token_info = cursor.fetchone()
            
                if not token_info:
                    cursor.execute(
                        """SELECT t.revoked, t.device_id, t.key_id, t.token, t.expires_at
                        FROM tokens t 
                        WHERE t.token = ?""",
                        (normalized_token,),
                    )
                    token_info = cursor.fetchone()

                if not token_info:
                    log.warning(f"Token not found in database.")
                    log.info(f"Normalized token hash: {hash(normalized_token)}")
                    log.info(f"Validated token hash: {hash(validated_token)}")
                    
                    cursor.execute("SELECT token FROM tokens")
                    db_tokens = cursor.fetchall()
                    log.info(f"Database contains {len(db_tokens)} tokens")
                    for db_token in db_tokens:
                        log.info(f"Database token hash: {hash(db_token['token'])}")
                    
                    return TokenValidationResult(is_valid=False, error="Token not found")

            except sqlite3.Error as e:
                log.error(f"Database error during token lookup: {e}")
                return TokenValidationResult(
                    is_valid=False, error="Database error during validation"
                )

            if token_info["revoked"]:
                log.info(f"Token is revoked for device {token_info['device_id']}")
                return TokenValidationResult(is_valid=False, error="Token revoked")

            try:
                exp_time = from_timestamp(token_info["expires_at"])
                log.debug(f"Token expires at: {exp_time}")
                
                header = self._parse_token_header(token)
                key = await self._get_key_for_token(header)
                if not key:
                    log.warning(f"Key {header.get('kid')} not found")
                    return TokenValidationResult(
                        is_valid=False, error="Invalid signing key"
                    )

                payload = jwt.decode(token, key)
                payload.validate()

                self.token_cache.cache_token(token, payload)
                return TokenValidationResult(
                    is_valid=True,
                    payload=payload,
                    token=token,
                    device_id=token_info["device_id"],
                    key_id=token_info["key_id"],
                )
            except (TokenError, JWTError) as e:
                log.warning(f"Token validation failed: {e}")
                return TokenValidationResult(is_valid=False, error=str(e))
        except Exception as e:
            log.exception("Unexpected error during token verification")
            return TokenValidationResult(
                is_valid=False, error=f"Validation failed: {str(e)}"
            )
        finally:
            if should_close and conn:
                try:
                    conn.close()
                    log.debug("Database connection closed")
                except Exception as e:
                    log.exception(f"Failed to close database connection: {e}")

    async def purge_expired_tokens(self):
        """Background task to purge expired/revoked tokens"""
        while True:
            conn = None
            try:
                conn = await self.app_state.db_manager.get_connection()
                cursor = conn.cursor()

                now = int(datetime.now(timezone.utc).timestamp())
                purge_cutoff = now - (30 * 24 * 60 * 60)  # 30 days ago
                
                cursor.execute(
                    """SELECT COUNT(*) as total,
                    SUM(CASE WHEN expires_at < ? THEN 1 ELSE 0 END) as expired,
                    SUM(CASE WHEN revoked = TRUE THEN 1 ELSE 0 END) as revoked
                    FROM tokens""", 
                    (now,)
                )
                stats = cursor.fetchone()
                log.debug(f"Before purge - Total: {stats['total']}, Expired: {stats['expired']}, Revoked: {stats['revoked']}")

                cursor.execute(
                    """DELETE FROM tokens 
                    WHERE (revoked = TRUE AND expires_at < ?) 
                    OR expires_at < ?""", 
                    (purge_cutoff, purge_cutoff)
                )

                deleted_count = cursor.rowcount

                conn.commit()
                if deleted_count > 0:
                    log.info(f"Purged {deleted_count} tokens expired before {purge_cutoff}")

            except Exception as e:
                if conn:
                    conn.rollback()
                log.exception(f"Failed to purge tokens: {e}")
            finally:
                if conn:
                    conn.close()
                await asyncio.sleep(3600)

    async def verify_cache_state(self, token: str = None) -> dict:
        """
        Verify the cache state, optionally for a specific token

        Args:
            token: Optional token to check specifically

        Returns:
            dict: Cache state information
        """
        cache_stats = self.token_cache.get_cache_stats()

        if token:
            token = normalize_token(token)
            token_state = self.token_cache.debug_token_state(token)

            conn = None
            try:
                conn = await self.app_state.db_manager.get_connection()
                cursor = conn.cursor()

                cursor.execute(
                    """SELECT revoked, expires_at 
                    FROM tokens 
                    WHERE token = ?""",
                    (token,),
                )
                db_info = cursor.fetchone()

                if db_info:
                    token_state.update(
                        {
                            "in_database": True,
                            "db_revoked": bool(db_info["revoked"]),
                            "db_expires_at": db_info["expires_at"],
                        }
                    )
                else:
                    token_state.update(
                        {
                            "in_database": False,
                            "db_revoked": None,
                            "db_expires_at": None,
                        }
                    )

            except Exception as e:
                log.error(f"Failed to check database state: {e}")
                token_state.update({"database_error": str(e)})
            finally:
                if conn:
                    conn.close()

            return {"cache_stats": cache_stats, "token_state": token_state}

        return {"cache_stats": cache_stats}


security = HTTPBearer()


def is_localhost_request(request: Request) -> bool:
    """Check if request comes from loopback address (127.0.0.1/::1)"""
    client_ip = ipaddress.ip_address(request.client.host)
    return client_ip.is_loopback


async def verify_auth(request: Request, api_key: Optional[str]):
    """
    Use HMAC for internal requests, JWT for external requests
    """
    if is_localhost_request(request):
        return await verify_hmac(request)
    else:
        if not api_key:
            raise HTTPException(
                status_code=401, detail="External requests require authentication"
            )
        return await verify_jwt_token(api_key)


async def verify_jwt_token(
    request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)
):
    token = credentials.credentials
    try:
        validation_result = await request.app.state.token_manager.verify_token(token)
        if not validation_result.is_valid:
            raise HTTPException(
                status_code=401, 
                detail=validation_result.error or "Invalid token"
            )
        return validation_result
    except TokenError as e:
        raise HTTPException(status_code=401, detail=str(e))


async def verify_hmac(request: Request):
    """Verify HMAC signature for internal requests"""
    if not is_localhost_request(request):
        raise HTTPException(
            status_code=403,
            detail="Access forbidden: endpoint available only on localhost",
        )

    signature = request.headers.get("X-Request-Signature")
    if not signature:
        raise HTTPException(status_code=401, detail="Missing signature header")

    secret = request.app.state.security_manager.shared_secret
    body = await request.body()
    canonical_string = f"{request.method}\n{request.url.path}\n{body.decode()}"

    calculated = hmac.new(secret, canonical_string.encode(), hashlib.sha256).hexdigest()

    log.debug(f"Server calculated signature: {calculated}")
    log.debug(f"Client provided signature: {signature}")

    if not hmac.compare_digest(signature, calculated):
        raise HTTPException(status_code=401, detail="Invalid signature")
    return True
