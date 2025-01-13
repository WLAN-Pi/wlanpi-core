import asyncio
import logging
import time
from collections import defaultdict
from datetime import datetime, timezone
from typing import Dict, List

from wlanpi_core.core.database import DatabaseManager

log = logging.getLogger("uvicorn")

IMPORTANT_PATTERNS = ['/auth/', '/network/', '/system/']

class DeviceActivityManager:
    def __init__(
        self, 
        app_state,
        buffer_size: int = 1000,
        flush_interval: int = 3600 
    ):
        self.app_state = app_state
        self.buffer_size = buffer_size
        self.flush_interval = flush_interval
        self.buffer: List[dict] = []
        self.stats_buffer: Dict[str, dict] = defaultdict(
            lambda: {
                'request_count': 0,
                'error_count': 0,
                'endpoints': set(),
                'last_activity': None
            }
        )
        self.last_flush = time.time()
        self._lock = asyncio.Lock()

    def _is_important_endpoint(self, endpoint: str) -> bool:
        """Determine if detailed logging needed for endpoint"""
        return any(pattern in endpoint for pattern in IMPORTANT_PATTERNS)

    async def record_activity(self, token: str, endpoint: str, status_code: int):
        """Record device activity with buffering for efficiency"""
        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT device_id FROM tokens WHERE token = ?", (token,))
            result = cursor.fetchone()
            if not result:
                log.warning(f"Token not found in database during activity recording")
                return

            device_id = result[0]
            timestamp = datetime.now(timezone.utc)
            utc_timestamp = int(timestamp.timestamp())

            async with self._lock:
                stats = self.stats_buffer[device_id]
                stats['request_count'] += 1
                if status_code >= 400:
                    stats['error_count'] += 1
                stats['endpoints'].add(endpoint)
                stats['last_activity'] = utc_timestamp

                if status_code >= 400 or self._is_important_endpoint(endpoint):
                    self.buffer.append({
                        'device_id': device_id,
                        'endpoint': endpoint,
                        'status_code': status_code,
                        'timestamp': utc_timestamp
                    })

                cursor.execute(
                    """INSERT INTO device_activity 
                    (device_id, endpoint, status_code, timestamp) 
                    VALUES (?, ?, ?, ?)""", 
                    (device_id, endpoint, status_code, utc_timestamp)
                )
                conn.commit()

                if len(self.buffer) >= self.buffer_size or \
                   time.time() - self.last_flush > self.flush_interval:
                    await self.flush_buffers()

        except Exception as e:
            log.error(f"Failed to record activity: {str(e)}")
            if conn:
                conn.rollback()
        finally:
            if conn:
                conn.close()

    async def flush_buffers(self):
        """Flush buffered data to database"""
        async with self._lock:
            if not self.buffer and not self.stats_buffer:
                return

            conn = None
            try:
                conn = await self.app_state.db_manager.get_connection()
                cursor = conn.cursor()
                cursor.execute("BEGIN TRANSACTION")

                if self.buffer:
                    cursor.executemany(
                        """INSERT INTO device_activity_recent 
                        (device_id, endpoint, status_code, timestamp)
                        VALUES (?, ?, ?, ?)""",
                        [(a['device_id'], a['endpoint'], a['status_code'], a['timestamp'])
                         for a in self.buffer]
                    )

                for device_id, stats in self.stats_buffer.items():
                    cursor.execute(
                        """INSERT OR REPLACE INTO device_stats 
                        (device_id, request_count, error_count, endpoint_count, last_activity)
                        VALUES (?, 
                            COALESCE((SELECT request_count FROM device_stats WHERE device_id = ?) + ?, ?),
                            COALESCE((SELECT error_count FROM device_stats WHERE device_id = ?) + ?, ?),
                            ?,
                            ?
                        )""",
                        (
                            device_id,
                            device_id, stats['request_count'], stats['request_count'],
                            device_id, stats['error_count'], stats['error_count'],
                            len(stats['endpoints']),
                            stats['last_activity']
                        )
                    )

                cursor.execute("COMMIT")
                self.buffer.clear()
                self.stats_buffer.clear()
                self.last_flush = time.time()
                log.info("Successfully flushed activity buffers")

            except Exception as e:
                if conn:
                    cursor.execute("ROLLBACK")
                log.error(f"Failed to flush buffers: {str(e)}")
            finally:
                if conn:
                    conn.close()

    async def get_device_activity(self, device_id: str, limit: int = 100) -> List[dict]:
        """Get recent activity for a device"""
        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """SELECT endpoint, status_code, timestamp
                FROM device_activity
                WHERE device_id = ?
                ORDER BY timestamp DESC
                LIMIT ?""", 
                (device_id, limit)
            )
            
            return [{
                "endpoint": row[0],
                "status_code": row[1],
                "timestamp": datetime.fromtimestamp(row[2], tz=timezone.utc).isoformat()
            } for row in cursor.fetchall()]

        except Exception as e:
            log.error(f"Failed to get device activity: {str(e)}")
            return []
        finally:
            if conn:
                conn.close()

    async def get_device_stats(self, device_id: str) -> dict:
        """Get device statistics including token info"""
        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """SELECT request_count, error_count, endpoint_count, last_activity 
                FROM device_stats 
                WHERE device_id = ?""",
                (device_id,)
            )
            stats = cursor.fetchone()
            
            # Get token info
            cursor.execute(
                """SELECT created_at, expires_at, revoked
                FROM tokens
                WHERE device_id = ?
                ORDER BY created_at DESC
                LIMIT 1""", 
                (device_id,)
            )
            token = cursor.fetchone()

            if not stats:
                return {}

            return {
                "token_created": token[0] if token else None,
                "token_expires": token[1] if token else None,
                "token_revoked": token[2] if token else None,
                "total_requests": stats[0],
                "error_count": stats[1],
                "unique_endpoints": stats[2],
                "last_activity": datetime.fromtimestamp(stats[3], tz=timezone.utc).isoformat() if stats[3] else None
            }

        except Exception as e:
            log.error(f"Failed to get device stats: {str(e)}")
            return {}
        finally:
            if conn:
                conn.close()

    async def list_active_devices(self) -> List[dict]:
        """List all devices with active tokens and their activity counts"""
        conn = None
        try:
            conn = await self.app_state.db_manager.get_connection()
            cursor = conn.cursor()
            now = int(datetime.now(timezone.utc).timestamp())
            
            cursor.execute(
                """SELECT 
                    t.device_id,
                    t.created_at,
                    t.expires_at,
                    ds.request_count,
                    ds.last_activity
                FROM tokens t
                LEFT JOIN device_stats ds ON t.device_id = ds.device_id
                WHERE t.expires_at > ? AND t.revoked = FALSE""",
                (now,)
            )
            
            return [{
                "device_id": row[0],
                "token_created": datetime.fromtimestamp(row[1], tz=timezone.utc).isoformat(),
                "token_expires": datetime.fromtimestamp(row[2], tz=timezone.utc).isoformat(),
                "activity_count": row[3] or 0,
                "last_activity": datetime.fromtimestamp(row[4], tz=timezone.utc).isoformat() if row[4] else None
            } for row in cursor.fetchall()]

        except Exception as e:
            log.error(f"Failed to list active devices: {str(e)}")
            return []
        finally:
            if conn:
                conn.close()