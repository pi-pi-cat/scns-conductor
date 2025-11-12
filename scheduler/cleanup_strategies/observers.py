"""
策略观察者 - 执行监控
"""

from abc import ABC, abstractmethod

from loguru import logger

from .types import CleanupResult


class StrategyObserver(ABC):
    """策略观察者接口"""

    @abstractmethod
    def on_strategy_executed(self, result: CleanupResult):
        """策略执行完成时调用"""
        pass

    @abstractmethod
    def on_strategy_failed(self, result: CleanupResult):
        """策略执行失败时调用"""
        pass


class LoggingObserver(StrategyObserver):
    """日志观察者（默认）"""

    def on_strategy_executed(self, result: CleanupResult):
        if result.items_cleaned > 0:
            logger.info(
                f"✓ [{result.strategy_name}] Cleaned {result.items_cleaned} items"
            )

    def on_strategy_failed(self, result: CleanupResult):
        logger.error(f"✗ [{result.strategy_name}] Failed: {result.error_message}")


class MetricsObserver(StrategyObserver):
    """指标收集观察者（可扩展为 Prometheus 等）"""

    def __init__(self):
        self.metrics = {
            "total_executions": 0,
            "total_success": 0,
            "total_failures": 0,
            "total_items_cleaned": 0,
        }

    def on_strategy_executed(self, result: CleanupResult):
        self.metrics["total_executions"] += 1
        self.metrics["total_success"] += 1
        self.metrics["total_items_cleaned"] += result.items_cleaned

    def on_strategy_failed(self, result: CleanupResult):
        self.metrics["total_executions"] += 1
        self.metrics["total_failures"] += 1

    def get_metrics(self) -> dict:
        """获取指标"""
        return self.metrics.copy()

