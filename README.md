# SCNS-Conductor

**轻量级、高可靠的作业调度系统** - 专为鲲鹏（ARM）架构优化

[![Python](https://img.shields.io/badge/Python-3.10-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104-green.svg)](https://fastapi.tiangolo.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 📚 文档导航

**完整技术文档请访问**: [docs/README.md](docs/README.md) ⭐

快速链接：
- 🔥 [Worker模块优化总结](docs/WORKER_MODULE_OPTIMIZATION_SUMMARY.md) ⭐⭐⭐ **NEW!**
- 🔥 [Worker并发模型详解](docs/WORKER_CONCURRENCY.md)
- 🔥 [故障容错机制](docs/FAULT_TOLERANCE_SUMMARY.md)  
- 🔥 [API使用示例](docs/API_EXAMPLES.md)
- 🔥 [Worker模块改进详解](docs/WORKER_IMPROVEMENTS_DONE.md) ⭐⭐
- 🔥 [API模块改进详解](docs/API_IMPROVEMENTS_DONE.md)
- 🔥 [部署指南](docs/DEPLOYMENT.md)
- 📋 [最终更新总结](docs/FINAL_UPDATE_SUMMARY.md)

---

## 🎯 项目简介

SCNS-Conductor 是一个现代化的作业调度和管理系统，设计用于自动化管理计算密集型作业的完整生命周期。系统采用类似 Slurm 的 RESTful API 风格，提供简洁高效的作业提交、查询和取消接口。

### 核心特性

- ✅ **RESTful API** - 清晰的 HTTP 接口，易于集成
- ✅ **异步高性能** - FastAPI + asyncpg 异步架构
- ✅ **智能调度** - FIFO + First Fit 资源调度算法
- ✅ **高可靠性** - PostgreSQL 持久化，RQ 任务队列
- ✅ **可重启性** - 服务重启自动恢复状态
- ✅ **ARM 优化** - 完全支持鲲鹏（aarch64）架构
- ✅ **容器化** - Docker 镜像，开箱即用

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
└──┬──────────┬───────────┬───┘
   │          │           │
   ▼          ▼           ▼
┌──────┐ ┌───────┐ ┌──────────┐
│ PG   │ │ Redis │ │   Logs   │
│ DB   │ │  RQ   │ │ (Files)  │
└──────┘ └───┬───┘ └──────────┘
             │
             ▼
      ┌─────────────┐
      │ RQ Workers  │
      │  + Scheduler│
      └─────────────┘
```

## 🚀 快速开始

### 前置要求

- Python 3.10+
- PostgreSQL 14+
- Redis 7+
- Docker & Docker Compose (可选)

### 方式一：Docker 部署（推荐）

```bash
# 1. 克隆项目
git clone <repository-url>
cd scns-conductor

# 2. 启动所有服务
make docker-up

# 3. 检查健康状态
make health
```

服务启动后：
- API 服务: http://localhost:8000
- API 文档: http://localhost:8000/docs
- PostgreSQL: localhost:5432
- Redis: localhost:6379

### 方式二：本地开发

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境
cp .env.example app.properties
# 编辑 app.properties，配置数据库和 Redis 连接

# 3. 初始化数据库
python scripts/init_db.py

# 4. 启动 API 服务
make run-api

# 5. 启动 Worker（另一个终端）
make run-worker
```

## 📚 API 使用指南

### 1. 提交作业

```bash
curl -X POST http://localhost:8000/jobs/submit \
  -H "Content-Type: application/json" \
  -d '{
    "job": {
      "account": "project_alpha",
      "environment": {
        "PATH": "/opt/myapp/bin:/usr/local/bin"
      },
      "current_working_directory": "/tmp/test",
      "standard_output": "output.log",
      "standard_error": "error.log",
      "ntasks_per_node": 1,
      "cpus_per_task": 2,
      "memory_per_node": "4G",
      "name": "test_job",
      "time_limit": "30",
      "partition": "default",
      "exclusive": false
    },
    "script": "#!/bin/bash\necho \"Hello World\"\nsleep 10\necho \"Done\""
  }'
```

**响应：**
```json
{
  "job_id": "1001"
}
```

### 2. 查询作业状态

```bash
curl http://localhost:8000/jobs/query/1001
```

**响应：**
```json
{
  "job_id": "1001",
  "state": "RUNNING",
  "error_msg": null,
  "time": {
    "submit_time": "2025-11-07T10:20:30Z",
    "start_time": "2025-11-07T10:20:35Z",
    "end_time": null,
    "eligible_time": "2025-11-07T10:20:30Z",
    "elapsed_time": "0-00:05:20",
    "limit_time": "30:00"
  },
  "job_log": {
    "stdout": "Hello World\n",
    "stderr": ""
  },
  "detail": {
    "job_name": "test_job",
    "user": "project_alpha",
    "partition": "default",
    "allocated_cpus": 2,
    "allocated_nodes": 1,
    "node_list": "worker-node-01",
    "exit_code": ":",
    "work_dir": "/tmp/test",
    "data_source": "API",
    "account": "project_alpha"
  }
}
```

### 3. 取消作业

```bash
curl -X POST http://localhost:8000/jobs/cancel/1001
```

**响应：**
```json
{
  "msg": "取消成功"
}
```

## 🔧 配置说明

编辑 `app.properties` 文件：

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

# 资源配置
NODE_NAME=kunpeng-node-01
TOTAL_CPUS=64                    # 节点总 CPU 核心数
DEFAULT_PARTITION=compute-high-mem

# 日志配置
LOG_LEVEL=INFO
LOG_FILE=/var/log/scns-conductor/app.log

# 作业路径配置
JOB_WORK_BASE_DIR=/var/scns-conductor/jobs
SCRIPT_DIR=/var/scns-conductor/scripts
```

## 📁 项目结构

```
scns-conductor/
├── api/                    # API 服务
│   ├── main.py            # FastAPI 应用入口
│   ├── routers/           # 路由定义
│   ├── schemas/           # Pydantic 数据模型
│   ├── services/          # 业务逻辑层
│   └── Dockerfile         # API Docker 镜像
│
├── worker/                # Worker 服务
│   ├── main.py           # Worker 入口
│   ├── executor.py       # 作业执行器
│   ├── scheduler.py      # 调度器
│   ├── resource_tracker.py  # 资源跟踪
│   └── Dockerfile        # Worker Docker 镜像
│
├── core/                 # 核心共享模块
│   ├── config.py         # 配置管理
│   ├── database.py       # 数据库连接
│   ├── redis_client.py   # Redis 连接
│   ├── models.py         # 数据模型
│   └── utils/            # 工具函数
│
├── scripts/              # 运维脚本
│   ├── init_db.py        # 数据库初始化
│   ├── health_check.py   # 健康检查
│   └── cleanup.py        # 清理脚本
│
├── migrations/           # 数据库迁移
├── docker-compose.yml    # Docker 编排
└── Makefile             # 常用命令
```

## 🛠️ 开发指南

### 运行测试

```bash
make test
```

### 代码检查

```bash
make lint
```

### 代码格式化

```bash
make format
```

### 数据库迁移

```bash
# 生成迁移脚本
make migrate-create msg="add new field"

# 应用迁移
make migrate
```

## 📊 监控与维护

### 健康检查

```bash
# 检查所有服务状态
python scripts/health_check.py

# 或使用 HTTP 端点
curl http://localhost:8000/health
```

### 清理任务

```bash
# 清理陈旧的资源和作业
python scripts/cleanup.py
```

### 日志查看

```bash
# Docker 环境
docker-compose logs -f api
docker-compose logs -f worker

# 本地开发
tail -f /var/log/scns-conductor/app.log
```

## 🔐 安全建议

1. **生产环境配置**
   - 修改默认密码
   - 使用强密码策略
   - 启用 PostgreSQL SSL 连接
   - 配置 Redis AUTH

2. **网络安全**
   - 使用防火墙限制端口访问
   - 仅暴露必要的服务端口
   - 考虑使用 API 网关

3. **权限控制**
   - 限制作业执行用户权限
   - 隔离作业工作目录
   - 定期审计作业日志

## 🐛 故障排查

### API 服务无法启动

```bash
# 检查数据库连接
python scripts/health_check.py

# 查看日志
docker-compose logs api
```

### Worker 不执行作业

```bash
# 检查 Redis 连接
redis-cli ping

# 检查资源配置
# 确认 TOTAL_CPUS 配置正确

# 查看 Worker 日志
docker-compose logs worker
```

### 作业卡在 PENDING 状态

```bash
# 检查资源是否充足
# 当前可用 CPU < 作业请求 CPU 时会等待

# 查看资源使用情况
python scripts/health_check.py
```

## 🤝 贡献指南

欢迎提交 Issue 和 Pull Request！

1. Fork 本项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 提交 Pull Request

## 📝 版本历史

- **v1.0.0** (2025-11-07)
  - 初始版本发布
  - 支持作业提交、查询、取消
  - FIFO + First Fit 调度算法
  - Docker 容器化部署

## 📄 许可证

本项目采用 MIT 许可证 - 详见 [LICENSE](LICENSE) 文件

## 🙏 致谢

- [FastAPI](https://fastapi.tiangolo.com/) - 现代化的 Web 框架
- [SQLAlchemy](https://www.sqlalchemy.org/) - Python SQL 工具包
- [RQ](https://python-rq.org/) - 简单的任务队列
- [Loguru](https://github.com/Delgan/loguru) - 优雅的日志库

## 📧 联系方式

如有问题或建议，请通过以下方式联系：

- 提交 Issue: [GitHub Issues](https://github.com/your-repo/issues)
- 邮件: your-email@example.com

---

**Built with ❤️ for High-Performance Computing on ARM Architecture**

