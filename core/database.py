"""
数据库连接管理 - 支持异步和同步两种模式
- 异步用于 FastAPI（使用 asyncpg）
- 同步用于 RQ workers（使用 psycopg2）
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
from .exceptions import DatabaseNotInitializedException


@singleton
class AsyncDatabaseManager:
    """
    FastAPI 异步数据库连接管理器
    使用 asyncpg 驱动实现高性能异步数据库操作
    """

    def __init__(self):
        self._engine: Optional[AsyncEngine] = None
        self._session_factory: Optional[async_sessionmaker[AsyncSession]] = None

    def init(self) -> None:
        """初始化异步数据库引擎和会话工厂"""
        if self._engine is not None:
            logger.warning("AsyncDatabaseManager 已经初始化过")
            return

        settings = get_settings()
        database_url = settings.get_database_url(async_driver=True)

        # 创建带连接池的异步引擎
        self._engine = create_async_engine(
            database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,  # 使用前验证连接
            pool_recycle=3600,  # 1 小时后回收连接
        )

        # 创建会话工厂
        self._session_factory = async_sessionmaker(
            self._engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        logger.info("异步数据库管理器初始化完成")

    async def close(self) -> None:
        """关闭数据库引擎并清理连接"""
        if self._engine:
            await self._engine.dispose()
            logger.info("异步数据库连接已关闭")

    @asynccontextmanager
    async def get_session(self) -> AsyncIterator[AsyncSession]:
        """
        获取一个异步数据库会话（上下文管理器）

        用法示例：
            async with async_db.get_session() as session:
                result = await session.execute(query)
        """
        if self._session_factory is None:
            raise DatabaseNotInitializedException("AsyncDatabaseManager")

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
            raise DatabaseNotInitializedException("AsyncDatabaseManager")

        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        logger.info("数据库表已创建")

    @property
    def engine(self) -> AsyncEngine:
        """获取异步引擎实例"""
        if self._engine is None:
            raise DatabaseNotInitializedException("AsyncDatabaseManager")
        return self._engine

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._engine is not None


@singleton
class SyncDatabaseManager:
    """
    RQ workers 同步数据库连接管理器
    使用 psycopg2 驱动以兼容 RQ
    """

    def __init__(self):
        self._engine: Optional[create_engine] = None
        self._session_factory: Optional[sessionmaker[Session]] = None

    def init(self) -> None:
        """初始化同步数据库引擎和会话工厂"""
        if self._engine is not None:
            logger.warning("SyncDatabaseManager 已经初始化过")
            return

        settings = get_settings()
        database_url = settings.get_database_url(async_driver=False)

        # 创建带连接池的同步引擎
        self._engine = create_engine(
            database_url,
            echo=False,
            pool_size=20,
            max_overflow=10,
            pool_pre_ping=True,
            pool_recycle=3600,
            poolclass=pool.QueuePool,
        )

        # 启用断连检查
        @event.listens_for(self._engine, "connect")
        def receive_connect(dbapi_conn, connection_record):
            connection_record.info["pid"] = dbapi_conn.get_backend_pid()

        # 创建会话工厂
        self._session_factory = sessionmaker(
            self._engine,
            class_=Session,
            expire_on_commit=False,
            autocommit=False,
            autoflush=False,
        )

        logger.info("同步数据库管理器初始化完成")

    def close(self) -> None:
        """关闭数据库引擎并清理连接"""
        if self._engine:
            self._engine.dispose()
            logger.info("同步数据库连接已关闭")

    @contextmanager
    def get_session(self) -> Iterator[Session]:
        """
        获取一个同步数据库会话（上下文管理器）

        用法示例：
            with sync_db.get_session() as session:
                result = session.execute(query)
        """
        if self._session_factory is None:
            raise DatabaseNotInitializedException("SyncDatabaseManager")

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
            raise DatabaseNotInitializedException("SyncDatabaseManager")

        SQLModel.metadata.create_all(self._engine)
        logger.info("数据库表已创建")

    @property
    def engine(self):
        """获取同步引擎实例"""
        if self._engine is None:
            raise DatabaseNotInitializedException("SyncDatabaseManager")
        return self._engine

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._engine is not None


# 全局实例
async_db = AsyncDatabaseManager()
sync_db = SyncDatabaseManager()


# FastAPI 依赖项
async def get_async_session() -> AsyncIterator[AsyncSession]:
    """
    FastAPI 依赖函数：获取异步数据库会话

    用法示例:
        @app.get("/items")
        async def get_items(session: AsyncSession = Depends(get_async_session)):
            ...
    """
    async with async_db.get_session() as session:
        yield session
