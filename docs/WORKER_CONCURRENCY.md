# Worker 并发模型详解

## 🤔 关键问题：一个 Worker = 只能运行一个作业？

### ❌ 错误理解
```
Worker进程 → 只能运行一个作业 → 其他作业必须等待
```

### ✅ 正确理解
```
Worker进程（单个）
  ├─ 作业A (subprocess, PID=1001, 8核) ← 同时运行
  ├─ 作业B (subprocess, PID=1002, 4核) ← 同时运行
  ├─ 作业C (subprocess, PID=1003, 2核) ← 同时运行
  └─ 作业D等待调度（因为 8+4+2=14核，还有50核可用）
```

---

## 🏗️ 架构详解

### 1. Worker 进程结构

```python
主进程: Worker
  │
  ├─ 线程1: RQ Worker（处理任务队列）
  │   └─ execute_job_task(job_id)
  │       └─ subprocess.Popen(bash script)  ← 作业进程
  │
  ├─ 线程2: Scheduler Daemon（调度守护进程）
  │   └─ 每5秒检查PENDING作业
  │       └─ 分配资源 → 标记RUNNING
  │
  └─ 线程3: Resource Tracker（资源跟踪）
      └─ 管理CPU资源池（64核）
```

### 2. 并发模型图

```
时间轴：
T0  │ Worker启动
    │
T1  │ 用户提交 Job-1 (需要8核)
    │ ├─ API创建记录 (state=PENDING)
    │ └─ 入队RQ
    │
T2  │ 调度器检测到Job-1
    │ ├─ 检查资源：8/64核可用 ✓
    │ ├─ 分配资源
    │ └─ 标记RUNNING
    │
T3  │ RQ Worker执行Job-1
    │ ├─ 创建subprocess (PID=1001)
    │ └─ Job-1开始运行... (使用8核)
    │
T4  │ 用户提交 Job-2 (需要4核)
    │ └─ API创建记录 (state=PENDING)
    │
T5  │ 调度器检测到Job-2
    │ ├─ 检查资源：56/64核可用 ✓
    │ ├─ 分配资源
    │ └─ 标记RUNNING
    │
T6  │ RQ Worker执行Job-2
    │ ├─ 创建subprocess (PID=1002)
    │ └─ Job-2开始运行... (使用4核)
    │
    │ ⚡ 此时：Job-1和Job-2同时运行！
    │ 资源使用：12/64核
```

---

## 🔍 详细工作流程

### 阶段1：作业提交

```python
# 用户提交作业
POST /jobs/submit
  ↓
API Service:
  1. 验证请求
  2. 创建Job记录 (state=PENDING)
  3. 保存到PostgreSQL
  4. 返回job_id
  ↓
数据库:
  jobs表: [Job-1001 (PENDING), Job-1002 (PENDING)]
```

### 阶段2：调度器工作

```python
# Scheduler Daemon (后台线程，每5秒运行)
while True:
    # 查询PENDING作业
    pending_jobs = db.query(Job).filter(state=PENDING).order_by(submit_time)
    
    for job in pending_jobs:
        required_cpus = job.cpus_per_task * job.ntasks_per_node
        
        if resource_tracker.can_allocate(required_cpus):
            # 有足够资源，立即调度
            allocate_resources(job, required_cpus)
            job.state = RUNNING
            db.commit()
        else:
            # 资源不足，等待
            logger.debug(f"Job {job.id} 等待资源")
    
    time.sleep(5)
```

### 阶段3：作业执行

```python
# RQ Worker执行任务（每个作业独立的subprocess）
def execute_job_task(job_id):
    job = db.get(job_id)
    
    # 创建独立的子进程运行脚本
    process = subprocess.Popen(
        ['/bin/bash', f'job_{job_id}.sh'],
        preexec_fn=os.setsid  # 创建新进程组
    )
    
    # Worker主进程继续，可以处理其他作业
    process.wait()  # 等待作业完成
    
    # 作业完成，释放资源
    release_resources(job_id)
```

---

## 📊 并发能力对比

### 场景1：64核服务器

| 作业配置 | 最大并发数 | 说明 |
|---------|-----------|------|
| 每个作业8核 | 8个 | 64÷8=8 |
| 每个作业4核 | 16个 | 64÷4=16 |
| 每个作业2核 | 32个 | 64÷2=32 |
| 每个作业1核 | 64个 | 64÷1=64 |
| 混合 (8+4+2+1) | 多个 | 动态分配 |

### 场景2：实际运行示例

```bash
# 查看当前运行的作业
$ ps aux | grep "job_"

user  1001  bash /var/scns-conductor/scripts/job_1001.sh  # 8核
user  1002  bash /var/scns-conductor/scripts/job_1002.sh  # 4核
user  1003  bash /var/scns-conductor/scripts/job_1003.sh  # 2核
user  1004  bash /var/scns-conductor/scripts/job_1004.sh  # 1核

# 总共使用：8+4+2+1=15核，还有49核可用
```

---

## 🚀 扩展性：多Worker部署

### 单Worker限制

```
Worker-1 (节点1: 64核)
  ├─ 最多64核并发
  └─ 单点故障风险
```

### 多Worker扩展

