"""
异步读取作业日志文件的服务
"""
import os
from typing import Tuple
import aiofiles
from loguru import logger

from core.models import Job


class LogReaderService:
    """读取作业日志文件的服务"""
    
    @staticmethod
    async def read_log_file(file_path: str, max_lines: int = 1000) -> str:
        """
        异步读取日志文件（带大小限制）
        
        Args:
            file_path: 日志文件路径
            max_lines: 最多读取的行数（从末尾开始）
        
        Returns:
            文件内容字符串
        """
        if not os.path.exists(file_path):
            return ""
        
        try:
            # 检查文件大小
            file_size = os.path.getsize(file_path)
            
            # 小文件直接读取
            if file_size < 1024 * 1024:  # 小于1MB
                async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = await f.read()
                    return content
            
            # 大文件读取最后N行
            async with aiofiles.open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                lines = []
                async for line in f:
                    lines.append(line)
                    if len(lines) > max_lines:
                        lines.pop(0)
                
                content = ''.join(lines)
                if len(lines) == max_lines:
                    content = f"... (showing last {max_lines} lines) ...\n" + content
                
                return content
        
        except Exception as e:
            logger.error(f"Failed to read log file {file_path}: {e}")
            return f"[Error reading log file: {e}]"
    
    @staticmethod
    async def get_job_logs(job: Job) -> Tuple[str, str]:
        """
        Get stdout and stderr logs for a job
        
        Args:
            job: Job model instance
        
        Returns:
            Tuple of (stdout_content, stderr_content)
        """
        # Construct full paths
        stdout_path = os.path.join(job.work_dir, job.stdout_path)
        stderr_path = os.path.join(job.work_dir, job.stderr_path)
        
        # Read both files concurrently
        import asyncio
        stdout_content, stderr_content = await asyncio.gather(
            LogReaderService.read_log_file(stdout_path),
            LogReaderService.read_log_file(stderr_path),
            return_exceptions=False
        )
        
        return stdout_content, stderr_content

