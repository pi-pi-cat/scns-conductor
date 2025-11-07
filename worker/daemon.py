"""
守护进程基类和调度器守护进程
"""
import threading
import time
from abc import ABC, abstractmethod
from typing import Optional
from loguru import logger

from core.config import get_settings
from .scheduler import ResourceScheduler


class DaemonThread(threading.Thread, ABC):
    """
    守护线程基类
    
    提供标准的守护线程功能：
    - 启动/停止控制
    - 上下文管理器支持
    - 优雅的资源清理
    """
    
    def __init__(self, name: str, check_interval: float = 5.0):
        """
        初始化守护线程
        
        Args:
            name: 线程名称
            check_interval: 检查间隔（秒）
        """
        super().__init__(daemon=True, name=name)
        self.check_interval = check_interval
        self._stop_event = threading.Event()
        self._started = False
    
    def __enter__(self):
        """上下文管理器入口"""
        self.start()
        self._started = True
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        if self._started:
            self.stop()
            self.join(timeout=10)
        return False
    
    @abstractmethod
    def do_work(self) -> None:
        """
        执行实际工作（子类实现）
        
        此方法会在循环中被调用
        """
        pass
    
    def run(self) -> None:
        """主循环"""
        logger.info(f"🚀 {self.name} started")
        
        while not self._stop_event.is_set():
            try:
                self.do_work()
            except Exception as e:
                logger.error(f"❌ {self.name} error: {e}", exc_info=True)
            
            # 等待下一次检查
            self._stop_event.wait(self.check_interval)
        
        logger.info(f"🛑 {self.name} stopped")
    
    def stop(self) -> None:
        """停止守护线程"""
        self._stop_event.set()
    
    @property
    def is_running(self) -> bool:
        """检查是否正在运行"""
        return not self._stop_event.is_set()


class SchedulerDaemon(DaemonThread):
    """
    调度器守护进程
    
    周期性检查待处理作业并进行调度
    
    使用示例:
        # 方式1：传统方式
        daemon = SchedulerDaemon()
        daemon.start()
        try:
            ...
        finally:
            daemon.stop()
            daemon.join()
        
        # 方式2：上下文管理器（推荐）✅
        with SchedulerDaemon() as daemon:
            ...  # 自动启动和清理
    """
    
    def __init__(self, check_interval: float = 5.0):
        """
        初始化调度器守护进程
        
        Args:
            check_interval: 调度检查间隔（秒）
        """
        super().__init__(name="SchedulerDaemon", check_interval=check_interval)
        self.scheduler = ResourceScheduler()
        self._last_stats_time = 0
    
    def do_work(self) -> None:
        """执行调度工作"""
        # 调度待处理作业
        scheduled_jobs = self.scheduler.schedule_pending_jobs()
        
        if scheduled_jobs:
            logger.info(f"✅ Scheduled {len(scheduled_jobs)} jobs")
        
        # 定期记录资源统计（每分钟）
        current_time = int(time.time())
        if current_time - self._last_stats_time >= 60:
            self._log_resource_stats()
            self._last_stats_time = current_time
    
    def _log_resource_stats(self) -> None:
        """记录资源统计信息"""
        stats = self.scheduler.get_resource_stats()
        logger.info(
            f"📊 Resource stats: {stats['used_cpus']}/{stats['total_cpus']} CPUs "
            f"({stats['utilization']:.1f}% utilization)"
        )

