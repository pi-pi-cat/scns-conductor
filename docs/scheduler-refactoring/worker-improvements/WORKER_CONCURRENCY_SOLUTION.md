# Worker 单机并发执行方案

## 📋 问题分析

### 当前问题
- Worker 一次只能运行一个任务（单进程单线程）
- 即使有足够的 CPU 资源，也无法并发执行多个作业
- 作业必须串行执行，导致资源利用率低

### 根本原因
RQ Worker 默认是**单进程单线程**的：
```python
# 当前实现
worker = Worker([queue])
worker.work()  # 阻塞执行，一次只处理一个任务
```

执行流程：
```
Redis 队列: [Job1, Job2, Job3, Job4]
               ↓
          RQ Worker (单进程)
               ↓
执行 Job1 → fork 子进程 → 等待完成（阻塞）
  ↓
Job1 完成后才执行 Job2  ← 串行执行！
```

## 🎯 解决方案对比

### 方案 1: 多进程 Worker（推荐）⭐

**原理**：启动多个独立的 Worker 进程，每个进程从同一个 Redis 队列取任务。

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

**优点**：
- ✅ 真正的并发执行（多进程，不受 Python GIL 限制）
- ✅ 充分利用多核 CPU
- ✅ 进程隔离，一个 Worker 崩溃不影响其他
- ✅ 符合 RQ 的设计理念
- ✅ 资源管理清晰（每个 Worker 独立管理资源）

**缺点**：
- ⚠️ 需要管理多个进程
- ⚠️ 资源占用稍高（每个进程独立的内存空间）

**适用场景**：**推荐用于生产环境**

---

### 方案 2: RQ Worker Pool（不推荐）

**原理**：使用 RQ 的 worker pool 功能（如果支持）。

**问题**：
- ❌ RQ 标准版本不支持 worker pool
- ❌ 需要第三方扩展或自定义实现
- ❌ 兼容性和稳定性未知

**结论**：**不推荐使用**

---

### 方案 3: 线程池/进程池（不推荐）

**原理**：在单个 Worker 中使用线程池或进程池。

**问题**：
- ❌ 线程受 Python GIL 限制，无法真正并发执行 CPU 密集型任务
- ❌ 进程池需要额外管理，复杂度高
- ❌ 与 RQ 的设计理念不符

**结论**：**不推荐使用**

---

## ✅ 推荐方案：多进程 Worker

### 架构设计

```
主进程 (worker/main.py)
    │
    ├─ 初始化（数据库、Redis、注册）
    │
    ├─ 启动 N 个 Worker 子进程
    │   ├─ Worker-1 (PID: 1001)
    │   ├─ Worker-2 (PID: 1002)
    │   ├─ Worker-3 (PID: 1003)
    │   └─ Worker-N (PID: 100N)
    │
    └─ 监控和信号处理
```

### 实现方案

#### 1. 修改 `worker/main.py`

