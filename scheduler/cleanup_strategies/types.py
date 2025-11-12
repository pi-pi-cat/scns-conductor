"""
清理策略类型定义
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class CleanupResult:
    """清理结果"""

    strategy_name: str
    items_cleaned: int
    success: bool
    error_message: Optional[str] = None
    execution_time: float = 0.0  # 执行时间（秒）

