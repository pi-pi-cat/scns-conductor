"""
资源指标收集和监控
简化版本，移除复杂的观察者模式
"""

from dataclasses import dataclass
from typing import Callable, List, Optional
from loguru import logger

from worker.config import get_worker_config


@dataclass
class ResourceMetrics:
    """资源使用指标"""
    
    total_cpus: int
    used_cpus: int
    available_cpus: int
    utilization: float
    
    def __str__(self) -> str:
        return (
            f"CPUs: {self.used_cpus}/{self.total_cpus} "
            f"({self.utilization:.1f}% utilization)"
        )


class MetricsCollector:
    """
    指标收集器
    
    简化版本，使用简单的回调机制而不是观察者模式
    """
    
    def __init__(self) -> None:
        """初始化指标收集器"""
        self._allocations_count = 0
        self._releases_count = 0
        self._total_allocated = 0
        self._total_released = 0
        
        # 回调函数列表
        self._on_allocation_callbacks: List[Callable[[int, ResourceMetrics], None]] = []
        self._on_release_callbacks: List[Callable[[int, ResourceMetrics], None]] = []
        
        # 配置
        self._config = get_worker_config()
    
    def on_allocation(self, callback: Callable[[int, ResourceMetrics], None]) -> None:
        """
        注册资源分配回调
        
        Args:
            callback: 回调函数，接收 (cpus, metrics) 参数
        """
        self._on_allocation_callbacks.append(callback)
    
    def on_release(self, callback: Callable[[int, ResourceMetrics], None]) -> None:
        """
        注册资源释放回调
        
        Args:
            callback: 回调函数，接收 (cpus, metrics) 参数
        """
        self._on_release_callbacks.append(callback)
    
    def record_allocation(self, cpus: int, metrics: ResourceMetrics) -> None:
        """
        记录资源分配
        
        Args:
            cpus: 分配的CPU数量
            metrics: 当前资源指标
        """
        self._allocations_count += 1
        self._total_allocated += cpus
        
        # 记录日志
        if self._config.LOG_RESOURCE_ALLOCATION:
            logger.info(f"📈 Resource allocated: {cpus} CPUs ({metrics})")
        
        # 检查告警阈值
        if metrics.utilization >= self._config.RESOURCE_ALERT_THRESHOLD:
            logger.warning(
                f"⚠️  High resource utilization: {metrics.utilization:.1f}% "
                f"(threshold: {self._config.RESOURCE_ALERT_THRESHOLD}%)"
            )
        
        # 执行回调
        for callback in self._on_allocation_callbacks:
            try:
                callback(cpus, metrics)
            except Exception as e:
                logger.error(f"资源分配回调执行失败: {e}")
    
    def record_release(self, cpus: int, metrics: ResourceMetrics) -> None:
        """
        记录资源释放
        
        Args:
            cpus: 释放的CPU数量
            metrics: 当前资源指标
        """
        self._releases_count += 1
        self._total_released += cpus
        
        # 记录日志
        if self._config.LOG_RESOURCE_RELEASE:
            logger.info(f"📉 Resource released: {cpus} CPUs ({metrics})")
        
        # 执行回调
        for callback in self._on_release_callbacks:
            try:
                callback(cpus, metrics)
            except Exception as e:
                logger.error(f"资源释放回调执行失败: {e}")
    
    def get_statistics(self) -> dict:
        """
        获取统计信息
        
        Returns:
            统计信息字典
        """
        return {
            "allocations_count": self._allocations_count,
            "releases_count": self._releases_count,
            "total_allocated": self._total_allocated,
            "total_released": self._total_released,
        }
    
    def reset_statistics(self) -> None:
        """重置统计信息"""
        self._allocations_count = 0
        self._releases_count = 0
        self._total_allocated = 0
        self._total_released = 0

