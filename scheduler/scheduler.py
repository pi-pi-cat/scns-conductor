"""
Job Scheduler - 作业调度器

算法：FIFO + First Fit
资源管理：使用 ResourceManager 统一管理资源

架构说明：
- 使用 ResourceManager 统一管理资源
- 使用 SchedulerRepository 封装数据库操作
- 使用 CleanupStrategyManager 管理清理策略
- 遵循单一职责原则和关注点分离
"""

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job
from core.enums import ResourceStatus
from core.redis_client import redis_manager
from core.services import ResourceManager
from scheduler.cleanup_strategies import CleanupStrategyManager, create_default_manager
from scheduler.repositories import SchedulerRepository


class JobScheduler:
    """
    作业调度器 v4.1 - Repository 模式重构

    架构改进：
    - 使用 ResourceManager 统一管理资源
    - 使用 SchedulerRepository 封装数据库操作
    - 使用 CleanupStrategyManager 管理清理策略
    - 遵循单一职责原则，降低耦合度
    """

    def __init__(
        self,
        resource_manager: ResourceManager = None,
        cleanup_manager: CleanupStrategyManager = None,
    ):
        """
        初始化调度器

        Args:
            resource_manager: 资源管理器（可选，用于依赖注入）
            cleanup_manager: 清理策略管理器（可选，用于依赖注入）
        """
        self.settings = get_settings()
        self.queue = redis_manager.get_queue()

        # 使用资源管理器（依赖注入）
        self.resource_manager = resource_manager or ResourceManager()

        # 使用清理策略管理器（依赖注入）
        self.cleanup_manager = cleanup_manager or create_default_manager()

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
            pending_jobs = SchedulerRepository.get_pending_jobs(session)

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
        预留资源并将作业加入队列

        注意：这里只是预留资源（status=reserved），真正的资源分配
        在 Worker 开始执行时才会更新为 allocated 状态。这样可以避免
        作业被调度但未实际运行时资源被永久占用的问题。

        Args:
            session: 数据库会话
            job: 作业对象
            cpus: 要分配的 CPU 数量

        Returns:
            True 如果成功
        """
        try:
            # 1. 创建资源预留记录（status=reserved）
            SchedulerRepository.create_resource_allocation(
                session=session,
                job_id=job.id,
                allocated_cpus=cpus,
                node_name=self.settings.NODE_NAME,
                status=ResourceStatus.RESERVED,
            )

            # 2. 更新作业状态为 RUNNING
            SchedulerRepository.update_job_to_running(
                session=session,
                job=job,
                node_name=self.settings.NODE_NAME,
            )

            # 3. 提交数据库（确保状态持久化）
            session.flush()

            # 4. 不在这里更新资源缓存，因为资源还没有真正分配
            # 缓存会在 Worker 开始执行时更新

            # 5. 加入执行队列
            self.queue.enqueue(
                "worker.executor.execute_job",
                job.id,
                job_id=f"job_{job.id}",
                job_timeout=24 * 3600,
            )

            logger.info(
                f"✓ Scheduled job {job.id} ({job.name}): {cpus} CPUs (reserved)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to schedule job {job.id}: {e}")
            # 事务会自动回滚
            return False

    def execute_cleanup_strategies(self, current_time: int):
        """
        执行所有到期的清理策略

        Args:
            current_time: 当前时间戳
        """
        self.cleanup_manager.execute_due_strategies(current_time)

    def get_stats(self) -> dict:
        """获取资源统计信息"""
        return self.resource_manager.get_stats()

    def sync_resource_cache(self):
        """
        从数据库同步资源状态到 Redis（容错机制）
        """
        self.resource_manager.sync_cache_from_db()
