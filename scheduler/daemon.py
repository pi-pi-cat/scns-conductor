"""
Scheduler Daemon - 调度守护进程

周期性执行调度任务
"""

import time
import threading

from loguru import logger


class SchedulerDaemon(threading.Thread):
    """调度守护进程"""

    def __init__(
        self,
        scheduler,
        check_interval: float = 5.0,
        stats_interval: int = 60,
    ):
        """
        Args:
            scheduler: JobScheduler 实例
            check_interval: 调度检查间隔（秒）
            stats_interval: 统计输出间隔（秒）
        """
        super().__init__(daemon=True, name="SchedulerDaemon")
        self.scheduler = scheduler
        self.check_interval = check_interval
        self.stats_interval = stats_interval
        self._stop_event = threading.Event()
        self._last_stats_time = 0

    def run(self):
        """主循环"""
        logger.info("Scheduler daemon started")

        while not self._stop_event.is_set():
            try:
                # 调度作业
                self.scheduler.schedule()

                # 释放已完成作业的资源（兜底）
                self.scheduler.release_completed()

                # 定期输出统计
                current_time = int(time.time())
                if current_time - self._last_stats_time >= self.stats_interval:
                    self._log_stats()
                    self._last_stats_time = current_time

            except Exception as e:
                logger.error(f"Scheduler daemon error: {e}", exc_info=True)

            # 等待下一次检查
            self._stop_event.wait(self.check_interval)

        logger.info("Scheduler daemon stopped")

    def stop(self):
        """停止守护进程"""
        self._stop_event.set()

    def _log_stats(self):
        """输出统计信息"""
        stats = self.scheduler.get_stats()
        logger.info(
            f"📊 Resources: {stats['used_cpus']}/{stats['total_cpus']} CPUs "
            f"({stats['utilization']:.1f}% utilization)"
        )
