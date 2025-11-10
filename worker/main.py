"""
Worker 主入口（重构版）
运行 RQ Worker 和调度器守护进程
"""

import sys
import os
import multiprocessing
from rq import Worker
from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.redis_client import redis_manager
from core.utils.logger import setup_logger

# 使用新的模块结构
from worker.core.daemon import SchedulerDaemon
from worker.core.executor import execute_job_task
from worker.recovery.manager import RecoveryManager
from worker.utils.signal_handler import SignalHandler


def run_worker_process(worker_id: int, settings) -> None:
    """
    运行单个 Worker 进程
    
    Args:
        worker_id: Worker 进程编号
        settings: 配置对象
    """
    # 重新初始化数据库连接（子进程需要独立的连接）
    try:
        sync_db.init()
        logger.info(f"Worker-{worker_id}: 数据库连接已初始化")
    except Exception as e:
        logger.error(f"Worker-{worker_id}: 数据库初始化失败: {e}")
        return
    
    # 重新初始化 Redis 连接
    try:
        redis_manager.init()
        if not redis_manager.ping():
            raise ConnectionError("无法连接到 Redis")
        logger.info(f"Worker-{worker_id}: Redis 连接已初始化")
    except Exception as e:
        logger.error(f"Worker-{worker_id}: Redis 初始化失败: {e}")
        return
    
    # 获取队列
    queue = redis_manager.get_queue()
    
    # 创建 Worker
    worker = Worker(
        [queue],
        connection=redis_manager.get_connection(),
        name=f"worker-{settings.NODE_NAME}-{worker_id}",
    )
    
    logger.info(f"🚀 Worker-{worker_id} ({worker.name}) 已启动，等待作业...")
    
    # 设置信号处理
    signal_handler = SignalHandler()
    signal_handler.on_shutdown(
        lambda: logger.info(f"🛑 Worker-{worker_id} 正在停止...")
    ).on_shutdown(worker.request_stop).register()
    
    # 运行 Worker
    try:
        worker.work(
            burst=settings.WORKER_BURST,
            with_scheduler=False,
        )
    except KeyboardInterrupt:
        logger.info(f"⚠️  Worker-{worker_id} 被用户中断")
    except Exception as e:
        logger.error(f"❌ Worker-{worker_id} 运行错误: {e}", exc_info=True)
    finally:
        sync_db.close()
        redis_manager.close()
        logger.info(f"✅ Worker-{worker_id} 已停止")


def main() -> None:
    """
    Worker 服务主入口

    启动流程：
    1. 初始化配置和日志
    2. 连接数据库和 Redis
    3. 执行故障恢复检查
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

    # 检查并发配置
    worker_concurrency = settings.WORKER_CONCURRENCY
    logger.info("-" * 60)
    logger.info(f"节点名称: {settings.NODE_NAME}")
    logger.info(f"总 CPU 核心数: {settings.TOTAL_CPUS}")
    logger.info(f"Worker 并发数: {worker_concurrency}")
    logger.info("-" * 60)

    # 使用上下文管理器启动调度器守护进程（只在主进程中启动一次）
    try:
        with SchedulerDaemon() as scheduler_daemon:
            logger.info("✓ 调度器守护进程已启动（主进程）")

            # 如果并发数 > 1，启动多个 Worker 进程
            if worker_concurrency > 1:
                logger.info(f"🚀 启动 {worker_concurrency} 个 Worker 进程...")
                
                # 启动多个 Worker 子进程
                worker_processes = []
                for i in range(worker_concurrency):
                    process = multiprocessing.Process(
                        target=run_worker_process,
                        args=(i + 1, settings),
                        name=f"Worker-{i + 1}"
                    )
                    process.start()
                    worker_processes.append(process)
                    logger.info(f"✓ Worker-{i + 1} 进程已启动 (PID: {process.pid})")
                
                logger.info("=" * 60)
                logger.info(f"✅ {worker_concurrency} 个 Worker 进程已就绪，等待作业...")
                logger.info("=" * 60)
                
                # 设置主进程信号处理
                signal_handler = SignalHandler()
                signal_handler.on_shutdown(
                    lambda: logger.info("🛑 正在停止所有 Worker 进程...")
                ).on_shutdown(scheduler_daemon.stop).register()
                
                # 等待所有 Worker 进程
                try:
                    for process in worker_processes:
                        process.join()
                except KeyboardInterrupt:
                    logger.info("⚠️  收到中断信号，正在终止所有 Worker...")
                    for process in worker_processes:
                        process.terminate()
                    for process in worker_processes:
                        process.join(timeout=10)
                
                logger.info("✅ 所有 Worker 进程已停止")
            
            else:
                # 单 Worker 模式（兼容原来的逻辑）
                logger.info("🚀 启动单 Worker 模式...")
                
                worker = Worker(
                    [queue],
                    connection=redis_manager.get_connection(),
                    name=f"worker-{settings.NODE_NAME}",
                )
                
                # 设置信号处理器
                signal_handler = SignalHandler()
                signal_handler.on_shutdown(
                    lambda: logger.info("🛑 正在停止 Worker...")
                ).on_shutdown(scheduler_daemon.stop).on_shutdown(
                    worker.request_stop
                ).register()
                
                # 运行 Worker
                try:
                    logger.info("=" * 60)
                    logger.info("🚀 Worker 已就绪，等待作业...")
                    logger.info("=" * 60)
                    worker.work(
                        burst=settings.WORKER_BURST,
                        with_scheduler=False,
                    )
                except KeyboardInterrupt:
                    logger.info("⚠️  Worker 被用户中断")
                except Exception as e:
                    logger.error(f"❌ Worker 运行错误: {e}", exc_info=True)

    finally:
        # 清理资源
        logger.info("=" * 60)
        logger.info("正在关闭主进程...")
        logger.info("=" * 60)

        sync_db.close()
        redis_manager.close()

        logger.info("✅ Worker 服务已安全停止")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()
