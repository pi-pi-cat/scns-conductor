"""
作业调度系统的枚举类型定义
"""

from enum import Enum


class JobState(str, Enum):
    """作业状态枚举"""

    PENDING = "PENDING"  # 等待调度
    RUNNING = "RUNNING"  # 正在运行
    COMPLETED = "COMPLETED"  # 已完成
    FAILED = "FAILED"  # 失败
    CANCELLED = "CANCELLED"  # 已取消


class DataSource(str, Enum):
    """数据来源枚举"""

    API = "API"  # API接口
    CLI = "CLI"  # 命令行
    WEB = "WEB"  # Web界面


class ResourceStatus(str, Enum):
    """资源分配状态枚举"""

    RESERVED = "reserved"  # 预留：调度器已分配，但Worker尚未开始执行
    ALLOCATED = "allocated"  # 已分配：Worker正在执行，资源实际占用
    RELEASED = "released"  # 已释放：作业完成，资源已回收
