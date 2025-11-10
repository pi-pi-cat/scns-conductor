"""
Worker 故障恢复管理器（策略模式版）
处理 Worker 异常退出后的状态恢复和孤儿作业清理
"""

import time
from typing import Optional

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.models import Job
from core.enums import JobState
from worker.recovery.strategies import (
    RecoveryStrategy,
    RecoveryResult,
    OrphanJobRecoveryStrategy,
    TimeoutJobRecoveryStrategy,
    StaleAllocationCleanupStrategy,
    PendingJobRecoveryStrategy,
    CompositeRecoveryStrategy,
)


class RecoveryManager:
    """
    恢复管理器（策略模式版）

    负责在 Worker 启动时检查并恢复系统状态：
    1. 检测孤儿作业（RUNNING 状态但进程已不存在）
    2. 清理资源分配
    3. 标记失败作业
    4. 释放被占用的资源

    使用示例:
        # 使用默认策略
        manager = RecoveryManager()
        result = manager.recover_on_startup()

        # 使用自定义策略
        custom_strategy = OrphanJobRecoveryStrategy()
        manager = RecoveryManager(strategy=custom_strategy)
        result = manager.recover_on_startup()
    """

    def __init__(self, strategy: Optional[RecoveryStrategy] = None) -> None:
        """
        初始化恢复管理器

        Args:
            strategy: 恢复策略（默认使用组合策略）
        """
        self.settings = get_settings()
        # 默认使用组合策略
        self.strategy = strategy or CompositeRecoveryStrategy(
            [
                PendingJobRecoveryStrategy(),  # 首先恢复 PENDING 作业
                OrphanJobRecoveryStrategy(),
                TimeoutJobRecoveryStrategy(),
                StaleAllocationCleanupStrategy(),
            ]
        )

    def recover_on_startup(self) -> RecoveryResult:
        """
        Worker 启动时执行恢复操作（使用策略模式）

        执行步骤：
        1. 查找所有可能需要恢复的作业
        2. 应用恢复策略
        3. 提交变更并返回结果

        Returns:
            恢复操作结果
        """
        start_time = time.time()
        logger.info("=" * 60)
        logger.info(f"开始执行 Worker 启动恢复检查（策略：{self.strategy.name}）")
        logger.info("=" * 60)

        with sync_db.get_session() as session:
            # 查找所有可能需要恢复的作业（PENDING、RUNNING、COMPLETED、FAILED、CANCELLED）
            jobs = (
                session.query(Job)
                .filter(
                    Job.state.in_(
                        [
                            JobState.PENDING,  # 添加 PENDING 状态
                            JobState.RUNNING,
                            JobState.COMPLETED,
                            JobState.FAILED,
                            JobState.CANCELLED,
                        ]
                    )
                )
                .all()
            )

            if not jobs:
                logger.info("✅ 没有需要检查的作业")
                return RecoveryResult(
                    recovered_jobs=[],
                    skipped_jobs=[],
                    total_jobs=0,
                    success_rate=100.0,
                    duration_seconds=time.time() - start_time,
                )

            logger.info(f"📋 发现 {len(jobs)} 个作业，开始应用恢复策略...")

            recovered = []
            skipped = []

            for job in jobs:
                if self.strategy.should_recover(session, job):
                    if self.strategy.recover_job(session, job):
                        recovered.append(job.id)
                        logger.info(f"✅ 成功恢复作业 {job.id}")
                    else:
                        skipped.append(job.id)
                        logger.debug(f"⏭️  跳过作业 {job.id}")
                else:
                    skipped.append(job.id)

            # 提交所有变更
            session.commit()

            duration = time.time() - start_time
            total = len(jobs)
            success_rate = (len(recovered) / total * 100) if total > 0 else 100.0

            result = RecoveryResult(
                recovered_jobs=recovered,
                skipped_jobs=skipped,
                total_jobs=total,
                success_rate=success_rate,
                duration_seconds=duration,
            )

            logger.info("=" * 60)
            logger.info(f"📊 {result}")
            logger.info("=" * 60)

            return result
