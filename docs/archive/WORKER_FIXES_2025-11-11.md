# Worker 修复总结 (2025-11-11)

## 修复的三个问题

### 1. Worker 名称冲突问题 ✅

**问题**：每次重启 worker 时出现错误
```
❌ Worker error: There exists an active worker named 'worker-kunpeng-compute-01' already
```

**原因**：Worker 异常退出时，Redis 中会留下旧的 worker 注册记录，导致重启时名称冲突。

**解决方案**：在启动前清理过期的 worker 记录

```python
# worker/main.py
# 清理过期的 worker（解决重启时名称冲突）
worker_name = f"worker-{settings.NODE_NAME}"
connection = redis_manager.get_connection()

# 获取所有 worker
from rq.worker import Worker as RQWorker
all_workers = RQWorker.all(connection=connection)

# 查找同名 worker
for w in all_workers:
    if w.name == worker_name:
        # 检查是否还活着
        if w.state in ['busy', 'idle']:
            # 尝试发送心跳，如果失败说明 worker 已死
            try:
                w.refresh()
                if not w.is_alive():
                    logger.warning(f"🧹 Cleaning up dead worker: {worker_name}")
                    w.register_death()
            except Exception as e:
                logger.warning(f"🧹 Cleaning up stale worker: {worker_name} - {e}")
                w.register_death()
        else:
            logger.warning(f"🧹 Cleaning up stopped worker: {worker_name}")
            w.register_death()
```

### 2. 数据库初始化策略 ✅

**用户反馈**：已通过环境变量解决 macOS fork 问题，希望在主程序中初始化数据库连接。

**修改**：恢复在主进程中初始化数据库

```python
# worker/main.py
def main():
    # 初始化数据库
    try:
        sync_db.init()
        logger.info("✓ Database connected")
    except Exception as e:
        logger.error(f"✗ Database connection failed: {e}")
        sys.exit(1)
```

**环境变量设置**（用户已配置）：
```bash
export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES
```

### 3. 资源释放逻辑错误 ✅

**问题**：资源释放的查询逻辑反了

**原来的错误代码**：
```python
# 错误：查找已释放的资源，然后再标记为已释放（逻辑矛盾）
allocation = (
    session.query(ResourceAllocation)
    .filter(
        ResourceAllocation.job_id == job_id,
        ResourceAllocation.released,  # ❌ 查找已释放的
    )
    .first()
)
```

**修复后的正确代码**：
```python
# 正确：查找未释放的资源，然后标记为已释放
allocation = (
    session.query(ResourceAllocation)
    .filter(
        ResourceAllocation.job_id == job_id,
        ~ResourceAllocation.released,  # ✅ 查找未释放的
    )
    .first()
)

if allocation:
    # 标记为已释放
    allocation.released = True
    allocation.released_time = datetime.utcnow()
    session.commit()
```

## 代码规范修复

1. ✅ 移除未使用的 `import os`
2. ✅ 修复 bare `except` → `except Exception as e`
3. ✅ 修复 `== False` → `~ResourceAllocation.released`

## 测试验证

修复后应该验证：

1. **Worker 重启**：多次重启 worker，不应该出现名称冲突错误
2. **任务执行**：提交任务，验证能正常执行
3. **资源释放**：任务完成后，检查数据库中 `resource_allocations` 表，确认 `released=True`

```bash
# 启动 worker
python -m worker.main

# 查看资源分配状态
psql -d your_database -c "SELECT job_id, allocated_cpus, released, released_time FROM resource_allocations ORDER BY id DESC LIMIT 10;"
```

## 相关文件

- `worker/main.py` - Worker 主入口，添加了过期 worker 清理逻辑
- `worker/executor.py` - 任务执行器，修复了资源释放逻辑

## 日期

2025-11-11

