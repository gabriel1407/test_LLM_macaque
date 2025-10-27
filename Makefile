# Makefile for LLM Summarizer Service
# Provides convenient commands for development and deployment

.PHONY: help install dev test lint format clean build run docker-dev docker-prod deploy

# Default target
help:
	@echo "LLM Summarizer Service - Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  install     - Install dependencies"
	@echo "  dev         - Run development server"
	@echo "  test        - Run tests"
	@echo "  lint        - Run linting"
	@echo "  format      - Format code"
	@echo "  clean       - Clean temporary files"
	@echo ""
	@echo "Docker:"
	@echo "  docker-dev  - Start development environment with Redis"
	@echo "  docker-prod - Start production environment"
	@echo "  build       - Build Docker image"
	@echo "  run         - Run Docker container"
	@echo ""
	@echo "Deployment:"
	@echo "  deploy      - Deploy to production"
	@echo "  logs        - View application logs"
	@echo "  status      - Check service status"

# Development commands
install:
	@echo "Installing dependencies..."
	pip install -r requirements.txt

dev:
	@echo "Starting development server..."
	uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

test:
	@echo "Running tests..."
	pytest tests/ -v --cov=app --cov-report=html --cov-report=term

lint:
	@echo "Running linting..."
	flake8 app/
	mypy app/

format:
	@echo "Formatting code..."
	black app/
	isort app/

clean:
	@echo "Cleaning temporary files..."
	find . -type f -name "*.pyc" -delete
	find . -type d -name "__pycache__" -delete
	find . -type d -name "*.egg-info" -exec rm -rf {} +
	rm -rf .pytest_cache
	rm -rf .coverage
	rm -rf htmlcov/
	rm -rf dist/
	rm -rf build/

# Docker commands
docker-dev:
	@echo "Starting development environment..."
	docker-compose -f docker-compose.dev.yml up -d
	@echo "Redis is running on localhost:6379"
	@echo "Redis Commander available at http://localhost:8081 (admin/dev123)"

docker-prod:
	@echo "Starting production environment..."
	docker-compose up -d
	@echo "API available at http://localhost:8000"
	@echo "Redis Commander available at http://localhost:8081 (admin/admin123)"

build:
	@echo "Building Docker image..."
	docker build -t llm-summarizer:latest .

build-dev:
	@echo "Building development Docker image..."
	docker build --target development -t llm-summarizer:dev .

run:
	@echo "Running Docker container..."
	docker run -p 8000:8000 --env-file .env llm-summarizer:latest

# Deployment commands
deploy:
	@echo "Deploying to production..."
	@echo "Make sure to set environment variables in .env"
	docker-compose down
	docker-compose pull
	docker-compose up -d
	@echo "Deployment complete!"

logs:
	@echo "Viewing application logs..."
	docker-compose logs -f api

logs-redis:
	@echo "Viewing Redis logs..."
	docker-compose logs -f redis

status:
	@echo "Checking service status..."
	docker-compose ps
	@echo ""
	@echo "Health check:"
	curl -f http://localhost:8000/v1/healthz || echo "Service not responding"

# Database/Cache commands
redis-cli:
	@echo "Connecting to Redis CLI..."
	docker-compose exec redis redis-cli

redis-monitor:
	@echo "Monitoring Redis commands..."
	docker-compose exec redis redis-cli monitor

cache-stats:
	@echo "Getting cache statistics..."
	curl -H "Authorization: Bearer admin-key-67890" http://localhost:8000/v1/admin/cache/stats | jq

cache-clear:
	@echo "Clearing cache..."
	curl -X POST -H "Authorization: Bearer admin-key-67890" http://localhost:8000/v1/admin/cache/clear

# Environment setup
setup-env:
	@echo "Setting up environment..."
	cp .env.example .env
	@echo "Please edit .env with your configuration"

# SSL certificate generation (for development)
generate-ssl:
	@echo "Generating self-signed SSL certificates..."
	mkdir -p ssl
	openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
		-keyout ssl/key.pem \
		-out ssl/cert.pem \
		-subj "/C=US/ST=State/L=City/O=Organization/CN=localhost"

# Backup and restore
backup-redis:
	@echo "Backing up Redis data..."
	docker-compose exec redis redis-cli BGSAVE
	docker cp $$(docker-compose ps -q redis):/data/dump.rdb ./backup-$$(date +%Y%m%d-%H%M%S).rdb

restore-redis:
	@echo "Restoring Redis data..."
	@echo "Usage: make restore-redis BACKUP_FILE=backup-file.rdb"
	@if [ -z "$(BACKUP_FILE)" ]; then echo "Please specify BACKUP_FILE"; exit 1; fi
	docker-compose stop redis
	docker cp $(BACKUP_FILE) $$(docker-compose ps -q redis):/data/dump.rdb
	docker-compose start redis

# Monitoring
monitor:
	@echo "Starting monitoring dashboard..."
	@echo "API Health: http://localhost:8000/v1/healthz"
	@echo "API Docs: http://localhost:8000/docs"
	@echo "Redis Commander: http://localhost:8081"
	@echo "Metrics: http://localhost:8000/v1/admin/metrics"

# Performance testing
load-test:
	@echo "Running load test..."
	@echo "Make sure the service is running first"
	curl -X POST \
		-H "Authorization: Bearer demo-key-12345" \
		-H "Content-Type: application/json" \
		-d '{"text":"This is a test text for summarization. It contains multiple sentences to test the summarization functionality.","max_tokens":50}' \
		http://localhost:8000/v1/summarize

# Security scan
security-scan:
	@echo "Running security scan..."
	docker run --rm -v $(PWD):/app pyupio/safety check --file /app/requirements.txt

# Update dependencies
update-deps:
	@echo "Updating dependencies..."
	pip-compile --upgrade requirements.in
	pip install -r requirements.txt
