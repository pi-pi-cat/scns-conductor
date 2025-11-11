# 资源管理设计

## 🎯 设计原则

**核心思想**：**数据库是资源状态的唯一真实源**

### 为什么不使用单例模式的 ResourceManager？

#### ❌ 错误方案：进程内单例

```python
@singleton
class ResourceManager:
    def __init__(self):
        self._used_cpus = 0  # 这个状态只在当前进程有效！
```

**问题**：
- Scheduler 进程有自己的实例
- Worker-1 进程有自己的实例
- Worker-2 进程有自己的实例
- **它们互相不知道对方的存在！状态完全不一致！**

#### ✅ 正确方案：数据库作为唯一真实源

```python
# 每次调度时从数据库查询当前资源使用情况
allocated = db.query(
    "SELECT SUM(allocated_cpus) FROM resource_allocation "
    "WHERE released = false"
)
available = TOTAL_CPUS - allocated
```

**优势**：
- ✅ 所有进程看到的是同一份数据
- ✅ 数据库事务保证一致性
- ✅ 无需额外的同步机制
- ✅ 状态持久化，重启不丢失

---

## 🏗️ 架构设计

### 资源状态存储

```
PostgreSQL - resource_allocation 表
┌─────────┬──────────┬───────────────┬──────────┐
│ job_id  │ cpus     │ released      │ node     │
├─────────┼──────────┼───────────────┼──────────┤
│ 1       │ 8        │ false         │ node-01  │
│ 2       │ 4        │ false         │ node-01  │
│ 3       │ 16       │ true          │ node-01  │
└─────────┴──────────┴───────────────┴──────────┘

当前已用: SELECT SUM(cpus) WHERE released=false
         = 8 + 4 = 12 CPUs
```

### 工作流程

```
1. Scheduler 调度
   ↓
2. 查询: SELECT SUM(allocated_cpus) 
   FROM resource_allocation 
   WHERE released = false
   ↓
3. 计算: available = TOTAL - allocated
   ↓
4. 判断: if available >= required
   ↓
5. 分配:
   - INSERT INTO resource_allocation (...)
   - UPDATE job SET state = RUNNING
   - COMMIT 事务
   ↓
6. 入队: enqueue(job_id)
   ↓
7. Worker 执行作业
   ↓
8. 释放:
   - UPDATE resource_allocation SET released = true
   - COMMIT 事务
```

---

## 💡 核心实现

### Scheduler 调度时分配资源

```python
def schedule(self):
    with db.session() as session:
        # 1. 查询当前已分配资源
        allocated = session.query(
            func.sum(ResourceAllocation.allocated_cpus)
        ).filter(
            ResourceAllocation.released == False
        ).scalar() or 0
        
        available = TOTAL_CPUS - allocated
        
        # 2. 查询待调度作业
        pending_jobs = session.query(Job).filter(
            Job.state == PENDING
        ).order_by(Job.submit_time).all()
        
        # 3. 尝试调度
        for job in pending_jobs:
            if available >= job.required_cpus:
                # 创建分配记录
                allocation = ResourceAllocation(
                    job_id=job.id,
                    allocated_cpus=job.required_cpus,
                    released=False
                )
                session.add(allocation)
                
                # 更新作业状态
                job.state = RUNNING
                
                # 提交事务
                session.flush()
                
                # 入队
                queue.enqueue("execute_job", job.id)
                
                available -= job.required_cpus
        
        session.commit()
```

### Worker 执行完成后释放资源

```python
def _release_resources(self, job_id):
    with db.session() as session:
        allocation = session.query(ResourceAllocation).filter(
            ResourceAllocation.job_id == job_id,
            ResourceAllocation.released == False
        ).first()
        
        if allocation:
            # 标记为已释放
            allocation.released = True
            allocation.released_time = datetime.utcnow()
            session.commit()
```

---

## 🔒 一致性保证

### 数据库事务

使用数据库事务保证操作的原子性：

```python
with db.session() as session:
    # 所有操作在一个事务中
    # 查询
    # 插入
    # 更新
    session.commit()  # 全部成功，或全部回滚
```

### 并发控制

PostgreSQL 的 MVCC（多版本并发控制）机制自动处理并发：

- 每个事务看到的是一致的快照
- 不需要显式加锁
- 性能足够好

### 如果需要更强的一致性

可以使用 `SELECT FOR UPDATE`：

```python
# 锁定行，防止并发修改
allocated = session.query(
    func.sum(ResourceAllocation.allocated_cpus)
).filter(
    ResourceAllocation.released == False
).with_for_update().scalar()
```

