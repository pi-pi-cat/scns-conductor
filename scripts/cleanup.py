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
from core.enums import JobState, ResourceStatus
from core.utils.logger import setup_logger


def cleanup_stale_reservations(max_age_minutes: int = 10):
    """
    清理长期停留在 RESERVED 状态的资源预留
    
    场景：作业被调度后入队，但队列丢失或Worker崩溃，导致作业永远不会执行。
    这些作业会停留在 RESERVED 状态，虽然不占用真实资源，但会污染数据。
    
    参数:
        max_age_minutes: 超过此时间的 RESERVED 记录将被清理（默认10分钟）
    """
    logger.info(f"正在检查超过 {max_age_minutes} 分钟的预留记录...")
    
    threshold_date = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    
    with sync_db.get_session() as session:
        # 查找长期停留在 RESERVED 状态的资源分配
        stale_reservations = (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status == ResourceStatus.RESERVED,
                ResourceAllocation.allocation_time < threshold_date,
                Job.state == JobState.RUNNING,  # 作业还认为自己在运行
            )
            .all()
        )
        
        count = 0
        for allocation in stale_reservations:
            job_id = allocation.job_id
            logger.warning(
                f"检测到预留超时: job_id={job_id}, "
                f"预留时长={(datetime.utcnow() - allocation.allocation_time).total_seconds() / 60:.1f} 分钟"
            )
            
            # 标记作业为失败
            job = allocation.job
            job.state = JobState.FAILED
            job.end_time = datetime.utcnow()
            job.error_msg = "作业预留超时，可能由于队列丢失或Worker未启动"
            job.exit_code = "-3:0"
            
            # 释放预留（虽然不占用真实资源，但要清理记录）
            allocation.status = ResourceStatus.RELEASED
            allocation.released_time = datetime.utcnow()
            
            count += 1
        
        session.commit()
        
        logger.info(f"已清理 {count} 条预留超时记录")
        return count


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
                ResourceAllocation.status != ResourceStatus.RELEASED,
            )
            .all()
        )

        count = 0
        for allocation in stale_allocations:
            allocation.status = ResourceStatus.RELEASED
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
                and job.resource_allocation.status != ResourceStatus.RELEASED
            ):
                job.resource_allocation.status = ResourceStatus.RELEASED
                job.resource_allocation.released_time = datetime.utcnow()

            count += 1

        session.commit()

        logger.info(f"已修复 {count} 条卡住的作业")


def main():
    """清理主流程入口"""
    import argparse
    
    parser = argparse.ArgumentParser(description="数据库清理工具")
    parser.add_argument(
        "--reservations",
        action="store_true",
        help="清理预留超时的资源分配（默认10分钟）",
    )
    parser.add_argument(
        "--stuck-jobs",
        action="store_true",
        help="修复卡住的作业（默认48小时）",
    )
    parser.add_argument(
        "--stale-resources",
        action="store_true",
        help="清理过期的资源分配（默认7天）",
    )
    parser.add_argument(
        "--old-jobs",
        action="store_true",
        help="删除过期的作业记录（默认30天）",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="执行所有清理任务",
    )
    
    args = parser.parse_args()
    
    # 初始化日志
    setup_logger("INFO")

    logger.info("=" * 70)
    logger.info("🧹 数据库清理脚本")
    logger.info("=" * 70)

    try:
        sync_db.init()
        logger.info("✓ 数据库连接成功")
    except Exception as e:
        logger.error(f"✗ 数据库连接失败: {e}")
        sys.exit(1)
    
    logger.info("-" * 70)
    
    # 如果没有指定任何参数，默认执行所有清理
    if not any([args.reservations, args.stuck_jobs, args.stale_resources, args.old_jobs]):
        args.all = True
    
    try:
        # 1. 清理预留超时（高优先级）
        if args.all or args.reservations:
            logger.info("\n📋 任务1: 清理预留超时的资源分配")
            cleanup_stale_reservations(max_age_minutes=10)
        
        # 2. 修复卡住的作业
        if args.all or args.stuck_jobs:
            logger.info("\n📋 任务2: 修复卡住的作业")
            fix_stuck_jobs()
        
        # 3. 清理过期资源分配
        if args.all or args.stale_resources:
            logger.info("\n📋 任务3: 清理过期资源分配")
            cleanup_stale_resources(days=7)
        
        # 4. 清理过期作业
        if args.all or args.old_jobs:
            logger.info("\n📋 任务4: 清理过期作业记录")
            cleanup_old_jobs(days=30)
        
        logger.info("-" * 70)
        logger.info("✅ 清理完成")
        
    except Exception as e:
        logger.error(f"❌ 清理过程中出错: {e}", exc_info=True)
        sys.exit(1)
    
    finally:
        sync_db.close()


if __name__ == "__main__":
    main()
