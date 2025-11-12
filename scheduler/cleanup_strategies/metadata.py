"""
策略元数据和装饰器
"""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class StrategyMetadata:
    """策略元数据"""

    priority: int = 100  # 执行优先级（数字越小越先执行）
    depends_on: List[str] = field(default_factory=list)  # 依赖的策略名称列表
    tags: List[str] = field(default_factory=list)  # 标签列表
    timeout: Optional[int] = None  # 超时时间（秒），None 表示不限制
    retry_on_failure: bool = False  # 失败是否重试
    enabled_by_default: bool = True  # 默认是否启用


def strategy_metadata(
    priority: int = 100,
    depends_on: List[str] = None,
    tags: List[str] = None,
    timeout: Optional[int] = None,
    retry_on_failure: bool = False,
    enabled_by_default: bool = True,
):
    """
    策略元数据装饰器

    使用示例:
        @strategy_metadata(
            priority=1,
            depends_on=['completed_job_cleanup'],
            tags=['critical', 'resource'],
            timeout=60,
        )
        class MyStrategy(BaseCleanupStrategy):
            pass
    """

    def decorator(cls):
        cls._metadata = StrategyMetadata(
            priority=priority,
            depends_on=depends_on or [],
            tags=tags or [],
            timeout=timeout,
            retry_on_failure=retry_on_failure,
            enabled_by_default=enabled_by_default,
        )
        return cls

    return decorator

