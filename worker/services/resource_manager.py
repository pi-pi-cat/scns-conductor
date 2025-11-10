"""
资源管理服务
整合资源跟踪和指标收集功能
"""

import threading
from typing import Optional
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import ResourceAllocation
from worker.monitoring.metrics import MetricsCollector, ResourceMetrics


class ResourceManager:
    """
    资源管理器
    
    线程安全的CPU资源管理，整合了指标收集功能
    简化版本，移除了复杂的观察者模式
    """
    
    def __init__(self) -> None:
        """初始化资源管理器"""
        self._lock = threading.Lock()
        settings = get_settings()
        self._total_cpus = settings.TOTAL_CPUS
        self._used_cpus = 0
        
        # 指标收集器
        self.metrics = MetricsCollector()
        
        # 加载当前使用情况
        self._load_current_usage()
    
    def _load_current_usage(self) -> None:
        """
        从数据库加载当前资源使用情况
        在初始化时调用以恢复状态
        """
        try:
            with sync_db.get_session() as session:
                # 查询所有未释放的分配
                allocations = (
                    session.query(ResourceAllocation)
                    .filter(ResourceAllocation.released == False)
                    .all()
                )
                
                self._used_cpus = sum(a.allocated_cpus for a in allocations)
                
                logger.info(
                    f"Resource manager initialized: "
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
        尝试分配CPU资源
        
        Args:
            cpus: 要分配的CPU数量
        
        Returns:
            分配成功返回True，否则返回False
        """
        with self._lock:
            if not self.can_allocate(cpus):
                return False
            
            self._used_cpus += cpus
            metrics = self._get_metrics_unlocked()
            
            logger.debug(
                f"Allocated {cpus} CPUs: used={self._used_cpus}/{self._total_cpus}"
            )
        
        # 在锁外记录指标（避免死锁）
        self.metrics.record_allocation(cpus, metrics)
        return True
    
    def release(self, cpus: int) -> None:
        """
        释放已分配的CPU资源
        
        Args:
            cpus: 要释放的CPU数量
        """
        with self._lock:
            self._used_cpus = max(0, self._used_cpus - cpus)
            metrics = self._get_metrics_unlocked()
            
            logger.debug(
                f"Released {cpus} CPUs: used={self._used_cpus}/{self._total_cpus}"
            )
        
        # 在锁外记录指标（避免死锁）
        self.metrics.record_release(cpus, metrics)
    
    @property
    def available_cpus(self) -> int:
        """获取可用CPU数量"""
        with self._lock:
            return self._total_cpus - self._used_cpus
    
    @property
    def used_cpus(self) -> int:
        """获取已使用CPU数量"""
        with self._lock:
            return self._used_cpus
    
    @property
    def total_cpus(self) -> int:
        """获取总CPU数量"""
        return self._total_cpus
    
    def get_metrics(self) -> ResourceMetrics:
        """
        获取当前资源指标（线程安全）
        
        Returns:
            ResourceMetrics 对象
        """
        with self._lock:
            return self._get_metrics_unlocked()
    
    def _get_metrics_unlocked(self) -> ResourceMetrics:
        """
        获取资源指标（内部使用，不加锁）
        
        调用此方法前必须已持有锁
        
        Returns:
            ResourceMetrics 对象
        """
        available = self._total_cpus - self._used_cpus
        utilization = (self._used_cpus / self._total_cpus * 100) if self._total_cpus > 0 else 0.0
        
        return ResourceMetrics(
            total_cpus=self._total_cpus,
            used_cpus=self._used_cpus,
            available_cpus=available,
            utilization=utilization,
        )
    
    def get_stats(self) -> dict:
        """
        获取资源统计信息（兼容旧接口）
        
        Returns:
            资源统计字典
        """
        metrics = self.get_metrics()
        return {
            "total_cpus": metrics.total_cpus,
            "used_cpus": metrics.used_cpus,
            "available_cpus": metrics.available_cpus,
            "utilization": metrics.utilization,
        }

