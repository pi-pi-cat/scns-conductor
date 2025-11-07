# SCNS-Conductor

**轻量级、高可靠的作业调度系统** - 专为鲲鹏（ARM）架构优化

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## 📚 文档导航

**完整技术文档**: 👉 **[docs/INDEX.md](docs/INDEX.md)** ⭐⭐⭐

### 🚀 快速开始

| 文档 | 说明 |
|------|------|
| [API 使用示例](docs/API_EXAMPLES.md) | 5分钟快速上手 |
| [部署指南](docs/DEPLOYMENT.md) | Docker 一键部署 |
| [项目结构](docs/PROJECT_STRUCTURE.md) | 代码组织结构 |

### 🏗️ 核心架构

| 文档 | 说明 |
|------|------|
| [系统架构](docs/ARCHITECTURE.md) | 整体架构设计 |
| [Worker 并发模型](docs/WORKER_CONCURRENCY.md) | 并发机制详解 |
| [故障容错机制](docs/FAULT_TOLERANCE_SUMMARY.md) | 可靠性保证 |

### 🔧 最新更新

| 文档 | 说明 |
|------|------|
| [勘误报告](docs/ERRATUM.md) | 代码审查与修复 🆕 |
| [Worker 优化](docs/WORKER_MODULE_OPTIMIZATION_SUMMARY.md) | 性能优化总结 |
| [更新总结](docs/FINAL_UPDATE_SUMMARY.md) | v1.0.0 完整更新 |

---

## 🎯 项目简介

SCNS-Conductor 是一个现代化的作业调度和管理系统，设计用于自动化管理计算密集型作业的完整生命周期。系统采用类似 Slurm 的 RESTful API 风格，提供简洁高效的作业提交、查询和取消接口。

### ✨ 核心特性

- ✅ **RESTful API** - 清晰的 HTTP 接口，易于集成
- ✅ **异步高性能** - FastAPI + asyncpg 异步架构
- ✅ **智能调度** - FIFO + First Fit 资源调度算法
- ✅ **高可靠性** - PostgreSQL 持久化，RQ 任务队列
- ✅ **故障恢复** - 服务重启自动恢复状态
- ✅ **ARM 优化** - 完全支持鲲鹏（aarch64）架构
- ✅ **容器化** - Docker 镜像，开箱即用

---

## 🏗️ 系统架构

```
┌─────────────────┐
│   Client/User   │
└────────┬────────┘
         │ REST API
         ▼
┌─────────────────────────────┐
│   FastAPI Service (Async)   │
│   - Submit Jobs             │
│   - Query Status            │
│   - Cancel Jobs             │
└────────┬────────────────────┘
         │
         ▼
┌──────────────────────────────────────┐
│         PostgreSQL Database          │
│  - Jobs Table                        │
│  - Resource Allocations              │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│           Redis + RQ Queue           │
└──────────────┬───────────────────────┘
               │
               ▼
┌──────────────────────────────────────┐
│        Worker Service (Sync)         │
│  ┌────────────────────────────────┐  │
│  │    Scheduler Daemon (线程)     │  │
│  │  - 监控PENDING作业              │  │
│  │  - FIFO + First Fit调度        │  │
│  │  - 分配CPU资源                  │  │
│  └────────────────────────────────┘  │
│  ┌────────────────────────────────┐  │
│  │      RQ Worker (线程池)        │  │
│  │  - 执行作业脚本                 │  │
│  │  - 监控作业状态                 │  │
│  │  - 资源管理                     │  │
│  └────────────────────────────────┘  │
└──────────────────────────────────────┘
```

**详细架构**: 查看 [系统架构文档](docs/ARCHITECTURE.md)

---

## 🚀 快速开始

### 前置要求

- Docker & Docker Compose
- Python 3.10+（开发环境）

### 一键部署

