"""
清理策略基类和元数据
"""

from abc import ABC, abstractmethod

from loguru import logger
from sqlalchemy.orm import Session

from .metadata import StrategyMetadata
from .types import CleanupResult

# 全局策略注册表（类级别）
_strategy_registry: dict = {}


class BaseCleanupStrategy(ABC):
    """
    清理策略基类 V4.0

    特性：
    - 自动注册（__init_subclass__）
    - 元数据支持（装饰器）
    - 钩子方法（生命周期）
    - 模板方法（统一执行流程）
    """

    def __init_subclass__(cls, **kwargs):
        """子类定义时自动调用，实现自动注册"""
        super().__init_subclass__(**kwargs)

        # 只注册非抽象的具体策略类
        if not getattr(cls, "__abstractmethods__", None):
            # 使用类名作为注册键（可以通过类属性覆盖）
            registry_key = getattr(cls, "_registry_key", None) or cls.__name__
            _strategy_registry[registry_key] = cls

            # 如果没有元数据，创建默认元数据
            if not hasattr(cls, "_metadata"):
                cls._metadata = StrategyMetadata()

            logger.debug(f"Auto-registered strategy: {registry_key} -> {cls.__name__}")

    def __init__(self, interval_seconds: int, enabled: bool = None):
        """
        Args:
            interval_seconds: 执行间隔（秒）
            enabled: 是否启用（None 时使用元数据的 enabled_by_default）
        """
        self.interval_seconds = interval_seconds
        self.enabled = (
            enabled if enabled is not None else self._get_metadata().enabled_by_default
        )
        self.last_run_time = 0

    def _get_metadata(self) -> StrategyMetadata:
        """获取策略元数据"""
        return getattr(self.__class__, "_metadata", StrategyMetadata())

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """策略描述"""
        pass

    @abstractmethod
    def _do_cleanup(self, session: Session) -> int:
        """
        执行具体的清理逻辑（子类实现）

        Args:
            session: 数据库会话

        Returns:
            清理的记录数量
        """
        pass

    # ========================================================================
    # 钩子方法（可选实现）
    # ========================================================================

    def before_execute(self, session: Session) -> bool:
        """
        执行前的钩子（可选）

        可以用于：
        - 前置检查（如检查是否有待清理的数据）
        - 条件判断（如只在特定条件下执行）
        - 日志记录

        Args:
            session: 数据库会话

        Returns:
            True 继续执行, False 跳过执行
        """
        return True

    def after_execute(self, session: Session, result: CleanupResult):
        """
        执行后的钩子（可选）

        可以用于：
        - 后置处理（如发送通知）
        - 日志增强
        - 指标记录

        Args:
            session: 数据库会话
            result: 执行结果
        """
        pass

    def on_error(self, session: Session, error: Exception):
        """
        错误处理钩子（可选）

        可以用于：
        - 错误通知
        - 错误日志增强
        - 错误恢复

        Args:
            session: 数据库会话
            error: 异常对象
        """
        pass

    # ========================================================================
    # 模板方法 - 统一执行流程
    # ========================================================================

    def execute(self, session: Session) -> CleanupResult:
        """
        执行清理逻辑（模板方法）

        统一处理：
        - 前置钩子检查
        - 异常捕获
        - 事务提交/回滚
        - 结果构建
        - 后置钩子调用
        - 错误钩子调用

        子类只需实现 _do_cleanup() 返回清理数量即可

        Args:
            session: 数据库会话

        Returns:
            清理结果
        """
        import time

        start_time = time.time()

        # 前置钩子
        if not self.before_execute(session):
            return self._build_skipped_result()

        try:
            # 执行清理逻辑
            count = self._do_cleanup(session)

            if count > 0:
                session.commit()
                logger.info(f"[{self.name}] Cleaned {count} items")

            execution_time = time.time() - start_time
            result = self._build_success_result(count, execution_time)

            # 后置钩子
            self.after_execute(session, result)

            return result

        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"[{self.name}] Failed: {e}", exc_info=True)

            # 错误钩子
            self.on_error(session, e)

            session.rollback()
            return self._build_error_result(e, execution_time)

    def _build_success_result(self, count: int, execution_time: float) -> CleanupResult:
        """构建成功结果"""
        return CleanupResult(
            strategy_name=self.name,
            items_cleaned=count,
            success=True,
            execution_time=execution_time,
        )

    def _build_error_result(
        self, error: Exception, execution_time: float
    ) -> CleanupResult:
        """构建错误结果"""
        return CleanupResult(
            strategy_name=self.name,
            items_cleaned=0,
            success=False,
            error_message=str(error),
            execution_time=execution_time,
        )

    def _build_skipped_result(self) -> CleanupResult:
        """构建跳过结果"""
        return CleanupResult(
            strategy_name=self.name,
            items_cleaned=0,
            success=True,
            error_message="Skipped by before_execute hook",
        )

    def should_run(self, current_time: int) -> bool:
        """判断是否应该执行"""
        if not self.enabled:
            return False
        return (current_time - self.last_run_time) >= self.interval_seconds

    def mark_run(self, current_time: int):
        """标记已执行"""
        self.last_run_time = current_time


def get_strategy_registry() -> dict:
    """获取策略注册表（用于管理器）"""
    return _strategy_registry
