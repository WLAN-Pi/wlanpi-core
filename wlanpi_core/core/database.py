from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import AsyncGenerator, Optional, TypeVar

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.ext.asyncio import (
    AsyncAttrs,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column

from wlanpi_core.constants import DATABASE_PATH
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class DatabaseError(Exception):
    """Base class for database errors"""


# Naming convention for database constraints to support migrations
convention = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}
metadata = MetaData(naming_convention=convention)


class Base(AsyncAttrs, DeclarativeBase):
    """
    Base class for SQLAlchemy models with additional helper methods

    Provides:
    - Automatic table naming (snake_case)
    - Metadata with naming conventions
    - Timestamps for created/updated records
    """

    metadata = metadata

    @declared_attr.directive
    def __tablename__(cls) -> str:
        """
        Convert CamelCase class names to snake_case table names
        e.g. DeviceActivity -> device_activity
        """
        return "".join(
            ["_" + c.lower() if c.isupper() else c for c in cls.__name__]
        ).lstrip("_")

    created_at: Mapped[DateTime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[Optional[DateTime]] = mapped_column(
        DateTime, onupdate=func.now(), nullable=True
    )


ModelType = TypeVar("ModelType", bound=Base)


class DatabaseManager:
    """
    Async database management class with connection pooling and session handling

    Supports:
    - Async engine creation
    - Connection pooling
    - Session management
    - Logging and error handling
    """

    def __init__(
        self,
        database_url: Optional[str] = None,
        echo: bool = False,
        pool_recycle: int = 1800,
    ):
        """
        Initialize async database engine and session factory

        Args:
            database_url: Database connection URL (defaults to sqlite+aiosqlite)
            echo: Whether to log SQL statements
            pool_recycle: Recycle connections after this many seconds (optional)
        """
        if database_url is None:
            database_url = f"sqlite+aiosqlite:///{DATABASE_PATH}"

        try:
            self._engine = create_async_engine(database_url, echo=echo)

            self._async_session_factory = async_sessionmaker(
                bind=self._engine,
                class_=AsyncSession,
                expire_on_commit=False,
                autoflush=False,
            )

            self._initialized = False
            self._lock = asyncio.Lock()

            log.debug(
                "Database engine initialized",
                extra={
                    "component": "database",
                    "action": "initialize",
                    "database_url": database_url,
                    "echo": echo,
                },
            )

        except Exception as e:
            log.error(
                "Database engine initialization failed",
                extra={
                    "component": "database",
                    "action": "init_error",
                    "error": str(e),
                },
            )
            raise

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncGenerator[AsyncSession, None]:
        """
        Async context manager for database sessions

        Yields:
            An async database session
        """
        async with self._async_session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def initialize_models(self):
        """
        Create all database tables defined in models
        """
        async with self._lock:
            if self._initialized:
                return

            log.info("Initializing database")
            try:
                db_path = Path(DATABASE_PATH).parent
                db_path.mkdir(parents=True, exist_ok=True)

                async with self._engine.begin() as conn:
                    await conn.run_sync(Base.metadata.create_all)

                self._initialized = True

                log.debug(
                    "Database tables initialized",
                    extra={"component": "database", "action": "initialize_models"},
                )
            except Exception as e:
                log.error(
                    "Database tables initialization failed",
                    extra={"component": "database", "action": "initialize_models"},
                    exc_info=e,
                )
                raise

    async def cleanup(self) -> None:
        """Cleanup database connections"""
        if self._engine:
            await self._engine.dispose()
            log.debug("Database connections cleaned up")


class BaseRepository:
    """
    Generic async repository with common CRUD operations

    Can be inherited by specific model repositories
    """

    def __init__(self, session: AsyncSession):
        self._session = session

    async def add(self, model: ModelType) -> ModelType:
        """Add a new model instance to the database"""
        self._session.add(model)
        await self._session.flush()
        return model

    async def add_all(self, models: list[ModelType]) -> list[ModelType]:
        """Add multiple model instances to the database"""
        self._session.add_all(models)
        await self._session.flush()
        return models

    async def delete(self, model: ModelType) -> None:
        """Delete a model instance from the database"""
        await self._session.delete(model)
        await self._session.flush()

    async def merge(self, model: ModelType) -> ModelType:
        """Update an existing model instance"""
        model = await self._session.merge(model)
        await self._session.flush()
        return model
