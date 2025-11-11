"""
Resource Manager - 资源管理器（门面模式）

职责：
- 统一管理资源分配和释放
- 封装 Redis 缓存操作
- 提供清晰的资源管理 API
- 同步数据库和缓存状态
"""

from contextlib import contextmanager
from typing import Optional

from loguru import logger
from redis import Redis
from sqlalchemy import func
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import sync_db
from core.models import ResourceAllocation
from core.redis_client import redis_manager
from core.services.worker_repository import WorkerRepository


class ResourceCache:
    """资源缓存抽象（策略模式）"""

    # Redis 键名常量
    KEY_ALLOCATED_CPUS = "resource:allocated_cpus"
    KEY_AVAILABLE_CPUS = "resource:available_cpus"

    def __init__(self, redis_client: Optional[Redis] = None):
        """
        初始化缓存

        Args:
            redis_client: Redis 客户端（可选，用于依赖注入）
        """
        self._redis = redis_client or redis_manager.get_connection()

    def get_allocated_cpus(self) -> Optional[int]:
        """
        获取已分配的 CPU 数量

        Returns:
            CPU 数量或 None（缓存未命中）
        """
        try:
            value = self._redis.get(self.KEY_ALLOCATED_CPUS)
            return int(value) if value is not None else None
        except Exception as e:
            logger.error(f"Failed to get allocated CPUs from cache: {e}")
            return None

    def set_allocated_cpus(self, cpus: int) -> bool:
        """
        设置已分配的 CPU 数量

        Args:
            cpus: CPU 数量

        Returns:
            True 如果设置成功
        """
        try:
            self._redis.set(self.KEY_ALLOCATED_CPUS, cpus)
            return True
        except Exception as e:
            logger.error(f"Failed to set allocated CPUs in cache: {e}")
            return False

    def increment_allocated(self, cpus: int) -> bool:
        """
        增加已分配的 CPU 数量

        Args:
            cpus: 要增加的 CPU 数量

        Returns:
            True 如果操作成功
        """
        try:
            self._redis.incrby(self.KEY_ALLOCATED_CPUS, cpus)
            logger.debug(f"Incremented allocated CPUs by {cpus}")
            return True
        except Exception as e:
            logger.error(f"Failed to increment allocated CPUs: {e}")
            return False

    def decrement_allocated(self, cpus: int) -> bool:
        """
        减少已分配的 CPU 数量

        Args:
            cpus: 要减少的 CPU 数量

        Returns:
            True 如果操作成功
        """
        try:
            self._redis.decrby(self.KEY_ALLOCATED_CPUS, cpus)
            logger.debug(f"Decremented allocated CPUs by {cpus}")
            return True
        except Exception as e:
            logger.error(f"Failed to decrement allocated CPUs: {e}")
            return False

    def clear(self) -> bool:
        """
        清空缓存

        Returns:
            True 如果操作成功
        """
        try:
            self._redis.delete(self.KEY_ALLOCATED_CPUS, self.KEY_AVAILABLE_CPUS)
            return True
        except Exception as e:
            logger.error(f"Failed to clear cache: {e}")
            return False


