"""
清理策略模块

架构 V4.0 - 完整优化版：
- BaseCleanupStrategy: 抽象基类，定义清理策略接口，自动注册子类
- 具体策略类: 继承基类，实现具体清理逻辑（自动注册）
- CleanupStrategyManager: 管理器，调度所有策略

特性：
- ✅ 使用 __init_subclass__ 实现自动注册（无需手动调用 register）
- ✅ 装饰器模式：策略元数据配置（优先级、依赖、标签）
- ✅ 钩子方法：前置/后置处理和错误处理
- ✅ 观察者模式：策略执行监控（指标、告警等）
- ✅ 配置驱动：从 YAML 配置文件加载策略配置

性能优化：
- ✅ 排序结果缓存（只在注册/注销时重新计算）
- ✅ 每个策略使用独立事务（减少 session 持有时间）
- ✅ 消除重复数据库查询
"""

# 导入策略类以触发自动注册
from .strategies import (
    CompletedJobCleanupStrategy,
    OldJobCleanupStrategy,
    StaleReservationCleanupStrategy,
    StuckJobCleanupStrategy,
)

# 导出公共接口
from .base import BaseCleanupStrategy
from .config import (
    create_default_manager,
    create_manager_from_config,
    get_registered_strategies,
)
from .manager import CleanupStrategyManager
from .metadata import StrategyMetadata, strategy_metadata
from .observers import LoggingObserver, MetricsObserver, StrategyObserver
from .types import CleanupResult

__all__ = [
    # 基类和接口
    "BaseCleanupStrategy",
    "CleanupResult",
    "StrategyMetadata",
    "strategy_metadata",
    # 观察者
    "StrategyObserver",
    "LoggingObserver",
    "MetricsObserver",
    # 管理器
    "CleanupStrategyManager",
    # 具体策略
    "CompletedJobCleanupStrategy",
    "StaleReservationCleanupStrategy",
    "StuckJobCleanupStrategy",
    "OldJobCleanupStrategy",
    # 工具函数
    "create_default_manager",
    "create_manager_from_config",
    "get_registered_strategies",
]

