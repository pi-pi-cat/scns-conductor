# API 服务 Dockerfile
# 针对 ARM/aarch64（鲲鹏）架构优化

FROM python:3.10-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# 优化镜像层缓存，优先拷贝依赖文件
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install --no-cache-dir -r requirements.txt

# 拷贝应用代码
COPY core/ ./core/
COPY api/ ./api/
COPY app.properties .

# 创建日志和作业所需目录
RUN mkdir -p /var/log/scns-conductor /var/scns-conductor/jobs /var/scns-conductor/scripts

# 暴露 API 端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# 启动 API 服务
CMD ["python", "-m", "uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

