"""
Job Scheduler - 作业调度器

算法：FIFO + First Fit
- FIFO: 按提交时间排序
- First Fit: 有资源就分配
"""

from datetime import datetime
from typing import List

from loguru import logger
from sqlalchemy.orm import Session

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from core.redis_client import redis_manager

from shared.resource_manager import ResourceManager


class JobScheduler:
    """作业调度器"""
    
    def __init__(self):
        self.settings = get_settings()
        self.resource_manager = ResourceManager()
        self.queue = redis_manager.get_queue()
    
    def schedule(self) -> int:
        """
        调度待处理作业
        
        Returns:
            已调度的作业数量
        """
        scheduled_count = 0
        
        with sync_db.get_session() as session:
            # 查询 PENDING 作业（按提交时间排序）
            pending_jobs = (
                session.query(Job)
                .filter(Job.state == JobState.PENDING)
                .order_by(Job.submit_time)
                .all()
            )
            
            if not pending_jobs:
                return 0
            
            logger.debug(f"Found {len(pending_jobs)} pending jobs")
            
            # 尝试调度每个作业
            for job in pending_jobs:
                if self._try_schedule_job(session, job):
                    scheduled_count += 1
            
            session.commit()
        
        if scheduled_count > 0:
            utilization = self.resource_manager.get_utilization()
            logger.info(
                f"✅ Scheduled {scheduled_count} jobs, "
                f"utilization: {utilization:.1f}%"
            )
        
        return scheduled_count
    
    def _try_schedule_job(self, session: Session, job: Job) -> bool:
        """
        尝试调度单个作业
        
        Returns:
            True 如果调度成功
        """
        required_cpus = job.total_cpus_required
        
        # 检查资源
        if not self.resource_manager.can_allocate(required_cpus):
            logger.debug(
                f"Job {job.id}: insufficient resources "
                f"(need {required_cpus}, available {self.resource_manager.available})"
            )
            return False
        
        # 分配资源
        if not self.resource_manager.allocate(required_cpus):
            return False
        
        try:
            # 创建资源分配记录
            allocation = ResourceAllocation(
                job_id=job.id,
                allocated_cpus=required_cpus,
                node_name=self.settings.NODE_NAME,
                allocation_time=datetime.utcnow(),
                released=False,
            )
            session.add(allocation)
            
            # 更新作业状态
            job.state = JobState.RUNNING
            job.start_time = datetime.utcnow()
            job.node_list = self.settings.NODE_NAME
            
            # 提交数据库更改
            session.flush()
            
            # 加入执行队列
            self.queue.enqueue(
                "worker.executor.execute_job",
                job.id,
                job_id=f"job_{job.id}",
                job_timeout=24 * 3600,
            )
            
            logger.info(
                f"✓ Scheduled job {job.id} ({job.name}): "
                f"{required_cpus} CPUs"
            )
            return True
        
        except Exception as e:
            logger.error(f"Failed to schedule job {job.id}: {e}")
            # 回滚资源
            self.resource_manager.release(required_cpus)
            # 回滚数据库（session 会自动回滚）
            return False
    
    def release_completed(self) -> int:
        """
        释放已完成作业的资源（兜底机制）
        
        Returns:
            释放的作业数量
        """
        released_count = 0
        
        with sync_db.get_session() as session:
            # 查询已完成但未释放资源的作业
            stale_allocations = (
                session.query(ResourceAllocation)
                .join(Job)
                .filter(
                    ResourceAllocation.released == False,
                    Job.state.in_([
                        JobState.COMPLETED,
                        JobState.FAILED,
                        JobState.CANCELLED
                    ])
                )
                .all()
            )
            
            for allocation in stale_allocations:
                allocation.released = True
                allocation.released_time = datetime.utcnow()
                self.resource_manager.release(allocation.allocated_cpus)
                
                logger.warning(
                    f"♻️  Released orphan resources for job {allocation.job_id}: "
                    f"{allocation.allocated_cpus} CPUs"
                )
                released_count += 1
            
            if released_count > 0:
                session.commit()
        
        return released_count
    
    def get_stats(self) -> dict:
        """获取资源统计信息"""
        return {
            "total_cpus": self.resource_manager.total,
            "used_cpus": self.resource_manager.used,
            "available_cpus": self.resource_manager.available,
            "utilization": self.resource_manager.get_utilization(),
        }

