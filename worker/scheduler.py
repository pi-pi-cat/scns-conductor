"""
作业调度器 - 实现FIFO + First Fit资源分配算法
"""

from datetime import datetime
from typing import List
from sqlalchemy.orm import Session
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from .resource_tracker import ResourceTracker


class ResourceScheduler:
    """
    作业调度器 - 实现FIFO + First Fit算法
    基于可用CPU资源调度待处理作业
    """

    def __init__(self):
        self.resource_tracker = ResourceTracker()
        self.settings = get_settings()

    def schedule_pending_jobs(self) -> List[int]:
        """
        基于可用资源调度待处理作业

        返回值:
            已调度作业的ID列表
        """
        scheduled_jobs = []

        with sync_db.get_session() as session:
            # 查询待处理作业，按提交时间排序（FIFO）
            pending_jobs = (
                session.query(Job)
                .filter(Job.state == JobState.PENDING)
                .order_by(Job.submit_time)
                .all()
            )

            if not pending_jobs:
                return scheduled_jobs

            logger.info(f"🔍 发现 {len(pending_jobs)} 个待处理作业，开始调度...")

            # 尝试调度每个作业
            for job in pending_jobs:
                required_cpus = job.total_cpus_required

                # 检查资源是否可分配（First Fit）
                if self.resource_tracker.can_allocate(required_cpus):
                    # 分配资源
                    if self._allocate_resources(session, job, required_cpus):
                        scheduled_jobs.append(job.id)
                        logger.info(
                            f"已调度作业 {job.id} ({job.name}): cpus={required_cpus}"
                        )
                else:
                    logger.info(
                        f"⏳ 作业 {job.id} ({job.name}) 资源不足: "
                        f"需要={required_cpus} CPUs, "
                        f"可用={self.resource_tracker.available_cpus} CPUs"
                    )

            # 提交所有变更
            session.commit()

        if scheduled_jobs:
            stats = self.resource_tracker.get_stats()
            logger.info(
                f"共调度 {len(scheduled_jobs)} 个作业，"
                f"资源利用率: {stats['utilization']:.1f}%"
            )

        return scheduled_jobs

    def _allocate_resources(self, session: Session, job: Job, cpus: int) -> bool:
        """
        给指定作业分配资源

        参数:
            session: 数据库会话
            job: 目标作业
            cpus: 待分配的CPU数量

        返回:
            分配成功返回True，否则返回False
        """
        try:
            # 更新资源跟踪器
            if not self.resource_tracker.allocate(cpus):
                return False

            # 创建资源分配记录
            allocation = ResourceAllocation(
                job_id=job.id,
                allocated_cpus=cpus,
                node_name=self.settings.NODE_NAME,
                allocation_time=datetime.utcnow(),
                released=False,
            )
            session.add(allocation)

            # 更新作业状态
            job.state = JobState.RUNNING
            job.start_time = datetime.utcnow()
            job.node_list = self.settings.NODE_NAME

            return True

        except Exception as e:
            logger.error(f"为作业 {job.id} 分配资源失败: {e}")
            # 回滚资源跟踪器
            self.resource_tracker.release(cpus)
            return False

    def release_resources(self, job_id: int) -> None:
        """
        释放已完成作业占用的资源

        参数:
            job_id: 作业ID
        """
        with sync_db.get_session() as session:
            # 查找资源分配记录
            allocation = (
                session.query(ResourceAllocation)
                .filter(
                    ResourceAllocation.job_id == job_id,
                    ResourceAllocation.released == False,
                )
                .first()
            )

            if allocation:
                # 标记为已释放
                allocation.released = True
                allocation.released_time = datetime.utcnow()

                # 更新资源跟踪器
                self.resource_tracker.release(allocation.allocated_cpus)

                session.commit()

                logger.info(
                    f"已释放作业 {job_id} 的资源: cpus={allocation.allocated_cpus}"
                )
            else:
                logger.warning(f"未找到作业 {job_id} 的活跃分配记录")

    def get_resource_stats(self) -> dict:
        """获取当前资源统计信息"""
        return self.resource_tracker.get_stats()
