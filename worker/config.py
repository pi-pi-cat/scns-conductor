"""
Worker 模块配置
统一管理 Worker 相关的配置参数
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class WorkerConfig:
    """Worker 配置类"""
    
    # 调度器配置
    SCHEDULER_CHECK_INTERVAL: float = 5.0  # 调度检查间隔（秒）
    SCHEDULER_STATS_INTERVAL: int = 60  # 资源统计记录间隔（秒）
    
    # 作业执行配置
    JOB_SCHEDULING_TIMEOUT: int = 3600  # 作业调度超时（秒）
    JOB_WAIT_RETRY_INTERVAL: float = 1.0  # 等待调度重试间隔（秒）
    PROCESS_TERM_GRACE_PERIOD: int = 5  # 进程终止宽限期（秒）
    
    # 恢复配置
    RECOVERY_MAX_RUNTIME_HOURS: int = 72  # 最大运行时间（小时）
    RECOVERY_MAX_ALLOCATION_AGE_HOURS: int = 48  # 最大资源分配保留时间（小时）
    
    # 监控配置
    RESOURCE_ALERT_THRESHOLD: float = 90.0  # 资源使用率告警阈值（百分比）
    
    # 日志配置
    LOG_RESOURCE_ALLOCATION: bool = True  # 是否记录资源分配日志
    LOG_RESOURCE_RELEASE: bool = True  # 是否记录资源释放日志
    
    # 守护进程配置
    DAEMON_THREAD_JOIN_TIMEOUT: float = 10.0  # 守护线程关闭超时（秒）


# 全局配置实例
_worker_config: Optional[WorkerConfig] = None


def get_worker_config() -> WorkerConfig:
    """
    获取 Worker 配置实例（单例）
    
    Returns:
        WorkerConfig 实例
    """
    global _worker_config
    if _worker_config is None:
        _worker_config = WorkerConfig()
    return _worker_config


def set_worker_config(config: WorkerConfig) -> None:
    """
    设置 Worker 配置实例
    
    Args:
        config: WorkerConfig 实例
    """
    global _worker_config
    _worker_config = config

