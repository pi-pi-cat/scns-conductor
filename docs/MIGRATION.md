# 迁移指南 - v2.0

## 🎯 重大变更

### 架构重构

**旧结构**（混乱）:
```
worker/
  - main.py (包含调度逻辑)
  - core/
    - scheduler.py
    - executor.py
    - daemon.py
  - services/
  - utils/
scheduler_service.py (根目录)
```

**新结构**（清晰）:
```
scheduler/          # 调度服务（独立）
  - main.py
  - scheduler.py
  - daemon.py

worker/             # Worker 服务（独立）
  - main.py
  - executor.py

shared/             # 共享代码
  - resource_manager.py
  - process_utils.py
```

## 🚀 迁移步骤

### 1. 停止旧服务

```bash
# 停止所有运行的服务
pkill -f "worker/main.py"
pkill -f "scheduler_service.py"
pkill -f "uvicorn api.main"
```

### 2. 更新代码

```bash
git pull
# 或
# 直接使用新代码
```

### 3. 启动新服务

```bash
# 方式 1: 使用 Makefile
make dev-infra         # 启动基础设施
make dev-scheduler     # 终端 1
make dev-worker        # 终端 2
make dev-api           # 终端 3

# 方式 2: 直接运行
python scheduler/main.py
python worker/main.py
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

## 📦 Docker 部署

```bash
# 停止旧服务
docker-compose down

# 启动新服务
docker-compose up -d

# 检查状态
docker-compose ps
docker-compose logs -f
```

## 🔧 配置变更

### 废弃的配置

- `WORKER_CONCURRENCY` - 不再需要，Worker 可独立扩展

### 保持不变

```properties
POSTGRES_HOST=localhost
REDIS_HOST=localhost
NODE_NAME=node-01
TOTAL_CPUS=8
JOB_WORK_BASE_DIR=/path/to/jobs
SCRIPT_DIR=/path/to/scripts
```

## 📝 代码变更

### 调度服务

**旧代码** (已删除):
- `scheduler_service.py`
- `worker/core/scheduler.py`
- `worker/core/daemon.py`

**新代码**:
- `scheduler/main.py`
- `scheduler/scheduler.py`
- `scheduler/daemon.py`

### Worker 服务

**旧代码** (已删除):
- `worker/main.py` (复杂的多进程版本)
- `worker/core/executor.py`

**新代码**:
- `worker/main.py` (简化版本)
- `worker/executor.py`

### 共享代码

**旧代码** (已移动):
- `worker/services/resource_manager.py`
- `worker/utils/process_utils.py`
- `worker/utils/signal_handler.py`

**新代码**:
- `shared/resource_manager.py`
- `shared/process_utils.py`

## ✅ 验证迁移

### 1. 检查服务运行

```bash
# 检查进程
ps aux | grep "scheduler/main.py"
ps aux | grep "worker/main.py"
ps aux | grep "uvicorn"

# Docker 检查
docker-compose ps
```

### 2. 提交测试作业

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job": {
      "name": "migration-test",
      "account": "test",
      "cpus_per_task": 1,
      "ntasks_per_node": 1
    },
    "script": "#!/bin/bash\necho Migration successful!\nsleep 5"
  }'
```

### 3. 查看日志

```bash
# Scheduler 日志
tail -f logs/scheduler.log

# Worker 日志
tail -f logs/worker.log

# Docker 日志
docker-compose logs -f scheduler
docker-compose logs -f worker
```

### 4. 验证作业流程

1. ✅ 作业创建为 PENDING
2. ✅ Scheduler 日志显示调度成功
3. ✅ 作业状态变为 RUNNING
4. ✅ Worker 日志显示执行中
5. ✅ 作业状态变为 COMPLETED
6. ✅ 资源正确释放

## 🐛 常见问题

### Q: 找不到模块

确保 Python 路径正确：
```python
# scheduler/main.py 和 worker/main.py 都包含：
sys.path.insert(0, str(Path(__file__).parent.parent))
```

### Q: Scheduler 不调度作业

1. 检查 Scheduler 是否运行
2. 查看日志是否有错误
3. 确认资源充足

### Q: Worker 无法执行作业

1. 检查 RQ 队列名称是否一致
2. 确认作业状态为 RUNNING
3. 检查 Worker 是否连接到正确的 Redis

## 🎉 迁移完成

迁移后的系统具有以下优势：

✅ **清晰的目录结构** - scheduler/ worker/ shared/  
✅ **独立的服务** - 可分别扩展  
✅ **简化的代码** - 移除历史包袱  
✅ **更好的可维护性** - 职责清晰  

---

**版本**: v2.0  
**日期**: 2025-11-10

