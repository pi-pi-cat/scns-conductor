# Worker 容错机制文档

## 📋 问题分析

### 可能的故障场景

1. **Worker 进程崩溃**
   - 系统 OOM 导致进程被杀
   - 未捕获的异常导致进程退出
   - 硬件故障导致服务器宕机

2. **网络中断**
   - 与数据库的连接断开
   - 与 Redis 的连接断开

3. **作业执行异常**
   - 作业脚本死循环
   - 作业超时
   - 作业进程被手动杀死

### 核心问题

**Q1**: Worker 异常退出时，正在运行的作业会怎样？
**A1**: 作业进程会成为"孤儿进程"，继续运行但无人管理

**Q2**: 重启 Worker 后会发生什么？
**A2**: 如果没有恢复机制，这些作业会永远保持 RUNNING 状态

**Q3**: 会不会重复执行已完成的作业？
**A3**: 不会，因为作业状态存储在数据库中

---

## ✅ 解决方案：多层容错机制

### 1. 启动时状态恢复

#### 机制说明

Worker 启动时自动执行恢复检查：

```python
# worker/main.py
def main():
    # ... 初始化 ...
    
    # 关键：执行故障恢复
    recovery_manager = RecoveryManager()
    recovery_manager.recover_on_startup()
    
    # ... 启动 Worker ...
```

#### 恢复流程

```
Worker 启动
    ↓
查询所有 RUNNING 状态的作业
    ↓
对每个作业：
    ├─ 检查进程是否存在 (os.kill(pid, 0))
    │
    ├─ 进程存在？
    │  ├─ 是 → 保持 RUNNING 状态（进程还在运行）
    │  └─ 否 → 标记为 FAILED + 释放资源（孤儿进程）
    ↓
记录日志并继续启动
```

#### 代码示例

```python
def recover_on_startup(self):
    """Worker 启动时执行恢复"""
    running_jobs = session.query(Job).filter(
        Job.state == JobState.RUNNING
    ).all()
    
    for job in running_jobs:
        if not self._is_job_process_alive(job):
            # 进程不存在，标记为失败
            self._mark_job_as_failed_on_recovery(job)

def _is_job_process_alive(self, job):
    """检查进程是否存活"""
    try:
        os.kill(allocation.process_id, 0)  # 信号0不会真正发送
        return True
    except OSError:
        return False  # 进程不存在
```

---

### 2. 进程追踪

#### 存储进程 ID

在作业执行时，将进程 ID 存储到数据库：

```python
# worker/executor.py
def _run_job(self, job: Job):
    process = subprocess.Popen(['/bin/bash', script_path], ...)
    
    # 关键：存储进程ID到数据库
    self._store_process_id(job.id, process.pid)
    
    return process.wait()

def _store_process_id(self, job_id: int, pid: int):
    """存储进程ID到资源分配表"""
    allocation = session.query(ResourceAllocation).filter(
        ResourceAllocation.job_id == job_id
    ).first()
    
    if allocation:
        allocation.process_id = pid
        session.commit()
```

#### 数据库表结构

```sql
-- resource_allocations 表
CREATE TABLE resource_allocations (
    id BIGINT PRIMARY KEY,
    job_id BIGINT UNIQUE,
    allocated_cpus INTEGER,
    node_name VARCHAR(255),
    process_id INTEGER,  -- 关键字段：存储进程ID
    released BOOLEAN,
    ...
);
```

---

### 3. 幂等性保证

#### 资源释放幂等性

```python
def release_resources(self, job_id: int):
    """释放资源（幂等操作）"""
    allocation = session.query(ResourceAllocation).filter(
        ResourceAllocation.job_id == job_id,
        ResourceAllocation.released == False  # 只释放未释放的
    ).first()
    
    if allocation:
        allocation.released = True
        allocation.released_time = datetime.utcnow()
        session.commit()
    
    # 多次调用不会出错
```

#### 作业取消幂等性

```python
async def cancel_job(job_id: int):
    """取消作业（幂等操作）"""
    job = await get_job(job_id)
    
    # 已经是终态，直接返回成功
    if job.state in [JobState.COMPLETED, JobState.FAILED, JobState.CANCELLED]:
        return  # 幂等：不报错
    
    # 执行取消逻辑
    job.state = JobState.CANCELLED
    await session.commit()
```

---

### 4. RQ 任务重试配置

#### 不重试策略

对于作业执行任务，**不应该自动重试**：

```python
# worker/executor.py
from rq.decorators import job

@job('scns_jobs', timeout='24h', result_ttl=86400)
def execute_job_task(job_id: int):
    """
    RQ 任务入口
    
    注意：此任务失败后不会自动重试
    原因：作业可能已经部分执行，重试会导致重复执行
    """
    executor = JobExecutor()
    executor.execute_job(job_id)
```

#### 为什么不重试？

| 场景 | 自动重试的问题 | 正确处理方式 |
|------|----------------|--------------|
| 作业执行到一半 Worker 崩溃 | 重试会重新执行，可能造成重复 | 标记为 FAILED，用户决定是否重新提交 |
| 数据库临时不可用 | RQ 重试可能成功 | Worker 启动时恢复检查会处理 |
| 作业脚本有 bug | 重试无意义，会一直失败 | 标记为 FAILED，用户修复脚本后重新提交 |

---

### 5. 定期健康检查

#### 后台监控（可选）

可以添加一个定期检查孤儿作业的后台任务：

