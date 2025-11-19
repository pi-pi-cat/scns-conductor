"""
Execution Stages - 执行阶段

定义作业执行过程中的各个阶段
"""

from enum import Enum


class ExecutionStage(Enum):
    """执行阶段枚举"""
    
    INITIALIZED = "initialized"  # 初始化
    LOADED = "loaded"  # 作业已加载
    RESOURCES_ALLOCATED = "resources_allocated"  # 资源已分配
    PREPARED = "prepared"  # 环境已准备
    RUNNING = "running"  # 正在执行
    COMPLETED = "completed"  # 执行完成
    FAILED = "failed"  # 执行失败
    CLEANED_UP = "cleaned_up"  # 已清理

