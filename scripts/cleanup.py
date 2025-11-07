#!/usr/bin/env python3
"""
清理孤立作业与资源的脚本
"""

import sys
from pathlib import Path
from datetime import datetime, timedelta

# 将项目根目录添加到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.config import get_settings
from core.database import sync_db
from core.models import Job, ResourceAllocation
from core.enums import JobState
from core.utils.logger import setup_logger


def cleanup_stale_resources(days: int = 7):
    """
    清理已完成作业（完成/失败/取消）超过N天且未释放的资源分配

    参数:
        days: 天数阈值，早于该天数的资源将被处理
    """
    logger.info(f"正在清理超过 {days} 天的已完成作业资源...")

    threshold_date = datetime.utcnow() - timedelta(days=days)

    with sync_db.get_session() as session:
        # 查找状态为已完成/失败/取消且结束时间早于阈值、资源未释放的分配
        stale_allocations = (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
                Job.end_time < threshold_date,
                ResourceAllocation.released == False,
            )
            .all()
        )

        count = 0
        for allocation in stale_allocations:
            allocation.released = True
            allocation.released_time = datetime.utcnow()
            count += 1

        session.commit()

        logger.info(f"已释放 {count} 条过期资源分配记录")


def cleanup_old_jobs(days: int = 30):
    """
    删除非常老的已完成作业（包含级联删除资源分配）

    参数:
        days: 天数阈值，早于该天数的作业将被删除
    """
    logger.info(f"正在删除超过 {days} 天的已完成作业...")

    threshold_date = datetime.utcnow() - timedelta(days=days)

    with sync_db.get_session() as session:
        # 查询需要删除的作业
        jobs_to_delete = (
            session.query(Job)
            .filter(
                Job.state.in_(
                    [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]
                ),
                Job.end_time < threshold_date,
            )
            .all()
        )

        count = len(jobs_to_delete)

        # 删除作业（级联删除资源分配）
        for job in jobs_to_delete:
            session.delete(job)

        session.commit()

        logger.info(f"已删除 {count} 条过期作业")


def fix_stuck_jobs():
    """
    修复被卡住的作业：即处于运行状态且已运行超48小时的作业，强制将其设置为失败并释放资源
    """
    logger.info("正在检查卡住的作业...")

    with sync_db.get_session() as session:
        # 查找运行超48小时的"RUNNING"作业
        threshold_date = datetime.utcnow() - timedelta(hours=48)

        stuck_jobs = (
            session.query(Job)
            .filter(Job.state == JobState.RUNNING, Job.start_time < threshold_date)
            .all()
        )

        count = 0
        for job in stuck_jobs:
            logger.warning(f"检测到卡住的作业: {job.id} ({job.name})")
            job.state = JobState.FAILED
            job.end_time = datetime.utcnow()
            job.error_msg = "因超时由清理脚本标记为失败"
            job.exit_code = "-2:0"

            # 释放资源
            if (
                getattr(job, "resource_allocation", None)
                and not job.resource_allocation.released
            ):
                job.resource_allocation.released = True
                job.resource_allocation.released_time = datetime.utcnow()

            count += 1

        session.commit()

        logger.info(f"已修复 {count} 条卡住的作业")


def main():
    """清理主流程入口"""
    # 初始化日志
    setup_logger("INFO")

    logger.info("=== 开始运行清理任务 ===")

    try:
        sync_db.init()

        # 依次运行各项清理任务
        cleanup_stale_resources(days=7)
        fix_stuck_jobs()
        # 如需启用作业物理删除，取消下行注释
        # cleanup_old_jobs(days=30)

        logger.info("=== 清理任务已成功完成 ===")

    except Exception as e:
        logger.error(f"清理任务失败: {e}", exc_info=True)
        sys.exit(1)

    finally:
        sync_db.close()


if __name__ == "__main__":
    main()
