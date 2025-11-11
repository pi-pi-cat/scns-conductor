"""
Scheduler Service - 主入口

独立的调度服务，负责：
1. 扫描 PENDING 作业
2. 检查资源可用性
3. 分配资源并更新状态为 RUNNING
4. 将作业加入执行队列
"""

import sys
import signal
import threading
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.redis_client import redis_manager
from core.utils.logger import setup_logger

from scheduler.scheduler import JobScheduler
from scheduler.daemon import SchedulerDaemon


def main():
    """调度服务主入口"""
    settings = get_settings()
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)
    
    logger.info("=" * 70)
    logger.info("🧠 SCNS-Conductor Scheduler Service v2.0")
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
    
    logger.info("-" * 70)
    logger.info(f"Node: {settings.NODE_NAME}")
    logger.info(f"Total CPUs: {settings.TOTAL_CPUS}")
    logger.info(f"Queue: {redis_manager.get_queue().name}")
    logger.info("-" * 70)
    
    # 创建调度器
    scheduler = JobScheduler()
    
    # 创建守护进程
    daemon = SchedulerDaemon(scheduler)
    
    # 设置信号处理
    stop_event = threading.Event()
    
    def signal_handler(signum, frame):
        logger.info(f"🛑 Received signal {signum}, shutting down...")
        daemon.stop()
        stop_event.set()
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # 启动守护进程
    daemon.start()
    
    logger.info("=" * 70)
    logger.info("🚀 Scheduler service is running...")
    logger.info("=" * 70)
    
    # 等待停止信号
    try:
        stop_event.wait()
    except KeyboardInterrupt:
        logger.info("⚠️  Keyboard interrupt received")
        daemon.stop()
    
    # 清理
    daemon.join(timeout=10)
    sync_db.close()
    redis_manager.close()
    
    logger.info("=" * 70)
    logger.info("✅ Scheduler service stopped")
    logger.info("=" * 70)


if __name__ == "__main__":
    main()

