# 资源状态流转分析 - 正常与异常情况

## 📊 状态机

```
        调度          执行开始        完成/失败
[无记录] → [RESERVED] → [ALLOCATED] → [RELEASED]
            ↓              ↓              ↓
         异常1          异常2          正常
```

---

## ✅ 正常流程

### 场景1: 作业正常完成

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | 用户提交作业 | PENDING | (无记录) | 0 |
| T2 | Scheduler 调度 | RUNNING | RESERVED | 0 (不计入) |
| T3 | Worker 开始执行 | RUNNING | ALLOCATED | +N (真正占用) |
| T4 | 作业执行完成 | COMPLETED | RELEASED | -N (释放) |

**资源变化**：
- T1→T2: 无变化（预留不占用）
- T2→T3: 真正占用 N 个 CPU
- T3→T4: 释放 N 个 CPU

**兜底机制**：
- `Scheduler.release_completed()` 定期检查并释放已完成作业的资源
- `scripts/cleanup.py` 清理脚本

---

### 场景2: 作业执行失败

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | Scheduler 调度 | RUNNING | RESERVED | 0 |
| T2 | Worker 开始执行 | RUNNING | ALLOCATED | +N |
| T3 | 作业执行失败 | FAILED | RELEASED | -N |

**资源变化**：与正常完成相同

**兜底机制**：同场景1

---

### 场景3: 手动取消作业

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | Worker 正在执行 | RUNNING | ALLOCATED | N |
| T2 | 用户调用 cancel API | RUNNING | ALLOCATED | N |
| T3 | 终止进程，更新状态 | CANCELLED | RELEASED | -N |

**处理逻辑**：
```python
# api/services/job_service.py
async def cancel_job(job_id: int):
    # 1. 终止进程
    await _kill_job_process(job)
    # 2. 更新作业状态
    await JobRepository.update_job_state(job_id, JobState.CANCELLED)
    # 3. 释放资源
    await JobRepository.release_resource_allocation(job_id)
```

**兜底机制**：
- `Scheduler.release_completed()` 会处理已取消但未释放资源的作业

---

## ⚠️ 异常情况

### 异常1: 调度后、执行前服务崩溃

**场景描述**：Scheduler 创建了 RESERVED 记录并入队，但 Worker 还没来得及执行就服务重启了。

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | Scheduler 调度 | RUNNING | RESERVED | 0 ✅ |
| T2 | 服务崩溃重启 | RUNNING | RESERVED | 0 ✅ |
| T3 | 队列丢失，作业永不执行 | RUNNING | RESERVED | 0 ✅ |

**资源影响**：
- ✅ **无资源泄漏**！RESERVED 状态不计入已分配
- ✅ Redis 缓存正确（为 0）

**问题**：
- ❌ 作业卡在 RUNNING 状态
- ❌ ResourceAllocation 记录永远停在 RESERVED

**是否能识别**：
```sql
-- 可以识别：长期处于 RESERVED 状态的记录
SELECT job_id, allocated_cpus, 
       EXTRACT(EPOCH FROM (NOW() - allocation_time))/60 as minutes
FROM resource_allocations
WHERE status = 'reserved'
  AND allocation_time < NOW() - INTERVAL '5 minutes';
```

**处理方案**：
```python
# 新增清理逻辑（建议）
def cleanup_stale_reservations(max_age_minutes: int = 10):
    """清理长期停留在 RESERVED 状态的资源"""
    threshold = datetime.utcnow() - timedelta(minutes=max_age_minutes)
    
    with sync_db.get_session() as session:
        stale_reservations = (
            session.query(ResourceAllocation)
            .join(Job)
            .filter(
                ResourceAllocation.status == ResourceStatus.RESERVED,
                ResourceAllocation.allocation_time < threshold,
                Job.state == JobState.RUNNING,  # 作业还认为自己在运行
            )
            .all()
        )
        
        for allocation in stale_reservations:
            # 标记作业为失败
            job = allocation.job
            job.state = JobState.FAILED
            job.end_time = datetime.utcnow()
            job.error_msg = "作业预留超时，可能由于队列丢失"
            
            # 释放预留
            allocation.status = ResourceStatus.RELEASED
            allocation.released_time = datetime.utcnow()
        
        session.commit()
```

**兜底状态**：⚠️ 需要手动清理或添加新的清理逻辑

---

### 异常2: Worker 执行中崩溃（进程继续运行）

**场景描述**：Worker 进程崩溃，但作业进程成为孤儿进程继续运行。

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | Worker 执行中 | RUNNING | ALLOCATED | N |
| T2 | Worker 崩溃 | RUNNING | ALLOCATED | N ✅ |
| T3 | 作业进程继续运行 | RUNNING | ALLOCATED | N ✅ |
| T4 | 作业进程结束 | RUNNING ❌ | ALLOCATED ❌ | N ❌ |

