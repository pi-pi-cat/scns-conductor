# PID 存储到数据库实现

## 需求

将作业进程的 PID 存储到数据库的 `resource_allocations` 表中，以支持作业取消等管理功能。

## 实现方案

### 数据库模型

`ResourceAllocation` 模型中已经包含 `process_id` 字段：

```python
# core/models.py
class ResourceAllocation(SQLModel, table=True):
    # ...
    process_id: Optional[int] = Field(default=None, description="操作系统进程ID")
    # ...
```

### 存储 PID

修改 `worker/process_utils.py` 中的 `store_pid()` 函数：

```python
def store_pid(job_id: int, pid: int):
    """
    存储进程 ID 到数据库
    
    Args:
        job_id: 作业 ID
        pid: 进程 ID
    """
    try:
        with sync_db.get_session() as session:
            # 查找该作业的资源分配记录
            allocation = (
                session.query(ResourceAllocation)
                .filter(
                    ResourceAllocation.job_id == job_id,
                    ~ResourceAllocation.released,
                )
                .first()
            )
            
            if allocation:
                allocation.process_id = pid
                session.commit()
                logger.debug(f"Job {job_id} PID {pid} stored in database")
            else:
                logger.warning(f"No allocation found for job {job_id}, PID not stored")
    
    except Exception as e:
        logger.error(f"Failed to store PID for job {job_id}: {e}")
```

### 调用时机

在 `worker/executor.py` 中，当进程启动后立即存储 PID：

```python
# worker/executor.py - _run() 方法
process = subprocess.Popen(
    ["/bin/bash", script_path],
    stdout=stdout,
    stderr=stderr,
    cwd=job.work_dir,
    env=env,
    preexec_fn=os.setsid,
)

# 记录进程 ID（同时存储到数据库）
store_pid(job.id, process.pid)
logger.info(f"Job {job.id} started, PID: {process.pid}")
```

## 使用场景

### 1. 作业取消

`api/services/job_service.py` 中的 `cancel_job()` 方法使用数据库中的 PID 来终止作业：

```python
async def _kill_job_process(job: Job) -> None:
    """杀死正在运行的作业进程"""
    allocation = job.resource_allocation
    
    if allocation and allocation.process_id:
        try:
            # 向进程组发送SIGTERM信号以终止作业
            os.killpg(os.getpgid(allocation.process_id), signal.SIGTERM)
            logger.info(f"已向作业 {job.id} 发送SIGTERM信号 (PID: {allocation.process_id})")
        except ProcessLookupError:
            logger.warning(f"未找到作业 {job.id} 对应的进程 {allocation.process_id}")
        except Exception as e:
            logger.error(f"终止作业 {job.id} 进程失败: {e}")
```

### 2. 进程监控

可以通过查询数据库获取所有运行中作业的 PID：

```sql
SELECT 
    j.id as job_id,
    j.name,
    j.state,
    ra.process_id,
    ra.node_name
FROM jobs j
JOIN resource_allocations ra ON j.id = ra.job_id
WHERE j.state = 'RUNNING' AND ra.process_id IS NOT NULL;
```

### 3. 故障排查

当作业异常时，可以通过 PID 查看进程状态：

```bash
# 查看进程是否还在运行
ps -p <PID>

# 查看进程树
pstree -p <PID>

# 查看进程资源使用
top -p <PID>
```

## 数据流程

```
1. Scheduler: 调度作业
   ├─ 创建 ResourceAllocation (process_id = NULL)
   ├─ 更新 Job.state = RUNNING
   └─ 加入执行队列

2. Worker: 执行作业
   ├─ 启动进程 (subprocess.Popen)
   ├─ 获取 PID
   └─ 更新 ResourceAllocation.process_id = PID  ← 新增

3. Cancel Job (可选):
   ├─ 查询 ResourceAllocation.process_id
   ├─ 发送 SIGTERM 信号
   └─ 更新 Job.state = CANCELLED

4. Worker: 完成作业
   ├─ 释放资源
   └─ 更新 Job.state = COMPLETED/FAILED
```

## 测试验证

### 1. 基本功能测试

```bash
# 1. 提交一个长时间运行的作业
curl -X POST http://localhost:8000/api/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "script": "#!/bin/bash\nsleep 300",
    "cpus": 1,
    "time_limit": 10
  }'

# 2. 查询作业状态（应该包含 PID）
curl http://localhost:8000/api/v1/jobs/1

# 3. 查询数据库验证 PID
psql -d your_database -c \
  "SELECT job_id, process_id, node_name FROM resource_allocations WHERE job_id = 1;"
```

**预期结果**：
- `process_id` 字段不为空
- PID 是有效的操作系统进程 ID

### 2. 作业取消测试

```bash
# 1. 提交作业
curl -X POST http://localhost:8000/api/v1/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "script": "#!/bin/bash\nsleep 300",
    "cpus": 1
  }'

# 2. 取消作业
curl -X POST http://localhost:8000/api/v1/jobs/1/cancel

# 3. 验证进程已终止
ps -p <PID>  # 应该显示进程不存在
```

### 3. 数据库查询测试

```sql
-- 查看所有运行中作业的 PID
SELECT 
    j.id,
    j.name,
    j.state,
    ra.process_id,
    ra.allocation_time,
    ra.node_name
FROM jobs j
LEFT JOIN resource_allocations ra ON j.id = ra.job_id
WHERE j.state = 'RUNNING'
ORDER BY j.id DESC;

-- 统计有 PID 的作业数量
SELECT 
    COUNT(*) as total_jobs,
    COUNT(ra.process_id) as jobs_with_pid
FROM jobs j
LEFT JOIN resource_allocations ra ON j.id = ra.job_id
WHERE j.state = 'RUNNING';
```

## 注意事项

### 1. PID 的生命周期

- **存储时机**：进程启动后立即存储
- **有效期**：仅在作业运行期间有效
- **释放后**：进程已结束，但 PID 仍保留用于审计

### 2. 错误处理

- 如果找不到资源分配记录，会记录警告但不影响作业执行
- 数据库更新失败会记录错误但不中断作业
- 作业取消时，如果进程已不存在（ProcessLookupError），会优雅处理

### 3. 跨节点场景

如果将来支持多节点：
- PID 只在启动作业的节点上有效
- 需要结合 `node_name` 字段使用
- 取消作业时需要在正确的节点上执行

## 相关文件

- `core/models.py` - `ResourceAllocation` 模型定义
- `worker/process_utils.py` - `store_pid()` 实现
- `worker/executor.py` - 调用 `store_pid()`
- `api/services/job_service.py` - 使用 PID 取消作业

## 日期

2025-11-11

