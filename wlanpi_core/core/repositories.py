from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Union

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from wlanpi_core.core.database import BaseRepository
from wlanpi_core.core.logging import get_logger
from wlanpi_core.core.models import (
    APIDevice,
    APIDeviceActivity,
    APIDeviceActivityRecent,
    APIDeviceStats,
    Token,
)

log = get_logger(__name__)


class TokenRepository(BaseRepository):
    """
    Repository for managing authentication tokens
    """

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_token_by_value(self, token_value: str) -> Optional[Token]:
        """
        Retrieve a token by its string value

        Args:
            token_value: The token string to search for

        Returns:
            Token instance or None
        """
        query = (
            select(Token)
            .options(selectinload(Token.signing_key))
            .where(Token.token == token_value)
        )
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def get_active_tokens_for_device(
        self, device_id: str, include_revoked: bool = False
    ) -> List[Token]:
        """
        Retrieve active tokens for a specific device

        Args:
            device_id: Device identifier
            include_revoked: Whether to include revoked tokens

        Returns:
            List of active tokens
        """
        query = (
            select(Token)
            .options(selectinload(Token.signing_key))
            .where(Token.device_id == device_id)
        )

        if not include_revoked:
            query = query.where(
                Token.revoked == False, Token.expires_at > datetime.now(timezone.utc)
            )

        result = await self._session.execute(query)
        return result.scalars().all()

    async def purge_expired_tokens(self) -> int:
        """
        Remove expired and revoked tokens

        Returns:
            Number of tokens deleted
        """
        delete_query = delete(Token).where(
            Token.revoked == True, Token.expires_at < datetime.now(timezone.utc)
        )

        result = await self._session.execute(delete_query)

        return result.rowcount


class DeviceRepository(BaseRepository):
    """
    Repository for managing device-related operations
    """

    async def get_or_create_device(self, device_id: str) -> APIDevice:
        """
        Retrieve an existing device or create a new one

        Args:
            device_id: Unique device identifier

        Returns:
            Device instance
        """
        query = select(APIDevice).where(APIDevice.device_id == device_id)
        result = await self._session.execute(query)
        device = result.scalar_one_or_none()

        if not device:
            device = APIDevice(device_id=device_id)
            self._session.add(device)
            await self._session.flush()

        device.last_seen = datetime.now(timezone.utc)

        return device

    async def get_device_stats(self, device_id: str) -> Optional[Dict]:
        query = (
            select(APIDeviceStats)
            .join(APIDevice)
            .join(Token)
            .where(APIDevice.device_id == device_id)
        )
        result = await self._session.execute(query)
        stats = result.scalar_one_or_none()

        if not stats:
            return None

        token_query = (
            select(Token)
            .where(Token.device_id == device_id, Token.revoked == False)
            .order_by(Token.created_at.desc())
        )
        result = await self._session.execute(token_query)
        token = result.scalar_one_or_none()

        return {
            "token_created": token.created_at if token else None,
            "token_expires": token.expires_at if token else None,
            "token_revoked": token.revoked if token else None,
            "total_requests": stats.request_count,
            "error_count": stats.error_count,
            "unique_endpoints": stats.endpoint_count,
            "last_activity": stats.last_activity,
        }

    async def update_device_stats(
        self, device_id: str, increment_requests: int = 1, increment_errors: int = 0
    ):
        """
        Update device statistics

        Args:
            device_id: Device identifier
            increment_requests: Number of requests to increment
            increment_errors: Number of errors to increment
        """
        await self.get_or_create_device(device_id)

        query = select(APIDeviceStats).where(APIDeviceStats.device_id == device_id)
        result = await self._session.execute(query)
        stats = result.scalar_one_or_none()

        if not stats:
            stats = APIDeviceStats(
                device_id=device_id,
                request_count=increment_requests,
                error_count=increment_errors,
                last_activity=datetime.now(timezone.utc),
            )
            self.add(stats)
        else:
            stats.request_count += increment_requests
            stats.error_count += increment_errors
            stats.last_activity = datetime.now(timezone.utc)

        return stats


