"""
Execution Middleware Base - 执行中间件基类

定义中间件接口和自动注册机制
"""

from abc import ABC
from typing import Optional

from loguru import logger

from worker.execution import JobExecutionContext


# 全局中间件注册表（类级别）
_middleware_registry: dict = {}


class MiddlewareMetadata:
    """中间件元数据"""
    
    def __init__(
        self,
        name: str,
        description: str = "",
        priority: int = 0,
        enabled_by_default: bool = True,
    ):
        """
        Args:
            name: 中间件名称
            description: 描述
            priority: 优先级（数字越大越先执行）
            enabled_by_default: 默认是否启用
        """
        self.name = name
        self.description = description
        self.priority = priority
        self.enabled_by_default = enabled_by_default


def middleware_metadata(
    name: str,
    description: str = "",
    priority: int = 0,
    enabled_by_default: bool = True,
):
    """
    中间件元数据装饰器
    
    Usage:
        @middleware_metadata(
            name="MyMiddleware",
            description="My middleware description",
            priority=10,
        )
        class MyMiddleware(BaseExecutionMiddleware):
            ...
    """
    def decorator(cls):
        cls._metadata = MiddlewareMetadata(
            name=name,
            description=description,
            priority=priority,
            enabled_by_default=enabled_by_default,
        )
        return cls
    return decorator


class BaseExecutionMiddleware(ABC):
    """
    执行中间件基类
    
    特性：
    - 自动注册（__init_subclass__）
    - 元数据支持（装饰器）
    - 钩子方法（生命周期）
    """
    
    def __init_subclass__(cls, **kwargs):
        """子类定义时自动调用，实现自动注册"""
        super().__init_subclass__(**kwargs)
        
        # 只注册非抽象的具体中间件类
        if not getattr(cls, "__abstractmethods__", None):
            # 使用类名作为注册键
            registry_key = getattr(cls, "_registry_key", None) or cls.__name__
            _middleware_registry[registry_key] = cls
            
            # 如果没有元数据，创建默认元数据
            if not hasattr(cls, "_metadata"):
                cls._metadata = MiddlewareMetadata(
                    name=registry_key,
                    description=f"{registry_key} middleware",
                    priority=0,
                )
            
            logger.debug(f"Auto-registered middleware: {registry_key} -> {cls.__name__}")
    
    def __init__(self, enabled: bool = None):
        """
        Args:
            enabled: 是否启用（None 时使用元数据的 enabled_by_default）
        """
        metadata = self._get_metadata()
        self.enabled = enabled if enabled is not None else metadata.enabled_by_default
    
    def _get_metadata(self) -> MiddlewareMetadata:
        """获取中间件元数据"""
        return getattr(self.__class__, "_metadata", MiddlewareMetadata(
            name=self.__class__.__name__,
            description="",
            priority=0,
        ))
    
    @property
    def name(self) -> str:
        """中间件名称"""
        return self._get_metadata().name
    
    @property
    def priority(self) -> int:
        """优先级"""
        return self._get_metadata().priority
    
    # ========================================================================
    # 钩子方法（可选实现）
    # ========================================================================
    
    def before_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """
        执行前处理
        
        Args:
            context: 执行上下文
        
        Returns:
            处理后的执行上下文
        """
        return context
    
    def after_execution(self, context: JobExecutionContext) -> JobExecutionContext:
        """
        执行后处理
        
        Args:
            context: 执行上下文
        
        Returns:
            处理后的执行上下文
        """
        return context
    
    def on_stage(self, stage: str, context: JobExecutionContext) -> JobExecutionContext:
        """
        阶段钩子
        
        Args:
            stage: 执行阶段
            context: 执行上下文
        
        Returns:
            处理后的执行上下文
        """
        return context
    
    def on_error(self, context: JobExecutionContext, error: Exception):
        """
        错误处理
        
        Args:
            context: 执行上下文
            error: 异常对象
        """
        pass


def get_middleware_registry():
    """获取中间件注册表（用于测试和调试）"""
    return _middleware_registry.copy()

