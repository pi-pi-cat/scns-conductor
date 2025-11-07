"""
Validation utilities
"""
import os
import re
from pathlib import Path
from typing import Optional


def validate_path(path: str, must_exist: bool = False) -> bool:
    """
    Validate a file system path
    
    Args:
        path: Path to validate
        must_exist: If True, path must exist
    
    Returns:
        True if valid
    
    Raises:
        ValueError: If path is invalid
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
    Validate memory format string
    
    Supports: 1G, 1024M, 1T, 512K, etc.
    
    Args:
        memory_str: Memory string to validate
    
    Returns:
        True if valid
    
    Raises:
        ValueError: If format is invalid
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
    Validate CPU count
    
    Args:
        cpus: CPU count to validate
        max_cpus: Optional maximum CPU limit
    
    Returns:
        True if valid
    
    Raises:
        ValueError: If CPU count is invalid
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
    Sanitize job name to prevent security issues
    
    Args:
        name: Job name to sanitize
    
    Returns:
        Sanitized job name
    """
    # Remove or replace dangerous characters
    sanitized = re.sub(r'[^\w\-_\.]', '_', name)
    
    # Limit length
    if len(sanitized) > 255:
        sanitized = sanitized[:255]
    
    return sanitized

