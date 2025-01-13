import asyncio
import logging
import sqlite3
from pathlib import Path
import threading
from typing import Optional

from wlanpi_core.core.auth import to_timestamp

log = logging.getLogger("uvicorn")


class DatabaseError(Exception):
    """Base class for database errors"""



class DatabaseCorruptionError(DatabaseError):
    """Raised when database corruption is detected"""



class DatabaseManager:
    def __init__(
        self,
        app_state,
        db_path: str = "/opt/wlanpi-core/.secrets/tokens.db",
        max_size_mb: int = 10
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
        await self._ensure_database_exists()

    async def _ensure_database_exists(self):
        """
        Ensure the database file exists and is accessible.
        Create it if it doesn't exist or is corrupted.
        """
        async with self._init_lock:  # Ensure only one thread handles recovery
            try:
                if not self.db_path.exists():
                    log.warning(
                        f"Database does not exist. Creating a new one."
                    )
                    self._create_base_database()
                    return

                if not await self.check_integrity():
                    log.error(f"Database {self.db_path} failed integrity check. Recreating.")
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
                self.db_path.unlink()

            conn = sqlite3.connect(self.db_path)
            for setting in self.database_settings:
                conn.execute(setting)

            from .migrations import run_migrations
            run_migrations(conn)
            conn.close()

            log.info(f"Created new database at {self.db_path}")
        except Exception as e:
            log.exception(f"Failed to create base database: {e}")
            raise DatabaseError(f"Database creation failed: {e}")

    async def check_integrity(self) -> bool:
        """Check database integrity and required structure
        Returns True if database checks pass, False if not"""
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Connection test
            cursor.execute("SELECT name FROM sqlite_master")
            cursor.fetchone()
            
            # Check WAL mode
            cursor.execute("PRAGMA journal_mode")
            if cursor.fetchone()[0] != "wal":
                log.error("Database not in WAL mode")
                return False

            # Check required indexes
            cursor.execute("SELECT name FROM sqlite_master WHERE type='index'")
            indexes = {row[0] for row in cursor.fetchall()}
            required_indexes = {"idx_tokens_device_id", "idx_tokens_expires"}
            if not required_indexes.issubset(indexes):
                log.error("Database missing required indexes")
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
            return True
        except sqlite3.DatabaseError:
            return False

    async def get_connection(self) -> sqlite3.Connection:
        thread_id = threading.get_ident()
        if hasattr(self._local, "conn") and self._verify_connection(self._local.conn):
            return self._local.conn
        
        async with self._conn_lock:
            # Check if we have a valid connection
            if hasattr(self._local, "conn"):
                if self._verify_connection(self._local.conn):
                    return self._local.conn
                else:
                    # Close bad connection
                    try:
                        self._local.conn.close()
                    except:
                        pass
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
            return size_mb <= self.max_size_mb
        except Exception as e:
            log.exception(f"Database size check failed: {e}")
            return False

    async def vacuum(self):
        async with self._conn_lock:
            try:
                conn = await self.get_connection()
                conn.execute("VACUUM")
                conn.commit()
                log.info("Database vacuum completed")
            except Exception as e:
                log.exception(f"Database vacuum failed: {e}")
                raise DatabaseError(f"Vacuum failed: {e}")

    async def backup(self, backup_path: Optional[Path] = None):
        """Create a backup of the database"""
        if not backup_path:
            backup_path = self.db_path.with_suffix(".db.backup")

        try:
            if await self.check_integrity():
                backup = sqlite3.connect(backup_path)
                with backup:
                    try:
                        (await self.get_connection()).backup(backup)
                    except sqlite3.Error as e:
                        log.exception(f"Backup API failed: {e}")
                        raise DatabaseError(f"Backup failed: {e}")
                log.info(f"Database backup created")
            else:
                log.exception("Won't backup corrupted database")
        except Exception as e:
            log.exception(f"Database backup failed: {e}")

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
        if hasattr(self._local, "conn"):
            try:
                self._local.conn.close()
            except sqlite3.Error:
                pass
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
