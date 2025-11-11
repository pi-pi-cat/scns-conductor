# Redis Keys 参考文档

## 概述

本文档详细列出了 SCNS-Conductor 系统中使用的所有 Redis 键及其用途。

---

## 📋 系统 Redis 键分类

### 1. Worker 注册相关 (动态资源管理)

#### `worker:{worker_id}`

**类型**: Hash (哈希)  
**生命周期**: 60 秒 TTL（通过心跳刷新）  
**用途**: 存储 Worker 节点的注册信息

**数据结构**:
```redis
HGETALL worker:kunpeng-compute-01

{
    "worker_id": "kunpeng-compute-01",
    "cpus": "96",
    "status": "ready",
    "hostname": "node-01.example.com",
    "registered_at": "2025-11-11T10:00:00",
    "last_heartbeat": "2025-11-11T10:05:30"
}
```

**字段说明**:
- `worker_id`: Worker 唯一标识（通常是 NODE_NAME）
- `cpus`: 该 Worker 提供的 CPU 核心数
- `status`: Worker 状态（ready/busy/stopping）
- `hostname`: Worker 所在主机名
- `registered_at`: 注册时间（ISO 8601 格式）
- `last_heartbeat`: 最后一次心跳时间

**生命周期管理**:
```python
# 创建/更新（TTL 60 秒）
HSET worker:kunpeng-compute-01 ...
EXPIRE worker:kunpeng-compute-01 60

# 心跳刷新（每 30 秒）
HSET worker:kunpeng-compute-01 last_heartbeat "2025-11-11T10:05:30"
EXPIRE worker:kunpeng-compute-01 60

# 自动过期（60 秒无心跳）
TTL worker:kunpeng-compute-01  # 返回 -2 表示已过期
```

**代码位置**:
- 定义: `core/services/worker_repository.py` (WorkerRepository)
- 创建: `worker/registry.py` (WorkerRegistry.register)
- 更新: `worker/registry.py` (WorkerRegistry._heartbeat_loop)
- 删除: `worker/registry.py` (WorkerRegistry.unregister)

**使用场景**:
1. **Worker 启动**: 注册到 Redis，声明自己的资源
2. **心跳维持**: 每 30 秒更新 `last_heartbeat` 和刷新 TTL
3. **Scheduler 查询**: 获取所有活跃 Worker，计算总资源
4. **Worker 停止**: 注销（删除键）或自然过期

**查询示例**:
```bash
# 查看所有活跃 Worker
redis-cli KEYS "worker:*"

# 查看特定 Worker 详情
redis-cli HGETALL worker:kunpeng-compute-01

# 查看 TTL
redis-cli TTL worker:kunpeng-compute-01
```

---

### 2. 资源缓存相关 (性能优化)

#### `resource:allocated_cpus`

**类型**: String (字符串)  
**生命周期**: 持久化（无 TTL）  
**用途**: 缓存当前已分配的 CPU 总数，避免频繁查询数据库

**数据结构**:
```redis
GET resource:allocated_cpus
"48"  # 表示已分配 48 个 CPU 核心
```

**生命周期管理**:
```python
# 初始化（从数据库同步）
SET resource:allocated_cpus "0"

# 分配资源时增加
INCRBY resource:allocated_cpus 4  # 分配 4 CPUs

# 释放资源时减少
DECRBY resource:allocated_cpus 4  # 释放 4 CPUs

# 定期同步（每 5 分钟）
SET resource:allocated_cpus "48"  # 从数据库重新同步
```

**代码位置**:
- 定义: `core/services/resource_manager.py` (ResourceCache.KEY_ALLOCATED_CPUS)
- 初始化: `scheduler/scheduler.py` (JobScheduler.__init__)
- 增加: `scheduler/scheduler.py` (_allocate_and_enqueue)
- 减少: `worker/executor.py` (_release_resources)
- 同步: `scheduler/scheduler.py` (sync_resource_cache)

**使用场景**:
1. **Scheduler 初始化**: 从数据库同步当前已分配资源
2. **作业调度**: 快速查询可用资源（<1ms）
3. **资源分配**: 增加已分配数量
4. **资源释放**: 减少已分配数量
5. **定期同步**: 每 5 分钟从数据库同步，确保一致性

**查询示例**:
```bash
# 查看已分配 CPU 数量
redis-cli GET resource:allocated_cpus

# 模拟分配
redis-cli INCRBY resource:allocated_cpus 4

# 模拟释放
redis-cli DECRBY resource:allocated_cpus 4
```

**性能对比**:
- 数据库查询: `SELECT SUM(allocated_cpus) FROM resource_allocations WHERE released = false` (~50-100ms)
- Redis 缓存: `GET resource:allocated_cpus` (<1ms)
- **性能提升**: 50-100 倍

---

#### `resource:available_cpus` (已定义但未使用)

**类型**: String (字符串)  
**生命周期**: N/A (当前未使用)  
**用途**: 预留键名，未来可用于缓存可用 CPU 数量