**资源影响**：
- ⚠️ **资源泄漏**！作业已结束但记录还是 ALLOCATED
- ❌ Redis 缓存不正确（占用 N，但实际已释放）

**是否能识别**：
```python
# 48小时超时检测（已实现）
def fix_stuck_jobs():
    """处理超过48小时的 RUNNING 作业"""
    threshold = datetime.utcnow() - timedelta(hours=48)
    
    stuck_jobs = session.query(Job).filter(
        Job.state == JobState.RUNNING,
        Job.start_time < threshold
    ).all()
```

**处理方案**：
- ✅ 已实现：`scripts/cleanup.py::fix_stuck_jobs()`
- ✅ 48小时超时检测

**兜底状态**：✅ 有兜底机制（48小时清理）

---

### 异常3: Worker 执行中崩溃（进程被杀死）

**场景描述**：Worker 崩溃且作业进程也被杀死。

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | Worker 执行中 | RUNNING | ALLOCATED | N |
| T2 | Worker 崩溃，进程被杀 | RUNNING | ALLOCATED | N ✅ |
| T3 | 永不完成 | RUNNING ❌ | ALLOCATED ❌ | N ❌ |

**资源影响**：
- ❌ **资源泄漏**！作业已死但记录还是 ALLOCATED
- ❌ Redis 缓存不正确

**处理方案**：
- ✅ 同异常2，48小时清理

**兜底状态**：✅ 有兜底机制（48小时清理）

---

### 异常4: Scheduler 调度但队列满/Redis 故障

**场景描述**：Scheduler 创建了 RESERVED 记录但入队失败。

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | Scheduler 尝试调度 | PENDING | (无记录) | 0 |
| T2 | 创建 RESERVED 记录 | - | RESERVED | 0 |
| T3 | 入队失败（异常） | ? | RESERVED ❌ | 0 |

**问题分析**：
```python
# scheduler/scheduler.py
def _allocate_and_enqueue(self, session, job: Job, cpus: int) -> bool:
    try:
        # 1. 创建资源预留记录
        allocation = ResourceAllocation(...)
        session.add(allocation)
        
        # 2. 更新作业状态
        job.state = JobState.RUNNING
        
        # 3. 提交数据库
        session.flush()  # ← 已提交到数据库
        
        # 4. 加入队列
        self.queue.enqueue(...)  # ← 如果这里失败？
        
        return True
    except Exception as e:
        # 事务会自动回滚 ✅
        return False
```

**实际影响**：
- ✅ **无问题**！如果 `queue.enqueue()` 失败，会抛出异常
- ✅ 事务回滚，RESERVED 记录不会创建
- ✅ Job.state 保持 PENDING

**兜底状态**：✅ 事务保护

---

### 异常5: Redis 缓存丢失/不一致

**场景描述**：Redis 重启或数据丢失，缓存与数据库不一致。

| 数据库实际 | Redis 缓存 | 影响 |
|-----------|-----------|------|
| 10 个 ALLOCATED | 0 (缓存丢失) | ❌ Scheduler 会过度调度 |
| 0 个 ALLOCATED | 10 (缓存未清理) | ❌ Scheduler 不敢调度 |

**是否能识别**：
```python
# 可以识别：对比数据库和缓存
def verify_cache_consistency():
    # 从数据库查询
    db_allocated = _query_allocated_cpus_from_db()
    
    # 从缓存查询
    cache_allocated = cache.get_allocated_cpus()
    
    if db_allocated != cache_allocated:
        logger.error(f"Cache inconsistent! DB: {db_allocated}, Cache: {cache_allocated}")
        return False
    
    return True
```

**处理方案**：
- ✅ 已实现：`ResourceManager.sync_cache_from_db()`
- ✅ Scheduler 守护进程每 5 分钟同步一次

```python
# scheduler/daemon.py
if current_time - self._last_sync_time >= self.sync_interval:
    self.scheduler.sync_resource_cache()  # 每5分钟同步
    self._last_sync_time = current_time
```

**兜底状态**：✅ 有定期同步机制（5分钟）

---

### 异常6: 作业取消但进程杀不死

**场景描述**：调用 cancel API，但进程拒绝终止。

| 时间点 | 操作 | Job.state | ResourceAllocation.status | Redis 缓存 |
|--------|------|-----------|---------------------------|-----------|
| T1 | 作业运行中 | RUNNING | ALLOCATED | N |
| T2 | 调用 cancel API | CANCELLED | RELEASED | -N |
| T3 | 进程继续运行 | CANCELLED ❌ | RELEASED | 0 |

**资源影响**：
- ✅ Redis 缓存已释放（不会阻塞新作业）
- ⚠️ 但进程仍在消耗实际 CPU

**是否能识别**：
- ⚠️ 较难识别（进程不受控制）
- 可以通过 `ps` 命令检查孤儿进程

