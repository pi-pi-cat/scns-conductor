"""
Thread-safe singleton decorator implementation
"""
import threading
from typing import Any, Callable, TypeVar
from functools import wraps


T = TypeVar('T')


def singleton(cls: type[T]) -> Callable[..., T]:
    """
    Thread-safe singleton decorator using double-checked locking pattern
    
    Usage:
        @singleton
        class MyClass:
            pass
    """
    instances = {}
    lock = threading.Lock()
    
    @wraps(cls)
    def get_instance(*args: Any, **kwargs: Any) -> T:
        # First check without locking for performance
        if cls not in instances:
            with lock:
                # Double-check after acquiring lock
                if cls not in instances:
                    instances[cls] = cls(*args, **kwargs)
        return instances[cls]
    
    return get_instance

