# 动态资源管理实施文档

## 概述

实施了方案 3（Worker 注册 + 心跳机制）+ 方案 2（Redis 缓存优化），实现动态资源管理和高性能资源查询。

## 核心改进

### 1. 动态资源感知 ✅
- Worker 启动时自动注册到 Redis
- Scheduler 从活跃 Worker 动态获取总资源
- 支持 Worker 动态上下线（自动扩缩容）

### 2. Redis 缓存优化 ✅  
- 已分配资源使用 Redis 缓存，查询性能从 50-100ms 降至 <1ms
- 资源分配/释放时自动更新缓存
- 定期从数据库同步（容错机制）

### 3. 心跳机制 ✅
- Worker 每 30 秒发送心跳
- Redis键 TTL 60 秒，超时自动过期
- Scheduler 只能看到活跃的 Worker

## 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                          Redis                              │
│                                                             │
│  worker:node-01 = {cpus: 96, status: ready, ...}           │
│  worker:node-02 = {cpus: 96, status: ready, ...}           │
│  resource:allocated_cpus = 48                               │
│                                                             │
│  TTL: 60秒（心跳刷新）                                       │
└─────────────────────────────────────────────────────────────┘
         ↑ 注册/心跳                    ↑ 查询
         │                              │
    ┌────┴─────┐                  ┌────┴─────┐
    │  Worker  │                  │ Scheduler│
    │  节点    │                  │          │
    └──────────┘                  └──────────┘
         │                              │
         │                              │
         ↓                              ↓
┌─────────────────────────────────────────────────────────────┐
│                      PostgreSQL                             │
│                                                             │
│  resource_allocations (持久化)                              │
│  └─ 数据库作为唯一真实源                                     │
└─────────────────────────────────────────────────────────────┘
```

## 实现细节

### Worker 注册模块 (`worker/registry.py`)

```python
class WorkerRegistry:
    """Worker 注册和心跳管理"""
    
    def register(self):
        """注册 Worker 到 Redis"""
        worker_info = {
            "worker_id": self.worker_id,
            "cpus": self.cpus,
            "status": "ready",
            "hostname": self.hostname,
            "registered_at": datetime.utcnow().isoformat(),
        }
        redis.hset(f"worker:{self.worker_id}", mapping=worker_info)
        redis.expire(f"worker:{self.worker_id}", 60)  # TTL 60秒
    
    def start_heartbeat(self):
        """启动心跳线程（每 30 秒）"""
        # 在独立线程中运行
        # 刷新 TTL + 更新 last_heartbeat
    
    def unregister(self):
        """注销 Worker"""
        redis.delete(f"worker:{self.worker_id}")
```

**特性**：
- 自动注册：Worker 启动时调用
- 独立心跳线程：不影响任务执行
- 优雅停止：注销时删除注册信息
- TTL 自动过期：Worker 异常退出时自动清理

### Worker 主程序集成 (`worker/main.py`)

```python
def main():
    # ...初始化数据库和 Redis...
    
    # 注册 Worker
    registry = WorkerRegistry()
    registry.register()
    registry.start_heartbeat()
    
    # 创建 RQ Worker
    worker = Worker(...)
    
    try:
        worker.work()
    finally:
        # 注销
        registry.unregister()
```

### Scheduler 动态资源计算 (`scheduler/scheduler.py`)

#### 新增方法

```python
def _get_total_cpus_dynamic(self) -> int:
    """动态获取所有活跃 Worker 的 CPU 总数"""
    worker_keys = redis.keys("worker:*")
    total_cpus = 0
    for key in worker_keys:
        worker_info = redis.hgetall(key)
        total_cpus += int(worker_info.get(b"cpus", 0))
    return total_cpus

def _get_allocated_cpus_cached(self) -> int:
    """从 Redis 缓存获取已分配资源（快速）"""
    allocated = redis.get("resource:allocated_cpus")
    if allocated:
        return int(allocated)
    # 缓存未命中，查询数据库
    return self._get_allocated_cpus(session)

