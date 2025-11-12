"""
清理策略数据库操作仓储

集中管理所有清理策略相关的数据库查询和更新操作
"""

from datetime import datetime, timedelta
from typing import List

from loguru import logger
from sqlalchemy.orm import Session

from core.models import Job, ResourceAllocation
from core.enums import JobState, ResourceStatus


class CleanupRepository:
    """
    清理策略数据库操作仓储

    职责：
    - 集中管理所有清理相关的数据库查询
    - 提供批量操作支持
    - 封装复杂的联表查询
    - 支持查询优化
    """

    # ========== 已完成作业相关 ==========

    @staticmethod
    def count_completed_jobs_with_unreleased_resources(session: Session) -> int:
        """
        统计已完成但未释放资源的作业数量

        用于 before_execute 快速检查

        Args:
            session: 数据库会话

        Returns:
            已完成但未释放资源的作业数量
        """
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status != ResourceStatus.RELEASED,
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
            )
            .count()
        )

    @staticmethod
    def get_completed_jobs_with_unreleased_resources(
        session: Session,
    ) -> List[ResourceAllocation]:
        """
        获取已完成但未释放资源的分配记录

        Args:
            session: 数据库会话

        Returns:
            ResourceAllocation 列表（包含关联的 Job）
        """
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status != ResourceStatus.RELEASED,
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
            )
            .all()
        )

    @staticmethod
    def release_resources_for_completed_jobs(
        session: Session, allocations: List[ResourceAllocation]
    ) -> int:
        """
        批量释放已完成作业的资源

        Args:
            session: 数据库会话
            allocations: 要释放的资源分配列表

        Returns:
            释放的资源数量
        """
        if not allocations:
            return 0

        now = datetime.utcnow()
        for allocation in allocations:
            allocation.status = ResourceStatus.RELEASED
            allocation.released_time = now

        return len(allocations)

    # ========== 预留超时相关 ==========

    @staticmethod
    def count_stale_reservations(session: Session, max_age_minutes: int) -> int:
        """
        统计超时的预留数量

        Args:
            session: 数据库会话
            max_age_minutes: 最大保留时间（分钟）

        Returns:
            超时的预留数量
        """
        threshold = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status == ResourceStatus.RESERVED,
                ResourceAllocation.allocation_time < threshold,
                Job.state == JobState.RUNNING,
            )
            .count()
        )

    @staticmethod
    def get_stale_reservations(
        session: Session, max_age_minutes: int
    ) -> List[ResourceAllocation]:
        """
        获取超时的预留记录

        Args:
            session: 数据库会话
            max_age_minutes: 最大保留时间（分钟）

        Returns:
            超时的 ResourceAllocation 列表（包含关联的 Job）
        """
        threshold = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        return (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status == ResourceStatus.RESERVED,
                ResourceAllocation.allocation_time < threshold,
                Job.state == JobState.RUNNING,
            )
            .all()
        )

    @staticmethod
    def cleanup_stale_reservation(
        session: Session,
        allocation: ResourceAllocation,
        error_msg: str = "作业预留超时，可能由于队列丢失或Worker未启动",
    ) -> None:
        """
        清理单个超时预留

        更新：
        - Job 状态为 FAILED
        - ResourceAllocation 状态为 RELEASED

        Args:
            session: 数据库会话
            allocation: 资源分配对象
            error_msg: 错误消息
        """
        job = allocation.job
        now = datetime.utcnow()

        job.state = JobState.FAILED
        job.end_time = now
        job.error_msg = error_msg
        job.exit_code = "-3:0"

        allocation.status = ResourceStatus.RELEASED
        allocation.released_time = now

    # ========== 卡住作业相关 ==========

    @staticmethod
    def get_stuck_jobs(session: Session, max_age_hours: int) -> List[Job]:
        """
        获取卡住的作业（运行时间超过阈值）

        Args:
            session: 数据库会话
            max_age_hours: 最大运行时间（小时）

        Returns:
            卡住的 Job 列表
        """
        threshold = datetime.utcnow() - timedelta(hours=max_age_hours)
        return (
            session.query(Job)
            .filter(Job.state == JobState.RUNNING, Job.start_time < threshold)
            .all()
        )

    @staticmethod
    def mark_job_as_failed(
        session: Session,
        job: Job,
        error_msg: str,
        exit_code: str = "-2:0",
    ) -> None:
        """
        标记作业为失败

        Args:
            session: 数据库会话
            job: 作业对象
            error_msg: 错误消息
            exit_code: 退出码
        """
        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = error_msg
        job.exit_code = exit_code

    @staticmethod
    def release_resource_for_job(session: Session, job: Job) -> None:
        """
        释放作业的资源（如果存在）

        Args:
            session: 数据库会话
            job: 作业对象
        """
        if (
            hasattr(job, "resource_allocation")
            and job.resource_allocation
            and job.resource_allocation.status != ResourceStatus.RELEASED
        ):
            job.resource_allocation.status = ResourceStatus.RELEASED
            job.resource_allocation.released_time = datetime.utcnow()

    # ========== 旧作业相关 ==========

    @staticmethod
    def get_old_jobs(session: Session, max_age_days: int) -> List[Job]:
        """
        获取过期的作业

        Args:
            session: 数据库会话
            max_age_days: 最大保留天数

        Returns:
            过期的 Job 列表
        """
        threshold = datetime.utcnow() - timedelta(days=max_age_days)
        return (
            session.query(Job)
            .filter(
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
                Job.end_time < threshold,
            )
            .all()
        )

    @staticmethod
    def delete_jobs_batch(session: Session, jobs: List[Job]) -> int:
        """
        批量删除作业

        Args:
            session: 数据库会话
            jobs: 要删除的作业列表

        Returns:
            删除的作业数量
        """
        if not jobs:
            return 0

        for job in jobs:
            session.delete(job)

        return len(jobs)