```
┌─────────────────────────────────────┐
│          PostgreSQL (共享)           │
│   jobs表: 所有作业状态               │
└───────┬─────────────┬────────────────┘
        │             │
        ▼             ▼
┌───────────────┐ ┌───────────────┐
│   Worker-1    │ │   Worker-2    │
│  (节点1:64核) │ │  (节点2:64核) │
├───────────────┤ ├───────────────┤
│ Job-1001 (8核)│ │ Job-2001 (8核)│
│ Job-1002 (4核)│ │ Job-2002 (4核)│
│ Job-1003 (2核)│ │ Job-2003 (2核)│
└───────────────┘ └───────────────┘
  ↓ 使用14核       ↓ 使用14核
  
总并发能力：128核
```

**实现方式**：
```yaml
# docker-compose.yml
worker-1:
  environment:
    NODE_NAME: worker-node-01
    TOTAL_CPUS: 64

worker-2:
  environment:
    NODE_NAME: worker-node-02
    TOTAL_CPUS: 64
```

---

## ⚡ 性能优化建议

### 1. 调整调度器检查间隔

```python
# worker/main.py
scheduler_daemon = SchedulerDaemon(
    check_interval=2  # 改为2秒，更快响应
)
```

### 2. CPU亲和性（高级）

```python
# worker/executor.py
import os

def _run_job(self, job: Job):
    # 设置CPU亲和性，绑定到特定核心
    cpu_set = range(start_cpu, start_cpu + job.allocated_cpus)
    os.sched_setaffinity(0, cpu_set)
    
    process = subprocess.Popen(...)
```

### 3. 优先级调度（未来扩展）

```python
# 当前：FIFO（先来先服务）
pending_jobs = query(Job).order_by(Job.submit_time)

# 未来：优先级调度
pending_jobs = query(Job).order_by(
    Job.priority.desc(),  # 先按优先级
    Job.submit_time       # 再按时间
)
```

---

## 🔧 监控并发状态

### 查询当前运行的作业

```bash
# API查询
curl http://localhost:8000/jobs/stats

# 响应
{
  "total_cpus": 64,
  "used_cpus": 15,
  "available_cpus": 49,
  "running_jobs": 4,
  "pending_jobs": 2
}
```

### 数据库查询

```sql
-- 当前运行的作业
SELECT 
    id, 
    name, 
    allocated_cpus, 
    start_time,
    EXTRACT(EPOCH FROM (NOW() - start_time)) as running_seconds
FROM jobs 
WHERE state = 'RUNNING'
ORDER BY start_time;

-- 资源使用统计
SELECT 
    SUM(allocated_cpus) as total_used_cpus,
    COUNT(*) as running_count
FROM jobs 
WHERE state = 'RUNNING';
```

---

## 📈 负载均衡策略

### 当前策略：本地CPU池

```
Worker检查：我有64核，用了14核，还能分配吗？
  ├─ 请求8核：可以 ✓
  ├─ 请求50核：可以 ✓
  └─ 请求51核：不行 ✗（需要等待）
```

### 未来：全局负载均衡

```
调度器查询：
  ├─ Worker-1: 14/64核使用
  ├─ Worker-2: 8/64核使用
  └─ Worker-3: 56/64核使用

新作业(8核) → 分配到Worker-2（负载最低）
```

---

## ⚠️ 常见误区

### 误区1：Worker必须等待作业完成

```python
# ❌ 错误理解
Worker → 执行Job-1 → 等待完成 → 执行Job-2

# ✅ 正确理解
Worker → 启动Job-1 (subprocess) → 立即可以启动Job-2
```

### 误区2：RQ队列会阻塞

```python
# ❌ 错误理解
RQ队列: Job-1在队列中 → Worker取出执行 → 完成后才能取下一个

# ✅ 正确理解
RQ队列: Job-1执行立即完成（启动subprocess）
       → Worker马上可以取Job-2
       → 实际作业在独立进程中运行
```

### 误区3：需要多个Worker才能并发

```python
# ❌ 错误想法
必须启动8个Worker进程才能同时运行8个作业

# ✅ 实际情况
1个Worker进程可以同时管理64个作业（如果每个1核）
因为每个作业是独立的subprocess
```

---

## 🎯 总结

### 关键要点

1. ✅ **一个Worker ≠ 一个作业**
   - Worker是管理者，不是执行者
   - 每个作业在独立的subprocess中运行

2. ✅ **并发受CPU资源限制，不受Worker数量限制**
   - 64核服务器可以同时运行64个1核作业
   - 或8个8核作业，或任意组合

3. ✅ **调度是自动的**
   - Scheduler Daemon每5秒检查
   - 有资源就立即调度
   - 无需人工干预

4. ✅ **扩展很简单**
   - 增加Worker进程 = 增加节点
   - 数据库共享，自动协调

### 性能数据

| 配置 | 单Worker并发 | 双Worker并发 |
|------|-------------|-------------|
| 64核服务器 | 最多64核 | 最多128核 |
| 1核作业 | 最多64个 | 最多128个 |
| 8核作业 | 最多8个 | 最多16个 |

---

**文档版本**: v1.0.0  
**最后更新**: 2025-11-07

