#!/usr/bin/env python3
"""
用于监控系统状态的健康检查脚本
"""

import sys
from pathlib import Path

# 将项目根目录添加到路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.config import get_settings
from core.database import sync_db
from core.redis_client import redis_manager
from core.models import Job
from core.enums import JobState
from core.utils.logger import setup_logger


def check_database() -> bool:
    """检查数据库连接"""
    try:
        sync_db.init()

        with sync_db.get_session() as session:
            # 简单查询以测试数据库连接
            result = session.query(Job).limit(1).first()

        logger.info("✓ 数据库连接正常")
        return True

    except Exception as e:
        logger.error(f"✗ 数据库连接失败: {e}")
        return False


def check_redis() -> bool:
    """检查Redis连接"""
    try:
        redis_manager.init()

        if redis_manager.ping():
            logger.info("✓ Redis连接正常")
            return True
        else:
            logger.error("✗ Redis连接失败：ping返回False")
            return False

    except Exception as e:
        logger.error(f"✗ Redis连接失败: {e}")
        return False


def check_job_stats():
    """显示任务统计信息"""
    try:
        with sync_db.get_session() as session:
            total_jobs = session.query(Job).count()
            pending_jobs = (
                session.query(Job).filter(Job.state == JobState.PENDING).count()
            )
            running_jobs = (
                session.query(Job).filter(Job.state == JobState.RUNNING).count()
            )
            completed_jobs = (
                session.query(Job).filter(Job.state == JobState.COMPLETED).count()
            )
            failed_jobs = (
                session.query(Job).filter(Job.state == JobState.FAILED).count()
            )
            cancelled_jobs = (
                session.query(Job).filter(Job.state == JobState.CANCELLED).count()
            )

            logger.info("任务统计信息:")
            logger.info(f"  总数:     {total_jobs}")
            logger.info(f"  待处理:   {pending_jobs}")
            logger.info(f"  运行中:   {running_jobs}")
            logger.info(f"  已完成:   {completed_jobs}")
            logger.info(f"  失败:     {failed_jobs}")
            logger.info(f"  已取消:   {cancelled_jobs}")

    except Exception as e:
        logger.error(f"获取任务统计信息失败: {e}")


def main():
    """主健康检查流程"""
    # 设置日志
    setup_logger("INFO")

    logger.info("=== 系统健康检查 ===")

    settings = get_settings()
    logger.info(f"节点: {settings.NODE_NAME}")
    logger.info(f"CPU总数: {settings.TOTAL_CPUS}")

    results = []

    # 检查数据库
    results.append(check_database())

    # 检查Redis
    results.append(check_redis())

    # 显示任务统计（如果数据库可访问）
    if results[0]:
        check_job_stats()

    # 清理资源
    sync_db.close()
    redis_manager.close()

    # 总体状态
    logger.info("=" * 30)
    if all(results):
        logger.info("✓ 综合状态: 健康")
        sys.exit(0)
    else:
        logger.error("✗ 综合状态: 不健康")
        sys.exit(1)


if __name__ == "__main__":
    main()
