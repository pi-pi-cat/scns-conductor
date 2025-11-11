"""
Job Scheduler - 作业调度器

算法：FIFO + First Fit
资源管理：使用 ResourceManager 统一管理资源

重构说明：
- 使用 ResourceManager 替代重复的资源查询逻辑
- 遵循 DRY 原则，避免代码重复
- 使用服务层提供的统一接口
"""

from datetime import datetime
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from core.redis_client import redis_manager
from core.services import ResourceManager


class JobScheduler:
    """
    作业调度器 v4.0 - 使用服务层架构

    改进：
    - 使用 ResourceManager 统一管理资源
    - 遵循 DRY 原则
    - 降低耦合度
    """

    def __init__(self, resource_manager: ResourceManager = None):
        """
        初始化调度器

        Args:
            resource_manager: 资源管理器（可选，用于依赖注入）
        """
        self.settings = get_settings()
        self.queue = redis_manager.get_queue()

        # 使用资源管理器（依赖注入）
        self.resource_manager = resource_manager or ResourceManager()

        # 初始化资源缓存
        self.resource_manager.init_cache()

    def schedule(self) -> int:
        """
        调度待处理作业

        Returns:
            已调度的作业数量
        """
        scheduled_count = 0

        # 1. 获取资源信息（使用 ResourceManager）
        total_cpus = self.resource_manager.get_total_cpus()
        if total_cpus == 0:
            logger.warning("⚠️  No active workers, skipping schedule")
            return 0

        with sync_db.get_session() as session:
            # 2. 获取可用资源
            available_cpus = self.resource_manager.get_available_cpus()

            # 3. 查询 PENDING 作业（按提交时间排序）
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
                f"available CPUs: {available_cpus}/{total_cpus}"
            )

            # 4. 尝试调度每个作业
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

            # 5. 提交所有更改
            session.commit()

        if scheduled_count > 0:
            stats = self.resource_manager.get_stats()
            logger.info(
                f"✅ Scheduled {scheduled_count} jobs, "
                f"utilization: {stats['utilization']:.1f}% "
                f"({stats['allocated_cpus']}/{stats['total_cpus']} CPUs)"
            )

        return scheduled_count

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
            # 1. 创建资源分配记录
            allocation = ResourceAllocation(
                job_id=job.id,
                allocated_cpus=cpus,
                node_name=self.settings.NODE_NAME,
                allocation_time=datetime.utcnow(),
                released=False,
            )
            session.add(allocation)

            # 2. 更新作业状态
            job.state = JobState.RUNNING
            job.start_time = datetime.utcnow()
            job.node_list = self.settings.NODE_NAME

            # 3. 提交数据库（确保状态持久化）
            session.flush()

            # 4. 更新资源缓存（使用 ResourceManager）
            self.resource_manager.allocate(cpus)

            # 5. 加入执行队列
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
        total_released_cpus = 0

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
                total_released_cpus += allocation.allocated_cpus

                logger.warning(
                    f"♻️  Released orphan resources for job {allocation.job_id}: "
                    f"{allocation.allocated_cpus} CPUs"
                )
                released_count += 1

            if released_count > 0:
                session.commit()
                # 使用 ResourceManager 更新缓存
                self.resource_manager.release(total_released_cpus)

        return released_count

    def get_stats(self) -> dict:
        """获取资源统计信息"""
        return self.resource_manager.get_stats()

    def sync_resource_cache(self):
        """
        从数据库同步资源状态到 Redis（容错机制）
        """
        self.resource_manager.sync_cache_from_db()
