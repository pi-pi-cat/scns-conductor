"""
进程管理工具函数
"""

import os
import signal
import time
from typing import Optional
from loguru import logger

from sqlalchemy.orm import Session
from core.models import ResourceAllocation
from core.database import sync_db


def check_process_exists(pid: int) -> bool:
    """
    检查进程是否存在
    
    Args:
        pid: 进程ID
    
    Returns:
        如果进程存在返回 True，否则返回 False
    """
    try:
        # 发送信号 0 检查进程是否存在（不会真正发送信号）
        os.kill(pid, 0)
        return True
    except OSError:
        return False
    except Exception as e:
        logger.error(f"检查进程 {pid} 状态时出错: {e}")
        return False


def kill_process_group(pid: int, grace_period: int = 5) -> bool:
    """
    终止进程组
    
    先尝试 SIGTERM 优雅终止，等待一段时间后使用 SIGKILL 强制终止
    
    Args:
        pid: 进程ID
        grace_period: 宽限期（秒）
    
    Returns:
        成功返回 True，否则返回 False
    """
    try:
        # 尝试优雅终止
        logger.info(f"发送 SIGTERM 到进程组 {pid}")
        os.killpg(os.getpgid(pid), signal.SIGTERM)
        
        # 等待宽限期
        time.sleep(grace_period)
        
        # 检查进程是否还存在
        if check_process_exists(pid):
            logger.warning(f"进程组 {pid} 未响应 SIGTERM，发送 SIGKILL")
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        
        return True
    except ProcessLookupError:
        # 进程已经不存在
        return True
    except Exception as e:
        logger.error(f"终止进程组 {pid} 失败: {e}")
        return False


def store_process_id(job_id: int, pid: int) -> bool:
    """
    在资源分配记录中存储进程ID
    
    Args:
        job_id: 作业ID
        pid: 进程ID
    
    Returns:
        成功返回 True，否则返回 False
    """
    try:
        with sync_db.get_session() as session:
            allocation = (
                session.query(ResourceAllocation)
                .filter(ResourceAllocation.job_id == job_id)
                .first()
            )
            
            if allocation:
                allocation.process_id = pid
                session.commit()
                return True
            else:
                logger.warning(f"未找到作业 {job_id} 的资源分配记录")
                return False
    except Exception as e:
        logger.error(f"存储进程ID失败: {e}")
        return False


def get_process_id(job_id: int, session: Optional[Session] = None) -> Optional[int]:
    """
    获取作业的进程ID
    
    Args:
        job_id: 作业ID
        session: 数据库会话（可选）
    
    Returns:
        进程ID，如果不存在返回 None
    """
    try:
        if session:
            allocation = (
                session.query(ResourceAllocation)
                .filter(ResourceAllocation.job_id == job_id)
                .first()
            )
            return allocation.process_id if allocation else None
        else:
            with sync_db.get_session() as session:
                allocation = (
                    session.query(ResourceAllocation)
                    .filter(ResourceAllocation.job_id == job_id)
                    .first()
                )
                return allocation.process_id if allocation else None
    except Exception as e:
        logger.error(f"获取进程ID失败: {e}")
        return None

