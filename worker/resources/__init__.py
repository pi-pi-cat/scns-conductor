"""
Resources Module - 资源管理模块

职责：
- 资源管理器包装器
- 资源分配和释放管理
"""

from .wrapper import ResourceManagerWrapper, ResourceAllocationError

__all__ = [
    "ResourceManagerWrapper",
    "ResourceAllocationError",
]

