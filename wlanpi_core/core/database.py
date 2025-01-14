import asyncio
import sqlite3
import threading
from pathlib import Path
from typing import Optional

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class DatabaseError(Exception):
    """Base class for database errors"""


class DatabaseCorruptionError(DatabaseError):
    """Raised when database corruption is detected"""


class DatabaseManager:
    """Database management class with structured logging

    All database operations are logged with the following context:
    - component: always "database"
    - action: specific operation being performed
    - Additional context specific to the operation

    Log levels:
    - DEBUG: Connection management, routine checks
    - INFO: Database creation, significant state changes
    - WARNING: Recoverable errors
    - ERROR: Operation failures
    """

    def __init__(
        self,
        app_state,
        db_path: str = "/opt/wlanpi-core/.secrets/tokens.db",
        max_size_mb: int = 10,
    ):
        self.app_state = app_state
        self.db_path = Path(db_path)
        self.max_size_mb = max_size_mb
        self.database_settings = [
            "PRAGMA foreign_keys=ON",
            "PRAGMA journal_mode=WAL",
            "PRAGMA synchronous=NORMAL",
            "PRAGMA temp_store=MEMORY",
            "PRAGMA cache_size=-2000",
        ]
        self._local = threading.local()
        self._conn_lock = asyncio.Lock()
        self._init_lock = asyncio.Lock()

    async def initialize(self):
        log.debug(
            "Starting database initialization",
            extra={
                "component": "database",
                "action": "initialize",
                "db_path": str(self.db_path),
                "max_size_mb": self.max_size_mb,
            },
        )
        await self._ensure_database_exists()
        log.debug(
            "Database initialization complete",
            extra={"component": "database", "action": "initialize_complete"},
        )

    async def _ensure_database_exists(self):
        """
        Ensure the database file exists and is accessible.
        Create it if it doesn't exist or is corrupted.
        """
        async with self._init_lock:  # Ensure only one thread handles recovery
            try:
                if not self.db_path.exists():
                    log.warning(
                        "Database creation needed",
                        extra={
                            "component": "database",
                            "action": "create_database",
                            "db_path": str(self.db_path),
                            "reason": "not_exists",
                        },
                    )
                    self._create_base_database()
                    return

                if not await self.check_integrity():
                    log.error(
                        "Database integrity check failed",
                        extra={
                            "component": "database",
                            "action": "recreate_database",
                            "db_path": str(self.db_path),
                            "reason": "integrity_check_failed",
                        },
                    )
                    self._create_base_database()
            except Exception as e:
                log.exception(f"Unexpected error checking database: {e}")
                raise DatabaseError(f"Cannot ensure or verify database integrity: {e}")

    def _create_base_database(self):
        """
        Create a new database with base schema
        """
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

            if self.db_path.exists():
                log.debug(
                    "Removing existing database",
                    extra={
                        "component": "database",
                        "action": "create_database",
                        "db_path": str(self.db_path),
                    },
                )
                self.db_path.unlink()

            conn = sqlite3.connect(self.db_path)
            for setting in self.database_settings:
                conn.execute(setting)

            from .migrations import run_migrations

            run_migrations(conn)
            conn.close()

            log.info(
                "Created new database",
                extra={
                    "component": "database",
                    "action": "create_database",
                    "db_path": str(self.db_path),
                },
            )

        except Exception as e:
            log.error(
                "Database creation failed",
                extra={
                    "component": "database",
                    "action": "create_database_error",
                    "db_path": str(self.db_path),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            raise DatabaseError(f"Database creation failed: {e}")

    async def check_integrity(self) -> bool:
        """Check database integrity and required structure
        Returns True if database checks pass, False if not"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)

            if conn is None:
                log.error(
                    "Unable to connect to database",
                    extra={
                        "component": "database",
                        "action": "check_integrity",
                    },
                )
                return False

            cursor = conn.cursor()

            log.debug(
                "Starting database integrity check",
                extra={
                    "component": "database",
                    "action": "check_integrity",
                    "db_path": str(self.db_path),
                },
            )

            # Connection test
            cursor.execute("SELECT name FROM sqlite_master")
            cursor.fetchone()

            # Check WAL mode
            cursor.execute("PRAGMA journal_mode")
            journal_mode_result = cursor.fetchone()
            if journal_mode_result is None:
                log.error(
                    "Unable to retrieve journal mode",
                    extra={
                        "component": "database",
                        "action": "check_journal_mode",
                    },
                )
                return False

            journal_mode = journal_mode_result[0]

            if journal_mode != "wal":
                log.error(
                    "Invalid journal mode",
                    extra={
                        "component": "database",
                        "action": "check_journal_mode",
                        "expected": "wal",
                        "actual": journal_mode,
                    },
                )
                return False

            # Check required indexes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}
            required_indexes = {"idx_tokens_device_id", "idx_tokens_expires"}
            if not required_indexes.issubset(indexes):
                missing_indexes = required_indexes - indexes
                log.error(
                    "Missing required indexes",
                    extra={
                        "component": "database",
                        "action": "check_indexes",
                        "missing_indexes": list(missing_indexes),
                    },
                )
                return False

            # Check database integrity
            cursor.execute("PRAGMA integrity_check")
            if cursor.fetchone()[0] != "ok":
                log.error("Database integrity check failed")
                return False

            # Check foreign key constraints
            cursor.execute("PRAGMA foreign_key_check")
            if cursor.fetchall():
                log.error("Database foreign key check failed")
                return False

            return True

        except sqlite3.DatabaseError:
            log.error(f"Database {self.db_path} is corrupted")
            return False
        except Exception as e:
            log.exception(f"Unexpected error checking database: {e}")
            raise DatabaseError(f"Cannot verify database: {e}")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception as e:
                    log.warning(f"Error closing connection during verification: {e}")

    def _verify_connection(self, conn: sqlite3.Connection) -> bool:
        """Verify that a connection is alive and the database is valid"""
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master")
            cursor.fetchone()
            log.debug(
                "Database connection verified",
                extra={
                    "component": "database",
                    "action": "verify_connection",
                    "status": "valid",
                },
            )
            return True
        except sqlite3.DatabaseError:
            log.debug(
                "Database connection invalid",
                extra={
                    "component": "database",
                    "action": "verify_connection",
                    "status": "invalid",
                },
            )
            return False

    async def get_connection(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        log.debug(
            "Getting connection",
            extra={
                "component": "database",
                "action": "get_connection",
                "thread_id": thread_id,
            },
        )
        if hasattr(self._local, "conn") and self._verify_connection(self._local.conn):
            log.debug(
                "Reusing existing connection",
                extra={
                    "component": "database",
                    "action": "get_connection",
                    "thread_id": thread_id,
                    "connection_status": "reused",
                },
            )
            return self._local.conn

        async with self._conn_lock:
            # Check if we have a valid connection
            if hasattr(self._local, "conn"):
                if self._verify_connection(self._local.conn):
                    log.debug(
                        "Connection verified",
                        extra={
                            "component": "database",
                            "action": "verify_connection",
                            "thread_id": thread_id,
                            "connection_status": "valid",
                        },
                    )
                    return self._local.conn
                else:
                    # Close bad connection
                    try:
                        self._local.conn.close()
                        log.debug(
                            "Closed invalid connection",
                            extra={
                                "component": "database",
                                "action": "close_connection",
                                "thread_id": thread_id,
                                "connection_status": "invalid",
                            },
                        )
                    except:
                        log.warning(
                            "Failed to close invalid connection",
                            extra={
                                "component": "database",
                                "action": "close_connection",
                                "thread_id": thread_id,
                                "error": str(e),
                                "connection_status": "close_failed",
                            },
                        )
                    delattr(self._local, "conn")
            try:
                await self._ensure_database_exists()
                self._local.conn = sqlite3.connect(self.db_path)
                self._local.conn.row_factory = sqlite3.Row
                for setting in self.database_settings:
                    self._local.conn.execute(setting)
                log.debug(f"Created new connection for thread {thread_id}")
                return self._local.conn
            except sqlite3.Error as e:
                log.exception(f"Database connection error in thread {thread_id}: {e}")
                raise DatabaseError(f"Could not connect to database: {e}")

    def check_size(self) -> bool:
        """Check if database size is within limits"""
        try:
            size_mb = self.db_path.stat().st_size / (1024 * 1024)
            within_limits = size_mb <= self.max_size_mb
            log.debug(
                "Checked database size",
                extra={
                    "component": "database",
                    "action": "check_size",
                    "current_size_mb": round(size_mb, 2),
                    "max_size_mb": self.max_size_mb,
                    "within_limits": within_limits,
                },
            )
            return within_limits
        except Exception as e:
            log.error(
                "Database size check failed",
                extra={
                    "component": "database",
                    "action": "check_size_error",
                    "db_path": str(self.db_path),
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )
            return False

    async def vacuum(self):
        async with self._conn_lock:
            try:
                log.debug(
                    "Starting database vacuum",
                    extra={
                        "component": "database",
                        "action": "vacuum",
                        "db_path": str(self.db_path),
                    },
                )
                conn = await self.get_connection()
                conn.execute("VACUUM")
                conn.commit()
                log.debug(
                    "Database vacuum completed successfully",
                    extra={"component": "database", "action": "vacuum_complete"},
                )
            except Exception as e:
                log.error(
                    "Database vacuum failed",
                    extra={
                        "component": "database",
                        "action": "vacuum_failed",
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
                raise DatabaseError(f"Vacuum failed: {e}")

    async def backup(self, backup_path: Optional[Path] = None):
        """Create a backup of the database"""
        if not backup_path:
            backup_path = self.db_path.with_suffix(".db.backup")

        log.debug(
            "Starting database backup",
            extra={
                "component": "database",
                "action": "backup_start",
                "source_path": str(self.db_path),
                "backup_path": str(backup_path),
            },
        )

        try:
            if await self.check_integrity():
                backup = sqlite3.connect(backup_path)
                with backup:
                    try:
                        (await self.get_connection()).backup(backup)
                        log.debug(
                            "Database backup completed",
                            extra={
                                "component": "database",
                                "action": "backup_complete",
                                "backup_path": str(backup_path),
                            },
                        )
                    except sqlite3.Error as e:
                        log.error(
                            "Backup API error",
                            extra={
                                "component": "database",
                                "action": "backup_api_error",
                                "error": str(e),
                                "error_type": type(e).__name__,
                            },
                        )
                        raise DatabaseError(f"Backup failed: {e}")
            else:
                log.error(
                    "Cannot backup corrupted database",
                    extra={
                        "component": "database",
                        "action": "backup_failed",
                        "reason": "integrity_check_failed",
                    },
                )
        except Exception as e:
            log.error(
                "Database backup failed",
                extra={
                    "component": "database",
                    "action": "backup_failed",
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
            )

    def _check_conn_alive(self) -> bool:
        if not hasattr(self._local, "conn"):
            return False
        try:
            self._local.conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    async def close(self):
        """Close database connection"""
        thread_id = threading.get_ident()

        if hasattr(self._local, "conn"):
            log.debug(
                "Closing database connection",
                extra={
                    "component": "database",
                    "action": "close_connection",
                    "thread_id": thread_id,
                },
            )
            try:
                self._local.conn.close()
                log.debug(
                    "Database connection closed successfully",
                    extra={
                        "component": "database",
                        "action": "close_complete",
                        "thread_id": thread_id,
                    },
                )
            except sqlite3.Error as e:
                log.warning(
                    "Error closing database connection",
                    extra={
                        "component": "database",
                        "action": "close_error",
                        "thread_id": thread_id,
                        "error": str(e),
                        "error_type": type(e).__name__,
                    },
                )
            finally:
                del self._local.conn


class RetentionManager:
    def __init__(self, app: None, retention_days: int = 1):
        self.app = app
        self.retention_days = retention_days

    async def cleanup_old_data(self):
        """Remove old activity data"""
        try:
            conn = await self.app.db_manager.get_connection()
            cursor = conn.cursor()
            cursor.execute(
                """
                DELETE FROM device_activity_recent 
                WHERE timestamp < datetime('now', ? || ' days')
            """,
                (-self.retention_days,),
            )
            conn.commit()
            log.info(f"Ran clean up data older than {self.retention_days} days")
        except Exception as e:
            log.exception(f"Retention cleanup failed: {e}")
            conn.rollback()
