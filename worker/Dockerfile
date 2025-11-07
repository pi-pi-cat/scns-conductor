# Worker 服务 Dockerfile
# 针对 ARM/aarch64（鲲鹏）架构优化

FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖，包括用于脚本执行的 bash
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    bash \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 优先复制 requirements.txt 以优化缓存
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY core/ ./core/
COPY worker/ ./worker/
COPY app.properties .

# 创建必要的目录
RUN mkdir -p /var/log/scns-conductor /var/scns-conductor/jobs /var/scns-conductor/scripts

# 启动 worker 服务
CMD ["python", "-m", "worker.main"]

