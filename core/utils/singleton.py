"""
线程安全的单例装饰器实现
"""

import threading
from typing import Any, Callable, TypeVar
from functools import wraps

T = TypeVar("T")


def singleton(cls: type[T]) -> Callable[..., T]:
    """
    线程安全的单例装饰器，采用双重检查锁模式

    用法示例:
        @singleton
        class MyClass:
            pass
    """
    instances = {}  # 存储单例实例
    lock = threading.Lock()  # 全局锁，保证线程安全

    @wraps(cls)
    def get_instance(*args: Any, **kwargs: Any) -> T:
        # 首次检查（无锁，提高性能）
        if cls not in instances:
            with lock:
                # 获取锁后再次检查，防止多线程下重复创建
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]

    return get_instance
