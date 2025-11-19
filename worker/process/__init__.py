"""
Process Module - 进程管理模块

职责：
- 进程工具函数
- 进程生命周期管理
"""

from .utils import store_pid, kill_process_tree

__all__ = [
    "store_pid",
    "kill_process_tree",
]

