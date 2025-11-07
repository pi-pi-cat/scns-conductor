"""
观察者模式实现 - 资源变化监控
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from loguru import logger


class ResourceObserver(ABC):
    """资源观察者接口"""
    
    @abstractmethod
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        """
        资源分配时调用
        
        Args:
            cpus: 分配的CPU数量
            stats: 当前资源统计信息
        """
        pass
    
    @abstractmethod
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        """
        资源释放时调用
        
        Args:
            cpus: 释放的CPU数量
            stats: 当前资源统计信息
        """
        pass


class LoggingObserver(ResourceObserver):
    """
    日志观察者
    
    记录资源分配和释放事件
    """
    
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        logger.info(
            f"📈 Resource allocated: {cpus} CPUs "
            f"(utilization: {stats['utilization']:.1f}%)"
        )
    
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        logger.info(
            f"📉 Resource released: {cpus} CPUs "
            f"(utilization: {stats['utilization']:.1f}%)"
        )


class MetricsObserver(ResourceObserver):
    """
    指标收集观察者
    
    收集资源使用指标用于监控
    """
    
    def __init__(self):
        self.allocations_count = 0
        self.releases_count = 0
        self.total_allocated = 0
        self.total_released = 0
    
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        self.allocations_count += 1
        self.total_allocated += cpus
    
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        self.releases_count += 1
        self.total_released += cpus
    
    def get_metrics(self) -> Dict[str, Any]:
        """
        获取收集的指标
        
        Returns:
            指标字典
        """
        return {
            "allocations_count": self.allocations_count,
            "releases_count": self.releases_count,
            "total_allocated": self.total_allocated,
            "total_released": self.total_released,
        }


class AlertObserver(ResourceObserver):
    """
    告警观察者
    
    在资源使用率达到阈值时发出告警
    """
    
    def __init__(self, threshold: float = 90.0):
        """
        初始化告警观察者
        
        Args:
            threshold: 告警阈值（百分比）
        """
        self.threshold = threshold
    
    def on_resource_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        if stats['utilization'] >= self.threshold:
            logger.warning(
                f"⚠️  High resource utilization: {stats['utilization']:.1f}% "
                f"(threshold: {self.threshold}%)"
            )
    
    def on_resource_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        # 释放时不需要告警
        pass


class Observable:
    """
    可观察对象基类
    
    提供观察者的添加、移除和通知功能
    """
    
    def __init__(self):
        self._observers: List[ResourceObserver] = []
    
    def attach(self, observer: ResourceObserver) -> None:
        """
        添加观察者
        
        Args:
            observer: 观察者对象
        """
        if observer not in self._observers:
            self._observers.append(observer)
            logger.debug(f"✅ Attached observer: {observer.__class__.__name__}")
    
    def detach(self, observer: ResourceObserver) -> None:
        """
        移除观察者
        
        Args:
            observer: 观察者对象
        """
        if observer in self._observers:
            self._observers.remove(observer)
            logger.debug(f"❌ Detached observer: {observer.__class__.__name__}")
    
    def notify_allocated(self, cpus: int, stats: Dict[str, Any]) -> None:
        """
        通知所有观察者：资源已分配
        
        Args:
            cpus: 分配的CPU数量
            stats: 资源统计信息
        """
        for observer in self._observers:
            try:
                observer.on_resource_allocated(cpus, stats)
            except Exception as e:
                logger.error(f"❌ Observer notification error: {e}")
    
    def notify_released(self, cpus: int, stats: Dict[str, Any]) -> None:
        """
        通知所有观察者：资源已释放
        
        Args:
            cpus: 释放的CPU数量
            stats: 资源统计信息
        """
        for observer in self._observers:
            try:
                observer.on_resource_released(cpus, stats)
            except Exception as e:
                logger.error(f"❌ Observer notification error: {e}")