```bash
# 1. 克隆项目
git clone https://github.com/your-org/scns-conductor.git
cd scns-conductor

# 2. 启动服务
docker-compose up -d

# 3. 检查服务状态
docker-compose ps

# 4. 查看日志
docker-compose logs -f api worker
```

**完整部署指南**: 查看 [部署文档](docs/DEPLOYMENT.md)

### API 快速示例

#### 提交作业

```bash
curl -X POST http://localhost:8000/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "job": {
      "name": "test-job",
      "account": "user1",
      "partition": "default",
      "ntasks_per_node": 1,
      "cpus_per_task": 4,
      "memory_per_node": "8G",
      "time_limit": "60",
      "current_working_directory": "/tmp/jobs",
      "standard_output": "stdout.txt",
      "standard_error": "stderr.txt"
    },
    "script": "#!/bin/bash\necho \"Hello World\"\nsleep 10"
  }'
```

#### 查询作业

```bash
curl http://localhost:8000/jobs/query/1001
```

#### 取消作业

```bash
curl -X POST http://localhost:8000/jobs/cancel/1001
```

**更多示例**: 查看 [API 示例文档](docs/API_EXAMPLES.md)

---

## 📁 项目结构

```
scns-conductor/
├── api/                    # FastAPI 服务
│   ├── main.py            # 应用入口
│   ├── routers/           # API 路由
│   ├── services/          # 业务逻辑
│   └── schemas/           # 数据模型
├── worker/                # Worker 服务
│   ├── main.py            # Worker 入口
│   ├── scheduler.py       # 调度器
│   ├── executor.py        # 执行器
│   ├── recovery.py        # 故障恢复
│   └── observers.py       # 观察者模式
├── core/                  # 核心模块
│   ├── config.py          # 配置管理
│   ├── database.py        # 数据库连接
│   ├── models.py          # ORM 模型
│   └── redis_client.py    # Redis 客户端
├── scripts/               # 运维脚本
├── migrations/            # 数据库迁移
├── docs/                  # 📚 完整文档
│   ├── INDEX.md          # 文档导航中心 ⭐
│   ├── README.md         # 文档总览
│   └── ...               # 详细技术文档
├── docker-compose.yml     # Docker 编排
└── requirements.txt       # Python 依赖
```

**详细说明**: 查看 [项目结构文档](docs/PROJECT_STRUCTURE.md)

---

## 🔧 核心功能

### 作业管理

- ✅ 作业提交（RESTful API）
- ✅ 作业查询（状态、日志、资源）
- ✅ 作业取消（优雅终止）
- ✅ 作业历史记录

### 资源调度

- ✅ FIFO（先进先出）调度
- ✅ First Fit 资源分配
- ✅ CPU 资源管理
- ✅ 资源利用率监控

### 可靠性保障

- ✅ 数据库持久化
- ✅ Worker 重启恢复
- ✅ 孤儿作业检测
- ✅ 进程监控

### 监控与日志

- ✅ 结构化日志（Loguru）
- ✅ 请求追踪（Request ID）
- ✅ 资源监控
- ✅ 健康检查接口

**详细功能**: 查看 [功能文档](docs/ARCHITECTURE.md)

---

## 📊 技术栈

### 后端框架

- **FastAPI** - 现代化异步 Web 框架
- **SQLModel** - 数据库 ORM（SQLAlchemy + Pydantic）
- **Pydantic** - 数据验证

### 数据存储

- **PostgreSQL** - 关系型数据库
- **Redis** - 缓存和消息队列

### 任务队列

- **RQ (Redis Queue)** - Python 任务队列

### 日志监控

- **Loguru** - 结构化日志

### 部署工具

- **Docker** - 容器化
- **Docker Compose** - 服务编排
- **Alembic** - 数据库迁移

---

## 🔍 工作原理

### 作业生命周期

