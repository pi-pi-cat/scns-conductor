# Worker 并发执行功能

## 问题背景

### 原始问题
用户发现：**当多个作业并发提交时，系统没有并发执行的能力**。

### 根本原因
RQ Worker 默认是**单进程单线程**的，一次只能执行一个任务：

```
Redis 队列: [Job1, Job2, Job3, Job4]
               ↓
          RQ Worker (单进程)
               ↓
执行 Job1 → fork 子进程
  ↓ 等待子进程完成... ← 阻塞在这里
  ↓
Job1 完成后才执行 Job2  ← 串行执行！
```

**执行流程分析**：
1. Worker 从 Redis 队列取出 Job1
2. 调用 `execute_job_task(1)`
3. 在 `executor.execute_job()` 中：
   - 等待调度（轮询数据库）
   - Fork 子进程运行脚本
   - **阻塞等待子进程完成**  ← 问题所在
4. Job1 完成后，Worker 才会取出 Job2

即使调度器可以同时调度多个作业（资源足够），Worker 也是**串行处理队列中的任务**。

## 解决方案

### 多进程 Worker 模式

启动多个独立的 Worker 进程，每个进程从同一个 Redis 队列取任务：

```
                    Redis 队列: [Job1, Job2, Job3, Job4]
                           ↓
        ┌──────────────────┼──────────────────┬──────────────────┐
        ↓                  ↓                  ↓                  ↓
   Worker-1           Worker-2           Worker-3           Worker-4
        ↓                  ↓                  ↓                  ↓
   执行 Job1          执行 Job2          执行 Job3          执行 Job4
        ↓                  ↓                  ↓                  ↓
   并发执行！        并发执行！        并发执行！        并发执行！
```

**优势**：
- ✅ 真正的并发执行（多进程，不受 Python GIL 限制）
- ✅ 充分利用多核 CPU
- ✅ 进程隔离，一个 Worker 崩溃不影响其他
- ✅ 符合 RQ 的设计理念

## 配置方式

### 1. 修改配置文件

在 `app.properties` 中设置 `WORKER_CONCURRENCY`：

```properties
# Worker Configuration
WORKER_CONCURRENCY=4  # 启动 4 个 Worker 进程
WORKER_BURST=false
```

**建议值**：
- 小型系统：2-4 个 Worker
- 中型系统：4-8 个 Worker
- 大型系统：8-16 个 Worker
- 根据 CPU 核心数和作业类型调整

**注意**：
- Worker 数量不宜超过 `TOTAL_CPUS / 最小作业 CPU 需求`
- 例如：32 核系统，每个作业至少需要 4 核，建议最多 8 个 Worker

### 2. 启动 Worker

```bash
# 启动多进程 Worker（会自动读取 WORKER_CONCURRENCY）
python worker/main.py
```

**日志输出**：
```
============================================================
节点名称: kunpeng-compute-01
总 CPU 核心数: 32
Worker 并发数: 4
------------------------------------------------------------
✓ 调度器守护进程已启动（主进程）
🚀 启动 4 个 Worker 进程...
✓ Worker-1 进程已启动 (PID: 12345)
✓ Worker-2 进程已启动 (PID: 12346)
✓ Worker-3 进程已启动 (PID: 12347)
✓ Worker-4 进程已启动 (PID: 12348)
============================================================
✅ 4 个 Worker 进程已就绪，等待作业...
============================================================
```

### 3. 验证并发执行

**提交多个作业**：
```bash
# 快速提交 4 个作业
for i in {1..4}; do
  curl -X POST http://localhost:8000/api/jobs/submit \
    -H "Content-Type: application/json" \
    -d '{
      "job": {
        "account": "test",
        "name": "concurrent-job-'$i'",
        "partition": "compute-high-mem",
        "ntasks_per_node": 1,
        "cpus_per_task": 4,
        "memory_per_node": "8G"
      },
      "script": "#!/bin/bash\necho \"Job '$i' is running\"\nsleep 10"
    }'
done
```

**观察执行**：
- 查看数据库：4 个作业应该**同时**处于 `RUNNING` 状态
- 查看日志：4 个 Worker 各自处理一个作业
- 查看进程：`ps aux | grep worker` 看到多个 Worker 进程

## 架构说明

### 进程结构

```
主进程 (python worker/main.py)
├─ Scheduler Daemon (守护线程) ← 只在主进程中启动
│  └─ 每 5 秒扫描 PENDING 作业，分配资源
│
├─ Worker-1 进程
│  └─ 从 Redis 队列取任务并执行
│
├─ Worker-2 进程
│  └─ 从 Redis 队列取任务并执行
│
├─ Worker-3 进程
│  └─ 从 Redis 队列取任务并执行
│
└─ Worker-4 进程
   └─ 从 Redis 队列取任务并执行
```

### 关键点

1. **调度器只启动一次**：
   - Scheduler Daemon 在主进程中启动
   - 负责全局的资源调度
   - 所有 Worker 共享同一个调度器

2. **Worker 独立运行**：
   - 每个 Worker 是独立的进程
   - 从同一个 Redis 队列取任务（自动负载均衡）
   - 各自维护独立的数据库连接

3. **资源管理同步**：
   - ResourceManager 是单例（所有进程共享同一个实例）
   - 通过数据库同步资源状态
   - 内存状态通过 allocate/release 方法同步

### 并发流程

