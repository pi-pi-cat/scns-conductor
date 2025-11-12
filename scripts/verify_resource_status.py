#!/usr/bin/env python3
"""
资源状态改进验证脚本

用于验证资源状态管理改进是否正常工作
"""

import sys
from pathlib import Path

# 将项目根目录添加到sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.config import get_settings
from core.database import sync_db
from core.models import ResourceAllocation
from core.enums import ResourceStatus
from core.utils.logger import setup_logger


def check_status_field():
    """检查 status 字段是否存在"""
    logger.info("检查 status 字段...")
    
    try:
        with sync_db.get_session() as session:
            # 尝试查询 status 字段
            result = session.execute(
                "SELECT status FROM resource_allocations LIMIT 1"
            )
            logger.info("✅ status 字段已存在")
            return True
    except Exception as e:
        logger.error(f"❌ status 字段不存在: {e}")
        logger.error("请先运行数据库迁移脚本")
        return False


def check_status_index():
    """检查索引是否存在"""
    logger.info("检查索引...")
    
    try:
        with sync_db.get_session() as session:
            # 查询索引
            result = session.execute("""
                SELECT indexname 
                FROM pg_indexes 
                WHERE tablename = 'resource_allocations' 
                  AND indexname = 'idx_resource_allocation_status'
            """)
            
            if result.fetchone():
                logger.info("✅ 索引 idx_resource_allocation_status 已存在")
                return True
            else:
                logger.warning("⚠️  索引 idx_resource_allocation_status 不存在")
                return False
    except Exception as e:
        logger.error(f"❌ 检查索引失败: {e}")
        return False


def show_status_distribution():
    """显示各状态的资源分配分布"""
    logger.info("查询资源状态分布...")
    
    try:
        with sync_db.get_session() as session:
            # 按状态统计
            result = session.execute("""
                SELECT 
                    status,
                    COUNT(*) as job_count,
                    SUM(allocated_cpus) as total_cpus
                FROM resource_allocations
                GROUP BY status
                ORDER BY status
            """)
            
            logger.info("\n📊 资源状态分布:")
            logger.info("-" * 60)
            logger.info(f"{'状态':<15} {'作业数':<10} {'总CPU数':<10}")
            logger.info("-" * 60)
            
            total_jobs = 0
            total_cpus = 0
            
            for row in result:
                status, job_count, cpus = row
                cpus = cpus or 0
                logger.info(f"{status:<15} {job_count:<10} {cpus:<10}")
                total_jobs += job_count
                total_cpus += cpus
            
            logger.info("-" * 60)
            logger.info(f"{'总计':<15} {total_jobs:<10} {total_cpus:<10}")
            logger.info("-" * 60)
            
    except Exception as e:
        logger.error(f"❌ 查询失败: {e}")


def check_long_reserved():
    """检查长期处于 reserved 状态的记录"""
    logger.info("检查长期预留的资源...")
    
    try:
        with sync_db.get_session() as session:
            result = session.execute("""
                SELECT 
                    job_id,
                    allocated_cpus,
                    allocation_time,
                    EXTRACT(EPOCH FROM (NOW() - allocation_time))/60 as minutes
                FROM resource_allocations
                WHERE status = 'reserved'
                  AND allocation_time < NOW() - INTERVAL '5 minutes'
                ORDER BY allocation_time
            """)
            
            rows = result.fetchall()
            
            if rows:
                logger.warning(f"\n⚠️  发现 {len(rows)} 个长期预留的资源:")
                logger.info("-" * 60)
                logger.info(f"{'作业ID':<10} {'CPU':<8} {'预留时长(分钟)':<15}")
                logger.info("-" * 60)
                
                for row in rows:
                    job_id, cpus, alloc_time, minutes = row
                    logger.warning(f"{job_id:<10} {cpus:<8} {minutes:<15.1f}")
                
                logger.info("-" * 60)
                logger.info("建议：检查这些作业是否正常，可能需要手动清理")
            else:
                logger.info("✅ 没有发现长期预留的资源")
                
    except Exception as e:
        logger.error(f"❌ 查询失败: {e}")


def check_enum_values():
    """检查枚举值是否正确"""
    logger.info("检查枚举值...")
    
    expected = {
        ResourceStatus.RESERVED: "reserved",
        ResourceStatus.ALLOCATED: "allocated",
        ResourceStatus.RELEASED: "released",
    }
    
    all_correct = True
    for enum_val, expected_str in expected.items():
        if enum_val.value == expected_str:
            logger.info(f"✅ {enum_val.name} = '{enum_val.value}'")
        else:
            logger.error(f"❌ {enum_val.name} = '{enum_val.value}' (期望 '{expected_str}')")
            all_correct = False
    
    return all_correct


def main():
    """主函数"""
    # 初始化日志
    setup_logger("INFO")
    
    logger.info("=" * 70)
    logger.info("🔍 资源状态改进验证脚本")
    logger.info("=" * 70)
    
    # 初始化数据库
    try:
        sync_db.init()
        logger.info("✅ 数据库连接成功")
    except Exception as e:
        logger.error(f"❌ 数据库连接失败: {e}")
        sys.exit(1)
    
    logger.info("-" * 70)
    
    # 运行检查
    checks = [
        ("枚举值", check_enum_values),
        ("数据库字段", check_status_field),
        ("数据库索引", check_status_index),
    ]
    
    passed = 0
    failed = 0
    
    for name, check_func in checks:
        logger.info(f"\n{'='*70}")
        logger.info(f"检查项: {name}")
        logger.info(f"{'='*70}")
        
        try:
            if check_func():
                passed += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"检查失败: {e}", exc_info=True)
            failed += 1
    
    # 显示统计信息
    logger.info(f"\n{'='*70}")
    show_status_distribution()
    
    logger.info(f"\n{'='*70}")
    check_long_reserved()
    
    # 总结
    logger.info(f"\n{'='*70}")
    logger.info("验证总结")
    logger.info(f"{'='*70}")
    logger.info(f"通过: {passed}/{len(checks)}")
    logger.info(f"失败: {failed}/{len(checks)}")
    
    if failed == 0:
        logger.info("\n🎉 所有检查通过！资源状态改进已正常工作")
        return 0
    else:
        logger.error(f"\n⚠️  有 {failed} 项检查未通过，请查看上面的错误信息")
        return 1


if __name__ == "__main__":
    sys.exit(main())

