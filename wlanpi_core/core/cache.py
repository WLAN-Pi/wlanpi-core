from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple, Union

from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.models import SigningKey
from wlanpi_core.utils.general import SingletonMeta

log = get_logger(__name__)


class SKeyCache(metaclass=SingletonMeta):
    """
    Cache for signing keys
    """

    def __init__(self) -> None:
        self._cache: Dict[int, SigningKey] = {}
        self._active_key_id: Optional[int] = None

    def cache_key(self, key: SigningKey) -> None:
        """Cache a SigningKey and set as active if specified"""
        self._cache[key.id] = key
        if key.active:
            self._active_key_id = key.id

    @property
    def active_key(self) -> Optional[SigningKey]:
        """Get the currently active SigningKey"""
        if self._active_key_id is None:
            return None
        return self._cache.get(self._active_key_id)

    def get_key(self, key_id: int) -> Optional[SigningKey]:
        """Get a cached SigningKey by id"""
        return self._cache.get(key_id)

    def clear(self) -> None:
        """Clear all cached keys"""
        self._cache.clear()
        self._active_key_id = None


class TokenCache(metaclass=SingletonMeta):
    """
    Cache for tokens
    """

    _token_cache: Dict[str, Dict[str, Any]] = {}  # Positive caching
    _validation_cache: Dict[str, Dict[str, Union[datetime, bool]]] = (
        {}
    )  # Negative caching
    _cache_ttl: int = 300  # 5 minute TTL for validation results
    _timestamp_cache: Dict[int, Tuple[bool, int]] = {}  # store result and creation time
    _timestamp_cache_ttl: int = 3600  # 1 hour TTL for timestamp cache
    _max_timestamp_entries: int = 1000

    def __init__(self) -> None:
        pass

    def _cleanup_timestamp_cache(self) -> None:
        """Remove expired entries from timestamp cache"""
        now = int(datetime.now(timezone.utc).timestamp())
        expired_keys = [
            ts
            for ts, (_, created_at) in self._timestamp_cache.items()
            if now - created_at > self._timestamp_cache_ttl
        ]

        if expired_keys:
            for key in expired_keys:
                self._timestamp_cache.pop(key, None)
            log.debug(
                "Cleaned up expired timestamp cache entries",
                extra={
                    "component": "auth",
                    "action": "cache_cleanup",
                    "removed_count": len(expired_keys),
                },
            )

        if len(self._timestamp_cache) > self._max_timestamp_entries:
            sorted_items = sorted(
                self._timestamp_cache.items(),
                key=lambda x: x[1][1],  # Sort by creation time
            )
            excess_count = len(sorted_items) - self._max_timestamp_entries
            to_remove = sorted_items[:excess_count]
            for ts, _ in to_remove:
                self._timestamp_cache.pop(ts, None)

            log.debug(
                "Removed oldest timestamp cache entries",
                extra={
                    "component": "auth",
                    "action": "cache_cleanup",
                    "removed_count": excess_count,
                },
            )

    def _check_timestamp_expired(self, exp_timestamp: int) -> bool:
        """
        Check if a timestamp is expired.

        Args:
            exp_timestamp: Unix timestamp for expiration time

        Returns:
            bool: True if expired, False if still valid
        """
        now = int(datetime.now(timezone.utc).timestamp())

        if exp_timestamp in self._timestamp_cache:
            result, created_at = self._timestamp_cache[exp_timestamp]
            if now - created_at <= self._timestamp_cache_ttl:
                return result
            self._timestamp_cache.pop(exp_timestamp)
            log.debug(
                "Timestamp cache entry expired",
                extra={
                    "component": "auth",
                    "action": "cache_expired",
                    "timestamp": exp_timestamp,
                },
            )

        result = exp_timestamp <= now

        self._timestamp_cache[exp_timestamp] = (result, now)

        if len(self._timestamp_cache) > self._max_timestamp_entries:
            self._cleanup_timestamp_cache()

        return result

    def _is_token_expired(self, payload: dict) -> bool:
        """Check if token is expired"""
        try:
            exp = payload.get("exp")
            iat = payload.get("iat")

            if not exp or not iat:
                return True

            now = datetime.now(timezone.utc).timestamp()
            return now > exp
        except (TypeError, ValueError):
            return True

    def cache_token(self, token: str, payload: Dict[str, Any]) -> None:
        """
        Cache token payload if not expired

        Args:
            token: Token string
            payload: Decoded token payload
        """
        if not self._is_token_expired(payload):
            self._token_cache[token] = payload
            self._validation_cache[token] = {
                "timestamp": datetime.now(timezone.utc),
                "is_valid": True,
            }

    def get_cached_token(self, token: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a cached token payload if valid

        Args:
            token: Token string to retrieve

        Returns:
            Cached token payload or None
        """
        validation = self._validation_cache.get(token)

        if validation:
            cache_age = (
                datetime.now(timezone.utc) - validation["timestamp"]
            ).total_seconds()
            if cache_age > self._cache_ttl:
                self._validation_cache.pop(token, None)
                self._token_cache.pop(token, None)
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
        self._validation_cache[token] = {
            "timestamp": datetime.now(timezone.utc),
            "is_valid": False,
        }
        self._token_cache.pop(token, None)
        log.debug("Token invalidated in cache")

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
            log.debug(
                f"Cleared {len(expired_validations)} expired validation entries and {len(expired_tokens)} expired tokens"
            )

    def clear(self) -> None:
        """Clear all caches"""
        self._token_cache.clear()
        self._validation_cache.clear()
        self._timestamp_cache.clear()
        log.debug("Cleared caches")

    def get_cache_stats(self) -> dict:
        """Get cache statistics"""
        return {
            "token_cache_size": len(self._token_cache),
            "validation_cache_size": len(self._validation_cache),
            "expired_tokens": sum(
                1 for p in self._token_cache.values() if self._is_token_expired(p)
            ),
        }

    def debug_token_state(self, token: str) -> dict:
        """Get token cache state"""
        validation = self._validation_cache.get(token)
        payload = self._token_cache.get(token)

        state = {
            "in_token_cache": token in self._token_cache,
            "in_validation_cache": token in self._validation_cache,
        }

        if validation:
            state.update(
                {
                    "validation_status": validation.get("is_valid"),
                    "validation_age": (
                        datetime.now(timezone.utc) - validation["timestamp"]
                    ).total_seconds(),
                }
            )

        if payload:
            state["is_expired"] = self._is_token_expired(payload)
            state["expiry_time"] = datetime.fromtimestamp(
                payload["exp"], timezone.utc
            ).isoformat()

        return state


class InMemoryCache(metaclass=SingletonMeta):
    """
    In-memory cache with optional timeout and maximum size
    """

    def __init__(self, maxsize: int = 128, default_timeout: int = 3600) -> None:
        """
        Initialize the cache

        Args:
            maxsize: Maximum number of items to store in cache
            default_timeout: Default timeout for cache entries in seconds
        """
        self._cache: Dict[str, Dict[str, Any]] = {}
        self._maxsize = maxsize
        self._default_timeout = default_timeout

    def _set(self, key: str, value: Any, timeout: Optional[int] = None) -> None:
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

    def delete(self, key: str) -> None:
        """
        Remove a key from the cache

        Args:
            key: Cache key to remove
        """
        self._cache.pop(key, None)
