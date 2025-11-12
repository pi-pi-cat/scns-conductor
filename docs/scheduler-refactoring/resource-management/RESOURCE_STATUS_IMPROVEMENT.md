# 资源状态管理改进

## 📋 问题背景

### 原有问题

在原有设计中，资源分配的时机存在问题：

```
时间线：
T1: Scheduler 创建 ResourceAllocation (released=False) ← 资源已"占用"
T2: Scheduler 更新 Job.state = RUNNING
T3: Scheduler 将作业入队
--- 如果在这里服务崩溃/重启 ---
T4: Worker 从队列取出作业（但队列可能已丢失）
T5: Worker 真正开始执行作业

问题：如果在 T3-T4 之间出问题，资源会一直被占用！
```

**核心问题**：
- 调度器在调度时就标记资源为已占用（`released=False`）
- 但作业可能还没有真正开始运行
- 如果服务重启或队列丢失，资源会永久泄漏
- 无法区分"已预留"和"真正在运行"的资源

## ✅ 改进方案

### 引入资源状态机制

为 `ResourceAllocation` 表增加 `status` 字段，明确区分资源的三种状态：

```python
class ResourceStatus(str, Enum):
    RESERVED = "reserved"    # 预留：调度器已分配，但Worker尚未开始执行
    ALLOCATED = "allocated"  # 已分配：Worker正在执行，资源实际占用
    RELEASED = "released"    # 已释放：作业完成，资源已回收
```

### 新的资源分配流程

```
阶段1: Scheduler 调度作业
  ├─ 创建 ResourceAllocation (status='reserved')  ← 仅预留
  ├─ 更新 Job.state = RUNNING
  └─ 入队作业
  
阶段2: Worker 开始执行
  ├─ 从队列取出作业
  ├─ 更新 ResourceAllocation (status='allocated')  ← 真正占用
  ├─ 更新 Redis 缓存（现在才计入已分配）
  └─ 执行作业脚本
  
阶段3: 作业完成
  ├─ 更新 ResourceAllocation (status='released')
  ├─ 更新 Redis 缓存（释放资源）
  └─ 更新作业最终状态
```

### 关键改进点

1. **预留不占用真实资源**
   - `reserved` 状态的资源不计入已分配
   - 只有 `allocated` 状态才算真正占用
   - 避免了预留但未执行导致的资源泄漏

2. **资源统计更准确**
   ```python
   # ResourceManager 只统计 allocated 状态
   def _query_allocated_cpus_from_db(self) -> int:
       return session.query(func.sum(ResourceAllocation.allocated_cpus))\
           .filter(ResourceAllocation.status == ResourceStatus.ALLOCATED)\
           .scalar() or 0
   ```

3. **智能释放机制**
   ```python
   # 只有真正分配的资源才需要释放缓存
   if old_status == ResourceStatus.ALLOCATED:
       self.resource_manager.release(cpus)
   ```

## 📊 状态转换图

```
      调度          执行开始        完成/失败/取消
[pending] → [reserved] → [allocated] → [released]
              ↓                          ↑
              └──────────────────────────┘
                 (异常情况：直接释放预留)
```

## 🔧 实施细节

### 1. 数据库模型变更

```python
class ResourceAllocation(SQLModel, table=True):
    # 新增字段
    status: str = Field(
        default="reserved",
        max_length=20,
        index=True,
        description="资源状态：reserved/allocated/released",
    )
    
    # 保留旧字段以兼容
    released: bool = Field(
        default=False, 
        description="[已废弃]使用status字段代替"
    )
```

### 2. Scheduler 变更

```python
def _allocate_and_enqueue(self, session, job: Job, cpus: int) -> bool:
    # 1. 创建资源预留记录（status=reserved）
    allocation = ResourceAllocation(
        job_id=job.id,
        allocated_cpus=cpus,
        status=ResourceStatus.RESERVED,  # 预留状态
        # ...
    )
    
    # 2. 不在这里更新资源缓存（资源还没有真正分配）
    # self.resource_manager.allocate(cpus)  # ❌ 删除
    
    # 3. 入队作业
    self.queue.enqueue("worker.executor.execute_job", job.id)
```

### 3. Worker 变更

```python
def execute(self, job_id: int):
    try:
        job = self._load_job(job_id)
        
        # ✅ 在真正开始执行前，将资源状态从 reserved 更新为 allocated
        self._mark_resources_allocated(job_id, job.allocated_cpus)
        
        # 执行作业
        exit_code = self._run(job)
    finally:
        self._release_resources(job_id)

def _mark_resources_allocated(self, job_id: int, cpus: int):
    """将资源状态从 reserved 更新为 allocated"""
    allocation.status = ResourceStatus.ALLOCATED
    session.commit()
    
    # 现在才真正占用资源
    self.resource_manager.allocate(cpus)
```

### 4. 资源释放变更

```python
def _release_resources(self, job_id: int):
    allocation = session.query(ResourceAllocation)\
        .filter(
            ResourceAllocation.job_id == job_id,
            ResourceAllocation.status != ResourceStatus.RELEASED
        ).first()
    
    if allocation:
        old_status = allocation.status
        allocation.status = ResourceStatus.RELEASED
        
        # 只有真正分配的资源才需要释放缓存
        if old_status == ResourceStatus.ALLOCATED:
            self.resource_manager.release(cpus)
```

## 📝 数据库变更

本改进需要修改数据库表结构：

**ResourceAllocation 表变更**：
- ✅ 新增 `status` 字段 (VARCHAR(20), NOT NULL, DEFAULT 'reserved')
- ❌ 删除 `released` 字段（不再需要）
- ✅ 创建索引 `idx_resource_allocation_status`

**如果是全新部署**：
直接使用新的模型创建表即可。

**如果已有数据**：
需要手动迁移数据或清空表重新开始。

## 🎯 优势总结

### 1. 防止资源泄漏
- 预留状态不计入真实占用
- 服务重启不会导致资源永久占用

### 2. 更准确的资源统计
- 只统计真正运行的作业
- 调度决策更精准

### 3. 更好的可观测性
- 可以区分"等待执行"和"正在执行"
- 便于问题排查和监控

### 4. 清晰的状态管理
- 使用枚举避免硬编码
- 状态转换清晰明确
- 易于理解和维护

## 📈 监控建议

```sql
-- 查看各状态的资源分配情况
SELECT 
    status,
    COUNT(*) as job_count,
    SUM(allocated_cpus) as total_cpus
FROM resource_allocations
GROUP BY status;

-- 查找长期处于 reserved 状态的异常记录
SELECT 
    job_id,
    allocated_cpus,
    allocation_time,
    EXTRACT(EPOCH FROM (NOW() - allocation_time))/60 as minutes_in_reserved
FROM resource_allocations
WHERE status = 'reserved'
  AND allocation_time < NOW() - INTERVAL '5 minutes';
```

## 🔄 如果需要重建表

```sql
-- 删除旧表（谨慎！会丢失数据）
DROP TABLE resource_allocations;

-- 重新创建表（通过应用自动创建）
# 重启应用，SQLModel 会自动创建新表结构
```

## 📚 相关文档

- [资源管理设计](./RESOURCE_MANAGEMENT.md)
- [架构文档](./ARCHITECTURE.md)
- [故障容错](./archive/FAULT_TOLERANCE_SUMMARY.md)

