"""
Worker main entry point
Runs RQ worker with scheduler daemon
"""

import signal
import sys
import threading
import time

from rq import Worker
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.redis_client import redis_manager
from core.utils.logger import setup_logger
from .scheduler import ResourceScheduler
from .executor import execute_job_task
from .recovery import RecoveryManager


class SchedulerDaemon(threading.Thread):
    """
    Scheduler daemon thread
    Periodically checks for pending jobs and schedules them
    """

    def __init__(self, check_interval: int = 5):
        """
        Initialize scheduler daemon

        Args:
            check_interval: Seconds between scheduling checks
        """
        super().__init__(daemon=True, name="SchedulerDaemon")
        self.check_interval = check_interval
        self.scheduler = ResourceScheduler()
        self._stop_event = threading.Event()

    def run(self) -> None:
        """Main daemon loop"""
        logger.info("Scheduler daemon started")

        while not self._stop_event.is_set():
            try:
                # Schedule pending jobs
                scheduled_jobs = self.scheduler.schedule_pending_jobs()

                if scheduled_jobs:
                    logger.info(f"Scheduled {len(scheduled_jobs)} jobs")

                # Log resource statistics periodically
                if int(time.time()) % 60 == 0:  # Every minute
                    stats = self.scheduler.get_resource_stats()
                    logger.info(
                        f"Resource stats: {stats['used_cpus']}/{stats['total_cpus']} CPUs "
                        f"({stats['utilization']:.1f}% utilization)"
                    )

            except Exception as e:
                logger.error(f"Scheduler daemon error: {e}", exc_info=True)

            # Wait before next check
            self._stop_event.wait(self.check_interval)

        logger.info("Scheduler daemon stopped")

    def stop(self) -> None:
        """Stop the daemon"""
        self._stop_event.set()


def setup_signal_handlers(worker: Worker, scheduler_daemon: SchedulerDaemon) -> None:
    """
    Setup signal handlers for graceful shutdown

    Args:
        worker: RQ worker instance
        scheduler_daemon: Scheduler daemon instance
    """

    def signal_handler(signum, frame):
        sig_name = signal.Signals(signum).name
        logger.info(f"Received {sig_name}, initiating graceful shutdown...")

        # Stop scheduler daemon
        scheduler_daemon.stop()

        # Stop worker
        worker.request_stop()

    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)


def main() -> None:
    """
    Worker 服务主入口

    启动流程：
    1. 初始化配置和日志
    2. 连接数据库和 Redis
    3. **执行故障恢复检查**（关键步骤）
    4. 启动调度器守护进程
    5. 启动 RQ Worker
    """
    # 加载配置
    settings = get_settings()

    # 设置日志
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)
    logger.info("=" * 60)
    logger.info("启动 SCNS-Conductor Worker 服务")
    logger.info("=" * 60)

    # 确保必需的目录存在
    settings.ensure_directories()

    # 初始化数据库
    try:
        sync_db.init()
        logger.info("✓ 数据库初始化成功")
    except Exception as e:
        logger.error(f"✗ 数据库初始化失败: {e}")
        sys.exit(1)

    # 初始化 Redis
    try:
        redis_manager.init()

        # 测试 Redis 连接
        if not redis_manager.ping():
            raise ConnectionError("无法连接到 Redis")

        logger.info("✓ Redis 初始化成功")
    except Exception as e:
        logger.error(f"✗ Redis 初始化失败: {e}")
        sys.exit(1)

    # ============ 关键：执行故障恢复 ============
    logger.info("-" * 60)
    logger.info("执行 Worker 启动恢复检查...")
    logger.info("-" * 60)
    try:
        recovery_manager = RecoveryManager()
        recovery_manager.recover_on_startup()
        logger.info("✓ 恢复检查完成")
    except Exception as e:
        logger.error(f"✗ 恢复检查失败: {e}")
        logger.warning("将继续启动 Worker，但可能存在孤儿作业")
    logger.info("-" * 60)

    # 获取 RQ 队列
    queue = redis_manager.get_queue()
    logger.info(f"✓ 使用队列: {queue.name}")

    # 创建 RQ Worker
    worker = Worker(
        [queue],
        connection=redis_manager.get_connection(),
        name=f"worker-{settings.NODE_NAME}",
    )

    logger.info("-" * 60)
    logger.info(f"Worker 名称: {worker.name}")
    logger.info(f"节点名称: {settings.NODE_NAME}")
    logger.info(f"总 CPU 核心数: {settings.TOTAL_CPUS}")
    logger.info("-" * 60)

    # 启动调度器守护进程
    scheduler_daemon = SchedulerDaemon(check_interval=5)
    scheduler_daemon.start()
    logger.info("✓ 调度器守护进程已启动")

    # 设置信号处理器（优雅退出）
    setup_signal_handlers(worker, scheduler_daemon)

    # 运行 Worker
    try:
        logger.info("=" * 60)
        logger.info("Worker 已就绪，等待作业...")
        logger.info("=" * 60)
        worker.work(
            burst=settings.WORKER_BURST,
            with_scheduler=False,  # 使用自定义调度器
        )
    except KeyboardInterrupt:
        logger.info("Worker 被用户中断")
    except Exception as e:
        logger.error(f"Worker 运行错误: {e}", exc_info=True)
    finally:
        # 清理资源
        logger.info("=" * 60)
        logger.info("正在关闭 Worker...")
        logger.info("=" * 60)

        scheduler_daemon.stop()
        scheduler_daemon.join(timeout=10)

        sync_db.close()
        redis_manager.close()

        logger.info("Worker 已安全停止")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
