from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)

MIGRATIONS = [
    """
    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY,
        applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS signing_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        key TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        active BOOLEAN DEFAULT TRUE
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS tokens (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token TEXT NOT NULL UNIQUE,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        expires_at TIMESTAMP NOT NULL,
        key_id INTEGER NOT NULL,
        device_id TEXT NOT NULL UNIQUE,
        revoked BOOLEAN DEFAULT FALSE,
        FOREIGN KEY (key_id) REFERENCES signing_keys (id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tokens_device_id ON tokens(device_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_tokens_expires ON tokens(expires_at);
    """,
    """
    CREATE TABLE IF NOT EXISTS device_activity (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        device_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        FOREIGN KEY (device_id) REFERENCES tokens (device_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_activity_device ON device_activity(device_id);
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_activity_timestamp ON device_activity(timestamp);
    """,
    """
    CREATE TABLE IF NOT EXISTS device_stats (
        device_id TEXT PRIMARY KEY,
        request_count INTEGER DEFAULT 0,
        error_count INTEGER DEFAULT 0,
        endpoint_count INTEGER DEFAULT 0,
        last_activity TIMESTAMP,
        FOREIGN KEY (device_id) REFERENCES tokens (device_id)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS device_activity_recent (
        id INTEGER PRIMARY KEY,
        device_id TEXT NOT NULL,
        endpoint TEXT NOT NULL,
        status_code INTEGER NOT NULL,
        timestamp TIMESTAMP NOT NULL,
        FOREIGN KEY (device_id) REFERENCES tokens (device_id)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_activity_recent_timestamp ON device_activity_recent(timestamp)
    """,
    """
    CREATE INDEX IF NOT EXISTS idx_activity_recent_device ON device_activity_recent(device_id)
    """,
    """
    CREATE TRIGGER IF NOT EXISTS cleanup_old_activity
    AFTER INSERT ON device_activity_recent
    BEGIN
        DELETE FROM device_activity_recent
        WHERE timestamp < datetime('now', '-1 day');
    END
    """,
]


def get_db_version(cursor) -> int:
    try:
        cursor.execute("SELECT MAX(version) FROM schema_version")
        version = cursor.fetchone()[0]
        return version if version is not None else 0
    except:
        return 0


def run_migrations(conn):
    """Run any pending database migrations.

    Args:
        conn: SQLite database connection provided by DatabaseManager

    Raises:
        Exception: If any migration fails
    """
    cursor = conn.cursor()

    try:
        # Create schema version table if it doesn't exist
        cursor.execute(MIGRATIONS[0])
        conn.commit()

        # Get current version
        current_version = get_db_version(cursor)

        # Start transaction for remaining migrations
        conn.execute("BEGIN TRANSACTION")

        # Run any new migrations
        for version, migration in enumerate(MIGRATIONS[1:], start=1):
            if version > current_version:
                log.debug(f"Applying migration {version}")

                if "CREATE TRIGGER" in migration:
                    cursor.execute(migration)
                else:
                    # Split and execute each statement separately for non-trigger migrations
                    statements = [
                        stmt.strip() for stmt in migration.split(";") if stmt.strip()
                    ]
                    for statement in statements:
                        cursor.execute(statement)

                # Record this migration
                cursor.execute(
                    "INSERT INTO schema_version (version) VALUES (?)", (version,)
                )

                log.debug(f"Successfully applied migration {version}")

        # Commit all migrations
        conn.commit()

    except Exception as e:
        log.error(f"Migration failed: {e}")
        conn.rollback()
        raise
