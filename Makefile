# SCNS-Conductor Makefile

.PHONY: help dev prod stop clean

help:  ## 显示帮助信息
	@echo "SCNS-Conductor v2.0 - 可用命令:"
	@echo ""
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'
	@echo ""

# 开发环境
dev-infra:  ## 启动基础设施（Postgres + Redis）
	docker-compose up postgres redis -d

dev-scheduler:  ## 启动 Scheduler
	python scheduler/main.py

dev-worker:  ## 启动 Worker
	python worker/main.py

dev-api:  ## 启动 API
	uvicorn api.main:app --host 0.0.0.0 --port 8000 --reload

# 生产环境
prod:  ## 启动所有服务（生产模式）
	docker-compose up -d

prod-scale:  ## 扩展 Worker (使用: make prod-scale N=5)
	docker-compose up -d --scale worker=$(N)

# 管理
stop:  ## 停止所有服务
	docker-compose down

logs:  ## 查看日志
	docker-compose logs -f

logs-scheduler:  ## 查看 Scheduler 日志
	docker-compose logs -f scheduler

logs-worker:  ## 查看 Worker 日志
	docker-compose logs -f worker

logs-api:  ## 查看 API 日志
	docker-compose logs -f api

# 清理
clean:  ## 清理所有容器和卷
	docker-compose down -v

# 数据库
db-init:  ## 初始化数据库
	python scripts/init_db.py

db-migrate:  ## 运行数据库迁移
	alembic upgrade head

# 开发
format:  ## 格式化代码
	black .

lint:  ## 检查代码
	flake8 .
	mypy .

test:  ## 运行测试
	pytest tests/

# 默认命令
.DEFAULT_GOAL := help
