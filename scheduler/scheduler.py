"""
Job Scheduler - 作业调度器

算法：FIFO + First Fit
资源管理：
- 动态资源：从 Redis 获取活跃 Worker 的总资源
- 资源缓存：使用 Redis 缓存已分配资源，提升性能
- 数据库持久化：保证一致性和故障恢复
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
    作业调度器 v3.0 - 动态资源管理

    核心改进：
    1. 动态资源感知：从活跃 Worker 获取总资源，支持动态扩缩容
    2. Redis 缓存：缓存已分配资源，避免频繁数据库查询
    3. 数据库持久化：保证数据一致性
    4. 定期同步：从数据库同步到 Redis（容错机制）
    """

    # Redis 键名
    REDIS_KEY_ALLOCATED_CPUS = "resource:allocated_cpus"
    REDIS_KEY_AVAILABLE_CPUS = "resource:available_cpus"

    def __init__(self):
        self.settings = get_settings()
        # 注意：不再使用配置文件中的固定 TOTAL_CPUS
        # 改为从 Redis 动态获取活跃 Worker 的总资源
        self.queue = redis_manager.get_queue()

        # 初始化 Redis 缓存
        self._init_resource_cache()

    def schedule(self) -> int:
        """
        调度待处理作业（使用动态资源）

        Returns:
            已调度的作业数量
        """
        scheduled_count = 0

        # 1. 获取动态总资源（从活跃 Worker）
        total_cpus = self._get_total_cpus_dynamic()

        if total_cpus == 0:
            logger.warning("⚠️  No active workers, skipping schedule")
            return 0

        with sync_db.get_session() as session:
            # 2. 获取已分配资源（优先使用 Redis 缓存）
            allocated_cpus = self._get_allocated_cpus_cached()
            available_cpus = total_cpus - allocated_cpus

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
            utilization = self._calculate_utilization()
            logger.info(
                f"✅ Scheduled {scheduled_count} jobs, "
                f"utilization: {utilization:.1f}% ({allocated_cpus + scheduled_count}/{total_cpus} CPUs)"
            )

        return scheduled_count

    def _init_resource_cache(self):
        """初始化 Redis 资源缓存（从数据库同步）"""
        try:
            with sync_db.get_session() as session:
                allocated_cpus = self._get_allocated_cpus(session)

            redis = redis_manager.get_connection()
            redis.set(self.REDIS_KEY_ALLOCATED_CPUS, allocated_cpus)

            logger.debug(f"Resource cache initialized: {allocated_cpus} CPUs allocated")

        except Exception as e:
            logger.warning(f"Failed to initialize resource cache: {e}")

    def _get_total_cpus_dynamic(self) -> int:
        """
        动态获取所有活跃 Worker 的 CPU 总数

        Returns:
            CPU 总数（如果没有活跃 Worker 则返回 0）
        """
        try:
            redis = redis_manager.get_connection()
            worker_keys = redis.keys("worker:*")

            if not worker_keys:
                return 0

            total_cpus = 0
            active_workers = []

            for key in worker_keys:
                worker_info = redis.hgetall(key)
                if worker_info:
                    cpus = int(worker_info.get(b"cpus", 0))
                    worker_id = worker_info.get(b"worker_id", b"unknown").decode()
                    total_cpus += cpus
                    active_workers.append(worker_id)

            logger.debug(
                f"Active workers: {len(active_workers)}, Total CPUs: {total_cpus}"
            )
            return total_cpus

        except Exception as e:
            logger.error(f"Failed to get dynamic total CPUs: {e}")
            # 降级：使用配置文件中的值
            return self.settings.TOTAL_CPUS

    def _get_allocated_cpus_cached(self) -> int:
        """
        获取已分配的 CPU 数量（优先使用 Redis 缓存）

        Returns:
            已分配的 CPU 数量
        """
        try:
            redis = redis_manager.get_connection()
            allocated = redis.get(self.REDIS_KEY_ALLOCATED_CPUS)

            if allocated is not None:
                return int(allocated)

            # 缓存未命中，从数据库查询
            logger.debug("Cache miss, querying database")
            with sync_db.get_session() as session:
                allocated = self._get_allocated_cpus(session)
                redis.set(self.REDIS_KEY_ALLOCATED_CPUS, allocated)
                return allocated

        except Exception as e:
            logger.error(f"Failed to get cached allocated CPUs: {e}")
            # 降级：直接查询数据库
            with sync_db.get_session() as session:
                return self._get_allocated_cpus(session)

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
        分配资源并将作业加入队列（包含 Redis 缓存更新）

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

            # 4. 更新 Redis 缓存（增加已分配资源）
            try:
                redis = redis_manager.get_connection()
                redis.incrby(self.REDIS_KEY_ALLOCATED_CPUS, cpus)
            except Exception as e:
                logger.warning(f"Failed to update Redis cache: {e}")

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
        释放已完成作业的资源（兜底机制 + Redis 缓存更新）

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

                # 更新 Redis 缓存（减少已分配资源）
                try:
                    redis = redis_manager.get_connection()
                    redis.decrby(self.REDIS_KEY_ALLOCATED_CPUS, total_released_cpus)
                except Exception as e:
                    logger.warning(f"Failed to update Redis cache: {e}")

        return released_count

    def _calculate_utilization(self) -> float:
        """
        计算当前资源利用率（使用动态资源）

        Returns:
            利用率百分比
        """
        total_cpus = self._get_total_cpus_dynamic()
        if total_cpus == 0:
            return 0.0

        allocated = self._get_allocated_cpus_cached()
        return (allocated / total_cpus) * 100.0

    def get_stats(self) -> dict:
        """获取资源统计信息（使用动态资源和缓存）"""
        total_cpus = self._get_total_cpus_dynamic()
        allocated = self._get_allocated_cpus_cached()
        available = total_cpus - allocated
        utilization = self._calculate_utilization()

        return {
            "total_cpus": total_cpus,
            "used_cpus": allocated,
            "available_cpus": available,
            "utilization": utilization,
        }

    def sync_resource_cache(self):
        """
        从数据库同步资源状态到 Redis（容错机制）

        定期调用此方法，确保 Redis 缓存与数据库一致
        """
        try:
            with sync_db.get_session() as session:
                allocated = self._get_allocated_cpus(session)

            redis = redis_manager.get_connection()
            redis.set(self.REDIS_KEY_ALLOCATED_CPUS, allocated)

            logger.debug(f"Resource cache synced: {allocated} CPUs allocated")

        except Exception as e:
            logger.error(f"Failed to sync resource cache: {e}")
