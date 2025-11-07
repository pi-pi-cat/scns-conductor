"""
基础 Repository - 提供通用的数据库操作模式

使用泛型和上下文管理器减少重复代码
"""

from contextlib import asynccontextmanager
from typing import TypeVar, Generic, Optional, List, Type, Dict, Any, Callable
from datetime import datetime

from sqlalchemy import select, update, delete, func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import SQLModel
from loguru import logger

from core.database import async_db


T = TypeVar("T", bound=SQLModel)


class BaseRepository(Generic[T]):
    """
    基础仓储类 - 提供通用的 CRUD 操作

    使用方法:
        class JobRepository(BaseRepository[Job]):
            model = Job

    优势:
        1. 消除重复的会话管理代码
        2. 统一的错误处理
        3. 自动化的日志记录
        4. 类型安全
    """

    model: Type[T] = None  # 子类必须设置

    @classmethod
    @asynccontextmanager
    async def _session(cls):
        """
        统一的会话管理上下文

        自动处理:
        - 会话创建
        - 事务提交
        - 错误回滚
        - 资源释放
        - 日志记录
        """
        start_time = datetime.utcnow()
        async with async_db.get_session() as session:
            try:
                yield session
                duration = (datetime.utcnow() - start_time).total_seconds()
                logger.debug(f"[{cls.__name__}] DB操作耗时: {duration:.3f}s")
            except Exception as e:
                logger.error(f"[{cls.__name__}] DB操作失败: {e}")
                raise

    @classmethod
    async def create(cls, data: Dict[str, Any]) -> T:
        """
        创建记录

        Args:
            data: 数据字典

        Returns:
            创建的对象
        """
        async with cls._session() as session:
            instance = cls.model(**data)
            session.add(instance)
            await session.flush()
            await session.refresh(instance)
            logger.debug(f"[{cls.__name__}] 创建成功: {instance.id}")
            return instance

    @classmethod
    async def get_by_id(cls, id: int) -> Optional[T]:
        """
        根据ID获取记录

        Args:
            id: 记录ID

        Returns:
            对象或None
        """
        async with cls._session() as session:
            return await session.get(cls.model, id)

    @classmethod
    async def get_by_ids(cls, ids: List[int]) -> List[T]:
        """
        根据ID列表批量获取

        Args:
            ids: ID列表

        Returns:
            对象列表
        """
        if not ids:
            return []

        async with cls._session() as session:
            query = select(cls.model).where(cls.model.id.in_(ids))
            result = await session.execute(query)
            return list(result.scalars().all())

    @classmethod
    async def get_all(cls, limit: int = 100, offset: int = 0) -> List[T]:
        """
        获取所有记录（分页）

        Args:
            limit: 返回数量限制
            offset: 偏移量

        Returns:
            对象列表
        """
        async with cls._session() as session:
            query = select(cls.model).limit(limit).offset(offset)
            result = await session.execute(query)
            return list(result.scalars().all())

    @classmethod
    async def update_by_id(cls, id: int, data: Dict[str, Any]) -> bool:
        """
        根据ID更新记录

        Args:
            id: 记录ID
            data: 更新数据

        Returns:
            是否更新成功
        """
        async with cls._session() as session:
            stmt = update(cls.model).where(cls.model.id == id).values(**data)
            result = await session.execute(stmt)
            success = result.rowcount > 0
            if success:
                logger.debug(f"[{cls.__name__}] 更新成功: id={id}")
            return success

    @classmethod
    async def delete_by_id(cls, id: int) -> bool:
        """
        根据ID删除记录

        Args:
            id: 记录ID

        Returns:
            是否删除成功
        """
        async with cls._session() as session:
            stmt = delete(cls.model).where(cls.model.id == id)
            result = await session.execute(stmt)
            success = result.rowcount > 0
            if success:
                logger.debug(f"[{cls.__name__}] 删除成功: id={id}")
            return success

    @classmethod
    async def count(cls, **filters) -> int:
        """
        统计记录数

        Args:
            **filters: 过滤条件

        Returns:
            记录总数
        """
        async with cls._session() as session:
            query = select(func.count()).select_from(cls.model)

            # 应用过滤条件
            for key, value in filters.items():
                if hasattr(cls.model, key) and value is not None:
                    query = query.where(getattr(cls.model, key) == value)

            result = await session.execute(query)
            return result.scalar_one()

    @classmethod
    async def exists(cls, id: int) -> bool:
        """
        检查记录是否存在

        Args:
            id: 记录ID

        Returns:
            是否存在
        """
        async with cls._session() as session:
            query = (
                select(func.count()).select_from(cls.model).where(cls.model.id == id)
            )
            result = await session.execute(query)
            return result.scalar_one() > 0

    @classmethod
    async def find_one(cls, **filters) -> Optional[T]:
        """
        根据条件查找单个记录

        Args:
            **filters: 过滤条件

        Returns:
            对象或None
        """
        async with cls._session() as session:
            query = select(cls.model)

            for key, value in filters.items():
                if hasattr(cls.model, key) and value is not None:
                    query = query.where(getattr(cls.model, key) == value)

            result = await session.execute(query)
            return result.scalar_one_or_none()

    @classmethod
    async def find_many(
        cls,
        limit: int = 100,
        offset: int = 0,
        order_by: Optional[str] = None,
        desc: bool = True,
        **filters,
    ) -> List[T]:
        """
        根据条件查找多个记录

        Args:
            limit: 返回数量限制
            offset: 偏移量
            order_by: 排序字段名
            desc: 是否降序
            **filters: 过滤条件

        Returns:
            对象列表
        """
        async with cls._session() as session:
            query = select(cls.model)

            # 应用过滤条件
            for key, value in filters.items():
                if hasattr(cls.model, key) and value is not None:
                    query = query.where(getattr(cls.model, key) == value)

            # 排序
            if order_by and hasattr(cls.model, order_by):
                order_column = getattr(cls.model, order_by)
                query = query.order_by(
                    order_column.desc() if desc else order_column.asc()
                )

            # 分页
            query = query.limit(limit).offset(offset)

            result = await session.execute(query)
            return list(result.scalars().all())

    @classmethod
    async def batch_update(cls, ids: List[int], data: Dict[str, Any]) -> int:
        """
        批量更新

        Args:
            ids: ID列表
            data: 更新数据

        Returns:
            更新的记录数
        """
        if not ids:
            return 0

        async with cls._session() as session:
            stmt = update(cls.model).where(cls.model.id.in_(ids)).values(**data)
            result = await session.execute(stmt)
            count = result.rowcount
            logger.debug(f"[{cls.__name__}] 批量更新: {count}条")
            return count

    @classmethod
    async def batch_delete(cls, ids: List[int]) -> int:
        """
        批量删除

        Args:
            ids: ID列表

        Returns:
            删除的记录数
        """
        if not ids:
            return 0

        async with cls._session() as session:
            stmt = delete(cls.model).where(cls.model.id.in_(ids))
            result = await session.execute(stmt)
            count = result.rowcount
            logger.debug(f"[{cls.__name__}] 批量删除: {count}条")
            return count


