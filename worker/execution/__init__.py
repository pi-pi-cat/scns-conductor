"""
Execution Module - 执行模块

职责：
- 定义执行上下文
- 定义执行阶段
- 提供执行相关的类型和接口
"""

from .context import JobExecutionContext
from .stages import ExecutionStage

__all__ = [
    "JobExecutionContext",
    "ExecutionStage",
]