```
T0: 提交 4 个作业
    ├─ API: Job1(PENDING), Job2(PENDING), Job3(PENDING), Job4(PENDING)
    └─ Redis: [job_1, job_2, job_3, job_4]

T1: Scheduler Daemon 扫描
    └─ 同时调度 4 个作业（资源足够）
       ├─ Job1(RUNNING), cpus_used = 4
       ├─ Job2(RUNNING), cpus_used = 8
       ├─ Job3(RUNNING), cpus_used = 12
       └─ Job4(RUNNING), cpus_used = 16

T2: Worker 并发执行
    ├─ Worker-1: 取出 job_1 → execute_job_task(1) → fork 子进程
    ├─ Worker-2: 取出 job_2 → execute_job_task(2) → fork 子进程
    ├─ Worker-3: 取出 job_3 → execute_job_task(3) → fork 子进程
    └─ Worker-4: 取出 job_4 → execute_job_task(4) → fork 子进程

T3: 4 个作业并发运行 ✓
```

## 性能考虑

### CPU 利用率

**之前（单 Worker）**：
```
作业 1: 使用 4 核，运行 60 秒
作业 2: 使用 4 核，运行 60 秒
作业 3: 使用 4 核，运行 60 秒
作业 4: 使用 4 核，运行 60 秒

总时间: 240 秒
CPU 利用率: 4/32 = 12.5%  ← 浪费！
```

**现在（4 Worker）**：
```
作业 1, 2, 3, 4: 各使用 4 核，并发运行 60 秒

总时间: 60 秒
CPU 利用率: 16/32 = 50%  ← 提升 4 倍！
```

### 内存占用

- 每个 Worker 进程约占用 50-100 MB 内存
- 4 个 Worker 约占用 200-400 MB
- 相对于作业的内存需求，这个开销可以忽略

### 数据库连接

- 每个 Worker 维护独立的连接池
- 建议配置数据库最大连接数 >= Worker 数 * 连接池大小
- PostgreSQL 默认 100 连接，通常足够

## 单 Worker 模式（兼容）

如果设置 `WORKER_CONCURRENCY=1`，系统会使用单 Worker 模式：

```bash
🚀 启动单 Worker 模式...
🚀 Worker 已就绪，等待作业...
```

**适用场景**：
- 开发和测试环境
- 小型系统（并发需求低）
- 资源受限的环境

## 监控和调试

### 查看 Worker 进程

```bash
# 查看所有 Worker 进程
ps aux | grep "worker/main.py"

# 示例输出
USER   PID   ...  CMD
user  12345  ...  python worker/main.py          # 主进程
user  12346  ...  python worker/main.py          # Worker-1
user  12347  ...  python worker/main.py          # Worker-2
user  12348  ...  python worker/main.py          # Worker-3
user  12349  ...  python worker/main.py          # Worker-4
```

### 查看 Worker 状态（RQ Dashboard）

可以使用 RQ Dashboard 监控 Worker：

```bash
pip install rq-dashboard
rq-dashboard -H localhost -p 6379 -d 0
```

打开浏览器访问 `http://localhost:9181`，可以看到：
- 活跃的 Worker 数量
- 每个 Worker 正在执行的任务
- 队列长度和等待任务数

### 查看资源利用率

```bash
# 查看 CPU 使用情况
htop

# 查看作业资源分配
psql -U scnsqap -d scns_conductor -c "
  SELECT job_id, allocated_cpus, node_name, released 
  FROM resource_allocations 
  WHERE released = false;
"
```

## 故障处理

### Worker 进程崩溃

如果某个 Worker 进程崩溃：
- 其他 Worker 继续正常运行
- 该 Worker 正在处理的作业会被标记为失败
- 重启 Worker 服务会恢复

### 资源死锁

如果所有 Worker 都在等待资源：
- 调度器会记录日志：`⏳ 作业 X 资源不足`
- 等待正在运行的作业完成释放资源
- 可以通过增加 `TOTAL_CPUS` 或减少作业的 CPU 需求

### 进程泄漏

如果 Worker 进程没有正确清理：

```bash
# 查找孤儿进程
pgrep -f "worker/main.py"

# 强制终止（谨慎使用）
pkill -9 -f "worker/main.py"

# 重新启动
python worker/main.py
```

## 最佳实践

1. **根据负载调整并发数**：
   - 监控 Worker 的空闲时间
   - 如果经常有作业排队，增加 Worker 数
   - 如果 Worker 经常空闲，减少 Worker 数

2. **合理分配资源**：
   - Worker 数量 * 最大作业 CPU <= TOTAL_CPUS
   - 例如：32 核，每个作业最多 8 核，建议 4 个 Worker

3. **监控和告警**：
   - 监控队列长度，超过阈值告警
   - 监控 Worker 进程数，异常退出告警
   - 监控资源利用率，长期低效告警

4. **分级处理**：
   - 可以为不同优先级的作业创建不同的队列
   - 为高优先级队列分配更多 Worker

## 后续优化方向

1. **动态调整 Worker 数量**：
   - 根据队列长度自动扩容/缩容
   - 类似 Kubernetes HPA

2. **Worker 进程池**：
   - 预创建进程池，减少启动开销
   - 进程复用，提高效率

3. **优先级队列**：
   - 支持作业优先级
   - 高优先级作业优先执行

4. **亲和性调度**：
   - 将相关作业调度到同一 Worker
   - 减少数据传输开销

## 总结

这次修复实现了真正的并发执行能力：

- ✅ **问题**：单 Worker 串行执行，无法并发
- ✅ **方案**：多进程 Worker，并发处理任务
- ✅ **配置**：通过 `WORKER_CONCURRENCY` 灵活调整
- ✅ **兼容**：保留单 Worker 模式，向后兼容
- ✅ **性能**：大幅提升 CPU 利用率和吞吐量

现在系统可以真正地并发执行多个作业了！🚀

---

**实现日期**: 2025-11-10  
**实现者**: AI Assistant  
**版本**: v1.0