class QueryBuilder:
    """
    查询构建器 - 提供链式调用的查询接口

    示例:
        jobs = await (
            QueryBuilder(Job)
            .where(state=JobState.RUNNING)
            .where(partition="compute")
            .order_by("submit_time", desc=True)
            .limit(10)
            .execute()
        )
    """

    def __init__(self, model: Type[T]):
        self.model = model
        self._query = select(model)
        self._filters = []

    def where(self, **conditions):
        """添加where条件"""
        for key, value in conditions.items():
            if hasattr(self.model, key) and value is not None:
                self._filters.append(getattr(self.model, key) == value)
        return self

    def order_by(self, field: str, desc: bool = True):
        """添加排序"""
        if hasattr(self.model, field):
            column = getattr(self.model, field)
            self._query = self._query.order_by(column.desc() if desc else column.asc())
        return self

    def limit(self, limit: int):
        """添加限制"""
        self._query = self._query.limit(limit)
        return self

    def offset(self, offset: int):
        """添加偏移"""
        self._query = self._query.offset(offset)
        return self

    async def execute(self) -> List[T]:
        """执行查询"""
        # 应用所有过滤条件
        for condition in self._filters:
            self._query = self._query.where(condition)

        async with async_db.get_session() as session:
            result = await session.execute(self._query)
            return list(result.scalars().all())

    async def first(self) -> Optional[T]:
        """获取第一个结果"""
        results = await self.limit(1).execute()
        return results[0] if results else None

    async def count(self) -> int:
        """获取结果数量"""
        # 应用过滤条件
        count_query = select(func.count()).select_from(self.model)
        for condition in self._filters:
            count_query = count_query.where(condition)

        async with async_db.get_session() as session:
            result = await session.execute(count_query)
            return result.scalar_one()
