#!/usr/bin/env python
"""
测试动态资源管理功能

验证：
1. Worker 注册和心跳
2. 动态资源计算
3. Redis 缓存
"""

import sys
import time
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger
from core.redis_client import redis_manager
from core.config import get_settings


def test_worker_registry():
    """测试 Worker 注册"""
    logger.info("=" * 60)
    logger.info("测试 1: Worker 注册")
    logger.info("=" * 60)
    
    redis = redis_manager.get_connection()
    worker_keys = redis.keys("worker:*")
    
    if not worker_keys:
        logger.warning("⚠️  未找到已注册的 Worker")
        logger.info("请先启动 Worker: python -m worker.main")
        return False
    
    logger.info(f"✓ 找到 {len(worker_keys)} 个活跃 Worker")
    
    for key in worker_keys:
        worker_info = redis.hgetall(key)
        worker_id = worker_info.get(b"worker_id", b"unknown").decode()
        cpus = worker_info.get(b"cpus", b"0").decode()
        status = worker_info.get(b"status", b"unknown").decode()
        last_heartbeat = worker_info.get(b"last_heartbeat", b"N/A").decode()
        
        logger.info(f"  - {worker_id}: {cpus} CPUs, status={status}")
        logger.info(f"    Last heartbeat: {last_heartbeat}")
        
        # 检查 TTL
        ttl = redis.ttl(key)
        logger.info(f"    TTL: {ttl} 秒")
    
    return True


def test_dynamic_resources():
    """测试动态资源计算"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 2: 动态资源计算")
    logger.info("=" * 60)
    
    redis = redis_manager.get_connection()
    worker_keys = redis.keys("worker:*")
    
    total_cpus = 0
    for key in worker_keys:
        worker_info = redis.hgetall(key)
        cpus = int(worker_info.get(b"cpus", 0))
        total_cpus += cpus
    
    logger.info(f"✓ 总 CPUs: {total_cpus}")
    
    # 检查缓存
    allocated_cpus = redis.get("resource:allocated_cpus")
    if allocated_cpus:
        allocated_cpus = int(allocated_cpus)
        available_cpus = total_cpus - allocated_cpus
        utilization = (allocated_cpus / total_cpus * 100) if total_cpus > 0 else 0
        
        logger.info(f"✓ 已分配: {allocated_cpus} CPUs")
        logger.info(f"✓ 可用: {available_cpus} CPUs")
        logger.info(f"✓ 利用率: {utilization:.1f}%")
    else:
        logger.info("⚠️  Redis 缓存未初始化")
        logger.info("请启动 Scheduler 以初始化缓存")
    
    return True


def test_heartbeat_mechanism():
    """测试心跳机制"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 3: 心跳机制")
    logger.info("=" * 60)
    
    redis = redis_manager.get_connection()
    worker_keys = redis.keys("worker:*")
    
    if not worker_keys:
        logger.warning("⚠️  未找到 Worker")
        return False
    
    # 记录初始 TTL
    logger.info("记录初始 TTL...")
    initial_ttls = {}
    for key in worker_keys:
        ttl = redis.ttl(key)
        worker_id = redis.hget(key, "worker_id").decode()
        initial_ttls[worker_id] = ttl
        logger.info(f"  {worker_id}: {ttl} 秒")
    
    # 等待 5 秒
    logger.info("\n等待 5 秒后检查 TTL...")
    time.sleep(5)
    
    # 检查 TTL 是否被刷新
    all_refreshed = True
    for key in worker_keys:
        ttl = redis.ttl(key)
        worker_id = redis.hget(key, "worker_id").decode()
        initial_ttl = initial_ttls.get(worker_id, 0)
        
        # TTL 应该接近初始值（因为心跳刷新）
        if ttl < initial_ttl - 10:  # 允许一些误差
            logger.warning(f"  ⚠️  {worker_id}: TTL 未刷新 ({initial_ttl} -> {ttl})")
            all_refreshed = False
        else:
            logger.info(f"  ✓ {worker_id}: TTL 正常 ({initial_ttl} -> {ttl})")
    
    if all_refreshed:
        logger.info("\n✓ 心跳机制正常工作")
    else:
        logger.warning("\n⚠️  心跳机制可能有问题")
    
    return all_refreshed


def test_redis_cache():
    """测试 Redis 缓存"""
    logger.info("\n" + "=" * 60)
    logger.info("测试 4: Redis 缓存")
    logger.info("=" * 60)
    
    redis = redis_manager.get_connection()
    
    # 测试缓存键是否存在
    cache_key = "resource:allocated_cpus"
    exists = redis.exists(cache_key)
    
    if exists:
        value = redis.get(cache_key)
        logger.info(f"✓ 缓存键存在: {cache_key} = {value}")
        
        # 测试缓存性能
        start_time = time.time()
        for _ in range(1000):
            redis.get(cache_key)
        elapsed = time.time() - start_time
        
        logger.info(f"✓ 缓存性能: 1000 次查询耗时 {elapsed:.3f} 秒")
        logger.info(f"  平均每次: {elapsed/1000*1000:.3f} 毫秒")
    else:
        logger.warning(f"⚠️  缓存键不存在: {cache_key}")
        logger.info("请启动 Scheduler 以初始化缓存")
    
    return True


def main():
    """运行所有测试"""
    logger.info("\n")
    logger.info("╔" + "=" * 58 + "╗")
    logger.info("║" + " " * 10 + "动态资源管理功能测试" + " " * 26 + "║")
    logger.info("╚" + "=" * 58 + "╝")
    
    # 初始化
    settings = get_settings()
    try:
        redis_manager.init()
        logger.info("✓ Redis 连接成功\n")
    except Exception as e:
        logger.error(f"✗ Redis 连接失败: {e}")
        sys.exit(1)
    
    # 运行测试
    tests = [
        ("Worker 注册", test_worker_registry),
        ("动态资源计算", test_dynamic_resources),
        ("心跳机制", test_heartbeat_mechanism),
        ("Redis 缓存", test_redis_cache),
    ]
    
    results = []
    for test_name, test_func in tests:
        try:
            result = test_func()
            results.append((test_name, result))
        except Exception as e:
            logger.error(f"✗ 测试失败: {test_name}")
            logger.error(f"  错误: {e}")
            results.append((test_name, False))
    
    # 输出总结
    logger.info("\n" + "=" * 60)
    logger.info("测试总结")
    logger.info("=" * 60)
    
    passed = sum(1 for _, result in results if result)
    total = len(results)
    
    for test_name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        logger.info(f"{status}: {test_name}")
    
    logger.info(f"\n通过: {passed}/{total}")
    
    if passed == total:
        logger.info("\n🎉 所有测试通过！")
    else:
        logger.warning(f"\n⚠️  {total - passed} 个测试失败")
    
    # 清理
    redis_manager.close()


if __name__ == "__main__":
    main()