def sync_resource_cache(self):
    """定期从数据库同步到 Redis（容错）"""
    allocated = self._get_allocated_cpus(session)
    redis.set("resource:allocated_cpus", allocated)
```

#### 修改调度逻辑

```python
def schedule(self) -> int:
    # 1. 动态获取总资源
    total_cpus = self._get_total_cpus_dynamic()
    if total_cpus == 0:
        logger.warning("No active workers")
        return 0
    
    # 2. 从缓存获取已分配资源
    allocated_cpus = self._get_allocated_cpus_cached()
    available_cpus = total_cpus - allocated_cpus
    
    # 3. 调度作业...
```

#### 资源分配时更新缓存

```python
def _allocate_and_enqueue(self, session, job, cpus):
    # 1. 数据库操作
    allocation = ResourceAllocation(...)
    session.add(allocation)
    session.flush()
    
    # 2. 更新 Redis 缓存
    redis.incrby("resource:allocated_cpus", cpus)
    
    # 3. 加入队列
    queue.enqueue(...)
```

### Worker 释放资源更新缓存 (`worker/executor.py`)

```python
def _release_resources(self, job_id: int):
    # 1. 更新数据库
    allocation.released = True
    session.commit()
    
    # 2. 更新 Redis 缓存
    redis.decrby("resource:allocated_cpus", cpus)
```

### Scheduler 守护进程 (`scheduler/daemon.py`)

```python
def run(self):
    while not self._stop_event.is_set():
        # 1. 调度作业
        self.scheduler.schedule()
        
        # 2. 释放已完成资源（兜底）
        self.scheduler.release_completed()
        
        # 3. 定期同步缓存（每 5 分钟）
        if current_time - self._last_sync_time >= 300:
            self.scheduler.sync_resource_cache()
        
        # 4. 输出统计（每 60 秒）
        if current_time - self._last_stats_time >= 60:
            self._log_stats()
```

## Redis 数据结构

### Worker 注册信息
```redis
worker:kunpeng-compute-01
{
    "worker_id": "kunpeng-compute-01",
    "cpus": "96",
    "status": "ready",
    "hostname": "node-01",
    "registered_at": "2025-11-11T10:00:00",
    "last_heartbeat": "2025-11-11T10:05:30"
}
TTL: 60秒
```

### 资源缓存
```redis
resource:allocated_cpus = "48"  # 已分配 48 CPUs
```

## 性能对比

| 操作 | 之前（数据库） | 现在（Redis + 动态） | 提升 |
|------|---------------|-------------------|------|
| 查询总资源 | 配置文件（固定） | Redis keys（动态） | 实时感知 |
| 查询已分配资源 | 50-100ms（SUM） | <1ms（GET） | **50-100倍** |
| Worker 上线 | 手动修改配置 | 自动注册 | **自动化** |
| Worker 下线 | 资源计算错误 | 心跳超时自动移除 | **故障自愈** |

## 容错机制

### 1. Redis 缓存不一致
- **问题**：Redis 缓存可能与数据库不一致
- **解决**：每 5 分钟从数据库同步到 Redis
- **降级**：Redis 查询失败时自动降级到数据库

### 2. Worker 异常退出
- **问题**：Worker 崩溃未注销
- **解决**：Redis 键 TTL 60秒自动过期
- **心跳**：30秒一次，确保活跃

### 3. 数据库更新失败
- **问题**：资源分配失败但 Redis 已更新
- **解决**：数据库事务回滚，定期同步修正

### 4. 网络分区
- **问题**：Worker 与 Redis 网络断开
- **解决**：心跳失败后 TTL 过期，Scheduler 自动移除

## 测试验证

### 1. 基本功能测试

```bash
# 启动 Scheduler
python -m scheduler.main

# 启动 Worker
python -m worker.main