```
1. 提交 (PENDING)
   ↓
   用户通过 API 提交作业
   作业写入数据库，状态为 PENDING
   作业入队到 RQ
   
2. 调度 (SCHEDULING)
   ↓
   Scheduler Daemon 周期性检查 PENDING 作业
   检查资源是否满足（CPU）
   分配资源，更新状态为 RUNNING
   
3. 执行 (RUNNING)
   ↓
   RQ Worker 接收任务
   Executor 执行作业脚本（subprocess）
   监控作业进程
   收集输出日志
   
4. 完成 (COMPLETED/FAILED)
   ↓
   更新作业状态
   释放资源
   记录退出码
```

**详细流程**: 查看 [Worker 并发模型](docs/WORKER_CONCURRENCY.md)

---

## 🛡️ 故障容错

### 故障恢复机制

- ✅ Worker 重启时自动检测孤儿作业
- ✅ 进程存活检测（os.kill(pid, 0)）
- ✅ 资源泄漏防护
- ✅ 数据库状态一致性保证

### 已知问题与修复

查看 [勘误报告](docs/ERRATUM.md) 了解已修复的问题。

**详细说明**: 查看 [故障容错文档](docs/FAULT_TOLERANCE_SUMMARY.md)

---

## 📈 性能特点

### 并发能力

- 单 Worker 支持多作业并发执行
- 资源池动态管理（64核示例可并发8-64个作业）
- 异步 I/O 提升 API 吞吐

### 资源利用

- FIFO + First Fit 算法保证公平性
- 资源实时监控
- 自动资源回收

**性能分析**: 查看 [Worker 并发模型](docs/WORKER_CONCURRENCY.md)

---

## 🔐 安全性

- ✅ 进程隔离（subprocess + process group）
- ✅ 用户权限隔离（account 字段）
- ✅ 资源配额限制
- ✅ API 参数验证（Pydantic）

---

## 🧪 开发与测试

### 开发环境

```bash
# 安装依赖
pip install -r requirements.txt
pip install -r requirements-dev.txt

# 启动数据库和 Redis
docker-compose up -d postgres redis

# 初始化数据库
python scripts/init_db.py

# 启动 API 服务
python -m uvicorn api.main:app --reload

# 启动 Worker
python -m worker.main
```

### 运维脚本

```bash
# 健康检查
python scripts/health_check.py

# 清理僵尸作业
python scripts/cleanup.py
```

---

## 📝 配置说明

配置文件：`app.properties`

```properties
# 数据库配置
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=scns_conductor
POSTGRES_USER=scns_user
POSTGRES_PASSWORD=your_password

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_DB=0

# Worker 配置
NODE_NAME=node-1
TOTAL_CPUS=64

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=/var/log/scns-conductor/app.log
```

---

## 📚 文档资源

### 核心文档

- **[文档导航中心](docs/INDEX.md)** - 所有文档索引 ⭐
- **[系统架构](docs/ARCHITECTURE.md)** - 架构设计
- **[API 示例](docs/API_EXAMPLES.md)** - 使用示例
- **[部署指南](docs/DEPLOYMENT.md)** - 部署说明

### 改进记录

- **[Worker 优化](docs/WORKER_MODULE_OPTIMIZATION_SUMMARY.md)** - 最新优化
- **[更新总结](docs/FINAL_UPDATE_SUMMARY.md)** - 完整更新
- **[勘误报告](docs/ERRATUM.md)** - 问题修复

### 更多文档

查看 [docs/INDEX.md](docs/INDEX.md) 获取完整文档列表。

---

## 🤝 贡献指南

欢迎贡献代码、文档或建议！

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

---

## 📄 许可证

本项目采用 MIT 许可证。详见 [LICENSE](LICENSE) 文件。

---

## 📞 联系方式

- **项目主页**: [GitHub Repository](#)
- **问题反馈**: [Issues](#)
- **文档中心**: [docs/INDEX.md](docs/INDEX.md)

---

## 🙏 致谢

感谢所有贡献者和使用者！

---

**版本**: v1.0.0  
**更新日期**: 2025-11-07  
**维护状态**: ✅ 积极维护中
