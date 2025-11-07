.PHONY: help install dev-install clean test lint format docker-build docker-up docker-down init-db health

# Default target
help:
	@echo "SCNS-Conductor - Job Scheduling System"
	@echo ""
	@echo "Available targets:"
	@echo "  install       - Install production dependencies"
	@echo "  dev-install   - Install development dependencies"
	@echo "  clean         - Clean up generated files"
	@echo "  test          - Run tests"
	@echo "  lint          - Run linters"
	@echo "  format        - Format code"
	@echo "  docker-build  - Build Docker images"
	@echo "  docker-up     - Start Docker services"
	@echo "  docker-down   - Stop Docker services"
	@echo "  init-db       - Initialize database"
	@echo "  health        - Run health check"

install:
	pip install -r requirements.txt

dev-install:
	pip install -r requirements-dev.txt

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} +
	find . -type f -name "*.pyc" -delete
	find . -type f -name "*.pyo" -delete
	find . -type f -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage

test:
	pytest tests/ -v --cov=core --cov=api --cov=worker

lint:
	flake8 core/ api/ worker/ --max-line-length=100
	mypy core/ api/ worker/ --ignore-missing-imports

format:
	black core/ api/ worker/ scripts/ --line-length=100
	isort core/ api/ worker/ scripts/

docker-build:
	docker-compose build

docker-up:
	docker-compose up -d
	@echo "Waiting for services to be healthy..."
	@sleep 10
	@echo "Services started. Initializing database..."
	docker-compose exec api python scripts/init_db.py

docker-down:
	docker-compose down

init-db:
	python scripts/init_db.py

health:
	python scripts/health_check.py

# Development shortcuts
run-api:
	python -m uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

run-worker:
	python -m worker.main

# Database migrations
migrate:
	alembic upgrade head

migrate-create:
	alembic revision --autogenerate -m "$(msg)"

