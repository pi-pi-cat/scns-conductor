#!/usr/bin/env python3
"""
数据库清理脚本 V2 - 使用策略模式

用法:
    python scripts/cleanup_v2.py                          # 执行所有策略
    python scripts/cleanup_v2.py --strategy stuck_job     # 执行指定策略
    python scripts/cleanup_v2.py --list                   # 列出所有策略
"""

import sys
import argparse
from pathlib import Path

# 将项目根目录添加到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.config import get_settings
from core.database import sync_db
from core.utils.logger import setup_logger
from scheduler.cleanup_strategies import create_default_manager


def main():
    parser = argparse.ArgumentParser(description="数据库清理工具 V2（策略模式）")
    parser.add_argument(
        "--list",
        action="store_true",
        help="列出所有清理策略"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        help="执行指定策略（可选：stale_reservation, completed_job, stuck_job, old_job）"
    )
    parser.add_argument(
        "--enable-old-job",
        action="store_true",
        help="启用旧作业清理策略（默认关闭）"
    )
    
    args = parser.parse_args()
    
    # 初始化日志
    setup_logger("INFO")
    
    logger.info("=" * 70)
    logger.info("🧹 数据库清理工具 V2（策略模式）")
    logger.info("=" * 70)
    
    # 初始化数据库
    try:
        sync_db.init()
        logger.info("✓ 数据库连接成功")
    except Exception as e:
        logger.error(f"✗ 数据库连接失败: {e}")
        return 1
    
    logger.info("-" * 70)
    
    try:
        # 创建策略管理器
        manager = create_default_manager()
        
        # 如果指定了启用旧作业清理
        if args.enable_old_job:
            old_job_strategy = manager.get_strategy("old_job_cleanup")
            if old_job_strategy:
                old_job_strategy.enabled = True
                logger.info("✓ 已启用旧作业清理策略")
        
        # 列出策略
        if args.list:
            logger.info("\n📋 可用的清理策略:\n")
            for strategy in manager.list_strategies():
                status = "启用" if strategy.enabled else "禁用"
                logger.info(
                    f"  {strategy.name:<30} [{status}]\n"
                    f"    描述: {strategy.description}\n"
                    f"    间隔: {strategy.interval_seconds}秒"
                )
            return 0
        
        # 执行指定策略
        if args.strategy:
            logger.info(f"\n📋 执行策略: {args.strategy}\n")
            result = manager.execute_strategy(args.strategy)
            
            if result:
                if result.success:
                    logger.info(f"✅ 完成: 清理了 {result.items_cleaned} 项")
                else:
                    logger.error(f"❌ 失败: {result.error_message}")
                    return 1
            else:
                logger.error(f"❌ 策略不存在: {args.strategy}")
                logger.info("使用 --list 查看可用策略")
                return 1
        
        # 执行所有启用的策略
        else:
            logger.info("\n📋 执行所有启用的策略:\n")
            results = manager.execute_due_strategies(current_time=0)  # 强制执行
            
            total_cleaned = sum(r.items_cleaned for r in results)
            failed = [r for r in results if not r.success]
            
            logger.info("-" * 70)
            logger.info(f"✅ 完成: 总共清理了 {total_cleaned} 项")
            
            if failed:
                logger.warning(f"⚠️  有 {len(failed)} 个策略执行失败")
                for r in failed:
                    logger.error(f"  - {r.strategy_name}: {r.error_message}")
                return 1
        
        return 0
    
    except Exception as e:
        logger.error(f"❌ 清理过程中出错: {e}", exc_info=True)
        return 1
    
    finally:
        sync_db.close()


if __name__ == "__main__":
    sys.exit(main())

