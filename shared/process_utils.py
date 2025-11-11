"""
Process Utilities - 进程管理工具
"""

import os
import signal
import time

from loguru import logger


def store_pid(job_id: int, pid: int):
    """
    存储进程 ID（可选实现）
    
    Args:
        job_id: 作业 ID
        pid: 进程 ID
    """
    # 可以将 PID 存储到文件或数据库
    # 这里简化处理，只记录日志
    logger.debug(f"Job {job_id} PID: {pid}")


def kill_process_tree(pid: int, timeout: int = 5):
    """
    终止进程树
    
    Args:
        pid: 进程 ID
        timeout: 超时时间（秒）
    """
    try:
        # 发送 SIGTERM
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        
        # 等待进程结束
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                os.kill(pid, 0)  # 检查进程是否存在
                time.sleep(0.1)
            except ProcessLookupError:
                return  # 进程已结束
        
        # 超时，发送 SIGKILL
        logger.warning(f"Process {pid} did not terminate, sending SIGKILL")
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    
    except ProcessLookupError:
        pass  # 进程不存在
    except Exception as e:
        logger.error(f"Failed to kill process {pid}: {e}")