```python
"""
Worker Service - 主入口（支持多进程并发）

支持通过 WORKER_CONCURRENCY 配置启动多个 Worker 进程
"""

import sys
import signal
import multiprocessing
from pathlib import Path

# 添加项目根目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent))

from loguru import logger

from core.config import get_settings
from core.database import sync_db
from core.redis_client import redis_manager
from core.utils.logger import setup_logger
from worker.registry import WorkerRegistry


def run_worker_process(worker_id: int, settings_dict: dict):
    """
    运行单个 Worker 进程
    
    Args:
        worker_id: Worker ID (1, 2, 3, ...)
        settings_dict: 配置字典（用于子进程）
    """
    import os
    
    # 重新初始化配置（子进程需要）
    from core.config import Settings
    settings = Settings(**settings_dict)
    
    # 设置日志
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)
    
    logger.info(f"🚀 Worker-{worker_id} started (PID: {os.getpid()})")
    
    try:
        # 初始化数据库
        sync_db.init()
        
        # 初始化 Redis
        redis_manager.init()
        if not redis_manager.ping():
            raise ConnectionError("Redis not available")
        
        # 获取队列
        queue = redis_manager.get_queue()
        
        # 初始化 Worker 注册器（每个 Worker 独立注册）
        registry = WorkerRegistry()
        
        # 注册 Worker（使用唯一的 worker_id）
        worker_name = f"worker-{settings.NODE_NAME}-{worker_id}"
        if not registry.register():
            logger.error(f"✗ Worker-{worker_id} registration failed")
            sys.exit(1)
        
        # 启动心跳线程
        if not registry.start_heartbeat():
            logger.error(f"✗ Worker-{worker_id} failed to start heartbeat")
            sys.exit(1)
        
        # 清理过期的 RQ worker
        connection = redis_manager.get_connection()
        from rq.worker import Worker as RQWorker
        
        all_workers = RQWorker.all(connection=connection)
        for w in all_workers:
            if w.name == worker_name:
                try:
                    w.refresh()
                    if not w.is_alive():
                        logger.warning(f"🧹 Cleaning up dead worker: {worker_name}")
                        w.register_death()
                except Exception as e:
                    logger.warning(f"🧹 Cleaning up stale worker: {worker_name} - {e}")
                    w.register_death()
        
        # 创建 RQ Worker
        worker = RQWorker(
            [queue],
            connection=connection,
            name=worker_name,
        )
        
        logger.info(f"✅ Worker-{worker_id} is ready, waiting for jobs...")
        
        # 运行 Worker（阻塞）
        worker.work(burst=settings.WORKER_BURST, with_scheduler=False)
        
    except KeyboardInterrupt:
        logger.info(f"⚠️  Worker-{worker_id} interrupted by user")
    except Exception as e:
        logger.error(f"❌ Worker-{worker_id} error: {e}", exc_info=True)
    finally:
        # 注销 Worker
        logger.info(f"Shutting down Worker-{worker_id}...")
        registry.unregister()
        
        # 关闭连接
        sync_db.close()
        redis_manager.close()
        
        logger.info(f"✅ Worker-{worker_id} stopped")


def main():
    """Worker 服务主入口（支持多进程）"""
    settings = get_settings()
    setup_logger(settings.LOG_LEVEL, settings.LOG_FILE)
    
    logger.info("=" * 70)
    logger.info("💪 SCNS-Conductor Worker Service v2.1 (Multi-Process)")
    logger.info("=" * 70)
    
    # 获取并发数
    concurrency = settings.WORKER_CONCURRENCY
    
    if concurrency < 1:
        logger.error("WORKER_CONCURRENCY must be >= 1")
        sys.exit(1)
    
    logger.info("-" * 70)
    logger.info(f"Node: {settings.NODE_NAME}")
    logger.info(f"Total CPUs: {settings.TOTAL_CPUS}")
    logger.info(f"Worker Concurrency: {concurrency}")
    logger.info("-" * 70)
    
    # 验证并发数合理性
    if concurrency > settings.TOTAL_CPUS:
        logger.warning(
            f"⚠️  WORKER_CONCURRENCY ({concurrency}) > TOTAL_CPUS ({settings.TOTAL_CPUS}), "
            f"may cause resource contention"
        )
    
    # 将配置转换为字典（用于传递给子进程）
    settings_dict = settings.model_dump()
    
    # 如果并发数为 1，直接运行（兼容旧版本）
    if concurrency == 1:
        logger.info("Running in single-worker mode")
        run_worker_process(1, settings_dict)
        return
    
    # 多进程模式
    logger.info(f"🚀 Starting {concurrency} worker processes...")
    
    # 创建进程列表
    processes = []
    
    # 信号处理
    def signal_handler(signum, frame):
        logger.info(f"🛑 Received signal {signum}, shutting down all workers...")
        for p in processes:
            if p.is_alive():
                p.terminate()
        # 等待所有进程结束
        for p in processes:
            p.join(timeout=5)
            if p.is_alive():
                logger.warning(f"Process {p.pid} did not terminate, killing...")
                p.kill()
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)
    
    # 启动多个 Worker 进程
    for i in range(1, concurrency + 1):
        p = multiprocessing.Process(
            target=run_worker_process,
            args=(i, settings_dict),
            name=f"Worker-{i}",
        )
        p.start()
        processes.append(p)
        logger.info(f"✓ Worker-{i} process started (PID: {p.pid})")
    
    logger.info("=" * 70)
    logger.info(f"✅ {concurrency} worker processes are ready, waiting for jobs...")
    logger.info("=" * 70)
    
    # 等待所有进程结束
    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        signal_handler(signal.SIGINT, None)


if __name__ == "__main__":
    main()
```

