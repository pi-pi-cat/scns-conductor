"""
Execution Middleware Module - 执行中间件模块

架构：
- BaseExecutionMiddleware: 抽象基类，定义中间件接口，自动注册子类
- 具体中间件类: 继承基类，实现具体逻辑（自动注册）
- MiddlewareManager: 管理器，管理所有中间件

特性：
- ✅ 使用 __init_subclass__ 实现自动注册（无需手动调用 register）
- ✅ 装饰器模式：中间件元数据配置（优先级、顺序）
- ✅ 钩子方法：before_execution, after_execution, on_stage, on_error
"""

# 导入中间件类以触发自动注册
from .metrics import MetricsMiddleware
from .logging import LoggingMiddleware
from .resource_monitoring import ResourceMonitoringMiddleware

# 导出公共接口
from .base import BaseExecutionMiddleware
from .manager import MiddlewareManager, create_default_manager, get_registered_middlewares

__all__ = [
    # 基类和接口
    "BaseExecutionMiddleware",
    # 管理器
    "MiddlewareManager",
    "create_default_manager",
    "get_registered_middlewares",
    # 具体中间件
    "LoggingMiddleware",
    "MetricsMiddleware",
    "ResourceMonitoringMiddleware",
]

