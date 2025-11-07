"""
验证工具
"""
import os
import re
from pathlib import Path
from typing import Optional


def validate_path(path: str, must_exist: bool = False) -> bool:
    """
    验证文件系统路径
    
    Args:
        path: 要验证的路径
        must_exist: 如果为True，路径必须存在
    
    Returns:
        有效则返回True
    
    Raises:
        ValueError: 如果路径无效
    """
    if not path or not path.strip():
        raise ValueError("Path cannot be empty")
    
    # Check for absolute path
    if not os.path.isabs(path):
        raise ValueError(f"Path must be absolute: {path}")
    
    # Check if exists (if required)
    if must_exist and not os.path.exists(path):
        raise ValueError(f"Path does not exist: {path}")
    
    return True


def validate_memory_format(memory_str: str) -> bool:
    """
    验证内存格式字符串
    
    支持：1G, 1024M, 1T, 512K 等
    
    Args:
        memory_str: 要验证的内存字符串
    
    Returns:
        有效则返回True
    
    Raises:
        ValueError: 如果格式无效
    """
    pattern = r'^\d+[KMGT]?$'
    if not re.match(pattern, memory_str, re.IGNORECASE):
        raise ValueError(
            f"Invalid memory format: {memory_str}. "
            "Expected format: <number>[K|M|G|T] (e.g., 16G, 1024M)"
        )
    return True


def validate_cpu_count(cpus: int, max_cpus: Optional[int] = None) -> bool:
    """
    验证CPU数量
    
    Args:
        cpus: 要验证的CPU数量
        max_cpus: 可选的最大CPU限制
    
    Returns:
        有效则返回True
    
    Raises:
        ValueError: 如果CPU数量无效
    """
    if cpus < 1:
        raise ValueError(f"CPU count must be at least 1, got: {cpus}")
    
    if max_cpus is not None and cpus > max_cpus:
        raise ValueError(
            f"CPU count {cpus} exceeds maximum allowed: {max_cpus}"
        )
    
    return True


def sanitize_job_name(name: str) -> str:
    """
    清理作业名称以防止安全问题
    
    Args:
        name: 要清理的作业名称
    
    Returns:
        清理后的作业名称
    """
    # Remove or replace dangerous characters
    sanitized = re.sub(r'[^\w\-_\.]', '_', name)
    
    # Limit length
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    
    return sanitized

