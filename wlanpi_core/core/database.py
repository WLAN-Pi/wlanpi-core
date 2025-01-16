import asyncio
import sqlite3
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Optional

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
        app_state: Any,
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

    async def initialize(self) -> None:
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

    async def _ensure_database_exists(self) -> None:
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
            except Exception:
                log.exception("Unexpected error checking database")
                raise DatabaseError("Cannot ensure or verify database integrity")

    def _create_base_database(self) -> None:
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

            log.debug(
                "Created new database",
                extra={
                    "component": "database",
                    "action": "create_database",
                    "db_path": str(self.db_path),
                },
            )

        except Exception:
            log.exception(
                "Database creation failed",
                extra={
                    "component": "database",
                    "action": "create_database_error",
                    "db_path": str(self.db_path),
                },
            )
            raise DatabaseError("Database creation failed")

    async def check_integrity(self) -> bool:
        """Check database integrity and required structure
        Returns True if database checks pass, False if not
        """
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
            log.error("Database %s is corrupted", self.db_path)
            return False
        except Exception:
            log.exception("Unexpected error checking database")
            raise DatabaseError("Cannot verify database")
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    log.warning(
                        "Error closing connection during verification", exc_info=True
                    )

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

    @asynccontextmanager
    async def get_connection(self) -> AsyncGenerator[sqlite3.Connection, None]:
        """Get a database connection as an async context manager"""
        thread_id = threading.get_ident()
        connection = None

        try:
            if hasattr(self._local, "conn"):
                connection = self._local.conn
                if self._verify_connection(connection):
                    log.debug(
                        "Reusing existing connection",
                        extra={
                            "component": "database",
                            "action": "get_connection",
                            "thread_id": thread_id,
                            "connection_status": "reused",
                        },
                    )
                    yield connection
                    return

            async with self._conn_lock:
                await self._ensure_database_exists()
                connection = sqlite3.connect(self.db_path)
                connection.row_factory = sqlite3.Row

                for setting in self.database_settings:
                    connection.execute(setting)

                self._local.conn = connection

                log.debug(
                    "Created new connection",
                    extra={
                        "component": "database",
                        "action": "get_connection",
                        "thread_id": thread_id,
                        "connection_status": "new",
                    },
                )
                yield connection

        except Exception:
            log.exception(
                "Database connection error",
                extra={
                    "component": "database",
                    "action": "get_connection_error",
                    "thread_id": thread_id,
                },
            )
            if connection:
                try:
                    connection.close()
                except Exception:
                    raise DatabaseError("Could not connect to database")

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
        except Exception:
            log.exception(
                "Database size check failed",
                extra={
                    "component": "database",
                    "action": "check_size_error",
                    "db_path": str(self.db_path),
                },
            )
            return False

    async def vacuum(self) -> None:
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
                async with self.get_connection() as conn:
                    conn.execute("VACUUM")
                    conn.commit()
                    log.debug(
                        "Database vacuum completed successfully",
                        extra={"component": "database", "action": "vacuum_complete"},
                    )
            except Exception as e:
                log.exception(
                    "Database vacuum failed",
                    extra={
                        "component": "database",
                        "action": "vacuum_failed",
                    },
                )
                raise DatabaseError(f"Vacuum failed: {e}")

    async def backup(self, backup_path: Optional[Path] = None) -> None:
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
                        async with self.get_connection() as connection:
                            connection.backup(backup)
                        log.debug(
                            "Database backup completed",
                            extra={
                                "component": "database",
                                "action": "backup_complete",
                                "backup_path": str(backup_path),
                            },
                        )
                    except sqlite3.Error as e:
                        log.exception(
                            "Backup API error",
                            extra={
                                "component": "database",
                                "action": "backup_api_error",
                            },
                        )
                        raise DatabaseError(f"Backup failed: {e}")
            else:
                log.exception(
                    "Cannot backup corrupted database",
                    extra={
                        "component": "database",
                        "action": "backup_failed",
                        "reason": "integrity_check_failed",
                    },
                )
                raise DatabaseError("Database integrity check failed")
        except Exception:
            log.exception(
                "Database backup failed",
                extra={
                    "component": "database",
                    "action": "backup_failed",
                },
            )
            raise

    def _check_conn_alive(self) -> bool:
        if not hasattr(self._local, "conn"):
            return False
        try:
            self._local.conn.execute("SELECT 1").fetchone()
            return True
        except sqlite3.Error:
            return False

    async def close(self) -> None:
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
            except sqlite3.Error:
                log.exception(
                    "Error closing database connection",
                    extra={
                        "component": "database",
                        "action": "close_error",
                        "thread_id": thread_id,
                    },
                )
            finally:
                del self._local.conn


class RetentionManager:
    def __init__(self, app_state: Any, retention_days: int = 1):
        self.app_state = app_state
        self.retention_days = retention_days

    async def cleanup_old_data(self) -> None:
        """Remove old activity data"""
        try:
            async with self.app_state.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    """
                    DELETE FROM device_activity_recent
                    WHERE timestamp < datetime('now', ? || ' days')
                """,
                    (-self.retention_days,),
                )
                conn.commit()
                log.debug(f"Ran clean up data older than {self.retention_days} days")
        except Exception:
            log.exception("Retention cleanup failed")
