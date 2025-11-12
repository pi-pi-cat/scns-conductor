"""
清理策略管理器
"""

from typing import Dict, List, Optional

from loguru import logger

from core.database import sync_db

from .base import BaseCleanupStrategy, get_strategy_registry
from .observers import LoggingObserver, StrategyObserver
from .types import CleanupResult


class CleanupStrategyManager:
    """
    清理策略管理器 V4.0

    特性：
    - 自动从注册表加载策略
    - 根据优先级和依赖关系排序（带缓存）
    - 支持观察者模式（监控）
    - 支持从配置文件加载

    性能优化：
    - 排序结果缓存（只在注册/注销时重新计算）
    - 每个策略使用独立事务（减少 session 持有时间）
    """

    def __init__(self, observers: List[StrategyObserver] = None):
        """
        Args:
            observers: 策略观察者列表（用于监控）
        """
        self.strategies: Dict[str, BaseCleanupStrategy] = {}
        self.observers: List[StrategyObserver] = observers or [LoggingObserver()]

        # 排序结果缓存（性能优化）
        self._sorted_strategies_cache: Optional[List[BaseCleanupStrategy]] = None

    def add_observer(self, observer: StrategyObserver):
        """添加观察者"""
        self.observers.append(observer)
        logger.debug(f"Added observer: {observer.__class__.__name__}")

    def register(self, strategy: BaseCleanupStrategy):
        """手动注册清理策略"""
        self.strategies[strategy.name] = strategy
        self._invalidate_sort_cache()  # 失效排序缓存
        logger.info(
            f"✓ Registered cleanup strategy: {strategy.name} - {strategy.description}"
        )

    def _invalidate_sort_cache(self):
        """失效排序缓存（策略注册/注销时调用）"""
        self._sorted_strategies_cache = None

    def _get_sorted_strategies(self) -> List[BaseCleanupStrategy]:
        """
        获取排序后的策略（惰性计算 + 缓存）

        只在策略注册/注销时重新计算，避免重复排序
        """
        if self._sorted_strategies_cache is None:
            self._sorted_strategies_cache = self._sort_strategies_by_priority()
        return self._sorted_strategies_cache

    def _sort_strategies_by_priority(self) -> List[BaseCleanupStrategy]:
        """
        根据优先级和依赖关系排序策略

        使用拓扑排序算法处理依赖关系

        注意：此方法会重新计算排序，通常应使用 _get_sorted_strategies() 获取缓存结果
        """
        # 构建依赖图
        strategy_map = {s.name: s for s in self.strategies.values()}
        in_degree = {name: 0 for name in strategy_map}
        graph = {name: [] for name in strategy_map}

        for strategy in self.strategies.values():
            metadata = strategy._get_metadata()
            for dep in metadata.depends_on:
                if dep in strategy_map:
                    graph[dep].append(strategy.name)
                    in_degree[strategy.name] += 1

        # 拓扑排序
        queue = [name for name, degree in in_degree.items() if degree == 0]
        result = []

        while queue:
            # 按优先级排序
            queue.sort(key=lambda n: strategy_map[n]._get_metadata().priority)

            current = queue.pop(0)
            result.append(strategy_map[current])

            for neighbor in graph[current]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)

        return result

    def auto_register_all(self, **strategy_kwargs):
        """
        自动注册所有已定义的策略类

        Args:
            **strategy_kwargs: 传递给各个策略的参数字典
        """
        _strategy_registry = get_strategy_registry()
        for registry_key, strategy_cls in _strategy_registry.items():
            # 获取该策略的特定配置
            kwargs = strategy_kwargs.get(registry_key, {})

            # 创建实例并注册
            strategy = strategy_cls(**kwargs)
            self.register(strategy)

    def _notify_observers(self, result: CleanupResult):
        """通知所有观察者"""
        if result.success:
            for observer in self.observers:
                observer.on_strategy_executed(result)
        else:
            for observer in self.observers:
                observer.on_strategy_failed(result)

    def execute_due_strategies(self, current_time: int) -> List[CleanupResult]:
        """
        执行所有到期的策略（按优先级和依赖关系排序）

        优化：
        - 使用缓存的排序结果（避免重复排序）
        - 每个策略使用独立事务（减少 session 持有时间）

        Args:
            current_time: 当前时间戳

        Returns:
            清理结果列表
        """
        results = []

        # 获取到期的策略
        due_strategies = [
            s for s in self.strategies.values() if s.should_run(current_time)
        ]

        if not due_strategies:
            return results

        # 使用缓存的排序结果（惰性计算）
        sorted_strategies = self._get_sorted_strategies()
        due_strategies = [s for s in sorted_strategies if s in due_strategies]

        # 每个策略使用独立事务（优化：减少 session 持有时间）
        for strategy in due_strategies:
            with sync_db.get_session() as session:
                logger.debug(f"Executing cleanup strategy: {strategy.name}")

                result = strategy.execute(session)
                strategy.mark_run(current_time)

                # 通知观察者
                self._notify_observers(result)

                results.append(result)

        return results

    def execute_strategy(self, strategy_name: str) -> Optional[CleanupResult]:
        """手动执行指定策略"""
        strategy = self.strategies.get(strategy_name)
        if not strategy:
            logger.error(f"Strategy not found: {strategy_name}")
            return None

        with sync_db.get_session() as session:
            result = strategy.execute(session)
            self._notify_observers(result)
            return result

    def list_strategies(self) -> List[BaseCleanupStrategy]:
        """列出所有策略（按优先级排序）"""
        return self._get_sorted_strategies()

    def get_strategy(self, name: str) -> Optional[BaseCleanupStrategy]:
        """获取策略"""
        return self.strategies.get(name)

    def unregister(self, strategy_name: str):
        """注销策略"""
        if strategy_name in self.strategies:
            del self.strategies[strategy_name]
            self._invalidate_sort_cache()  # 失效排序缓存
            logger.info(f"Unregistered strategy: {strategy_name}")