# 查看 Redis 中的 Worker 注册
redis-cli
> KEYS worker:*
> HGETALL worker:kunpeng-compute-01

# 查看资源缓存
> GET resource:allocated_cpus
```

**预期结果**：
- 看到 `worker:*` 键
- Worker 信息包含 cpus、status 等
- 资源缓存值正确

### 2. 动态扩缩容测试

```bash
# 初始：1 个 Worker (96 CPUs)
# 查看总资源
curl http://localhost:8000/api/v1/dashboard | jq '.resources'

# 启动第 2 个 Worker (96 CPUs)
NODE_NAME=worker-02 python -m worker.main

# 再次查看总资源
curl http://localhost:8000/api/v1/dashboard | jq '.resources'
```

**预期结果**：
- 初始总资源：96 CPUs
- 启动 Worker 2 后：192 CPUs（自动增加）
- 停止 Worker 2 后：96 CPUs（自动减少）

### 3. 心跳机制测试

```bash
# 启动 Worker
python -m worker.main

# 查看 TTL
redis-cli
> TTL worker:kunpeng-compute-01
(integer) 58  # 剩余秒数

# 等待 30 秒后再查看（心跳应该刷新 TTL）
> TTL worker:kunpeng-compute-01
(integer) 56  # 应该接近 60

# 强制杀死 Worker
kill -9 <pid>

# 等待 60 秒
> TTL worker:kunpeng-compute-01
(integer) -2  # 键已过期
> EXISTS worker:kunpeng-compute-01
(integer) 0  # 键不存在
```

### 4. 缓存一致性测试

```bash
# 提交作业
curl -X POST http://localhost:8000/api/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{"script": "sleep 60", "cpus": 4}'

# 查看 Redis 缓存
redis-cli
> GET resource:allocated_cpus
"4"

# 查看数据库
psql -d conductor -c \
  "SELECT SUM(allocated_cpus) FROM resource_allocations WHERE released = false;"
 4

# 手动删除 Redis 缓存（模拟缓存失效）
> DEL resource:allocated_cpus

# 等待下次调度（会从数据库重新加载到缓存）
# 查看日志
# "Cache miss, querying database"
```

### 5. 性能测试

```bash
# 测试资源查询性能
time redis-cli GET resource:allocated_cpus
# 输出：real 0m0.001s

# 对比数据库查询
time psql -d conductor -c \
  "SELECT SUM(allocated_cpus) FROM resource_allocations WHERE released = false;"
# 输出：real 0m0.050s

# 提升约 50 倍
```

## 监控指标

### Redis 监控

```bash
# 查看所有活跃 Worker
redis-cli KEYS "worker:*" | wc -l

# 查看资源使用
redis-cli GET resource:allocated_cpus

# 查看 Worker 详情
redis-cli HGETALL worker:kunpeng-compute-01
```

### 数据库监控

```sql
-- 查看资源分配情况
SELECT 
    COUNT(*) as total_allocations,
    SUM(allocated_cpus) as total_cpus,
    SUM(CASE WHEN released = false THEN allocated_cpus ELSE 0 END) as active_cpus
FROM resource_allocations;

-- 检查缓存一致性
SELECT SUM(allocated_cpus) as db_allocated
FROM resource_allocations 
WHERE released = false;
-- 对比 Redis: GET resource:allocated_cpus
```

### 日志监控

关键日志：
- Worker 注册：`✓ Worker registered: xxx (96 CPUs)`
- 心跳：`💓 Heartbeat sent: xxx`
- 动态资源：`Active workers: 2, Total CPUs: 192`
- 缓存同步：`Resource cache synced: 48 CPUs allocated`

## 故障排查

### 问题 1：Worker 注册失败
```
✗ Worker registration failed
```

**原因**：Redis 连接失败
**解决**：
```bash
# 检查 Redis 状态
redis-cli ping