#### 2. 修改 Worker 注册（支持多实例）

需要确保每个 Worker 进程都有唯一的标识：

```python
# worker/registry.py
class WorkerRegistry:
    def __init__(self, worker_id: Optional[int] = None, ...):
        # 如果提供了 worker_id，使用它；否则使用默认的 NODE_NAME
        if worker_id:
            self.worker_id = f"{self.settings.NODE_NAME}-{worker_id}"
        else:
            self.worker_id = self.settings.NODE_NAME
        # ...
```

#### 3. 资源管理考虑

**重要**：每个 Worker 进程都会：
- 独立注册到 Redis（使用唯一的 worker_id）
- 独立管理资源分配
- 独立发送心跳

**资源分配逻辑**：
- Scheduler 根据 `TOTAL_CPUS` 和已分配的 CPU 数量进行调度
- 每个 Worker 进程执行作业时，会更新资源状态
- 多个 Worker 并发执行时，资源管理器会自动跟踪总使用量

**示例**：
```
TOTAL_CPUS = 32
WORKER_CONCURRENCY = 4

Worker-1 执行 Job1 (4 CPUs) → 已用: 4/32
Worker-2 执行 Job2 (8 CPUs) → 已用: 12/32
Worker-3 执行 Job3 (4 CPUs) → 已用: 16/32
Worker-4 执行 Job4 (8 CPUs) → 已用: 24/32
剩余: 8 CPUs
```

---

## 📝 配置说明

### 配置文件 (`app.properties`)

```properties
# Worker Configuration
WORKER_CONCURRENCY=4  # 启动 4 个 Worker 进程
WORKER_BURST=false

# Resource Configuration
NODE_NAME=kunpeng-compute-01
TOTAL_CPUS=32
```

### 配置建议

**并发数选择原则**：
1. **不超过 CPU 核心数**：`WORKER_CONCURRENCY <= TOTAL_CPUS`
2. **考虑作业 CPU 需求**：`WORKER_CONCURRENCY <= TOTAL_CPUS / 最小作业CPU需求`
3. **留有余量**：建议 `WORKER_CONCURRENCY <= TOTAL_CPUS * 0.8`

**示例配置**：
- 32 核系统，每个作业至少 4 核 → 建议 `WORKER_CONCURRENCY = 4-8`
- 64 核系统，每个作业至少 2 核 → 建议 `WORKER_CONCURRENCY = 8-16`
- 16 核系统，每个作业至少 4 核 → 建议 `WORKER_CONCURRENCY = 2-4`

---

## 🚀 使用方式

### 1. 启动 Worker

```bash
# 启动多进程 Worker（自动读取 WORKER_CONCURRENCY）
python worker/main.py
```

**日志输出**：
```
======================================================================
💪 SCNS-Conductor Worker Service v2.1 (Multi-Process)
======================================================================
----------------------------------------------------------------------
Node: kunpeng-compute-01
Total CPUs: 32
Worker Concurrency: 4
----------------------------------------------------------------------
🚀 Starting 4 worker processes...
✓ Worker-1 process started (PID: 12345)
✓ Worker-2 process started (PID: 12346)
✓ Worker-3 process started (PID: 12347)
✓ Worker-4 process started (PID: 12348)
======================================================================
✅ 4 worker processes are ready, waiting for jobs...
======================================================================
```

