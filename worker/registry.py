"""
Worker Registry - Worker 注册和心跳管理

负责：
1. Worker 启动时注册到 Redis
2. 定期发送心跳保持活跃状态
3. Worker 停止时注销

重构说明：
- 使用 WorkerRepository 封装数据访问
- 遵循 DRY 原则，避免重复代码
"""

import socket
import threading
from typing import Optional

from loguru import logger

from core.config import get_settings
from core.services.worker_repository import WorkerRepository


class WorkerRegistry:
    """
    Worker 注册和心跳管理器

    功能：
    - 注册 Worker 到 Redis（包含 CPU 数量等信息）
    - 定期发送心跳（刷新 TTL）
    - 优雅注销
    """

    def __init__(
        self,
        worker_id: Optional[str] = None,
        cpus: Optional[int] = None,
        worker_repo: Optional[WorkerRepository] = None,
    ):
        """
        初始化 Worker 注册器

        Args:
            worker_id: Worker 唯一标识（默认使用 NODE_NAME）
            cpus: Worker 的 CPU 数量（默认使用配置文件中的 TOTAL_CPUS）
            worker_repo: Worker 仓储（可选，用于依赖注入）
        """
        self.settings = get_settings()

        # Worker ID：使用 NODE_NAME 作为唯一标识
        self.worker_id = worker_id or self.settings.NODE_NAME

        # CPU 数量
        self.cpus = cpus or self.settings.TOTAL_CPUS

        # 心跳配置
        self.heartbeat_interval = 30  # 心跳间隔（秒）
        self.ttl = 60  # Redis 键过期时间（秒），是心跳间隔的 2 倍

        # 心跳控制
        self._stop_event = threading.Event()
        self._heartbeat_thread: Optional[threading.Thread] = None

        # 主机信息
        self.hostname = socket.gethostname()

        # Worker 仓储（数据访问层）
        self._repo = worker_repo or WorkerRepository()

    def register(self) -> bool:
        """
        注册 Worker 到 Redis

        Returns:
            True 如果注册成功
        """
        success = self._repo.save(
            worker_id=self.worker_id,
            cpus=self.cpus,
            hostname=self.hostname,
            status="ready",
            ttl=self.ttl,
        )

        if success:
            logger.info(
                f"✓ Worker registered: {self.worker_id} "
                f"(hostname: {self.hostname}, {self.cpus} CPUs)"
            )

        return success

    def start_heartbeat(self) -> bool:
        """
        启动心跳线程

        Returns:
            True 如果启动成功
        """
        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            logger.warning("Heartbeat thread already running")
            return False

        try:
            self._stop_event.clear()
            self._heartbeat_thread = threading.Thread(
                target=self._heartbeat_loop, daemon=True, name="WorkerHeartbeat"
            )
            self._heartbeat_thread.start()

            logger.info(
                f"✓ Heartbeat started (interval: {self.heartbeat_interval}s, "
                f"TTL: {self.ttl}s)"
            )
            return True

        except Exception as e:
            logger.error(f"Failed to start heartbeat: {e}")
            return False

    def _heartbeat_loop(self):
        """心跳循环（在独立线程中运行）"""
        while not self._stop_event.is_set():
            try:
                # 使用仓储更新心跳
                self._repo.update_heartbeat(self.worker_id, self.ttl)
                logger.debug(f"💓 Heartbeat sent: {self.worker_id}")

            except Exception as e:
                logger.error(f"Heartbeat failed: {e}")

            # 等待下一次心跳
            self._stop_event.wait(self.heartbeat_interval)

        logger.info("Heartbeat thread stopped")

    def unregister(self):
        """
        注销 Worker（优雅停止）

        步骤：
        1. 停止心跳线程
        2. 从 Redis 删除注册信息
        """
        logger.info(f"Unregistering worker: {self.worker_id}")

        # 停止心跳线程
        self._stop_event.set()

        if self._heartbeat_thread and self._heartbeat_thread.is_alive():
            self._heartbeat_thread.join(timeout=5)
            if self._heartbeat_thread.is_alive():
                logger.warning("Heartbeat thread did not stop in time")

        # 使用仓储删除
        if self._repo.delete(self.worker_id):
            logger.info(f"✓ Worker unregistered: {self.worker_id}")
        else:
            logger.warning(f"Failed to unregister worker: {self.worker_id}")

    def update_status(self, status: str):
        """
        更新 Worker 状态

        Args:
            status: 状态字符串（如 "ready", "busy", "stopping"）
        """
        self._repo.update_status(self.worker_id, status)
