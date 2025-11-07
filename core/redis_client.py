"""
Redis connection manager with RQ queue support
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
    Singleton Redis connection manager
    Manages Redis connections and RQ queues
    """
    
    def __init__(self):
        self._pool: Optional[ConnectionPool] = None
        self._redis: Optional[Redis] = None
        self._queue: Optional[Queue] = None
    
    def init(self) -> None:
        """Initialize Redis connection pool and RQ queue"""
        if self._pool is not None:
            logger.warning("RedisManager already initialized")
            return
        
        settings = get_settings()
        
        # Create connection pool
        self._pool = ConnectionPool(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
            password=settings.REDIS_PASSWORD,
            max_connections=50,
            decode_responses=True,  # Automatically decode responses to strings
        )
        
        # Create Redis client
        self._redis = Redis(connection_pool=self._pool)
        
        # Create RQ queue
        self._queue = Queue(
            name=settings.RQ_QUEUE_NAME,
            connection=self._redis,
            default_timeout=settings.RQ_RESULT_TTL,
        )
        
        logger.info(f"Redis manager initialized (queue: {settings.RQ_QUEUE_NAME})")
    
    def close(self) -> None:
        """Close Redis connections"""
        if self._redis:
            self._redis.close()
        
        if self._pool:
            self._pool.disconnect()
        
        logger.info("Redis connections closed")
    
    def get_connection(self) -> Redis:
        """
        Get Redis connection
        
        Returns:
            Redis client instance
        """
        if self._redis is None:
            raise RedisNotInitializedException()
        return self._redis
    
    def get_queue(self) -> Queue:
        """
        Get RQ queue
        
        Returns:
            RQ Queue instance
        """
        if self._queue is None:
            raise RedisNotInitializedException()
        return self._queue
    
    @contextmanager
    def get_client(self) -> Iterator[Redis]:
        """
        Get Redis client as context manager
        
        Usage:
            with redis_manager.get_client() as client:
                client.set('key', 'value')
        """
        if self._redis is None:
            raise RedisNotInitializedException()
        
        try:
            yield self._redis
        finally:
            # Connection pooling handles cleanup
            pass
    
    def ping(self) -> bool:
        """
        Check if Redis is accessible
        
        Returns:
            True if Redis responds to ping
        """
        try:
            return self._redis.ping() if self._redis else False
        except Exception as e:
            logger.error(f"Redis ping failed: {e}")
            return False
    
    def enqueue_job(self, func, *args, **kwargs) -> str:
        """
        Enqueue a job to RQ
        
        Args:
            func: Function to execute
            *args: Positional arguments for the function
            **kwargs: Keyword arguments for the function
        
        Returns:
            Job ID
        """
        if self._queue is None:
            raise RedisNotInitializedException()
        
        job = self._queue.enqueue(func, *args, **kwargs)
        logger.debug(f"Enqueued job: {job.id}")
        return job.id
    
    def is_initialized(self) -> bool:
        """检查是否已初始化"""
        return self._redis is not None and self._queue is not None


# Global instance
redis_manager = RedisManager()


# Convenience function
def get_redis_manager() -> RedisManager:
    """Get Redis manager instance"""
    return redis_manager

