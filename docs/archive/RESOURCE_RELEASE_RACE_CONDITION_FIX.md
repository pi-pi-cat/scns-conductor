# 资源释放时序竞争问题修复

## 问题描述

用户报告：在 worker 执行 `self._release_resources(job_id)` 之前，`released` 值就已经是 `True` 了。

## 根本原因

这是一个**时序竞争问题（Race Condition）**，由 Worker 和 Scheduler 之间的并发操作导致。

### 问题流程图

```
时间轴：

Worker 进程:
  ├─ 执行任务 (_run)
  ├─ 更新状态为 COMPLETED (_update_completion)  ← 第 1 步
  │     ↓
  │     Job.state = COMPLETED
  │     released = False (还未释放)
  │     
  ├─ [等待...]                                    ← 第 2 步：还没到 finally 块
  │
  └─ 释放资源 (_release_resources)               ← 第 3 步：但已经是 True！

Scheduler 守护进程 (每 5 秒运行):
  └─ release_completed()                          ← 第 2.5 步：抢先释放
        ↓
        检测到: Job.state = COMPLETED 且 released = False
        ↓
        自动释放: released = True ✓
```

### 原始代码（有问题）

```python
# worker/executor.py (之前)
def execute(self, job_id: int):
    try:
        exit_code = self._run(job)
        self._update_completion(job_id, exit_code)  # ← 设置 state = COMPLETED
    except Exception as e:
        self._mark_failed(job_id, str(e))
    finally:
        self._release_resources(job_id)  # ← 但 scheduler 可能已经释放了！
```

### Scheduler 自动释放机制

```python
# scheduler/scheduler.py
def release_completed(self) -> int:
    """释放已完成作业的资源（兜底机制）"""
    # 查询已完成但未释放资源的作业
    stale_allocations = (
        session.query(ResourceAllocation)
        .join(Job)
        .filter(
            ~ResourceAllocation.released,
            Job.state.in_([JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]),
        )
        .all()
    )
    
    for allocation in stale_allocations:
        allocation.released = True  # ← 这里被提前释放了！
```

```python
# scheduler/daemon.py
def run(self):
    while not self._stop_event.is_set():
        self.scheduler.schedule()
        self.scheduler.release_completed()  # ← 每 5 秒运行一次
        self._stop_event.wait(5)
```

## 解决方案

**调整执行顺序：先释放资源，再更新状态**

### 修复后的代码

```python
# worker/executor.py (修复后)
def execute(self, job_id: int):
    exit_code = None
    error_occurred = False
    error_msg = None
    
    try:
        job = self._load_job(job_id)
        exit_code = self._run(job)
    except Exception as e:
        error_occurred = True
        error_msg = str(e)
    finally:
        # ✅ 重要：先释放资源，再更新状态
        # 避免 scheduler 的 release_completed() 抢先释放资源
        self._release_resources(job_id)
        
        # 更新最终状态
        if error_occurred:
            self._mark_failed(job_id, error_msg)
        elif exit_code is not None:
            self._update_completion(job_id, exit_code)
```

### 修复后的流程

```
Worker 进程:
  ├─ 执行任务 (_run)
  ├─ 释放资源 (_release_resources)               ← 第 1 步：先释放
  │     ↓
  │     released = True ✓
  │
  └─ 更新状态为 COMPLETED (_update_completion)   ← 第 2 步：再更新状态
        ↓
        Job.state = COMPLETED
        released = True (已经释放)

Scheduler 守护进程 (每 5 秒运行):
  └─ release_completed()
        ↓
        检测到: Job.state = COMPLETED 且 released = True
        ↓
        跳过：资源已经释放 ✓
```

## 为什么这样修复？

### 方案对比

| 方案 | 优点 | 缺点 |
|------|------|------|
| **先释放资源，再更新状态** ✅ | 简单、无副作用、完全避免竞争 | 无 |
| 在一个事务中同时更新 | 原子性好 | 需要重构代码，复杂度高 |
| 禁用 scheduler 自动释放 | 简单 | 失去兜底机制，可能造成资源泄漏 |
| 增加宽限期 | 减少竞争概率 | 不能完全解决，治标不治本 |

### 为什么先释放资源是安全的？

1. **资源已经分配**：任务执行时资源已经被占用
2. **状态仍是 RUNNING**：scheduler 不会重复调度
3. **释放是幂等的**：即使失败，scheduler 会兜底
4. **状态更新失败也安全**：资源已经释放，不会泄漏

## 测试验证

### 验证点

1. ✅ Worker 能正确释放资源
2. ✅ Scheduler 不会重复释放资源
3. ✅ 日志中不再出现 "No unreleased allocation found"
4. ✅ 资源利用率统计准确

### 测试步骤

```bash
# 1. 启动 scheduler
python -m scheduler.main

# 2. 启动 worker
python -m worker.main

# 3. 提交快速任务
curl -X POST http://localhost:8000/api/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "script": "#!/bin/bash\necho \"Quick task\"\nsleep 1",
    "cpus": 1,
    "time_limit": 1
  }'

# 4. 观察日志
# Worker 日志应该显示：
# ♻️  Released X CPUs for job Y
# 
# Scheduler 日志不应该显示：
# ♻️  Released orphan resources...
```

### 预期结果

- Worker 日志：正常释放资源
- Scheduler 日志：不会触发兜底释放
- 数据库：`released = True`, `released_time` 有值

```sql
-- 检查资源释放情况
SELECT 
    job_id, 
    allocated_cpus, 
    released, 
    allocation_time,
    released_time,
    (released_time - allocation_time) as duration
FROM resource_allocations 
ORDER BY id DESC 
LIMIT 10;
```

## 相关文件

- `worker/executor.py` - 修改了 `execute()` 方法的执行顺序
- `scheduler/scheduler.py` - `release_completed()` 兜底机制（未修改）
- `scheduler/daemon.py` - 每 5 秒运行一次（未修改）

## 日期

2025-11-11