**说明**:
- 该键已在 `ResourceCache` 中定义
- 当前系统通过动态计算获取可用资源：`available = total - allocated`
- 未来如果需要直接缓存可用资源，可以使用此键

---

### 3. RQ (Redis Queue) 相关 (任务队列)

RQ 是 Python 的 Redis 任务队列库，用于分布式任务调度。以下是 RQ 自动创建和管理的键。

#### `rq:queue:{queue_name}`

**类型**: List (列表)  
**生命周期**: 持久化  
**用途**: 存储待处理的任务 ID

**数据结构**:
```redis
LRANGE rq:queue:scns 0 -1

[
    "job_123",
    "job_124",
    "job_125"
]
```

**说明**:
- `queue_name` 默认为 `scns`（由配置文件 `RQ_QUEUE_NAME` 指定）
- Scheduler 将作业加入队列
- Worker 从队列中取出作业执行

**操作**:
```bash
# 查看队列长度
redis-cli LLEN rq:queue:scns

# 查看队列内容
redis-cli LRANGE rq:queue:scns 0 -1
```

---

#### `rq:job:{job_id}`

**类型**: Hash (哈希)  
**生命周期**: 24 小时（可配置 `RQ_RESULT_TTL`）  
**用途**: 存储任务的详细信息和执行结果

**数据结构**:
```redis
HGETALL rq:job:job_123

{
    "status": "finished",
    "origin": "scns",
    "created_at": "2025-11-11T10:00:00",
    "enqueued_at": "2025-11-11T10:00:01",
    "started_at": "2025-11-11T10:00:05",
    "ended_at": "2025-11-11T10:01:00",
    "result": "...",
    "exc_info": "...",
    "data": "..."  # pickled 数据
}
```

**状态**:
- `queued`: 已入队，等待执行
- `started`: 正在执行
- `finished`: 执行完成
- `failed`: 执行失败
- `deferred`: 延迟执行
- `scheduled`: 计划执行

**操作**:
```bash
# 查看任务详情
redis-cli HGETALL rq:job:job_123

# 查看任务状态
redis-cli HGET rq:job:job_123 status

# 查看所有任务
redis-cli KEYS "rq:job:*"
```

---

#### `rq:worker:{worker_name}`

**类型**: Hash (哈希)  
**生命周期**: 420 秒（7 分钟，RQ 默认）  
**用途**: RQ Worker 的注册信息（注意：与我们的 `worker:{worker_id}` 不同）

**说明**:
- 这是 RQ 自动创建的 Worker 注册信息
- 用于 RQ 的内部管理和监控
- 与我们的 `worker:{worker_id}` 是独立的两套系统：
  - `worker:{worker_id}`: 资源管理（CPU 数量、心跳）
  - `rq:worker:{worker_name}`: RQ 任务执行状态

**数据结构**:
```redis
HGETALL rq:worker:worker-kunpeng-compute-01

{
    "birth": "1699689600",
    "current_job": "job_123",
    "state": "busy",
    ...
}
```

---

#### `rq:workers`

**类型**: Set (集合)  
**生命周期**: 持久化  
**用途**: 存储所有活跃的 RQ Worker 名称

**数据结构**:
```redis
SMEMBERS rq:workers

[
    "worker-kunpeng-compute-01.12345",
    "worker-kunpeng-compute-01.12346"
]
```

---

#### `rq:finished:{queue_name}`

**类型**: Sorted Set (有序集合)  
**生命周期**: 持久化（可配置清理策略）  
**用途**: 存储已完成的任务 ID（按完成时间排序）

**数据结构**:
```redis
ZRANGE rq:finished:scns 0 -1 WITHSCORES

[
    "job_120", "1699689500",
    "job_121", "1699689550",
    "job_122", "1699689600"
]
```

---

#### `rq:failed:{queue_name}`

**类型**: Sorted Set (有序集合)  
**生命周期**: 持久化  
**用途**: 存储失败的任务 ID（按失败时间排序）

**说明**:
- 用于故障排查和重试
- 可以通过 RQ 工具查看失败原因

---

#### `rq:started:{queue_name}`

**类型**: Set (集合)  
**生命周期**: 临时（任务完成后移除）  
**用途**: 存储正在执行的任务 ID

---

#### `rq:deferred:{queue_name}`

**类型**: Sorted Set (有序集合)  
**生命周期**: 持久化  
**用途**: 存储延迟执行的任务

---

#### `rq:scheduled:{queue_name}`

**类型**: Sorted Set (有序集合)  
**生命周期**: 持久化  
**用途**: 存储计划执行的任务（定时任务）

---

## 📊 键空间统计

### 当前系统键数量估算

假设运行状态：
- 2 个 Worker 节点
- 10 个待处理任务
- 100 个已完成任务（24 小时内）

