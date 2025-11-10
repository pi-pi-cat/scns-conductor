"""
SCNS-Conductor Worker Service (重构版)
RQ-based job executor and scheduler

重构改进：
- 模块化目录结构，职责清晰
- 简化的监控机制，移除复杂的观察者模式
- 统一的配置管理
- 更好的类型注解和文档
"""

__version__ = "2.0.0"

# 核心模块
from worker.core import (
    DaemonThread,
    SchedulerDaemon,
    JobExecutor,
    execute_job_task,
    ResourceScheduler,
)

# 服务层
from worker.services import ResourceManager

# 恢复模块
from worker.recovery import (
    RecoveryManager,
    RecoveryStrategy,
    RecoveryResult,
    OrphanJobRecoveryStrategy,
    TimeoutJobRecoveryStrategy,
    StaleAllocationCleanupStrategy,
    CompositeRecoveryStrategy,
)

# 监控模块
from worker.monitoring import MetricsCollector, ResourceMetrics

# 工具模块
from worker.utils import (
    SignalHandler,
    check_process_exists,
    kill_process_group,
    store_process_id,
    get_process_id,
)

# 配置
from worker.config import get_worker_config, set_worker_config, WorkerConfig

__all__ = [
    # 版本
    "__version__",
    
    # 核心
    "DaemonThread",
    "SchedulerDaemon",
    "JobExecutor",
    "execute_job_task",
    "ResourceScheduler",
    
    # 服务
    "ResourceManager",
    
    # 恢复
    "RecoveryManager",
    "RecoveryStrategy",
    "RecoveryResult",
    "OrphanJobRecoveryStrategy",
    "TimeoutJobRecoveryStrategy",
    "StaleAllocationCleanupStrategy",
    "CompositeRecoveryStrategy",
    
    # 监控
    "MetricsCollector",
    "ResourceMetrics",
    
    # 工具
    "SignalHandler",
    "check_process_exists",
    "kill_process_group",
    "store_process_id",
    "get_process_id",
    
    # 配置
    "get_worker_config",
    "set_worker_config",
    "WorkerConfig",
]
