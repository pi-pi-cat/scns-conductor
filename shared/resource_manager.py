"""
Resource Manager - 资源管理器

线程安全的CPU资源管理
"""

import threading

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import ResourceAllocation
from core.utils.singleton import singleton


@singleton
class ResourceManager:
    """资源管理器（单例）"""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._total = get_settings().TOTAL_CPUS
        self._used = 0
        
        # 从数据库加载当前使用情况
        self._load_from_db()
    
    def _load_from_db(self):
        """从数据库加载当前资源使用情况"""
        try:
            with sync_db.get_session() as session:
                allocations = (
                    session.query(ResourceAllocation)
                    .filter(ResourceAllocation.released == False)
                    .all()
                )
                self._used = sum(a.allocated_cpus for a in allocations)
                
                logger.info(
                    f"Resource manager initialized: "
                    f"total={self._total}, used={self._used}, "
                    f"available={self.available}"
                )
        except Exception as e:
            logger.error(f"Failed to load resource usage: {e}")
            self._used = 0
    
    def can_allocate(self, cpus: int) -> bool:
        """检查是否可以分配指定数量的 CPU"""
        with self._lock:
            return (self._used + cpus) <= self._total
    
    def allocate(self, cpus: int) -> bool:
        """
        分配 CPU 资源
        
        Returns:
            True 如果分配成功
        """
        with self._lock:
            if not self.can_allocate(cpus):
                return False
            
            self._used += cpus
            logger.debug(f"Allocated {cpus} CPUs: {self._used}/{self._total}")
            return True
    
    def release(self, cpus: int):
        """释放 CPU 资源"""
        with self._lock:
            self._used = max(0, self._used - cpus)
            logger.debug(f"Released {cpus} CPUs: {self._used}/{self._total}")
    
    @property
    def total(self) -> int:
        """总 CPU 数"""
        return self._total
    
    @property
    def used(self) -> int:
        """已使用 CPU 数"""
        with self._lock:
            return self._used
    
    @property
    def available(self) -> int:
        """可用 CPU 数"""
        with self._lock:
            return self._total - self._used
    
    def get_utilization(self) -> float:
        """获取利用率（百分比）"""
        with self._lock:
            if self._total == 0:
                return 0.0
            return (self._used / self._total) * 100.0