# 检查配置
cat app.properties | grep REDIS
```

### 问题 2：Scheduler 看不到 Worker
```
⚠️  No active workers, skipping schedule
```

**原因**：
1. Worker 未启动
2. Worker 注册失败
3. 心跳超时

**排查**：
```bash
# 查看 Redis 中的 Worker
redis-cli KEYS "worker:*"

# 查看 Worker 日志
tail -f logs/worker.log | grep -E "register|heartbeat"
```

### 问题 3：资源统计不准确
```
total_cpus: 96 (实际应该是 192)
```

**原因**：某个 Worker 的心跳失败

**排查**：
```bash
# 检查所有 Worker 的 TTL
redis-cli KEYS "worker:*" | while read key; do
    echo "$key: $(redis-cli TTL $key)"
done

# 检查 Worker 心跳日志
grep "Heartbeat failed" logs/worker.log
```

### 问题 4：缓存与数据库不一致
```redis
GET resource:allocated_cpus
"48"
```
```sql
SELECT SUM(allocated_cpus) FROM resource_allocations WHERE released = false;
 52
```

**原因**：Redis 更新失败或网络抖动

**解决**：手动触发同步
```python
# 在 scheduler 中
scheduler.sync_resource_cache()
```

或等待自动同步（每 5 分钟）

## 最佳实践

### 1. Worker 部署
```bash
# 每个节点使用唯一的 NODE_NAME
export NODE_NAME=worker-node-01
export TOTAL_CPUS=96
python -m worker.main
```

### 2. Scheduler 配置
- 调度间隔：5秒（默认）
- 统计输出：60秒
- 缓存同步：300秒（5分钟）

### 3. Redis 配置
```conf
# 建议配置
maxmemory 256mb
maxmemory-policy allkeys-lru
save 900 1  # 持久化
```

### 4. 监控告警
- Worker 数量 < 预期：心跳失败告警
- 缓存不一致 > 10%：同步失败告警
- 资源利用率 > 90%：容量告警

## 升级指南

### 从旧版本升级

1. **备份数据库**
```bash
pg_dump conductor > backup.sql
```

2. **更新代码**
```bash
git pull
pip install -r requirements.txt
```

3. **无需数据迁移**
   - Worker 注册信息存储在 Redis（临时）
   - 数据库结构未改变

4. **重启服务**
```bash
# 停止旧服务
pkill -f "scheduler.main"
pkill -f "worker.main"

# 启动新服务
python -m scheduler.main &
python -m worker.main &
```

5. **验证**
```bash
# 检查 Worker 注册
redis-cli KEYS "worker:*"

# 提交测试作业
curl -X POST http://localhost:8000/api/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{"script": "echo test", "cpus": 1}'
```

### 回滚方案

如果出现问题，可以回滚到旧版本：

1. **停止新服务**
2. **恢复旧代码**
3. **清理 Redis**
```bash
redis-cli KEYS "worker:*" | xargs redis-cli DEL
redis-cli DEL resource:allocated_cpus
```
4. **启动旧服务**

## 未来优化

### 短期（1-2 周）
- [ ] 添加 Worker 状态监控页面
- [ ] 支持 Worker 负载均衡
- [ ] 优化心跳频率（自适应）

### 中期（1-2 月）
- [ ] 支持 Worker 分组（GPU/CPU）
- [ ] 实现资源预留机制
- [ ] 添加资源使用趋势分析

### 长期（3-6 月）
- [ ] 支持多数据中心部署
- [ ] 实现智能调度算法
- [ ] 容器化 Worker 管理

## 相关文件

- `worker/registry.py` - Worker 注册模块
- `worker/main.py` - Worker 主程序
- `scheduler/scheduler.py` - Scheduler 调度器
- `scheduler/daemon.py` - Scheduler 守护进程
- `worker/executor.py` - Worker 执行器
- `docs/RESOURCE_OPTIMIZATION_PROPOSALS.md` - 方案设计文档

## 更新日期

2025-11-11

