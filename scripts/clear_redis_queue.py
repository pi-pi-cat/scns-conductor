#!/usr/bin/env python3
"""
清理 Redis 队列中的所有作业数据
用于解决序列化/编码问题
"""

import sys
from pathlib import Path

# 将项目根目录添加到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.config import get_settings
from core.redis_client import redis_manager
from core.utils.logger import setup_logger


def clear_redis_queue():
    """清理 Redis 队列中的所有数据"""
    setup_logger("INFO")

    try:
        # 初始化 Redis
        redis_manager.init()
        settings = get_settings()

        logger.info("=" * 60)
        logger.info("清理 Redis 队列数据")
        logger.info("=" * 60)

        conn = redis_manager.get_connection()
        queue_name = settings.RQ_QUEUE_NAME

        # 获取队列相关的所有键
        keys_to_delete = []

        # RQ 队列相关键
        patterns = [
            f"rq:queue:{queue_name}",
            f"rq:queue:{queue_name}:*",
            f"rq:job:*",
            f"rq:worker:*",
            "rq:workers",
            "rq:workers:*",
            f"rq:finished:{queue_name}",
            f"rq:failed:{queue_name}",
            f"rq:started:{queue_name}",
            f"rq:deferred:{queue_name}",
            f"rq:scheduled:{queue_name}",
        ]

        for pattern in patterns:
            # 注意：keys() 返回字节，需要正确处理
            found_keys = conn.keys(pattern)
            if found_keys:
                keys_to_delete.extend(found_keys)
                # 解码 pattern 如果它是字节
                pattern_str = (
                    pattern.decode("utf-8") if isinstance(pattern, bytes) else pattern
                )
                logger.info(f"找到 {len(found_keys)} 个匹配 '{pattern_str}' 的键")

        if keys_to_delete:
            # 删除所有找到的键
            deleted_count = conn.delete(*keys_to_delete)
            logger.info(f"✅ 成功删除 {deleted_count} 个键")
        else:
            logger.info("✓ 没有找到需要删除的键")

        logger.info("=" * 60)
        logger.info("Redis 队列清理完成")
        logger.info("=" * 60)

    except Exception as e:
        logger.error(f"清理失败: {e}", exc_info=True)
        sys.exit(1)

    finally:
        redis_manager.close()


if __name__ == "__main__":
    clear_redis_queue()
