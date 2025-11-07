"""
恢复策略定义（策略模式）
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List
from datetime import datetime, timedelta
from loguru import logger

from sqlalchemy.orm import Session
from core.models import Job, ResourceAllocation
from core.enums import JobState


@dataclass
class RecoveryResult:
    """
    恢复操作结果

    记录恢复过程的统计信息
    """

    recovered_jobs: List[int]
    skipped_jobs: List[int]
    total_jobs: int
    success_rate: float
    duration_seconds: float

    def __str__(self) -> str:
        return (
            f"Recovery: {len(self.recovered_jobs)}/{self.total_jobs} jobs recovered "
            f"({self.success_rate:.1f}% success) in {self.duration_seconds:.2f}s"
        )


class RecoveryStrategy(ABC):
    """
    恢复策略抽象基类

    定义作业恢复的通用接口
    """

    @abstractmethod
    def should_recover(self, session: Session, job: Job) -> bool:
        """
        判断是否应该恢复此作业

        Args:
            session: 数据库会话
            job: 作业对象

        Returns:
            True if should recover
        """
        pass

    @abstractmethod
    def recover_job(self, session: Session, job: Job) -> bool:
        """
        恢复作业

        Args:
            session: 数据库会话
            job: 作业对象

        Returns:
            True if recovered successfully
        """
        pass

    @property
    @abstractmethod
    def name(self) -> str:
        """策略名称"""
        pass


class OrphanJobRecoveryStrategy(RecoveryStrategy):
    """
    孤儿作业恢复策略

    检查进程是否存在，不存在则标记为失败
    """

    @property
    def name(self) -> str:
        return "OrphanJobRecovery"

    def should_recover(self, session: Session, job: Job) -> bool:
        """只处理RUNNING状态的作业"""
        return job.state == JobState.RUNNING

    def recover_job(self, session: Session, job: Job) -> bool:
        """检查进程并恢复孤儿作业"""
        # 检查进程是否存在
        allocation = (
            session.query(ResourceAllocation)
            .filter(ResourceAllocation.job_id == job.id)
            .first()
        )

        if not allocation or not allocation.process_id:
            logger.warning(f"作业 {job.id} 没有进程ID记录")
            return self._mark_as_failed(session, job, allocation)

        try:
            # 发送信号 0 检查进程是否存在（不会真正发送信号）
            os.kill(allocation.process_id, 0)
            logger.info(f"作业 {job.id} 的进程 {allocation.process_id} 仍在运行")
            return False  # 进程存在，不需要恢复
        except OSError:
            # 进程不存在，标记为失败
            logger.warning(
                f"作业 {job.id} 的进程 {allocation.process_id} 不存在，标记为失败"
            )
            return self._mark_as_failed(session, job, allocation)
        except Exception as e:
            logger.error(f"检查进程状态时出错: {e}")
            return False

    def _mark_as_failed(
        self, session: Session, job: Job, allocation: ResourceAllocation
    ) -> bool:
        """将作业标记为失败并释放资源"""
        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = (
            "Worker 异常退出导致作业中断。"
            "此作业在 Worker 重启时被检测为孤儿进程并标记为失败。"
        )
        job.exit_code = "-999:0"  # 特殊退出码表示 Worker 异常

        if allocation:
            allocation.released = True
            allocation.released_time = datetime.utcnow()
            logger.info(f"释放作业 {job.id} 的资源：{allocation.allocated_cpus} CPUs")

        return True


class TimeoutJobRecoveryStrategy(RecoveryStrategy):
    """
    超时作业恢复策略

    处理运行时间过长的作业
    """

    def __init__(self, max_runtime_hours: int = 72):
        """
        初始化超时策略

        Args:
            max_runtime_hours: 最大运行时间（小时）
        """
        self.max_runtime_hours = max_runtime_hours

    @property
    def name(self) -> str:
        return f"TimeoutJobRecovery(max={self.max_runtime_hours}h)"

    def should_recover(self, session: Session, job: Job) -> bool:
        """检查RUNNING作业是否超时"""
        if job.state != JobState.RUNNING or not job.start_time:
            return False

        max_runtime = timedelta(hours=self.max_runtime_hours)
        current_runtime = datetime.utcnow() - job.start_time

        return current_runtime > max_runtime

    def recover_job(self, session: Session, job: Job) -> bool:
        """标记超时作业为失败"""
        logger.warning(
            f"作业 {job.id} 超过最大运行时间 {self.max_runtime_hours} 小时，标记为失败"
        )

        job.state = JobState.FAILED
        job.end_time = datetime.utcnow()
        job.error_msg = f"作业超过最大运行时间 {self.max_runtime_hours} 小时"
        job.exit_code = "-998:0"  # 超时退出码

        # 释放资源
        allocation = (
            session.query(ResourceAllocation)
            .filter(ResourceAllocation.job_id == job.id, ~ResourceAllocation.released)
            .first()
        )

        if allocation:
            allocation.released = True
            allocation.released_time = datetime.utcnow()
            logger.info(f"释放作业 {job.id} 的资源：{allocation.allocated_cpus} CPUs")

        return True


class StaleAllocationCleanupStrategy(RecoveryStrategy):
    """
    陈旧资源分配清理策略

    清理已完成但未释放资源的作业
    """

    def __init__(self, max_age_hours: int = 48):
        """
        初始化清理策略

        Args:
            max_age_hours: 最大保留时间（小时）
        """
        self.max_age_hours = max_age_hours

    @property
    def name(self) -> str:
        return f"StaleAllocationCleanup(max_age={self.max_age_hours}h)"

    def should_recover(self, session: Session, job: Job) -> bool:
        """检查终态作业的资源是否未释放"""
        if job.state not in [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]:
            return False

        if not job.end_time:
            return False

        max_age = timedelta(hours=self.max_age_hours)
        age = datetime.utcnow() - job.end_time

        if age <= max_age:
            return False

        # 检查是否有未释放的资源
        allocation = (
            session.query(ResourceAllocation)
            .filter(ResourceAllocation.job_id == job.id, ~ResourceAllocation.released)
            .first()
        )

        return allocation is not None

    def recover_job(self, session: Session, job: Job) -> bool:
        """释放陈旧的资源分配"""
        allocation = (
            session.query(ResourceAllocation)
            .filter(ResourceAllocation.job_id == job.id, ~ResourceAllocation.released)
            .first()
        )

        if allocation:
            allocation.released = True
            allocation.released_time = datetime.utcnow()
            logger.info(
                f"清理陈旧资源分配：作业 {job.id}, {allocation.allocated_cpus} CPUs"
            )
            return True

        return False


class CompositeRecoveryStrategy(RecoveryStrategy):
    """
    组合恢复策略

    按顺序应用多个策略
    """

    def __init__(self, strategies: List[RecoveryStrategy]):
        """
        初始化组合策略

        Args:
            strategies: 子策略列表
        """
        self.strategies = strategies

    @property
    def name(self) -> str:
        strategy_names = [s.name for s in self.strategies]
        return f"Composite({', '.join(strategy_names)})"

    def should_recover(self, session: Session, job: Job) -> bool:
        """如果任一策略需要恢复则返回True"""
        return any(s.should_recover(session, job) for s in self.strategies)

    def recover_job(self, session: Session, job: Job) -> bool:
        """应用第一个匹配的策略"""
        for strategy in self.strategies:
            if strategy.should_recover(session, job):
                logger.debug(f"应用策略: {strategy.name} 到作业 {job.id}")
                if strategy.recover_job(session, job):
                    return True
        return False
