"""
带RQ队列支持的Redis连接管理器
"""

from contextlib import contextmanager
from typing import Iterator, Optional

from redis import Redis, ConnectionPool
from rq import Queue
from loguru import logger

from .config import get_settings
from .utils.singleton import singleton
from .exceptions import RedisNotInitializedException


@singleton
class RedisManager:
    """
    单例Redis连接管理器
    用于管理Redis连接和RQ队列
    """

    def __init__(self):
        # 初始化连接池、Redis客户端和RQ队列
        self._pool: Optional[ConnectionPool] = None
        self._redis: Optional[Redis] = None
        self._queue: Optional[Queue] = None

    def init(self) -> None:
        """初始化Redis连接池和RQ队列"""
        if self._pool is not None:
            logger.warning("RedisManager 已经初始化")
            return

        settings = get_settings()

        # 创建Redis连接池
        # 注意：不使用 decode_responses=True，因为 RQ 需要处理二进制序列化数据（pickle）
        self._pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            max_connections=50,
        )

        # 创建Redis客户端
        self._redis = Redis(connection_pool=self._pool)

        # 创建RQ队列
        self._queue = Queue(
            name=settings.RQ_QUEUE_NAME,
            connection=self._redis,
            default_timeout=settings.RQ_RESULT_TTL,
        )

        logger.info(f"Redis管理器已初始化（队列: {settings.RQ_QUEUE_NAME}）")

    def close(self) -> None:
        """关闭Redis连接"""
        if self._redis:
            self._redis.close()

        if self._pool:
            self._pool.disconnect()

        logger.info("Redis连接已关闭")

    def get_connection(self) -> Redis:
        """
        获取Redis连接

        返回:
            Redis客户端实例
        """
        if self._redis is None:
            raise RedisNotInitializedException()
        return self._redis

    def get_queue(self) -> Queue:
        """
        获取RQ队列

        返回:
            RQ队列实例
        """
        if self._queue is None:
            raise RedisNotInitializedException()
        return self._queue

    @contextmanager
    def get_client(self) -> Iterator[Redis]:
        """
        以上下文管理器的形式获取Redis客户端

        用法示例:
            with redis_manager.get_client() as client:
                client.set('key', 'value')
        """
        if self._redis is None:
            raise RedisNotInitializedException()

        try:
            yield self._redis
        finally:
            # 连接池自动管理资源释放
            pass

    def ping(self) -> bool:
        """
        检查Redis是否可用

        返回:
            如果Redis响应ping则为True
        """
        try:
            return self._redis.ping() if self._redis else False
        except Exception as e:
            logger.error(f"Redis ping失败: {e}")
            return False

    def enqueue_job(self, func, *args, **kwargs) -> str:
        """
        向RQ队列添加一个任务

        参数:
            func: 执行的函数
            *args: 传给函数的位置参数
            **kwargs: 传给函数的关键字参数

        返回:
            任务ID
        """
        if self._queue is None:
            raise RedisNotInitializedException()

        job = self._queue.enqueue(func, *args, **kwargs)
        logger.debug(f"已入队任务: {job.id}")
        return job.id

    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._redis is not None and self._queue is not None


# 全局实例
redis_manager = RedisManager()


# 便捷函数
def get_redis_manager() -> RedisManager:
    """获取Redis管理器实例"""
    return redis_manager