**注意**：通常不需要，事务隔离级别已经足够。

---

## 📊 性能分析

### 查询开销

每次调度需要执行：
```sql
SELECT SUM(allocated_cpus) FROM resource_allocation WHERE released = false;
```

**性能**：
- 表中行数：通常 < 1000（运行中的作业数）
- 查询时间：< 10ms
- 索引优化：在 `released` 字段上建立索引

### 优化建议

如果性能成为瓶颈：

1. **添加索引**：
```sql
CREATE INDEX idx_resource_allocation_released 
ON resource_allocation(released) 
WHERE released = false;
```

2. **定期清理**：
```sql
-- 删除旧的已释放记录（保留最近7天）
DELETE FROM resource_allocation 
WHERE released = true 
AND released_time < NOW() - INTERVAL '7 days';
```

3. **如果仍不够**：升级到方案2（Redis）

---

## 🛡️ 故障处理

### Worker 崩溃

**问题**：Worker 崩溃，作业未能释放资源

**解决**：Scheduler 的兜底机制

```python
def release_completed(self):
    """检查已完成但未释放的作业"""
    with db.session() as session:
        stale = session.query(ResourceAllocation).join(Job).filter(
            ResourceAllocation.released == False,
            Job.state.in_([COMPLETED, FAILED, CANCELLED])
        ).all()
        
        for alloc in stale:
            alloc.released = True
            # 资源自动回收
```

Scheduler 每 5 秒检查一次，自动释放孤儿资源。

### 数据库连接失败

**问题**：数据库临时不可用

**解决**：
- Scheduler 和 Worker 会记录错误日志
- 等待数据库恢复后自动重连
- 未完成的作业保留在数据库中，恢复后继续处理

---

## 🔄 与其他方案对比

| 方案 | 复杂度 | 性能 | 一致性 | 适用场景 |
|------|--------|------|--------|----------|
| **方案1: 数据库**（当前） | ⭐ 简单 | ⭐⭐⭐ 好 | ⭐⭐⭐⭐⭐ 完美 | 单机/小集群 |
| 方案2: Redis | ⭐⭐⭐ 复杂 | ⭐⭐⭐⭐⭐ 极好 | ⭐⭐⭐⭐ 好 | 大规模集群 |
| 方案3: 中心服务 | ⭐⭐⭐⭐ 很复杂 | ⭐⭐⭐ 一般 | ⭐⭐⭐⭐ 好 | 复杂调度 |

**当前选择理由**：
- ✅ 最简单 - 无需额外组件
- ✅ 足够可靠 - 事务保证一致性
- ✅ 易于理解 - 新人友好
- ✅ 性能足够 - 中小规模完全够用

---

## 🚀 未来扩展

### 何时需要升级到 Redis？

**指标**：
- 节点数 > 100
- 并发调度 > 1000 jobs/min
- 调度延迟 > 5 秒

**升级方案**：
```python
# 使用 Redis 缓存分配状态
redis.set("cluster:used_cpus", allocated)

# 数据库作为持久化备份
db.insert(ResourceAllocation(...))
```

### 多节点集群

当前设计已支持多节点：
- 每个节点有自己的 Scheduler
- 需要确保只有一个 Scheduler 运行（使用分布式锁）

```python
# 使用 Redis 分布式锁
with redis_lock("scheduler_lock"):
    schedule()
```

---

## 📝 最佳实践

### 1. 定期清理历史数据

```sql
-- 每周执行
DELETE FROM resource_allocation 
WHERE released = true 
AND released_time < NOW() - INTERVAL '7 days';
```

### 2. 监控资源利用率

```python
def get_utilization():
    allocated = query_allocated()
    return (allocated / TOTAL_CPUS) * 100
```

记录到监控系统，及时发现异常。

### 3. 数据库索引

确保有以下索引：
```sql
CREATE INDEX idx_ra_released ON resource_allocation(released);
CREATE INDEX idx_ra_job_id ON resource_allocation(job_id);
CREATE INDEX idx_job_state ON job(state);
```

---

## 🎯 总结

**核心设计**：
- 数据库是资源状态的唯一真实源
- 事务保证一致性
- 简单可靠，易于维护

**优势**：
- ✅ 无进程间状态同步问题
- ✅ 无单例模式的陷阱
- ✅ 无死锁风险
- ✅ 自动故障恢复

**适用场景**：
- 单机部署
- 小到中型集群（< 100 节点）
- 对一致性要求高

---

**版本**: v2.0  
**设计日期**: 2025-11-11  
**状态**: ✅ 生产就绪

