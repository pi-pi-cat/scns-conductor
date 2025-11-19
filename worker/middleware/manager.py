"""
Middleware Manager - 中间件管理器

管理所有中间件的注册和执行
"""

from typing import List, Optional

from loguru import logger

from .base import BaseExecutionMiddleware, get_middleware_registry
from worker.execution import JobExecutionContext


class MiddlewareManager:
    """
    中间件管理器
    
    特性：
    - 自动从注册表加载中间件
    - 根据优先级排序
    - 支持启用/禁用中间件
    """
    
    def __init__(self):
        """初始化管理器"""
        self.middlewares: List[BaseExecutionMiddleware] = []
        self._sorted_cache: Optional[List[BaseExecutionMiddleware]] = None
    
    def register(self, middleware: BaseExecutionMiddleware):
        """
        注册中间件
        
        Args:
            middleware: 中间件实例
        """
        if middleware.enabled:
            self.middlewares.append(middleware)
            self._invalidate_sort_cache()
            logger.debug(f"Registered middleware: {middleware.name}")
    
    def register_all_from_registry(self, enabled_only: bool = True):
        """
        从注册表注册所有中间件
        
        Args:
            enabled_only: 是否只注册默认启用的中间件
        """
        registry = get_middleware_registry()
        for key, middleware_class in registry.items():
            middleware = middleware_class()
            if not enabled_only or middleware.enabled:
                self.register(middleware)
    
    def _invalidate_sort_cache(self):
        """失效排序缓存"""
        self._sorted_cache = None
    
    def _get_sorted_middlewares(self) -> List[BaseExecutionMiddleware]:
        """
        获取排序后的中间件（按优先级降序）
        
        Returns:
            排序后的中间件列表
        """
        if self._sorted_cache is None:
            self._sorted_cache = sorted(
                self.middlewares,
                key=lambda m: m.priority,
                reverse=True
            )
        return self._sorted_cache
    
    def execute_before(self, context: JobExecutionContext) -> JobExecutionContext:
        """
        执行所有中间件的 before_execution 钩子
        
        Args:
            context: 执行上下文
        
        Returns:
            处理后的执行上下文
        """
        for middleware in self._get_sorted_middlewares():
            if middleware.enabled:
                context = middleware.before_execution(context)
        return context
    
    def execute_after(self, context: JobExecutionContext) -> JobExecutionContext:
        """
        执行所有中间件的 after_execution 钩子（逆序）
        
        Args:
            context: 执行上下文
        
        Returns:
            处理后的执行上下文
        """
        for middleware in reversed(self._get_sorted_middlewares()):
            if middleware.enabled:
                context = middleware.after_execution(context)
        return context
    
    def execute_on_stage(self, stage: str, context: JobExecutionContext) -> JobExecutionContext:
        """
        执行所有中间件的 on_stage 钩子
        
        Args:
            stage: 执行阶段
            context: 执行上下文
        
        Returns:
            处理后的执行上下文
        """
        for middleware in self._get_sorted_middlewares():
            if middleware.enabled:
                context = middleware.on_stage(stage, context)
        return context
    
    def execute_on_error(self, context: JobExecutionContext, error: Exception):
        """
        执行所有中间件的 on_error 钩子
        
        Args:
            context: 执行上下文
            error: 异常对象
        """
        for middleware in self._get_sorted_middlewares():
            if middleware.enabled:
                middleware.on_error(context, error)


def create_default_manager() -> MiddlewareManager:
    """
    创建默认中间件管理器
    
    Returns:
        配置好的中间件管理器
    """
    manager = MiddlewareManager()
    manager.register_all_from_registry(enabled_only=True)
    logger.info(f"Created middleware manager with {len(manager.middlewares)} middlewares")
    return manager


def get_registered_middlewares():
    """获取所有已注册的中间件类"""
    return get_middleware_registry()