### 2. 验证并发执行

**提交多个作业**：
```bash
# 快速提交 4 个作业
for i in {1..4}; do
  curl -X POST http://localhost:8000/api/v1/jobs/submit \
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
- 查看进程：应该有 4 个独立的 Worker 进程在运行

---

## 🔍 监控和调试

### 1. 查看 Worker 进程

```bash
# 查看所有 Worker 进程
ps aux | grep "worker/main.py"

# 查看进程树
pstree -p | grep worker
```

### 2. 查看 Redis Worker 注册

```bash
# 连接到 Redis
redis-cli

# 查看所有 Worker
KEYS worker:*

# 查看 Worker 详情
HGETALL worker:kunpeng-compute-01-1
```

### 3. 查看日志

每个 Worker 进程会输出独立的日志：
```
[Worker-1] 🚀 Executing job 123
[Worker-2] 🚀 Executing job 124
[Worker-3] 🚀 Executing job 125
[Worker-4] 🚀 Executing job 126
```

---

## ⚠️ 注意事项

### 1. 资源管理
- 确保 `WORKER_CONCURRENCY` 不超过 `TOTAL_CPUS`
- 考虑作业的 CPU 需求，避免过度并发导致资源竞争

### 2. 进程管理
- 主进程负责启动和监控子进程
- 使用信号处理确保优雅关闭
- 子进程崩溃时，主进程可以检测并重启（可选）

### 3. 数据库连接
- 每个 Worker 进程需要独立的数据库连接
- 确保数据库连接池足够大

### 4. Redis 连接
- 每个 Worker 进程需要独立的 Redis 连接
- RQ 会自动管理 Redis 连接

### 5. 日志管理
- 多个进程可能同时写入日志文件
- 建议使用进程安全的日志处理器（loguru 已支持）

---

## 📊 性能对比

### 单 Worker（当前）
- 并发能力：1 个作业
- CPU 利用率：低（单核）
- 吞吐量：低

### 多 Worker（推荐）
- 并发能力：N 个作业（N = WORKER_CONCURRENCY）
- CPU 利用率：高（多核）
- 吞吐量：高（N 倍提升）

**示例**：
- 4 个 Worker，每个作业执行 10 秒
- 单 Worker：40 秒完成 4 个作业
- 多 Worker：10 秒完成 4 个作业（4 倍提升）

---

## 🔄 与现有系统的兼容性

### 兼容性检查

✅ **完全兼容**：
- Scheduler 无需修改（自动适配）
- ResourceManager 无需修改（自动跟踪）
- API 无需修改
- 数据库结构无需修改

✅ **向后兼容**：
- `WORKER_CONCURRENCY=1` 时，行为与当前版本完全一致
- 可以逐步增加并发数，无需停机

---

## 📝 实施步骤

### 阶段 1: 基础实现（1-2 天）
1. 修改 `worker/main.py` 支持多进程
2. 修改 `worker/registry.py` 支持多实例注册
3. 添加信号处理和进程监控

### 阶段 2: 测试验证（1-2 天）
1. 单元测试
2. 集成测试
3. 性能测试

### 阶段 3: 文档和部署（1 天）
1. 更新文档
2. 更新配置示例
3. 部署到测试环境

---

## 🎯 总结

**推荐方案**：多进程 Worker

**优势**：
- ✅ 真正的并发执行
- ✅ 充分利用多核 CPU
- ✅ 进程隔离，高可靠性
- ✅ 易于实现和维护
- ✅ 完全兼容现有系统

**实施难度**：低（1-2 天）

**风险**：低（向后兼容，可逐步启用）

**推荐配置**：
- 小型系统：`WORKER_CONCURRENCY = 2-4`
- 中型系统：`WORKER_CONCURRENCY = 4-8`
- 大型系统：`WORKER_CONCURRENCY = 8-16`

