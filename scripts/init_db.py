#!/usr/bin/env python3
"""
数据库初始化脚本
创建所有表，并可选地插入初始数据
"""

import sys
from pathlib import Path

# 添加项目根目录到PATH
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.config import get_settings
from core.database import sync_db, Base
from core.models import SystemResource
from core.utils.logger import setup_logger


def create_tables():
    """创建所有数据库表"""
    logger.info("正在创建数据库表...")

    try:
        sync_db.init()
        sync_db.create_tables()
        logger.info("数据库表创建成功")
    except Exception as e:
        logger.error(f"创建数据库表失败: {e}")
        raise


def seed_system_resources():
    """插入初始系统资源数据"""
    settings = get_settings()

    logger.info("正在插入系统资源数据...")

    try:
        with sync_db.get_session() as session:
            # 检查节点是否已存在
            existing = (
                session.query(SystemResource)
                .filter(SystemResource.node_name == settings.NODE_NAME)
                .first()
            )

            if existing:
                logger.info(f"节点 {settings.NODE_NAME} 已存在，跳过")
                return

            # 创建系统资源条目
            resource = SystemResource(
                node_name=settings.NODE_NAME,
                total_cpus=settings.TOTAL_CPUS,
                partition=settings.DEFAULT_PARTITION,
                available=True,
            )

            session.add(resource)
            session.commit()

            logger.info(
                f"已创建系统资源: {settings.NODE_NAME} "
                f"({settings.TOTAL_CPUS} 核心, 分区: {settings.DEFAULT_PARTITION})"
            )

    except Exception as e:
        logger.error(f"插入系统资源失败: {e}")
        raise


def main():
    """主初始化流程"""
    # 配置日志
    setup_logger("INFO")

    logger.info("=== 数据库初始化 ===")

    settings = get_settings()
    logger.info(f"数据库: {settings.POSTGRES_DB}")
    logger.info(f"主机: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")

    try:
        # 创建表
        create_tables()

        # 插入初始数据
        seed_system_resources()

        logger.info("=== 数据库初始化成功完成 ===")

    except Exception as e:
        logger.error(f"数据库初始化失败: {e}")
        sys.exit(1)

    finally:
        sync_db.close()


if __name__ == "__main__":
    main()