```python
# scripts/monitor_orphan_jobs.py
from worker.recovery import check_orphan_jobs

def monitor():
    """每5分钟检查一次孤儿作业"""
    while True:
        orphan_ids = check_orphan_jobs()
        if orphan_ids:
            logger.warning(f"发现孤儿作业: {orphan_ids}")
            # 可以发送告警
        time.sleep(300)
```

---

## 📊 故障场景处理矩阵

| 故障场景 | 作业状态 | 进程状态 | 恢复后的行为 | 资源释放 |
|---------|---------|---------|-------------|---------|
| Worker 正常关闭 | RUNNING | 被终止 | 标记为 FAILED | ✅ 释放 |
| Worker 崩溃 | RUNNING | 继续运行或已结束 | 检查进程，不存在则标记 FAILED | ✅ 释放 |
| 服务器宕机 | RUNNING | 已结束 | 重启后标记为 FAILED | ✅ 释放 |
| 作业正常完成 | COMPLETED | 已结束 | 无需处理 | ✅ 已释放 |
| 作业超时 | FAILED | 被杀死 | 无需处理 | ✅ 已释放 |
| 数据库连接中断 | 取决于时机 | 可能运行 | 恢复连接后检查 | 视情况而定 |

---

## 🔍 详细示例

### 示例 1：Worker 异常退出

#### 场景描述

```
T0: 用户提交作业 Job-001
T1: Worker 开始执行，创建进程 PID=12345
T2: Worker 进程崩溃（OOM）
T3: 作业进程 12345 继续运行或已结束
T4: 重启 Worker
```

#### 系统行为

```
T4: Worker 启动
    ↓
[恢复检查]
    ├─ 查询 Job-001, state=RUNNING
    ├─ 检查进程 12345 是否存在
    ├─ os.kill(12345, 0)
    │
    ├─ 进程不存在
    │  ├─ Job-001.state = FAILED
    │  ├─ Job-001.error_msg = "Worker 异常退出导致作业中断"
    │  ├─ Job-001.exit_code = "-999:0"
    │  └─ 释放 CPU 资源
    │
    └─ 日志记录
       "将孤儿作业 Job-001 标记为 FAILED"

[正常启动]
    继续启动 Worker，处理新作业
```

### 示例 2：进程仍在运行

```
T0: 提交长时间运行的作业 Job-002
T1: Worker 开始执行，PID=99999
T2: Worker 崩溃，但作业进程 99999 继续运行
T3: 重启 Worker

[恢复检查]
    ├─ 查询 Job-002, state=RUNNING
    ├─ 检查进程 99999
    ├─ os.kill(99999, 0) → 成功！
    │
    ├─ 进程存在
    │  ├─ 保持 Job-002.state = RUNNING
    │  └─ 日志: "作业 Job-002 的进程仍在运行"
    │
    └─ 注意：Worker 无法再控制这个进程
       （这是一个已知限制）
```

#### 限制说明

如果作业进程在 Worker 崩溃后仍在运行，重启的 Worker **无法再控制这个进程**：
- 无法获取日志输出（已经丢失）
- 无法发送终止信号
- 无法检测作业是否完成

**建议**：遇到这种情况时，手动检查并处理这些作业。

---

## 🛡️ 最佳实践

### 1. 监控告警

```python
# 在 recovery.py 中添加告警
def recover_on_startup(self):
    orphan_jobs = self._find_orphan_jobs()
    
    if len(orphan_jobs) > 10:
        # 发送紧急告警
        send_alert(
            "检测到大量孤儿作业",
            f"共 {len(orphan_jobs)} 个作业需要恢复"
        )
```

### 2. 定期清理

```bash
# 添加到 crontab
0 2 * * * python /app/scripts/cleanup.py
```

```python
# scripts/cleanup.py
recovery_manager = RecoveryManager()
recovery_manager.cleanup_stale_allocations(max_age_hours=48)
```

### 3. 进程组管理

确保使用进程组，以便一次性终止所有子进程：

```python
process = subprocess.Popen(
    ['/bin/bash', script_path],
    preexec_fn=os.setsid,  # 创建新进程组
    ...
)

# 终止时杀死整个进程组
os.killpg(os.getpgid(process.pid), signal.SIGTERM)
```

### 4. 健康检查

```bash
# 定期检查 Worker 健康状态
*/5 * * * * python /app/scripts/health_check.py
```

---

## 📝 配置建议

### Docker Compose

```yaml
worker:
  image: scns-worker:latest
  restart: always  # 自动重启
  deploy:
    restart_policy:
      condition: on-failure
      delay: 5s
      max_attempts: 3
```

### Systemd

```ini
[Service]
Restart=always
RestartSec=10s
```

---

## ✅ 总结

### 关键保证

1. ✅ **不会丢失作业**：所有状态存储在数据库
2. ✅ **不会重复执行**：通过数据库状态判断
3. ✅ **孤儿作业自动检测**：启动时恢复机制
4. ✅ **资源自动释放**：幂等性保证
5. ✅ **操作幂等性**：多次执行相同操作安全

### 已知限制

1. ⚠️ **Worker 崩溃时正在运行的作业可能继续执行**
   - 进程会成为孤儿进程
   - 但会被标记为 FAILED
   - 用户需要检查实际执行情况

2. ⚠️ **日志可能不完整**
   - Worker 崩溃前的日志已写入文件
   - 崩溃后的日志无法捕获

3. ⚠️ **进程仍在运行时无法控制**
   - 重启的 Worker 无法控制旧进程
   - 需要手动干预

### 推荐配置

```properties
# app.properties
LOG_LEVEL=INFO
WORKER_BURST=false  # 不要使用 burst 模式
```

---

**文档版本**: v1.0.0  
**最后更新**: 2025-11-07

