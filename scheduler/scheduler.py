"""
Job Scheduler - 作业调度器

算法：FIFO + First Fit
资源管理：直接使用数据库作为唯一真实源
"""

from datetime import datetime
from loguru import logger
from sqlalchemy import func

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from core.redis_client import redis_manager


class JobScheduler:
    """
    作业调度器

    使用数据库作为资源状态的唯一真实源：
    - 每次调度时查询当前已分配资源
    - 使用数据库事务保证一致性
    - 无需额外的资源管理器
    """

    def __init__(self):
        self.settings = get_settings()
        self.total_cpus = self.settings.TOTAL_CPUS
        self.queue = redis_manager.get_queue()

    def schedule(self) -> int:
        """
        调度待处理作业

        Returns:
            已调度的作业数量
        """
        scheduled_count = 0

        with sync_db.get_session() as session:
            # 查询当前已分配的 CPU 总数（从数据库）
            allocated_cpus = self._get_allocated_cpus(session)
            available_cpus = self.total_cpus - allocated_cpus

            # 查询 PENDING 作业（按提交时间排序）
            pending_jobs = (
                session.query(Job)
                .filter(Job.state == JobState.PENDING)
                .order_by(Job.submit_time)
                .all()
            )

            if not pending_jobs:
                return 0

            logger.debug(
                f"Found {len(pending_jobs)} pending jobs, "
                f"available CPUs: {available_cpus}/{self.total_cpus}"
            )

            # 尝试调度每个作业
            for job in pending_jobs:
                required_cpus = job.total_cpus_required

                # 检查资源是否充足
                if available_cpus >= required_cpus:
                    if self._allocate_and_enqueue(session, job, required_cpus):
                        available_cpus -= required_cpus
                        scheduled_count += 1
                else:
                    logger.debug(
                        f"Job {job.id}: insufficient resources "
                        f"(need {required_cpus}, available {available_cpus})"
                    )

            # 提交所有更改
            session.commit()

        if scheduled_count > 0:
            utilization = self._calculate_utilization()
            logger.info(
                f"✅ Scheduled {scheduled_count} jobs, utilization: {utilization:.1f}%"
            )

        return scheduled_count

    def _get_allocated_cpus(self, session) -> int:
        """
        从数据库查询当前已分配的 CPU 总数

        Args:
            session: 数据库会话

        Returns:
            已分配的 CPU 数量
        """
        result = (
            session.query(func.sum(ResourceAllocation.allocated_cpus))
            .filter(~ResourceAllocation.released)
            .scalar()
        )
        return result or 0

    def _allocate_and_enqueue(self, session, job: Job, cpus: int) -> bool:
        """
        分配资源并将作业加入队列

        Args:
            session: 数据库会话
            job: 作业对象
            cpus: 要分配的 CPU 数量

        Returns:
            True 如果成功
        """
        try:
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

            # 先提交数据库（确保状态持久化）
            session.flush()

            # 加入执行队列
            self.queue.enqueue(
                "worker.executor.execute_job",
                job.id,
                job_id=f"job_{job.id}",
                job_timeout=24 * 3600,
            )

            logger.info(f"✓ Scheduled job {job.id} ({job.name}): {cpus} CPUs")
            return True

        except Exception as e:
            logger.error(f"Failed to schedule job {job.id}: {e}")
            # 事务会自动回滚
            return False

    def release_completed(self) -> int:
        """
        释放已完成作业的资源（兜底机制）

        检查所有已完成但资源未释放的作业，并释放其资源

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
                    ~ResourceAllocation.released,
                    Job.state.in_(
                        [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                    ),
                )
                .all()
            )

            for allocation in stale_allocations:
                allocation.released = True
                allocation.released_time = datetime.utcnow()

                logger.warning(
                    f"♻️  Released orphan resources for job {allocation.job_id}: "
                    f"{allocation.allocated_cpus} CPUs"
                )
                released_count += 1

            if released_count > 0:
                session.commit()

        return released_count

    def _calculate_utilization(self) -> float:
        """
        计算当前资源利用率

        Returns:
            利用率百分比
        """
        with sync_db.get_session() as session:
            allocated = self._get_allocated_cpus(session)
            if self.total_cpus == 0:
                return 0.0
            return (allocated / self.total_cpus) * 100.0

    def get_stats(self) -> dict:
        """获取资源统计信息"""
        with sync_db.get_session() as session:
            allocated = self._get_allocated_cpus(session)
            available = self.total_cpus - allocated
            utilization = self._calculate_utilization()

            return {
                "total_cpus": self.total_cpus,
                "used_cpus": allocated,
                "available_cpus": available,
                "utilization": utilization,
            }