class ResourceManager:
    """
    资源管理器 - 门面模式

    统一管理所有资源相关操作，提供简洁的 API
    """

    def __init__(
        self,
        worker_repo: Optional[WorkerRepository] = None,
        cache: Optional[ResourceCache] = None,
    ):
        """
        初始化资源管理器

        Args:
            worker_repo: Worker 仓储（可选，用于依赖注入）
            cache: 资源缓存（可选，用于依赖注入）
        """
        self.settings = get_settings()
        self.worker_repo = worker_repo or WorkerRepository()
        self.cache = cache or ResourceCache()

    # ==================== 资源查询 ====================

    def get_total_cpus(self) -> int:
        """
        获取总 CPU 数量（动态）

        从所有活跃 Worker 获取

        Returns:
            总 CPU 数量
        """
        try:
            total_cpus = self.worker_repo.get_total_cpus()

            if total_cpus == 0:
                logger.warning("No active workers found")
                # 降级：使用配置文件中的值
                return self.settings.TOTAL_CPUS

            return total_cpus

        except Exception as e:
            logger.error(f"Failed to get total CPUs: {e}")
            return self.settings.TOTAL_CPUS

    def get_allocated_cpus(self, use_cache: bool = True) -> int:
        """
        获取已分配的 CPU 数量

        Args:
            use_cache: 是否使用缓存（默认 True）

        Returns:
            已分配的 CPU 数量
        """
        # 1. 尝试从缓存获取
        if use_cache:
            cached = self.cache.get_allocated_cpus()
            if cached is not None:
                return cached

            logger.debug("Cache miss, querying database")

        # 2. 从数据库查询
        allocated = self._query_allocated_cpus_from_db()

        # 3. 更新缓存
        self.cache.set_allocated_cpus(allocated)

        return allocated

    def get_available_cpus(self) -> int:
        """
        获取可用的 CPU 数量

        Returns:
            可用的 CPU 数量
        """
        total = self.get_total_cpus()
        allocated = self.get_allocated_cpus()
        return max(0, total - allocated)

    def get_utilization(self) -> float:
        """
        获取资源利用率

        Returns:
            利用率百分比 (0.0 - 100.0)
        """
        total = self.get_total_cpus()
        if total == 0:
            return 0.0

        allocated = self.get_allocated_cpus()
        return (allocated / total) * 100.0

    def get_stats(self) -> dict:
        """
        获取资源统计信息

        Returns:
            统计信息字典
        """
        total = self.get_total_cpus()
        allocated = self.get_allocated_cpus()
        available = total - allocated
        utilization = self.get_utilization()
        worker_count = self.worker_repo.count()

        return {
            "total_cpus": total,
            "allocated_cpus": allocated,
            "available_cpus": available,
            "utilization": utilization,
            "active_workers": worker_count,
        }

    # ==================== 资源操作 ====================

    def allocate(self, cpus: int) -> bool:
        """
        分配资源（仅更新缓存）

        Args:
            cpus: 要分配的 CPU 数量

        Returns:
            True 如果分配成功
        """
        return self.cache.increment_allocated(cpus)

    def release(self, cpus: int) -> bool:
        """
        释放资源（仅更新缓存）

        Args:
            cpus: 要释放的 CPU 数量

        Returns:
            True 如果释放成功
        """
        return self.cache.decrement_allocated(cpus)

    # ==================== 缓存同步 ====================

    def sync_cache_from_db(self) -> bool:
        """
        从数据库同步缓存（容错机制）

        Returns:
            True 如果同步成功
        """
        try:
            allocated = self._query_allocated_cpus_from_db()
            self.cache.set_allocated_cpus(allocated)
            logger.debug(f"Cache synced: {allocated} CPUs allocated")
            return True

        except Exception as e:
            logger.error(f"Failed to sync cache: {e}")
            return False

    def init_cache(self) -> bool:
        """
        初始化缓存（从数据库）

        Returns:
            True 如果初始化成功
        """
        return self.sync_cache_from_db()

    # ==================== 私有方法 ====================

    def _query_allocated_cpus_from_db(self) -> int:
        """
        从数据库查询已分配的 CPU 数量

        Returns:
            已分配的 CPU 数量
        """
        with sync_db.get_session() as session:
            result = (
                session.query(func.sum(ResourceAllocation.allocated_cpus))
                .filter(~ResourceAllocation.released)
                .scalar()
            )
            return result or 0

    # ==================== 上下文管理器 ====================

    @contextmanager
    def allocate_context(self, cpus: int):
        """
        资源分配上下文管理器

        使用示例：
            with resource_manager.allocate_context(4):
                # 使用资源
                ...
            # 自动释放

        Args:
            cpus: 要分配的 CPU 数量
        """
        try:
            self.allocate(cpus)
            yield
        finally:
            self.release(cpus)


# 全局单例
_resource_manager: Optional[ResourceManager] = None


def get_resource_manager() -> ResourceManager:
    """
    获取全局资源管理器实例（单例）

    Returns:
        ResourceManager 实例
    """
    global _resource_manager
    if _resource_manager is None:
        _resource_manager = ResourceManager()
    return _resource_manager
