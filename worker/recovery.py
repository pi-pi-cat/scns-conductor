"""
Worker 故障恢复模块
处理 Worker 异常退出后的状态恢复和孤儿作业清理
"""
import os
import signal
from datetime import datetime
from typing import List

from loguru import logger
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState


class RecoveryManager:
    """
    恢复管理器
    
    负责在 Worker 启动时检查并恢复系统状态：
    1. 检测孤儿作业（RUNNING 状态但进程已不存在）
    2. 清理资源分配
    3. 标记失败作业
    4. 释放被占用的资源
    """
    
    def __init__(self):
        self.settings = get_settings()
    
    def recover_on_startup(self) -> None:
        """
        Worker 启动时执行恢复操作
        
        执行步骤：
        1. 检查所有 RUNNING 状态的作业
        2. 验证进程是否还存在
        3. 对于不存在的进程，标记作业为 FAILED
        4. 释放所有相关资源
        """
        logger.info("开始执行 Worker 启动恢复检查...")
        
        with sync_db.get_session() as session:
            # 查找所有 RUNNING 状态的作业
            running_jobs = session.query(Job).filter(
                Job.state == JobState.RUNNING
            ).all()
            
            if not running_jobs:
                logger.info("没有需要恢复的 RUNNING 作业")
                return
            
            logger.info(f"发现 {len(running_jobs)} 个 RUNNING 状态的作业，开始检查...")
            
            recovered_count = 0
            for job in running_jobs:
                if self._is_job_process_alive(session, job):
                    logger.info(
                        f"作业 {job.id} 的进程仍在运行，保持 RUNNING 状态"
                    )
                else:
                    # 进程不存在，标记为失败
                    self._mark_job_as_failed_on_recovery(session, job)
                    recovered_count += 1
            
            session.commit()
            
            logger.info(
                f"恢复检查完成：标记了 {recovered_count} 个孤儿作业为 FAILED"
            )
    
    def _is_job_process_alive(self, session: Session, job: Job) -> bool:
        """
        检查作业的进程是否还存活
        
        Args:
            session: 数据库会话
            job: 作业对象
        
        Returns:
            True 如果进程存在，False 否则
        """
        # 查询资源分配记录获取进程ID
        allocation = session.query(ResourceAllocation).filter(
            ResourceAllocation.job_id == job.id
        ).first()
        
        if not allocation or not allocation.process_id:
            logger.warning(f"作业 {job.id} 没有进程ID记录")
            return False
        
        try:
            # 发送信号 0 检查进程是否存在（不会真正发送信号）
            os.kill(allocation.process_id, 0)
            return True
        except OSError:
            # 进程不存在
            logger.warning(
                f"作业 {job.id} 的进程 {allocation.process_id} 不存在"
            )
            return False
        except Exception as e:
            logger.error(f"检查进程状态时出错: {e}")
            return False
    
    def _mark_job_as_failed_on_recovery(
        self,
        session: Session,
        job: Job
    ) -> None:
        """
        将孤儿作业标记为失败并释放资源
        
        Args:
            session: 数据库会话
            job: 作业对象
        """
        logger.warning(
            f"将孤儿作业 {job.id} ({job.name}) 标记为 FAILED"
        )
        
        # 更新作业状态
        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = (
            "Worker 异常退出导致作业中断。"
            "此作业在 Worker 重启时被检测为孤儿进程并标记为失败。"
        )
        job.exit_code = "-999:0"  # 特殊退出码表示 Worker 异常
        
        # 释放资源
        allocation = session.query(ResourceAllocation).filter(
            ResourceAllocation.job_id == job.id,
            ResourceAllocation.released == False
        ).first()
        
        if allocation:
            allocation.released = True
            allocation.released_time = datetime.utcnow()
            logger.info(
                f"释放作业 {job.id} 的资源：{allocation.allocated_cpus} CPUs"
            )
    
    def cleanup_stale_allocations(self, max_age_hours: int = 48) -> int:
        """
        清理陈旧的资源分配记录
        
        对于已完成/失败/取消但资源未释放的作业，释放其资源
        
        Args:
            max_age_hours: 最大年龄（小时），超过此时间的完成作业将被清理
        
        Returns:
            清理的资源分配数量
        """
        logger.info(f"开始清理超过 {max_age_hours} 小时的陈旧资源...")
        
        from datetime import timedelta
        threshold_time = datetime.utcnow() - timedelta(hours=max_age_hours)
        
        with sync_db.get_session() as session:
            # 查找终态作业但资源未释放的记录
            stale_allocations = session.query(ResourceAllocation).join(Job).filter(
                Job.state.in_([JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]),
                Job.end_time < threshold_time,
                ResourceAllocation.released == False
            ).all()
            
            count = len(stale_allocations)
            
            for allocation in stale_allocations:
                allocation.released = True
                allocation.released_time = datetime.utcnow()
                logger.info(
                    f"释放陈旧资源分配：作业 {allocation.job_id}, "
                    f"{allocation.allocated_cpus} CPUs"
                )
            
            session.commit()
            
            logger.info(f"清理完成：释放了 {count} 个陈旧资源分配")
            return count


def check_orphan_jobs() -> List[int]:
    """
    独立函数：检查所有孤儿作业
    
    可以被定期任务调用，用于持续监控
    
    Returns:
        孤儿作业的 ID 列表
    """
    orphan_job_ids = []
    
    with sync_db.get_session() as session:
        running_jobs = session.query(Job).filter(
            Job.state == JobState.RUNNING
        ).all()
        
        for job in running_jobs:
            allocation = session.query(ResourceAllocation).filter(
                ResourceAllocation.job_id == job.id
            ).first()
            
            if not allocation or not allocation.process_id:
                continue
            
            try:
                os.kill(allocation.process_id, 0)
            except OSError:
                # 进程不存在
                orphan_job_ids.append(job.id)
                logger.warning(f"检测到孤儿作业: {job.id}")
        
        return orphan_job_ids

