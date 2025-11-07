"""
数据库连接管理 - 支持异步和同步两种模式
- 异步连接用于 FastAPI（使用 asyncpg）
- 同步连接用于 RQ workers（使用 psycopg2）
"""

from contextlib import asynccontextmanager, contextmanager
from typing import AsyncIterator, Iterator, Optional

from sqlalchemy import create_engine, event, pool
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import Session, sessionmaker
from sqlmodel import SQLModel
from loguru import logger

from .config import get_settings
from .utils.singleton import singleton


@singleton
class AsyncDatabaseManager:
    """
    Async database connection manager for FastAPI
    Uses asyncpg driver for high-performance async operations
    """

    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    def init(self) -> None:
        """Initialize async database engine and session factory"""
        if self._engine is not None:
            logger.warning("AsyncDatabaseManager already initialized")
            return

        settings = get_settings()
        database_url = settings.get_database_url(async_driver=True)

        # Create async engine with connection pooling
        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,  # Verify connections before using
            pool_recycle=3600,  # Recycle connections after 1 hour
        )

        # Create session factory
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        logger.info("Async database manager initialized")

    async def close(self) -> None:
        """Close database engine and cleanup connections"""
        if self._engine:
            await self._engine.dispose()
            logger.info("Async database connections closed")

    @asynccontextmanager
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """
        Get database session as async context manager

        Usage:
            async with async_db.get_session() as session:
                result = await session.execute(query)
        """
        if self._session_factory is None:
            raise RuntimeError(
                "AsyncDatabaseManager not initialized. Call init() first."
            )

        async with self._session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise
            finally:
                await session.close()

    async def create_tables(self) -> None:
        """创建所有数据库表（用于开发/测试）"""
        if self._engine is None:
            raise RuntimeError("AsyncDatabaseManager not initialized")

        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        logger.info("Database tables created")

    @property
    def engine(self) -> AsyncEngine:
        """Get the async engine instance"""
        if self._engine is None:
            raise RuntimeError("AsyncDatabaseManager not initialized")
        return self._engine


@singleton
class SyncDatabaseManager:
    """
    Sync database connection manager for RQ workers
    Uses psycopg2 driver for compatibility with RQ
    """

    def __init__(self):
        self._engine: Optional[create_engine] = None
        self._session_factory: Optional[sessionmaker[Session]] = None

    def init(self) -> None:
        """Initialize sync database engine and session factory"""
        if self._engine is not None:
            logger.warning("SyncDatabaseManager already initialized")
            return

        settings = get_settings()
        database_url = settings.get_database_url(async_driver=False)

        # Create sync engine with connection pooling
        self._engine = create_engine(
            database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            poolclass=pool.QueuePool,
        )

        # Enable pessimistic disconnect handling
        @event.listens_for(self._engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            connection_record.info["pid"] = dbapi_conn.get_backend_pid()

        # Create session factory
        self._session_factory = sessionmaker(
            self._engine,
            class_=Session,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        logger.info("Sync database manager initialized")

    def close(self) -> None:
        """Close database engine and cleanup connections"""
        if self._engine:
            self._engine.dispose()
            logger.info("Sync database connections closed")

    @contextmanager
    def get_session(self) -> Iterator[Session]:
        """
        Get database session as sync context manager

        Usage:
            with sync_db.get_session() as session:
                result = session.execute(query)
        """
        if self._session_factory is None:
            raise RuntimeError(
                "SyncDatabaseManager not initialized. Call init() first."
            )

        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def create_tables(self) -> None:
        """创建所有数据库表（用于开发/测试）"""
        if self._engine is None:
            raise RuntimeError("SyncDatabaseManager not initialized")

        SQLModel.metadata.create_all(self._engine)
        logger.info("Database tables created")

    @property
    def engine(self):
        """Get the sync engine instance"""
        if self._engine is None:
            raise RuntimeError("SyncDatabaseManager not initialized")
        return self._engine


# Global instances
async_db = AsyncDatabaseManager()
sync_db = SyncDatabaseManager()


# FastAPI 依赖
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """
    FastAPI 依赖函数，用于获取异步数据库会话

    使用方法:
        @app.get("/items")
        async def get_items(session: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with async_db.get_session() as session:
        yield session