class ActivityRepository(BaseRepository):
    """Repository for managing device activities"""

    async def create_activity(
        self,
        device_id: str,
        endpoint: str,
        status_code: int,
        activity_type: str = "recent",
    ) -> Union[APIDeviceActivity, APIDeviceActivityRecent]:
        """
        Create a new activity record

        Args:
            device_id: Device identifier
            endpoint: API endpoint accessed
            status_code: HTTP status code
            activity_type: "recent" or "historical"

        Returns:
            Created activity record
        """
        ActivityModel = (
            APIDeviceActivityRecent if activity_type == "recent" else APIDeviceActivity
        )

        activity = ActivityModel(
            device_id=device_id, endpoint=endpoint, status_code=status_code
        )

        self._session.add(activity)
        await self._session.flush()

        log.debug(
            f"Created {activity_type} activity",
            extra={
                "component": "activity",
                "action": "create",
                "device_id": device_id,
                "endpoint": endpoint,
                "status_code": status_code,
            },
        )

        return activity

    async def get_activities(
        self, device_id: Optional[str] = None, limit: int = 100, recent: bool = True
    ) -> List[Union[APIDeviceActivity, APIDeviceActivityRecent]]:
        """
        Retrieve activity records for a device

        Args:
            device_id: ID of the device to filter activities (optional)
            limit: Maximum number of activities to retrieve (default: 100)
            recent: Whether to retrieve recent activities or historical activities (default: True)

        Returns:
            List of activity records, either recent or historical
        """
        Model = APIDeviceActivityRecent if recent else APIDeviceActivity

        query = select(Model).order_by(Model.created_at.desc())
        if device_id:
            query = query.where(Model.device_id == device_id)
        query = query.limit(limit)

        result = await self._session.execute(query)
        return result.scalars().all()

    async def bulk_create_activities(
        self, activities: List[Dict], activity_type: str = "recent"
    ) -> List[Union[APIDeviceActivity, APIDeviceActivityRecent]]:
        """
        Bulk create activity records

        Args:
            activities: List of activity dictionaries
            activity_type: "recent" or "historical"

        Returns:
            List of created activities
        """
        Model = (
            APIDeviceActivityRecent if activity_type == "recent" else APIDeviceActivity
        )

        activity_models = []
        for data in activities:
            model = Model(**data)
            self._session.add(model)
            activity_models.append(model)

        await self._session.flush()
        log.debug(
            f"Bulk created {len(activities)} {activity_type} activities",
            extra={
                "component": "activity",
                "action": "bulk_create",
                "count": len(activities),
            },
        )
        return activity_models


class StatsRepository(BaseRepository):
    """Repository for managing device statistics"""

    async def get_stats(self, device_id: str) -> Optional[APIDeviceStats]:
        """
        Get statistics for a device

        Args:
            device_id: Device identifier

        Returns:
            Device statistics or None if not found
        """
        query = select(APIDeviceStats).where(APIDeviceStats.device_id == device_id)
        result = await self._session.execute(query)
        return result.scalar_one_or_none()

    async def update_stats(
        self,
        device_id: str,
        requests: int = 0,
        errors: int = 0,
        endpoints: Optional[Set[str]] = None,
    ) -> APIDeviceStats:
        """
        Update statistics for a device

        Args:
            device_id: Device identifier
            request_count: Number of requests to add
            error_count: Number of errors to add
            endpoint_count: Optional new endpoint count

        Returns:
            Updated statistics
        """
        query = select(APIDeviceStats).where(APIDeviceStats.device_id == device_id)
        result = await self._session.execute(query)
        stats = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)

        if stats:
            stats.request_count += requests
            stats.error_count += errors
            if endpoints is not None:
                stats.endpoint_count = len(endpoints)
            stats.last_activity = now
        else:
            stats = APIDeviceStats(
                device_id=device_id,
                request_count=requests,
                error_count=errors,
                endpoint_count=len(endpoints) if endpoints else 0,
                last_activity=now,
            )
            self._session.add(stats)

        await self._session.flush()
        return stats

    async def get_device_stats(self, device_id: str) -> Optional[Dict]:
        query = select(APIDeviceStats).where(APIDeviceStats.device_id == device_id)
        result = await self._session.execute(query)
        stats = result.scalar_one_or_none()

        if not stats:
            return None

        token_repo = TokenRepository(self._session)
        tokens = await token_repo.get_active_tokens_for_device(
            device_id, include_revoked=True
        )
        latest_token = tokens[0] if tokens else None

        return {
            "token_created": latest_token.created_at if latest_token else None,
            "token_expires": latest_token.expires_at if latest_token else None,
            "token_revoked": latest_token.revoked if latest_token else None,
            "total_requests": stats.request_count,
            "error_count": stats.error_count,
            "unique_endpoints": stats.endpoint_count,
            "last_activity": stats.last_activity,
        }

    async def get_active_devices(self) -> List[Dict]:
        """
        Get statistics for all active devices

        Returns:
            List of device statistics
        """
        now = datetime.now(timezone.utc)
        query = (
            select(Token, APIDeviceStats)
            .join(APIDeviceStats, Token.device_id == APIDeviceStats.device_id)
            .where(Token.expires_at > now, Token.revoked == False)
        )

        result = await self._session.execute(query)
        rows = result.all()

        return [
            {
                "device_id": token.device_id,
                "token_created": token.created_at,
                "token_expires": token.expires_at,
                "activity_count": stats.request_count if stats else 0,
                "last_activity": stats.last_activity if stats else None,
            }
            for token, stats in rows
        ]
