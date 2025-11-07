# SCNS-Conductor 架构设计文档

## 目录

1. [系统概述](#系统概述)
2. [架构原则](#架构原则)
3. [核心组件](#核心组件)
4. [数据流](#数据流)
5. [调度算法](#调度算法)
6. [可靠性设计](#可靠性设计)
7. [性能优化](#性能优化)
8. [扩展性](#扩展性)

## 系统概述

SCNS-Conductor 是一个轻量级、高可靠的作业调度系统，采用现代化的微服务架构，专为计算密集型作业管理设计。

### 设计目标

- **轻量级**: 最小化依赖，快速部署
- **高可靠**: 状态持久化，自动故障恢复
- **高性能**: 异步架构，充分利用多核
- **可扩展**: 模块化设计，易于扩展
- **ARM 优化**: 完全支持鲲鹏架构

## 架构原则

### 1. 无状态服务

所有服务组件（API、Worker）都是无状态的：
- 状态存储在 PostgreSQL 数据库
- 临时消息通过 Redis 传递
- 服务可随时重启而不丢失数据

### 2. 关注点分离

系统分为三层：
- **API 层**: 处理 HTTP 请求，数据验证
- **业务逻辑层**: 作业管理、调度策略
- **数据层**: 数据库操作、持久化

### 3. 异步优先

- API 服务使用 FastAPI + asyncpg 实现全异步
- Worker 使用 RQ 实现后台任务处理
- 充分利用 I/O 并发能力

### 4. 数据库作为真相源

- PostgreSQL 是系统的唯一权威数据源
- Redis 仅用作临时队列，不存储持久数据
- 所有状态变更都通过数据库事务保证一致性

## 核心组件

### API Service

**技术栈**: FastAPI + asyncpg + SQLAlchemy

**职责**:
- 接收 HTTP 请求
- 验证请求数据（Pydantic）
- 调用业务逻辑服务
- 返回响应

**特点**:
- 全异步架构，高并发性能
- 自动生成 OpenAPI 文档
- 类型安全的请求/响应验证

### Worker Service

**技术栈**: RQ + psycopg2 + subprocess

**职责**:
- 执行作业脚本
- 管理作业生命周期
- 资源分配和释放
- 日志收集

**特点**:
- 使用 subprocess 隔离作业执行
- 支持超时控制
- 进程组管理，便于终止

### Scheduler Daemon

**职责**:
- 定期检查 PENDING 作业
- 根据可用资源调度作业
- 实现 FIFO + First Fit 算法

**工作流程**:
```
1. 查询所有 PENDING 状态的作业（按提交时间排序）
2. 对每个作业：
   a. 检查所需 CPU 是否可用
   b. 如果可用，分配资源并标记为 RUNNING
3. 每 5 秒重复一次
```

### Resource Tracker

**职责**:
- 跟踪 CPU 资源使用情况
- 提供线程安全的资源分配接口
- 启动时从数据库恢复状态

**实现**:
- 使用 threading.Lock 保证线程安全
- 内存中维护资源计数器
- 与数据库保持同步

## 数据流

### 作业提交流程

```
User
  │
  │ POST /jobs/submit
  ▼
API Service
  │
  │ 1. 验证请求
  │ 2. 创建 Job 记录
  │ 3. 获取 job_id
  ▼
PostgreSQL
  │
  │ job_id
  ▼
User (返回 job_id)

[同时]
Worker Scheduler Daemon
  │
  │ 每 5 秒轮询
  ▼
检查 PENDING 作业
  │
  │ 如果资源可用
  ▼
更新状态为 RUNNING
创建资源分配记录
  │
  ▼
Worker 执行作业
```

### 作业查询流程

```
User
  │
  │ GET /jobs/query/{job_id}
  ▼
API Service
  │
  │ 1. 查询数据库
  │ 2. 读取日志文件
  │ 3. 计算时间信息
  ▼
返回完整作业信息
```

### 作业取消流程

```
User
  │
  │ POST /jobs/cancel/{job_id}
  ▼
API Service
  │
  │ 1. 查询作业状态
  │ 2. 发送 SIGTERM 信号
  │ 3. 更新状态为 CANCELLED
  │ 4. 释放资源
  ▼
PostgreSQL
```

## 调度算法

### FIFO + First Fit

**策略描述**:
1. **FIFO (First In First Out)**: 按作业提交时间排序
2. **First Fit**: 依次尝试分配，遇到第一个满足资源需求的作业就分配

**实现**:
```python
def schedule_pending_jobs():
    # 按提交时间排序
    pending_jobs = query_jobs(state=PENDING).order_by(submit_time)
    
    for job in pending_jobs:
        required_cpus = job.cpus_per_task * job.ntasks_per_node
        
        if resource_tracker.can_allocate(required_cpus):
            allocate_resources(job, required_cpus)
            mark_job_running(job)
```

**优点**:
- 简单易实现
- 公平性好
- 资源利用率高

**适用场景**:
- 单节点调度
- CPU 主要资源
- 作业规模相近

## 可靠性设计

### 1. 状态持久化

**原则**: 所有关键状态都存储在 PostgreSQL

**实现**:
- 作业状态、时间信息存储在 `jobs` 表
- 资源分配记录存储在 `resource_allocations` 表
- 使用数据库事务保证一致性

### 2. 故障恢复

**Worker 重启恢复**:
```python
# 启动时从数据库加载当前资源使用情况
def _load_current_usage(self):
    allocations = query(ResourceAllocation).filter(released=False)
    self._used_cpus = sum(a.allocated_cpus for a in allocations)
```

**处理僵尸作业**:
```python
# cleanup.py 中的逻辑
def fix_stuck_jobs():
    # 查找运行超过 48 小时的作业
    stuck_jobs = query(Job).filter(
        state=RUNNING,
        start_time < now() - timedelta(hours=48)
    )
    
    for job in stuck_jobs:
        job.state = FAILED
        release_resources(job)
```

### 3. 幂等性设计

**取消操作幂等性**:
- 检查作业当前状态
- 已完成/已取消的作业再次取消不报错
- 使用数据库 UNIQUE 约束防止重复资源分配

### 4. 优雅关闭

**信号处理**:
```python
def signal_handler(signum, frame):
    logger.info("Received signal, graceful shutdown...")
    scheduler_daemon.stop()
    worker.request_stop()
```

## 性能优化

### 1. 数据库连接池

**配置**:
```python
pool_size=20          # 连接池大小
max_overflow=10       # 最大溢出连接
pool_pre_ping=True    # 连接前测试
pool_recycle=3600     # 连接回收时间
```

### 2. 异步 I/O

**日志读取**:
```python
async def read_log_file(file_path):
    async with aiofiles.open(file_path) as f:
        content = await f.read()
    return content
```

**并发读取**:
```python
stdout, stderr = await asyncio.gather(
    read_log_file(stdout_path),
    read_log_file(stderr_path)
)
```

### 3. 索引优化

**关键索引**:
```sql
CREATE INDEX idx_job_state ON jobs(state);
CREATE INDEX idx_job_submit_time ON jobs(submit_time);
CREATE INDEX idx_resource_allocation_released ON resource_allocations(released);
```

### 4. 查询优化

**避免 N+1 查询**:
```python
# 使用 join 一次性获取相关数据
job = session.query(Job).options(
    joinedload(Job.resource_allocation)
).filter(Job.id == job_id).first()
```

## 扩展性

### 横向扩展

**多 Worker 节点**:
```yaml
# docker-compose.yml
worker-1:
  environment:
    NODE_NAME: worker-node-01
    TOTAL_CPUS: 32

worker-2:
  environment:
    NODE_NAME: worker-node-02
    TOTAL_CPUS: 32
```

### 垂直扩展

**增加资源**:
- 调整 `TOTAL_CPUS` 配置
- 增加数据库连接池大小
- 扩展 Redis 内存

### 功能扩展

**添加新的资源类型**:
1. 修改 `Job` 模型添加字段
2. 更新调度器考虑新资源
3. 扩展 API schema

**添加优先级调度**:
1. 在 `Job` 模型添加 `priority` 字段
2. 修改调度器排序逻辑
3. 更新 API 接受优先级参数

## 安全考虑

### 1. 脚本隔离

- 使用独立工作目录
- 限制环境变量
- 使用 `preexec_fn=os.setsid` 创建进程组

### 2. 路径验证

```python
def validate_path(path):
    if not os.path.isabs(path):
        raise ValueError("Path must be absolute")
```

### 3. 资源限制

- CPU 核心数限制
- 超时控制
- 内存限制（未来功能）

## 监控与可观测性

### 1. 结构化日志

```python
logger.info(
    "Job scheduled",
    extra={
        "job_id": job_id,
        "cpus": cpus,
        "utilization": utilization
    }
)
```

### 2. 健康检查

- API: `/health` 端点
- Worker: 资源统计日志
- 数据库: 连接测试

### 3. 指标收集

**当前支持**:
- 作业统计（总数、状态分布）
- 资源利用率
- 队列长度

**未来扩展**:
- Prometheus metrics
- 分布式追踪（Jaeger）
- 性能分析（cProfile）

---

**最后更新**: 2025-11-07

