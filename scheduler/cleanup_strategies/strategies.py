"""
具体清理策略实现
"""

from datetime import datetime

from loguru import logger
from sqlalchemy.orm import Session

from scheduler.repositories import CleanupRepository

from .base import BaseCleanupStrategy
from .metadata import strategy_metadata
from .types import CleanupResult


@strategy_metadata(
    priority=1,
    depends_on=[],
    tags=["critical", "resource"],
    timeout=60,
)
class CompletedJobCleanupStrategy(BaseCleanupStrategy):
    """释放已完成作业资源的策略（最高优先级）"""

    def __init__(self, interval_seconds: int = 5, repo: CleanupRepository = None):
        super().__init__(interval_seconds)
        self.repo = repo or CleanupRepository()

    @property
    def name(self) -> str:
        return "completed_job_cleanup"

    @property
    def description(self) -> str:
        return "释放已完成但未释放资源的作业"

    def before_execute(self, session: Session) -> bool:
        """
        前置检查：是否有待清理的已完成作业

        优化：移除 count 查询，直接执行 _do_cleanup
        如果数量为 0，影响很小，避免重复查询
        """
        # 不再执行 count 查询，直接执行 _do_cleanup
        # 如果数量为 0，_do_cleanup 会快速返回，影响很小
        return True

    def _do_cleanup(self, session: Session) -> int:
        """释放已完成作业的资源"""
        allocations = self.repo.get_completed_jobs_with_unreleased_resources(session)

        if not allocations:
            logger.debug(f"[{self.name}] No completed jobs to clean")
            return 0

        logger.debug(
            f"[{self.name}] Found {len(allocations)} completed jobs to clean"
        )
        return self.repo.release_resources_for_completed_jobs(session, allocations)

    def after_execute(self, session: Session, result: CleanupResult):
        """后置处理：记录清理统计"""
        if result.items_cleaned > 0:
            logger.info(
                f"[{self.name}] Released resources for {result.items_cleaned} completed jobs"
            )


@strategy_metadata(
    priority=2,
    depends_on=["completed_job_cleanup"],
    tags=["critical", "resource"],
    timeout=120,
)
class StaleReservationCleanupStrategy(BaseCleanupStrategy):
    """清理预留超时的策略"""

    def __init__(
        self,
        interval_seconds: int = 120,
        max_age_minutes: int = 10,
        repo: CleanupRepository = None,
    ):
        super().__init__(interval_seconds)
        self.max_age_minutes = max_age_minutes
        self.repo = repo or CleanupRepository()

    @property
    def name(self) -> str:
        return "stale_reservation_cleanup"

    @property
    def description(self) -> str:
        return f"清理超过 {self.max_age_minutes} 分钟的预留记录"

    def before_execute(self, session: Session) -> bool:
        """
        前置检查：是否有超时的预留

        优化：移除 count 查询，直接执行 _do_cleanup
        如果数量为 0，影响很小，避免重复查询
        """
        # 不再执行 count 查询，直接执行 _do_cleanup
        # 如果数量为 0，_do_cleanup 会快速返回，影响很小
        return True

    def _do_cleanup(self, session: Session) -> int:
        """清理预留超时的资源"""
        stale_reservations = self.repo.get_stale_reservations(
            session, self.max_age_minutes
        )

        if not stale_reservations:
            logger.debug(f"[{self.name}] No stale reservations to clean")
            return 0

        logger.info(
            f"[{self.name}] Found {len(stale_reservations)} stale reservations to clean"
        )

        for allocation in stale_reservations:
            # 记录日志
            logger.warning(
                f"♻️  [{self.name}] Job {allocation.job.id}: "
                f"reserved for {(datetime.utcnow() - allocation.allocation_time).total_seconds() / 60:.1f} min"
            )

            # 清理预留
            self.repo.cleanup_stale_reservation(session, allocation)

        return len(stale_reservations)

    def after_execute(self, session: Session, result: CleanupResult):
        """后置处理：如果清理数量多，发送告警"""
        if result.items_cleaned > 10:
            logger.warning(
                f"[{self.name}] ⚠️  Cleaned {result.items_cleaned} stale reservations "
                f"(may indicate queue or worker issues)"
            )


@strategy_metadata(
    priority=3,
    depends_on=["completed_job_cleanup"],
    tags=["maintenance"],
    timeout=300,
)
class StuckJobCleanupStrategy(BaseCleanupStrategy):
    """清理卡住作业的策略"""

    def __init__(
        self,
        interval_seconds: int = 3600,
        max_age_hours: int = 48,
        repo: CleanupRepository = None,
    ):
        super().__init__(interval_seconds)
        self.max_age_hours = max_age_hours
        self.repo = repo or CleanupRepository()

    @property
    def name(self) -> str:
        return "stuck_job_cleanup"

    @property
    def description(self) -> str:
        return f"清理运行超过 {self.max_age_hours} 小时的卡住作业"

    def _do_cleanup(self, session: Session) -> int:
        """清理卡住的作业"""
        stuck_jobs = self.repo.get_stuck_jobs(session, self.max_age_hours)

        for job in stuck_jobs:
            logger.warning(f"[{self.name}] Stuck job {job.id} ({job.name})")

            # 标记为失败
            self.repo.mark_job_as_failed(
                session, job, error_msg="因超时由清理脚本标记为失败"
            )

            # 释放资源
            self.repo.release_resource_for_job(session, job)

        return len(stuck_jobs)


@strategy_metadata(
    priority=4,
    depends_on=[],
    tags=["maintenance", "optional"],
    enabled_by_default=False,  # 默认禁用
)
class OldJobCleanupStrategy(BaseCleanupStrategy):
    """清理过期作业的策略（可选）"""

    def __init__(
        self,
        interval_seconds: int = 86400,
        max_age_days: int = 30,
        enabled: bool = False,
        repo: CleanupRepository = None,
    ):
        super().__init__(interval_seconds, enabled)
        self.max_age_days = max_age_days
        self.repo = repo or CleanupRepository()

    @property
    def name(self) -> str:
        return "old_job_cleanup"

    @property
    def description(self) -> str:
        return f"删除超过 {self.max_age_days} 天的已完成作业"

    def _do_cleanup(self, session: Session) -> int:
        """删除过期的作业"""
        old_jobs = self.repo.get_old_jobs(session, self.max_age_days)
        return self.repo.delete_jobs_batch(session, old_jobs)

