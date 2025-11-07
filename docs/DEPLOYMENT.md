# 部署指南

本文档提供 SCNS-Conductor 在不同环境下的部署指南。

## 目录

1. [Docker Compose 部署](#docker-compose-部署)
2. [生产环境部署](#生产环境部署)
3. [鲲鹏服务器部署](#鲲鹏服务器部署)
4. [高可用配置](#高可用配置)
5. [性能调优](#性能调优)

## Docker Compose 部署

### 快速启动（开发/测试）

适用于本地开发和小规模测试。

```bash
# 1. 克隆项目
git clone <repository-url>
cd scns-conductor

# 2. 启动所有服务
docker-compose up -d

# 3. 查看日志
docker-compose logs -f

# 4. 初始化数据库（首次运行）
docker-compose exec api python scripts/init_db.py

# 5. 健康检查
docker-compose exec api python scripts/health_check.py
```

### 自定义配置

```bash
# 1. 复制示例配置
cp .env.example .env

# 2. 编辑配置
vim .env

# 3. 使用自定义配置启动
docker-compose --env-file .env up -d
```

### 常用命令

```bash
# 停止服务
docker-compose down

# 停止并删除数据卷（注意：会删除所有数据）
docker-compose down -v

# 重启特定服务
docker-compose restart api
docker-compose restart worker

# 查看服务状态
docker-compose ps

# 进入容器
docker-compose exec api bash
docker-compose exec worker bash

# 查看日志
docker-compose logs -f api
docker-compose logs -f worker
```

## 生产环境部署

### 架构图

```
                        ┌─────────────┐
                        │   Nginx     │
                        │ (反向代理)   │
                        └──────┬──────┘
                               │
                   ┌───────────┴───────────┐
                   │                       │
            ┌──────▼──────┐        ┌──────▼──────┐
            │  API 服务    │        │  API 服务    │
            │  (容器 1)    │        │  (容器 2)    │
            └──────┬──────┘        └──────┬──────┘
                   │                       │
                   └───────────┬───────────┘
                               │
                   ┌───────────▼───────────┐
                   │                       │
            ┌──────▼──────┐        ┌──────▼──────┐
            │ Worker 服务  │        │ Worker 服务  │
            │  (节点 1)    │        │  (节点 2)    │
            └──────┬──────┘        └──────┬──────┘
                   │                       │
        ┌──────────┼───────────────────────┼──────────┐
        │          │                       │          │
    ┌───▼────┐ ┌───▼────┐            ┌────▼───┐ ┌────▼───┐
    │   PG   │ │ Redis  │            │  共享   │ │  监控   │
    │ (主从)  │ │(哨兵)  │            │ 存储    │ │        │
    └────────┘ └────────┘            └────────┘ └────────┘
```

### 1. 数据库高可用（PostgreSQL 主从复制）

#### 主节点配置

```bash
# postgresql.conf
wal_level = replica
max_wal_senders = 3
max_replication_slots = 3
hot_standby = on

# pg_hba.conf
# 允许从节点复制
host replication replicator 192.168.1.0/24 md5
```

#### 从节点配置

```bash
# recovery.conf
standby_mode = 'on'
primary_conninfo = 'host=192.168.1.100 port=5432 user=replicator password=xxx'
trigger_file = '/tmp/postgresql.trigger'
```

### 2. Redis 高可用（Sentinel）

```bash
# sentinel.conf
sentinel monitor mymaster 192.168.1.100 6379 2
sentinel down-after-milliseconds mymaster 5000
sentinel parallel-syncs mymaster 1
sentinel failover-timeout mymaster 10000
```

### 3. API 服务部署

#### 使用 Docker

```bash
# 构建镜像
docker build -t scns-api:1.0.0 -f api/Dockerfile .

# 运行容器
docker run -d \
  --name scns-api-1 \
  -p 8000:8000 \
  -v /data/scns/jobs:/var/scns-conductor/jobs \
  -v /data/scns/logs:/var/log/scns-conductor \
  -e POSTGRES_HOST=pg.example.com \
  -e POSTGRES_PASSWORD=secure_password \
  -e REDIS_HOST=redis.example.com \
  scns-api:1.0.0
```

#### 使用 Systemd

创建 `/etc/systemd/system/scns-api.service`:

```ini
[Unit]
Description=SCNS-Conductor API Service
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=scns
Group=scns
WorkingDirectory=/opt/scns-conductor
Environment="PATH=/opt/scns-conductor/venv/bin"
ExecStart=/opt/scns-conductor/venv/bin/python -m uvicorn api.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
systemctl daemon-reload
systemctl enable scns-api
systemctl start scns-api
systemctl status scns-api
```

### 4. Worker 服务部署

#### 使用 Docker

```bash
# 构建镜像
docker build -t scns-worker:1.0.0 -f worker/Dockerfile .

# 运行容器
docker run -d \
  --name scns-worker-node01 \
  -v /data/scns/jobs:/var/scns-conductor/jobs \
  -v /data/scns/logs:/var/log/scns-conductor \
  -e NODE_NAME=worker-node-01 \
  -e TOTAL_CPUS=64 \
  -e POSTGRES_HOST=pg.example.com \
  -e REDIS_HOST=redis.example.com \
  scns-worker:1.0.0
```

#### 使用 Systemd

创建 `/etc/systemd/system/scns-worker.service`:

```ini
[Unit]
Description=SCNS-Conductor Worker Service
After=network.target postgresql.service redis.service

[Service]
Type=simple
User=scns
Group=scns
WorkingDirectory=/opt/scns-conductor
Environment="PATH=/opt/scns-conductor/venv/bin"
ExecStart=/opt/scns-conductor/venv/bin/python -m worker.main
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

### 5. Nginx 反向代理

创建 `/etc/nginx/sites-available/scns-conductor`:

```nginx
upstream scns_api {
    least_conn;
    server 192.168.1.101:8000 weight=1 max_fails=3 fail_timeout=30s;
    server 192.168.1.102:8000 weight=1 max_fails=3 fail_timeout=30s;
}

server {
    listen 80;
    server_name scns.example.com;

    # 重定向到 HTTPS
    return 301 https://$server_name$request_uri;
}

server {
    listen 443 ssl http2;
    server_name scns.example.com;

    ssl_certificate /etc/ssl/certs/scns.crt;
    ssl_certificate_key /etc/ssl/private/scns.key;
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_ciphers HIGH:!aNULL:!MD5;

    # 限流
    limit_req_zone $binary_remote_addr zone=api_limit:10m rate=10r/s;
    limit_req zone=api_limit burst=20 nodelay;

    # 请求体大小限制
    client_max_body_size 10M;

    # API 端点
    location / {
        proxy_pass http://scns_api;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        
        # 超时设置
        proxy_connect_timeout 60s;
        proxy_send_timeout 60s;
        proxy_read_timeout 60s;
    }

    # 健康检查端点
    location /health {
        proxy_pass http://scns_api;
        access_log off;
    }

    # 访问日志
    access_log /var/log/nginx/scns-access.log;
    error_log /var/log/nginx/scns-error.log;
}
```

启用配置：

```bash
ln -s /etc/nginx/sites-available/scns-conductor /etc/nginx/sites-enabled/
nginx -t
systemctl reload nginx
```

## 鲲鹏服务器部署

### 系统要求

- OS: openEuler 20.03 LTS 或 CentOS 7/8 (ARM64)
- Python: 3.10+ (需要从源码编译或使用兼容仓库)
- PostgreSQL: 14+ (ARM64 版本)
- Redis: 7+ (ARM64 版本)

### 安装步骤

#### 1. 安装系统依赖

```bash
# openEuler
yum install -y gcc gcc-c++ python3-devel postgresql-devel redis

# 或从源码编译 Python 3.10
wget https://www.python.org/ftp/python/3.10.13/Python-3.10.13.tgz
tar -xzf Python-3.10.13.tgz
cd Python-3.10.13
./configure --enable-optimizations --prefix=/usr/local
make -j$(nproc)
make install
```

#### 2. 安装 PostgreSQL（ARM64）

```bash
# 添加 PostgreSQL 仓库
yum install -y https://download.postgresql.org/pub/repos/yum/reporpms/EL-8-aarch64/pgdg-redhat-repo-latest.noarch.rpm

# 安装 PostgreSQL 14
yum install -y postgresql14-server postgresql14-contrib

# 初始化数据库
/usr/pgsql-14/bin/postgresql-14-setup initdb

# 启动服务
systemctl enable postgresql-14
systemctl start postgresql-14
```

#### 3. 部署应用

```bash
# 创建应用目录
mkdir -p /opt/scns-conductor
cd /opt/scns-conductor

# 克隆代码
git clone <repository-url> .

# 创建虚拟环境
python3.10 -m venv venv
source venv/bin/activate

# 安装依赖
pip install -r requirements.txt

# 配置
cp .env.example app.properties
vim app.properties

# 初始化数据库
python scripts/init_db.py

# 使用 systemd 管理服务（参考上文）
```

### 性能优化（鲲鹏特定）

```bash
# 1. 启用大页内存
echo 'vm.nr_hugepages = 128' >> /etc/sysctl.conf
sysctl -p

# 2. 调整网络参数
cat >> /etc/sysctl.conf <<EOF
net.core.somaxconn = 65535
net.ipv4.tcp_max_syn_backlog = 8192
net.core.netdev_max_backlog = 16384
EOF
sysctl -p

# 3. PostgreSQL 调优
# 编辑 /var/lib/pgsql/14/data/postgresql.conf
shared_buffers = 4GB
effective_cache_size = 12GB
maintenance_work_mem = 1GB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
random_page_cost = 1.1
effective_io_concurrency = 200
work_mem = 20MB
min_wal_size = 1GB
max_wal_size = 4GB
```

## 高可用配置

### 主备切换脚本

```bash
#!/bin/bash
# promote_standby.sh - 提升备库为主库

set -e

STANDBY_HOST="192.168.1.101"
TRIGGER_FILE="/tmp/postgresql.trigger"

echo "Promoting standby to master..."
ssh $STANDBY_HOST "touch $TRIGGER_FILE"

echo "Waiting for promotion to complete..."
sleep 5

echo "Standby promoted to master"
```

### 健康监控脚本

```bash
#!/bin/bash
# health_monitor.sh - 定期健康检查

API_URL="http://localhost:8000/health"
LOG_FILE="/var/log/scns-conductor/health.log"

while true; do
    response=$(curl -s -o /dev/null -w "%{http_code}" $API_URL)
    
    if [ "$response" -ne 200 ]; then
        echo "$(date): API health check failed (HTTP $response)" >> $LOG_FILE
        # 发送告警（邮件、钉钉等）
        # send_alert "API health check failed"
    fi
    
    sleep 60
done
```

## 性能调优

### 1. API 服务调优

```properties
# app.properties

# 增加 API workers
API_WORKERS=16

# 数据库连接池
# 在 core/database.py 中调整
pool_size=50
max_overflow=20
```

### 2. Worker 调优

```properties
# app.properties

# 增加 worker 数量（多个 worker 进程）
# 在 docker-compose.yml 中增加 worker 副本

# 或使用多个物理节点，每个节点运行一个 worker
```

### 3. 数据库调优

```sql
-- 创建额外索引（如果查询较多）
CREATE INDEX idx_job_account_state ON jobs(account, state);
CREATE INDEX idx_job_partition_state ON jobs(partition, state);

-- 定期清理
DELETE FROM jobs WHERE end_time < NOW() - INTERVAL '90 days';

-- 分析表
ANALYZE jobs;
ANALYZE resource_allocations;
```

### 4. Redis 调优

```bash
# redis.conf
maxmemory 4gb
maxmemory-policy allkeys-lru
save ""  # 禁用持久化（如果可以接受数据丢失）
```

## 监控与告警

### Prometheus + Grafana

```yaml
# prometheus.yml
scrape_configs:
  - job_name: 'scns-api'
    static_configs:
      - targets: ['api:8000']
```

### 日志聚合（ELK Stack）

```yaml
# filebeat.yml
filebeat.inputs:
  - type: log
    paths:
      - /var/log/scns-conductor/*.log
    fields:
      service: scns-conductor
output.elasticsearch:
  hosts: ["elasticsearch:9200"]
```

---

**更多部署问题请参考 GitHub Issues 或联系技术支持**

