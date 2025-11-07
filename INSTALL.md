# 🚀 安装与运行指南

> **快速开始**: 5分钟内运行起来！

---

## 📋 前置要求

- Python 3.10+
- PostgreSQL 14+
- Redis 6+
- （可选）Docker & Docker Compose

---

## 方法 1: 使用 Docker（推荐）⭐⭐⭐

### 1. 启动所有服务

```bash
# 克隆项目
git clone <your-repo-url>
cd scns-conductor

# 一键启动
docker-compose up -d

# 查看日志
docker-compose logs -f

# 查看服务状态
docker-compose ps
```

### 2. 访问服务

- API 文档: http://localhost:8000/docs
- 健康检查: http://localhost:8000/health

### 3. 停止服务

```bash
docker-compose down
```

---

## 方法 2: 本地开发环境

### 1. 安装依赖

```bash
# 创建虚拟环境（推荐使用 conda）
conda create -n sncs-conductor python=3.10
conda activate sncs-conductor

# 或使用 venv
python -m venv venv
source venv/bin/activate  # Linux/Mac
# 或 venv\Scripts\activate  # Windows

# 安装依赖
cd scns-conductor
pip install -r requirements.txt

# 如果遇到 greenlet 缺失错误，手动安装
pip install greenlet==3.0.3
```

### 2. 启动 PostgreSQL 和 Redis

#### 使用 Docker（推荐）

```bash
# 只启动数据库和 Redis
docker-compose up -d postgres redis
```

#### 或手动安装

```bash
# macOS
brew install postgresql redis
brew services start postgresql
brew services start redis

# Ubuntu/Debian
sudo apt-get install postgresql redis-server
sudo systemctl start postgresql
sudo systemctl start redis-server
```

### 3. 配置数据库

```bash
# 复制配置文件
cp app.properties.example app.properties

# 编辑配置
vim app.properties
```

**重要配置项**:

```properties
# 数据库配置
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=scns_conductor
POSTGRES_USER=your_user
POSTGRES_PASSWORD=your_password

# Redis 配置
REDIS_HOST=localhost
REDIS_PORT=6379

# 路径配置（开发环境使用相对路径）
JOB_WORK_BASE_DIR=./data/jobs
SCRIPT_DIR=./data/scripts
LOG_FILE=  # 留空，输出到控制台
```

### 4. 初始化数据库

```bash
# 创建数据库表
python scripts/init_db.py
```

### 5. 启动服务

#### 启动 API 服务

```bash
# 方法 1: 使用 uvicorn（推荐）
python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# 方法 2: 直接运行（需要设置 PYTHONPATH）
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
python -m uvicorn api.main:app --reload

# 方法 3: 使用 Makefile
make run-api
```

#### 启动 Worker 服务（新终端）

```bash
# 激活虚拟环境
conda activate sncs-conductor

# 启动 Worker
python -m worker.main

# 或使用 Makefile
make run-worker
```

### 6. 验证服务

```bash
# 健康检查
curl http://localhost:8000/health

# API 文档
open http://localhost:8000/docs
```

---

## 🐛 常见问题

### 问题 1: ModuleNotFoundError: No module named 'core'

**原因**: Python 找不到项目模块

**解决方案**:

```bash
# 方法 1: 从项目根目录运行
cd /path/to/scns-conductor
python -m uvicorn api.main:app --reload

# 方法 2: 设置 PYTHONPATH
export PYTHONPATH="${PYTHONPATH}:$(pwd)"
```

### 问题 2: No module named 'greenlet'

**原因**: 缺少 SQLAlchemy 异步支持库

**解决方案**:

```bash
pip install greenlet==3.0.3
```

### 问题 3: Permission denied: '/var/log/scns-conductor'

**原因**: 没有写入 /var/log 的权限

**解决方案**:

编辑 `app.properties`:

```properties
# 注释掉或留空，使用控制台输出
LOG_FILE=
```

### 问题 4: password authentication failed for user

**原因**: 数据库用户名或密码错误

**解决方案**:

1. 检查 `app.properties` 中的数据库配置
2. 确认 PostgreSQL 用户存在并有权限

```bash
# 创建用户和数据库
psql postgres
CREATE USER scnsqap WITH PASSWORD 'Abcd123456';
CREATE DATABASE scns_conductor OWNER scnsqap;
```

### 问题 5: Connection refused (Redis)

**原因**: Redis 未启动

**解决方案**:

```bash
# macOS
brew services start redis

# Linux
sudo systemctl start redis-server

# 或使用 Docker
docker-compose up -d redis
```

---

## 📚 VSCode 调试配置

创建 `.vscode/launch.json`:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "API Server",
            "type": "python",
            "request": "launch",
            "module": "uvicorn",
            "args": [
                "api.main:app",
                "--reload",
                "--host",
                "0.0.0.0",
                "--port",
                "8000"
            ],
            "cwd": "${workspaceFolder}",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        },
        {
            "name": "Worker",
            "type": "python",
            "request": "launch",
            "module": "worker.main",
            "cwd": "${workspaceFolder}",
            "env": {
                "PYTHONPATH": "${workspaceFolder}"
            }
        }
    ]
}
```

---

## 🧪 运行测试

```bash
# 安装测试依赖
pip install -r requirements-dev.txt

# 运行测试
pytest

# 带覆盖率
pytest --cov=. --cov-report=html
```

---

## 📦 生产部署

### 使用 Docker Compose（推荐）

```bash
# 构建镜像
docker-compose build

# 启动服务
docker-compose up -d

# 查看日志
docker-compose logs -f api worker

# 扩展 Worker 数量
docker-compose up -d --scale worker=3
```

### 使用 systemd

创建服务文件 `/etc/systemd/system/scns-api.service`:

```ini
[Unit]
Description=SCNS-Conductor API Service
After=network.target postgresql.service redis.service

[Service]
Type=notify
User=scns
Group=scns
WorkingDirectory=/opt/scns-conductor
Environment="PYTHONPATH=/opt/scns-conductor"
ExecStart=/opt/scns-conductor/venv/bin/uvicorn api.main:app --host 0.0.0.0 --port 8000
Restart=always

[Install]
WantedBy=multi-user.target
```

启动服务:

```bash
sudo systemctl daemon-reload
sudo systemctl enable scns-api
sudo systemctl start scns-api
sudo systemctl status scns-api
```

---

## 🔧 环境变量说明

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `POSTGRES_HOST` | 数据库主机 | localhost |
| `POSTGRES_PORT` | 数据库端口 | 5432 |
| `POSTGRES_DB` | 数据库名称 | scns_conductor |
| `POSTGRES_USER` | 数据库用户 | scnsqap |
| `REDIS_HOST` | Redis 主机 | localhost |
| `REDIS_PORT` | Redis 端口 | 6379 |
| `API_HOST` | API 监听地址 | 0.0.0.0 |
| `API_PORT` | API 监听端口 | 8000 |
| `TOTAL_CPUS` | 可用 CPU 核心数 | 64 |
| `LOG_LEVEL` | 日志级别 | INFO |

---

## 📞 获取帮助

- **文档**: [docs/INDEX.md](docs/INDEX.md)
- **API 示例**: [docs/API_EXAMPLES.md](docs/API_EXAMPLES.md)
- **故障排查**: [docs/ERRATUM.md](docs/ERRATUM.md)

---

**更新日期**: 2025-11-07  
**版本**: v1.0.0