**处理方案**：
```python
# 改进建议：强制杀死
def kill_process_tree(pid: int, timeout: int = 5):
    # 1. 发送 SIGTERM（已实现）
    os.killpg(os.getpgid(pid), signal.SIGTERM)
    
    # 2. 等待超时
    # ...
    
    # 3. 发送 SIGKILL（已实现）
    os.killpg(os.getpgid(pid), signal.SIGKILL)
```

**兜底状态**：⚠️ 已有 SIGKILL，但极端情况下可能失效

---

## 🛡️ 现有防护机制总结

| 机制 | 作用 | 频率 |
|------|------|------|
| `Scheduler.release_completed()` | 释放已完成但未释放资源的作业 | 每5秒 |
| `ResourceManager.sync_cache_from_db()` | 同步 Redis 缓存与数据库 | 每5分钟 |
| `scripts/cleanup.py::fix_stuck_jobs()` | 清理超过48小时的卡住作业 | 手动/定时 |
| 事务保护 | 防止部分提交 | 自动 |

---

## ⚠️ 尚未处理的异常

### 1. 长期停留在 RESERVED 的记录

**问题**：作业被调度但从未执行（队列丢失）

**建议新增清理逻辑**：
```python
def cleanup_stale_reservations(max_age_minutes: int = 10):
    """清理超过 N 分钟的 RESERVED 记录"""
    # 实现见上文"异常1"
```

**添加位置**：
- `scripts/cleanup.py` 新增函数
- `scheduler/daemon.py` 定期调用

---

### 2. 作业取消但进程不死

**问题**：极端情况下 SIGKILL 可能失效

**建议改进**：
```python
# 监控孤儿进程
def check_orphan_processes():
    """检查所有已取消作业的进程"""
    cancelled_jobs = session.query(Job).filter(
        Job.state.in_([JobState.CANCELLED, JobState.FAILED, JobState.COMPLETED]),
        Job.end_time > datetime.utcnow() - timedelta(hours=1)
    ).all()
    
    for job in cancelled_jobs:
        if job.resource_allocation and job.resource_allocation.process_id:
            pid = job.resource_allocation.process_id
            # 检查进程是否还存在
            if process_exists(pid):
                logger.warning(f"Orphan process {pid} for job {job.id}")
                # 尝试再次杀死
                kill_process_tree(pid)
```

---

### 3. 极端高并发下的缓存不一致

**问题**：5分钟同步间隔可能过长

**建议改进**：
```python
# 方案1: 缩短同步间隔（30秒）
sync_interval: int = 30

# 方案2: 每次调度前先同步
def schedule(self):
    self.resource_manager.sync_cache_from_db()  # 确保数据最新
    # ... 调度逻辑
```

---

## 📊 状态流转完整图

```
用户提交
  ↓
[PENDING, 无记录, cache=0]
  ↓ Scheduler.schedule()
  ↓ 创建预留
  ↓
[RUNNING, RESERVED, cache=0] ← 异常1: 队列丢失 (需清理)
  ↓ queue.enqueue()
  ↓ 异常保护: 失败则回滚
  ↓
[RUNNING, RESERVED, cache=0]
  ↓ Worker.execute()
  ↓ 更新为 allocated
  ↓
[RUNNING, ALLOCATED, cache=N] ← 异常2/3: Worker崩溃 (48h清理)
  ↓ 执行脚本
  ↓
[RUNNING, ALLOCATED, cache=N]
  ↓ 完成 / 失败
  ↓ 释放资源
  ↓
[COMPLETED/FAILED, RELEASED, cache=0]

或者
  ↓ 用户取消
  ↓
[CANCELLED, RELEASED, cache=0] ← 异常6: 进程不死 (需监控)
```

---

## 🎯 改进建议优先级

### 高优先级 ⭐⭐⭐
1. **新增清理 RESERVED 超时记录** - 防止队列丢失导致的资源预留卡住
2. **缩短缓存同步间隔** - 从 5 分钟改为 1-2 分钟

### 中优先级 ⭐⭐
3. **监控孤儿进程** - 检查已取消作业的进程是否真的结束
4. **添加健康检查端点** - 暴露缓存一致性检查结果

### 低优先级 ⭐
5. **添加告警** - 当发现异常状态时发送通知
6. **仪表盘展示** - 可视化各状态的作业数量

---

## 📝 结论

**已处理的异常**：
- ✅ Worker 崩溃（48小时清理）
- ✅ Redis 缓存不一致（5分钟同步）
- ✅ 作业取消（强制杀死进程）
- ✅ 事务失败（自动回滚）

**需要添加处理的异常**：
- ⚠️ RESERVED 状态超时（队列丢失）
- ⚠️ 孤儿进程监控

**整体评估**：
- 新的设计 **显著改善** 了资源泄漏问题
- 大部分异常都有兜底机制
- 建议添加 RESERVED 超时清理以完善防护

