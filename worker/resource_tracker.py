"""
线程安全的CPU资源跟踪器（观察者模式版）
"""

import threading
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import ResourceAllocation
from .observers import Observable, LoggingObserver, AlertObserver


class ResourceTracker(Observable):
    """
    线程安全的CPU资源跟踪器
    管理可用的CPU资源用于作业调度
    """

    def __init__(self):
        super().__init__()  # 初始化Observable
        self._lock = threading.Lock()
        settings = get_settings()
        self._total_cpus = settings.TOTAL_CPUS
        self._used_cpus = 0
        self._load_current_usage()

        # 默认添加日志和告警观察者
        self.attach(LoggingObserver())
        self.attach(AlertObserver(threshold=90.0))

    def _load_current_usage(self) -> None:
        """
        从数据库加载当前资源使用情况
        在初始化时调用以恢复状态
        """
        try:
            with sync_db.get_session() as session:
                # Query all unreleased allocations
                allocations = (
                    session.query(ResourceAllocation)
                    .filter(ResourceAllocation.released == False)
                    .all()
                )

                self._used_cpus = sum(a.allocated_cpus for a in allocations)

                logger.info(
                    f"Resource tracker initialized: "
                    f"total={self._total_cpus}, used={self._used_cpus}, "
                    f"available={self.available_cpus}"
                )

        except Exception as e:
            logger.error(f"Failed to load current resource usage: {e}")
            self._used_cpus = 0

    def can_allocate(self, cpus: int) -> bool:
        """
        检查是否可以分配请求的CPU数量

        Args:
            cpus: 请求的CPU数量

        Returns:
            如果可以分配则返回True
        """
        with self._lock:
            return (self._used_cpus + cpus) <= self._total_cpus

    def allocate(self, cpus: int) -> bool:
        """
        尝试分配CPU资源（带观察者通知）

        Args:
            cpus: 要分配的CPU数量

        Returns:
            分配成功返回True，否则返回False
        """
        with self._lock:
            if self.can_allocate(cpus):
                self._used_cpus += cpus
                stats = self._get_stats_unlocked()

                logger.debug(
                    f"Allocated {cpus} CPUs: used={self._used_cpus}/{self._total_cpus}"
                )

                # 通知观察者（在锁外执行以避免死锁）
                self.notify_allocated(cpus, stats)
                return True
            return False

    def release(self, cpus: int) -> None:
        """
        释放已分配的CPU资源（带观察者通知）

        Args:
            cpus: 要释放的CPU数量
        """
        with self._lock:
            self._used_cpus = max(0, self._used_cpus - cpus)
            stats = self._get_stats_unlocked()

            logger.debug(
                f"Released {cpus} CPUs: used={self._used_cpus}/{self._total_cpus}"
            )

            # 通知观察者（在锁外执行以避免死锁）
            self.notify_released(cpus, stats)

    @property
    def available_cpus(self) -> int:
        """Get number of available CPUs"""
        with self._lock:
            return self._total_cpus - self._used_cpus

    @property
    def used_cpus(self) -> int:
        """Get number of used CPUs"""
        with self._lock:
            return self._used_cpus

    @property
    def total_cpus(self) -> int:
        """Get total CPUs"""
        return self._total_cpus

    def get_stats(self) -> dict:
        """
        获取资源统计信息（线程安全）

        Returns:
            资源统计字典
        """
        with self._lock:
            return self._get_stats_unlocked()

    def _get_stats_unlocked(self) -> dict:
        """
        获取资源统计信息（内部使用，不加锁）

        调用此方法前必须已持有锁

        Returns:
            资源统计字典
        """
        return {
            "total_cpus": self._total_cpus,
            "used_cpus": self._used_cpus,
            "available_cpus": self._total_cpus - self._used_cpus,
            "utilization": (self._used_cpus / self._total_cpus * 100)
            if self._total_cpus > 0
            else 0,
        }
