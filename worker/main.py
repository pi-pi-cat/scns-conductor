"""
Worker Service - 主入口

纯执行服务，从队列获取已调度的作业并执行
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from rq import Worker
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.redis_client import redis_manager
from core.utils.logger import setup_logger


def main():
    """Worker 服务主入口"""
    settings = get_settings()
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)

    logger.info("=" * 70)
    logger.info("💪 SCNS-Conductor Worker Service v2.0")
    logger.info("=" * 70)

    # 初始化数据库
    try:
        sync_db.init()
        logger.info("✓ Database connected")
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        sys.exit(1)

    # 初始化 Redis
    try:
        redis_manager.init()
        if not redis_manager.ping():
            raise ConnectionError("Redis not available")
        logger.info("✓ Redis connected")
    except Exception as e:
        logger.error(f"✗ Redis connection failed: {e}")
        sys.exit(1)

    # 获取队列
    queue = redis_manager.get_queue()

    logger.info("-" * 70)
    logger.info(f"Node: {settings.NODE_NAME}")
    logger.info(f"Queue: {queue.name}")
    logger.info("-" * 70)

    # 清理过期的 worker（解决重启时名称冲突）
    worker_name = f"worker-{settings.NODE_NAME}"
    connection = redis_manager.get_connection()

    # 获取所有 worker
    from rq.worker import Worker as RQWorker

    all_workers = RQWorker.all(connection=connection)

    # 查找同名 worker
    for w in all_workers:
        if w.name == worker_name:
            # 检查是否还活着
            if w.state in ["busy", "idle"]:
                # 尝试发送心跳，如果失败说明 worker 已死
                try:
                    w.refresh()
                    if not w.is_alive():
                        logger.warning(f"🧹 Cleaning up dead worker: {worker_name}")
                        w.register_death()
                except Exception as e:
                    logger.warning(f"🧹 Cleaning up stale worker: {worker_name} - {e}")
                    w.register_death()
            else:
                logger.warning(f"🧹 Cleaning up stopped worker: {worker_name}")
                w.register_death()

    # 创建 Worker
    worker = Worker(
        [queue],
        connection=connection,
        name=worker_name,
    )

    logger.info("=" * 70)
    logger.info("🚀 Worker is ready, waiting for jobs...")
    logger.info("=" * 70)

    # 运行 Worker
    try:
        worker.work(burst=settings.WORKER_BURST, with_scheduler=False)
    except KeyboardInterrupt:
        logger.info("⚠️  Worker interrupted by user")
    except Exception as e:
        logger.error(f"❌ Worker error: {e}", exc_info=True)
    finally:
        sync_db.close()
        redis_manager.close()
        logger.info("=" * 70)
        logger.info("✅ Worker stopped")
        logger.info("=" * 70)


if __name__ == "__main__":
    main()
