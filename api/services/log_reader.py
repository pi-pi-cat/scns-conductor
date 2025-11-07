"""
异步读取作业日志文件服务
"""

import os
from typing import Tuple
import aiofiles
from loguru import logger

from core.models import Job


class LogReaderService:
    """异步读取作业日志文件的服务"""

    @staticmethod
    async def read_log_file(file_path: str, max_lines: int = 1000) -> str:
        """
        异步读取日志文件（支持读取最后 N 行，适配大文件）

        参数:
            file_path: 日志文件路径
            max_lines: 最多读取的行数（针对大文件，仅读取末尾）

        返回:
            文件内容字符串
        """
        if not os.path.exists(file_path):
            return ""

        try:
            # 检查文件大小以判断读取方式
            file_size = os.path.getsize(file_path)

            # 小文件（< 1MB）直接全部读取
            if file_size < 1024 * 1024:  # 小于1MB
                async with aiofiles.open(
                    file_path, "r", encoding="utf-8", errors="ignore"
                ) as f:
                    content = await f.read()
                    return content

            # 大文件: 仅保留最后 max_lines 行
            async with aiofiles.open(
                file_path, "r", encoding="utf-8", errors="ignore"
            ) as f:
                lines = []
                async for line in f:
                    lines.append(line)
                    if len(lines) > max_lines:
                        lines.pop(0)

                content = "".join(lines)
                if len(lines) == max_lines:
                    # 加前缀说明为截断内容
                    content = f"...（仅展示最后 {max_lines} 行）...\n" + content

                return content

        except Exception as e:
            logger.error(f"读取日志文件失败 {file_path}: {e}")
            return f"[读取日志文件出错: {e}]"

    @staticmethod
    async def get_job_logs(job: Job) -> Tuple[str, str]:
        """
        获取指定作业的标准输出与标准错误日志内容（异步并发读取）

        参数:
            job: Job 模型实例

        返回:
            (stdout_content, stderr_content) 二元组
        """
        # 组装标准输出和错误的绝对路径
        stdout_path = os.path.join(job.work_dir, job.stdout_path)
        stderr_path = os.path.join(job.work_dir, job.stderr_path)

        # 并发读取两个文件
        import asyncio

        stdout_content, stderr_content = await asyncio.gather(
            LogReaderService.read_log_file(stdout_path),
            LogReaderService.read_log_file(stderr_path),
            return_exceptions=False,
        )

        return stdout_content, stderr_content