| 键类型 | 数量 | 示例 |
|--------|------|------|
| Worker 注册 | ~2 | `worker:node-01`, `worker:node-02` |
| 资源缓存 | 1 | `resource:allocated_cpus` |
| RQ 队列 | 1 | `rq:queue:scns` |
| RQ 任务详情 | ~110 | `rq:job:*` (10 待处理 + 100 已完成) |
| RQ Worker | ~2 | `rq:worker:*` |
| RQ Worker 集合 | 1 | `rq:workers` |
| RQ 任务状态 | ~5 | `rq:finished:scns`, `rq:failed:scns`, 等 |
| **总计** | **~122** | - |

---

## 🔍 键命名规范

### 系统自定义键

**格式**: `{namespace}:{identifier}`

**规范**:
- `worker:*` - Worker 相关
- `resource:*` - 资源管理相关
- 小写字母 + 下划线
- 避免特殊字符

### RQ 自动生成键

**格式**: `rq:{type}:{name}`

**规范**:
- `rq:queue:*` - 队列
- `rq:job:*` - 任务
- `rq:worker:*` - Worker
- 由 RQ 库自动管理

---

## 🛠️ 常用操作

### 查看所有系统键

```bash
# 查看所有 Worker
redis-cli KEYS "worker:*"

# 查看所有资源缓存
redis-cli KEYS "resource:*"

# 查看所有 RQ 相关键
redis-cli KEYS "rq:*"

# 查看所有键
redis-cli KEYS "*"
```

### 监控资源状态

```bash
# 查看活跃 Worker 数量
redis-cli KEYS "worker:*" | wc -l

# 查看已分配 CPU
redis-cli GET resource:allocated_cpus

# 查看队列长度
redis-cli LLEN rq:queue:scns

# 查看失败任务数量
redis-cli ZCARD rq:failed:scns
```

### 清理操作

```bash
# 清理所有 Worker 注册（谨慎！）
redis-cli DEL $(redis-cli KEYS "worker:*")

# 清理资源缓存
redis-cli DEL resource:allocated_cpus

# 清理 RQ 队列（使用专用脚本）
python scripts/clear_redis_queue.py
```

### 调试操作

```bash
# 查看 Worker 详情
redis-cli HGETALL worker:kunpeng-compute-01

# 查看 Worker TTL
redis-cli TTL worker:kunpeng-compute-01

# 查看任务详情
redis-cli HGETALL rq:job:job_123

# 查看队列中的任务
redis-cli LRANGE rq:queue:scns 0 -1

# 实时监控所有命令
redis-cli MONITOR
```

---

## 📈 数据流程图

### Worker 注册流程

```
Worker 启动
    ↓
HSET worker:{id} {...}  ← 创建注册信息
    ↓
EXPIRE worker:{id} 60   ← 设置 TTL
    ↓
[每 30 秒心跳]
    ↓
HSET worker:{id} last_heartbeat "..."
EXPIRE worker:{id} 60   ← 刷新 TTL
    ↓
Worker 停止 或 超时
    ↓
DEL worker:{id}  或 自动过期
```

### 资源分配流程

```
Scheduler 调度作业
    ↓
GET resource:allocated_cpus  ← 查询已分配 (快速)
    ↓
计算可用资源
    ↓
分配资源
    ↓
INCRBY resource:allocated_cpus {cpus}  ← 更新缓存
    ↓
数据库插入 resource_allocations
    ↓
LPUSH rq:queue:scns job_{id}  ← 加入队列
```

### 任务执行流程

```
Worker 从队列取任务
    ↓
LPOP rq:queue:scns  → job_{id}
    ↓
HSET rq:job:{id} status "started"
    ↓
执行任务
    ↓
完成
    ↓
HSET rq:job:{id} status "finished"
    ↓
ZADD rq:finished:scns {timestamp} job_{id}
    ↓
释放资源
    ↓
DECRBY resource:allocated_cpus {cpus}
    ↓
数据库更新 released=true
```

---

## ⚠️ 注意事项

### 1. TTL 管理

- `worker:*` 键有 60 秒 TTL，需要心跳维持
- 心跳失败会导致 Worker 自动过期（故障自愈）
- 不要手动删除活跃 Worker 的键

### 2. 缓存一致性

- `resource:allocated_cpus` 与数据库可能短暂不一致
- 每 5 分钟自动从数据库同步
- 影响极小（通常 <1%）

### 3. RQ 键管理

- RQ 相关键由 RQ 库自动管理
- 不要手动修改 `rq:*` 键（除非清理）
- 使用 RQ 提供的工具进行操作

### 4. 键命名冲突

- 避免使用 `worker:` 或 `resource:` 前缀创建自定义键
- RQ 键与系统键独立，不会冲突

---

## 📚 相关文档

- [ResourceManager 实现](../core/services/resource_manager.py)
- [WorkerRepository 实现](../core/services/worker_repository.py)
- [Redis 连接管理](../core/redis_client.py)
- [清理脚本](../scripts/clear_redis_queue.py)
- [动态资源管理文档](./DYNAMIC_RESOURCE_MANAGEMENT.md)

---

**最后更新**: 2025-11-11  
**版本**: v4.0 (服务层架构)

