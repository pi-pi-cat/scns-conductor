"""
Worker Repository - Worker 仓储模式

职责：
- 封装 Worker 数据访问逻辑
- 提供统一的 Worker 查询接口
- 管理 Worker 生命周期
"""

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

from loguru import logger
from redis import Redis

from core.redis_client import redis_manager


@dataclass
class WorkerInfo:
    """Worker 信息数据类"""

    worker_id: str
    cpus: int
    status: str
    hostname: str
    registered_at: datetime
    last_heartbeat: datetime
    ttl: int  # 剩余存活时间（秒）

    @property
    def is_alive(self) -> bool:
        """Worker 是否活跃"""
        return self.ttl > 0

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "worker_id": self.worker_id,
            "cpus": self.cpus,
            "status": self.status,
            "hostname": self.hostname,
            "registered_at": self.registered_at.isoformat(),
            "last_heartbeat": self.last_heartbeat.isoformat(),
            "ttl": self.ttl,
            "is_alive": self.is_alive,
        }


class WorkerRepository:
    """
    Worker 仓储 - 数据访问层

    使用仓储模式封装 Worker 相关的所有数据访问逻辑
    """

    # Redis 键前缀
    KEY_PREFIX = "worker:"

    def __init__(self, redis_client: Optional[Redis] = None):
        """
        初始化仓储

        Args:
            redis_client: Redis 客户端（可选，用于依赖注入）
        """
        self._redis = redis_client or redis_manager.get_connection()

    def save(
        self,
        worker_id: str,
        cpus: int,
        hostname: str,
        status: str = "ready",
        ttl: int = 60,
    ) -> bool:
        """
        保存 Worker 信息

        Args:
            worker_id: Worker 唯一标识
            cpus: CPU 数量
            hostname: 主机名
            status: 状态
            ttl: 过期时间（秒）

        Returns:
            True 如果保存成功
        """
        try:
            key = self._get_key(worker_id)
            now = datetime.utcnow().isoformat()

            worker_data = {
                "worker_id": worker_id,
                "cpus": cpus,
                "hostname": hostname,
                "status": status,
                "registered_at": now,
                "last_heartbeat": now,
            }

            self._redis.hset(key, mapping=worker_data)
            self._redis.expire(key, ttl)

            return True

        except Exception as e:
            logger.error(f"Failed to save worker {worker_id}: {e}")
            return False

    def update_heartbeat(self, worker_id: str, ttl: int = 60) -> bool:
        """
        更新心跳时间

        Args:
            worker_id: Worker ID
            ttl: 刷新 TTL

        Returns:
            True 如果更新成功
        """
        try:
            key = self._get_key(worker_id)
            self._redis.hset(key, "last_heartbeat", datetime.utcnow().isoformat())
            self._redis.expire(key, ttl)
            return True

        except Exception as e:
            logger.error(f"Failed to update heartbeat for {worker_id}: {e}")
            return False

    def update_status(self, worker_id: str, status: str) -> bool:
        """
        更新 Worker 状态

        Args:
            worker_id: Worker ID
            status: 新状态

        Returns:
            True 如果更新成功
        """
        try:
            key = self._get_key(worker_id)
            self._redis.hset(key, "status", status)
            return True

        except Exception as e:
            logger.error(f"Failed to update status for {worker_id}: {e}")
            return False

    def delete(self, worker_id: str) -> bool:
        """
        删除 Worker

        Args:
            worker_id: Worker ID

        Returns:
            True 如果删除成功
        """
        try:
            key = self._get_key(worker_id)
            self._redis.delete(key)
            return True

        except Exception as e:
            logger.error(f"Failed to delete worker {worker_id}: {e}")
            return False

    def find_by_id(self, worker_id: str) -> Optional[WorkerInfo]:
        """
        根据 ID 查找 Worker

        Args:
            worker_id: Worker ID

        Returns:
            WorkerInfo 或 None
        """
        try:
            key = self._get_key(worker_id)
            data = self._redis.hgetall(key)

            if not data:
                return None

            ttl = self._redis.ttl(key)
            return self._parse_worker_info(data, ttl)

        except Exception as e:
            logger.error(f"Failed to find worker {worker_id}: {e}")
            return None

    def find_all(self) -> List[WorkerInfo]:
        """
        查找所有活跃的 Worker

        Returns:
            WorkerInfo 列表
        """
        try:
            pattern = f"{self.KEY_PREFIX}*"
            keys = self._redis.keys(pattern)

            workers = []
            for key in keys:
                data = self._redis.hgetall(key)
                if data:
                    ttl = self._redis.ttl(key)
                    worker = self._parse_worker_info(data, ttl)
                    if worker:
                        workers.append(worker)

            return workers

        except Exception as e:
            logger.error(f"Failed to find all workers: {e}")
            return []

    def count(self) -> int:
        """
        统计活跃 Worker 数量

        Returns:
            Worker 数量
        """
        try:
            pattern = f"{self.KEY_PREFIX}*"
            keys = self._redis.keys(pattern)
            return len(keys)

        except Exception as e:
            logger.error(f"Failed to count workers: {e}")
            return 0

    def get_total_cpus(self) -> int:
        """
        获取所有活跃 Worker 的 CPU 总数

        Returns:
            CPU 总数
        """
        workers = self.find_all()
        return sum(w.cpus for w in workers)

    def exists(self, worker_id: str) -> bool:
        """
        检查 Worker 是否存在

        Args:
            worker_id: Worker ID

        Returns:
            True 如果存在
        """
        try:
            key = self._get_key(worker_id)
            return self._redis.exists(key) > 0

        except Exception as e:
            logger.error(f"Failed to check worker existence {worker_id}: {e}")
            return False

    def _get_key(self, worker_id: str) -> str:
        """生成 Redis 键名"""
        return f"{self.KEY_PREFIX}{worker_id}"

    def _parse_worker_info(self, data: dict, ttl: int) -> Optional[WorkerInfo]:
        """解析 Redis 数据为 WorkerInfo"""
        try:
            # 处理字节类型的键值
            def decode(value):
                if isinstance(value, bytes):
                    return value.decode("utf-8")
                return value

            worker_id = decode(data.get(b"worker_id") or data.get("worker_id"))
            cpus = int(decode(data.get(b"cpus") or data.get("cpus", 0)))
            status = decode(data.get(b"status") or data.get("status", "unknown"))
            hostname = decode(data.get(b"hostname") or data.get("hostname", "unknown"))

            registered_at_str = decode(
                data.get(b"registered_at") or data.get("registered_at", "")
            )
            last_heartbeat_str = decode(
                data.get(b"last_heartbeat") or data.get("last_heartbeat", "")
            )

            registered_at = datetime.fromisoformat(registered_at_str)
            last_heartbeat = datetime.fromisoformat(last_heartbeat_str)

            return WorkerInfo(
                worker_id=worker_id,
                cpus=cpus,
                status=status,
                hostname=hostname,
                registered_at=registered_at,
                last_heartbeat=last_heartbeat,
                ttl=ttl,
            )

        except Exception as e:
            logger.error(f"Failed to parse worker info: {e}")
            return None
