# SCNS-Conductor v2.0

> 高性能作业调度系统 - 全新架构

## 🏗️ 架构

```
┌─────────────┐
│ API Server  │  接收作业提交
└──────┬──────┘
       │ (创建 PENDING 作业)
       ↓
┌─────────────┐
│  Scheduler  │  调度 + 分配资源 + 入队
└──────┬──────┘
       │ (Redis Queue)
       ↓
┌─────────────┐
│   Worker    │  执行作业 + 释放资源
└─────────────┘
```

### 三个独立服务

| 服务 | 职责 | 可扩展 |
|------|------|--------|
| **API** | 接收请求，创建 PENDING 作业 | ✅ 是 |
| **Scheduler** | 调度作业，分配资源，入队 | ❌ 单例 |
| **Worker** | 执行作业，释放资源 | ✅ 是 |

## 🚀 快速开始

### 1. 启动基础设施

```bash
docker-compose up postgres redis -d
```

### 2. 启动服务

```bash
# 终端 1: Scheduler
python scheduler/main.py

# 终端 2: Worker
python worker/main.py

# 终端 3: API
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### 3. 提交作业

```bash
curl -X POST http://localhost:8000/api/v1/jobs \
  -H "Content-Type: application/json" \
  -d '{
    "job": {
      "name": "hello",
      "account": "user1",
      "cpus_per_task": 2,
      "ntasks_per_node": 1
    },
    "script": "#!/bin/bash\necho Hello World\nsleep 5"
  }'
```

## 📁 目录结构

```
scns-conductor/
├── api/                    # API 服务
├── scheduler/              # 调度服务
│   ├── main.py            # 入口
│   ├── scheduler.py       # 调度器
│   └── daemon.py          # 守护进程
├── worker/                 # Worker 服务
│   ├── main.py            # 入口
│   └── executor.py        # 执行器
├── shared/                 # 共享代码
│   ├── resource_manager.py
│   └── process_utils.py
├── core/                   # 基础设施
│   ├── config.py
│   ├── database.py
│   └── models.py
└── docker-compose.yml
```

## ⚙️ 配置

编辑 `app.properties`:

```properties
# Database
POSTGRES_HOST=localhost
POSTGRES_DB=scns_conductor
POSTGRES_USER=scnsqap
POSTGRES_PASSWORD=your_password

# Redis
REDIS_HOST=localhost

# Resources
NODE_NAME=node-01
TOTAL_CPUS=8

# Paths
JOB_WORK_BASE_DIR=/path/to/jobs
SCRIPT_DIR=/path/to/scripts
```

## 🐳 Docker 部署

```bash
# 启动所有服务
docker-compose up -d

# 扩展 Worker
docker-compose up -d --scale worker=5

# 查看日志
docker-compose logs -f scheduler
```

## 📊 工作流程

```
1. 用户提交作业 → API 创建 Job (PENDING)
2. Scheduler 扫描 PENDING → 检查资源
3. 资源充足 → 分配资源 → Job (RUNNING) → 入队
4. Worker 从队列取任务 → 执行脚本
5. 执行完成 → 更新状态 → 释放资源
```

## 🔧 开发

```bash
# 安装依赖
pip install -r requirements.txt

# 运行测试
pytest tests/

# 格式化代码
black .
```

## 📖 文档

- **[📚 文档中心](docs/README.md)** - 所有文档的入口
- **[📊 项目状态](docs/PROJECT_STATUS.md)** - 项目概况和统计
- **[🔐 资源管理](docs/RESOURCE_MANAGEMENT.md)** - 资源管理设计（重要）
- [🏗️ 架构说明](docs/ARCHITECTURE.md) - 系统设计原理
- [📁 项目结构](docs/STRUCTURE.md) - 目录组织详解
- [🔄 迁移指南](docs/MIGRATION.md) - 从旧版本升级
- [💻 API 示例](docs/API_EXAMPLES.md) - 接口使用方法
- [🚀 部署指南](docs/DEPLOYMENT.md) - 生产环境部署

## 🎯 特性

✅ 职责清晰的三层架构  
✅ 独立扩展各个服务  
✅ FIFO + First Fit 调度算法  
✅ 自动资源管理  
✅ 容错机制  
✅ 生产就绪  

## 📝 版本

**v2.0.0** - 2025-11-10
- 全新架构：独立的 Scheduler 和 Worker
- 简化代码，移除历史包袱
- 清晰的目录结构

## 📄 License

MIT License
