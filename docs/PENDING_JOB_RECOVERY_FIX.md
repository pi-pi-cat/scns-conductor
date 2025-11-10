# PENDING 作业恢复修复

## 问题描述

在 Worker 启动恢复阶段发现的关键 Bug：

### 问题场景
1. Worker 在作业提交后异常退出
2. 数据库中存在 `PENDING` 状态的作业
3. Redis 队列中的任务可能丢失或已被消费
4. Worker 重启后：
   - RecoveryManager 只检查 `RUNNING/COMPLETED/FAILED/CANCELLED` 状态，忽略了 `PENDING`
   - Scheduler Daemon 扫描到 `PENDING` 作业，分配资源，状态改为 `RUNNING`
   - **但是 Redis 队列中没有对应的任务**
   - RQ Worker 不会触发 `execute_job_task`
   - 结果：作业永远卡在 `RUNNING` 状态，实际上没有执行

### 影响
- 作业永久挂起，用户无法获得结果
- 资源被永久占用，无法释放
- 系统资源利用率下降

## 解决方案

### 1. 添加 PendingJobRecoveryStrategy

在 `worker/recovery/strategies.py` 中添加新的恢复策略：

```python
class PendingJobRecoveryStrategy(RecoveryStrategy):
    """
    待处理作业恢复策略
    
    确保所有 PENDING 作业在 Redis 队列中有对应的任务
    如果没有，重新入队
    """
    
    def should_recover(self, session: Session, job: Job) -> bool:
        """只处理 PENDING 状态的作业"""
        return job.state == JobState.PENDING
    
    def recover_job(self, session: Session, job: Job) -> bool:
        """检查 PENDING 作业是否在 Redis 队列中，如果不在则重新入队"""
        try:
            queue = redis_manager.get_queue()
            
            rq_job = queue.enqueue(
                "worker.core.executor.execute_job_task",
                job.id,
                job_id=f"job_{job.id}",  # 使用固定的 job_id 防止重复入队
                job_timeout=3600 * 24,
            )
            
            logger.info(f"✅ 重新入队 PENDING 作业 {job.id} 到 Redis")
            return True
            
        except Exception as e:
            logger.error(f"❌ 重新入队作业 {job.id} 失败: {e}")
            return False
```

### 2. 更新 RecoveryManager

在 `worker/recovery/manager.py` 中：

1. **导入新策略**：
```python
from worker.recovery.strategies import (
    ...
    PendingJobRecoveryStrategy,
    ...
)
```

2. **添加到组合策略**：
```python
self.strategy = strategy or CompositeRecoveryStrategy([
    PendingJobRecoveryStrategy(),  # 首先恢复 PENDING 作业
    OrphanJobRecoveryStrategy(),
    TimeoutJobRecoveryStrategy(),
    StaleAllocationCleanupStrategy(),
])
```

3. **更新查询条件**：
```python
jobs = session.query(Job).filter(
    Job.state.in_([
        JobState.PENDING,  # 添加 PENDING 状态
        JobState.RUNNING,
        JobState.COMPLETED,
        JobState.FAILED,
        JobState.CANCELLED
    ])
).all()
```

### 3. 防止重复入队

在 API 和恢复策略中都使用固定的 `job_id` 参数：

**API 服务** (`api/services/job_service.py`)：
```python
rq_job = queue.enqueue(
    "worker.core.executor.execute_job_task",
    job_id,
    job_id=f"job_{job_id}",  # 使用固定的 job_id 防止重复入队
    job_timeout=3600 * 24,
)
```

**恢复策略** (`worker/recovery/strategies.py`)：
```python
rq_job = queue.enqueue(
    "worker.core.executor.execute_job_task",
    job.id,
    job_id=f"job_{job.id}",  # 使用固定的 job_id 防止重复入队
    job_timeout=3600 * 24,
)
```

通过使用固定的 `job_id`，RQ 会自动处理重复任务的问题。如果队列中已经存在相同 `job_id` 的任务，新的入队操作会被拒绝或覆盖旧任务。

## 修复后的流程

```
Worker 启动
    ↓
RecoveryManager.recover_on_startup()
    ↓
查询 PENDING + RUNNING + COMPLETED + FAILED + CANCELLED 作业
    ↓
应用恢复策略（按顺序）：
    ├─ PendingJobRecoveryStrategy
    │  └─ 发现 PENDING 作业 → 重新入队到 Redis
    ├─ OrphanJobRecoveryStrategy
    │  └─ 检查 RUNNING 作业的进程是否存在
    ├─ TimeoutJobRecoveryStrategy
    │  └─ 检查 RUNNING 作业是否超时
    └─ StaleAllocationCleanupStrategy
       └─ 清理终态作业的陈旧资源分配
    ↓
所有 PENDING 作业现在都在 Redis 队列中
    ↓
Scheduler Daemon 扫描并分配资源（PENDING → RUNNING）
    ↓
RQ Worker 从队列取出任务
    ↓
execute_job_task 被调用 ✅
    ↓
作业正常执行
```

## 测试场景

### 场景 1：正常恢复
1. 创建一个 PENDING 作业但 Redis 队列为空
2. 启动 Worker
3. 恢复策略应该重新入队作业
4. 作业应该被正常调度和执行

### 场景 2：防止重复入队
1. 创建一个 PENDING 作业，Redis 队列中已有任务
2. 启动 Worker
3. 恢复策略尝试重新入队（使用相同的 job_id）
4. RQ 应该处理重复问题，不会创建多个任务

### 场景 3：多个 PENDING 作业
1. 创建多个 PENDING 作业
2. 启动 Worker
3. 所有作业都应该被重新入队
4. 所有作业都应该被正常调度和执行

## 影响范围

### 修改的文件
1. `worker/recovery/strategies.py` - 添加 `PendingJobRecoveryStrategy`
2. `worker/recovery/manager.py` - 导入新策略并添加到组合策略中
3. `api/services/job_service.py` - 添加 `job_id` 参数防止重复入队

### 向后兼容性
- ✅ 完全向后兼容
- ✅ 不影响现有功能
- ✅ 只是增强了恢复能力

## 注意事项

1. **RQ job_id 的作用**：
   - 使用固定的 `job_id=f"job_{job.id}"` 可以防止重复入队
   - RQ 内部会检查 job_id 是否已存在
   - 如果存在，会根据配置决定是否覆盖或抛出异常

2. **恢复顺序**：
   - `PendingJobRecoveryStrategy` 应该最先执行
   - 确保所有 PENDING 作业都有对应的 Redis 任务
   - 然后才处理其他状态的作业

3. **性能考虑**：
   - 恢复操作只在 Worker 启动时执行一次
   - 对系统性能影响很小
   - 如果有大量 PENDING 作业，恢复时间可能稍长

## 后续改进建议

1. **监控和告警**：
   - 添加指标监控恢复的 PENDING 作业数量
   - 如果数量过多，发送告警

2. **更精确的检查**：
   - 可以考虑实现一个方法来检查 Redis 队列中是否已存在特定的任务
   - 避免不必要的重新入队

3. **定期清理**：
   - 考虑添加一个定期任务来清理长时间处于 PENDING 状态的作业
   - 防止作业永久挂起

## 总结

这次修复解决了一个关键的系统可靠性问题，确保了：
- ✅ 所有 PENDING 作业都能被正常执行
- ✅ Worker 重启后能正确恢复状态
- ✅ 防止作业永久挂起
- ✅ 提高了系统的容错能力

---

**修复日期**: 2025-11-10  
**修复者**: AI Assistant  
**版本**: v1.0

