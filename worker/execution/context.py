"""
Job Execution Context - 作业执行上下文

统一管理作业执行过程中的所有状态和信息
"""

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict

import subprocess

from core.models import Job, ResourceAllocation


@dataclass
class JobExecutionContext:
    """
    作业执行上下文
    
    统一管理作业执行过程中的所有状态，包括：
    - 作业信息
    - 资源分配
    - 进程信息
    - 执行环境
    - 错误信息
    """
    
    job_id: int
    job: Optional[Job] = None
    allocation: Optional[ResourceAllocation] = None
    process: Optional[subprocess.Popen] = None
    process_id: Optional[int] = None
    start_time: datetime = field(default_factory=datetime.utcnow)
    script_path: Optional[str] = None
    stdout_path: Optional[Path] = None
    stderr_path: Optional[Path] = None
    env: Dict[str, str] = field(default_factory=dict)
    error: Optional[Exception] = None
    exit_code: Optional[int] = None
    
    def is_running(self) -> bool:
        """
        检查作业是否正在运行
        
        Returns:
            True 如果进程存在且仍在运行
        """
        if self.process is None:
            return False
        return self.process.poll() is None
    
    def elapsed_time(self) -> float:
        """
        获取已执行时间（秒）
        
        Returns:
            已执行的秒数
        """
        return (datetime.utcnow() - self.start_time).total_seconds()
    
    def has_error(self) -> bool:
        """
        检查是否有错误
        
        Returns:
            True 如果有错误
        """
        return self.error is not None
    
    def is_completed(self) -> bool:
        """
        检查作业是否已完成
        
        Returns:
            True 如果作业已完成（无论成功或失败）
        """
        return self.exit_code is not None or self.error is not None

