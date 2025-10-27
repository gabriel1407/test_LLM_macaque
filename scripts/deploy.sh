#!/bin/bash

# LLM Summarizer Service Deployment Script
# Supports multiple deployment targets: local, docker, swarm, kubernetes

set -euo pipefail

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
IMAGE_NAME="llm-summarizer"
IMAGE_TAG="${IMAGE_TAG:-latest}"
DEPLOYMENT_TARGET="${1:-local}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Logging functions
log_info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if required tools are installed
check_dependencies() {
    local deps=("$@")
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" &> /dev/null; then
            log_error "$dep is required but not installed"
            exit 1
        fi
    done
}

# Build Docker image
build_image() {
    log_info "Building Docker image: $IMAGE_NAME:$IMAGE_TAG"
    
    cd "$PROJECT_DIR"
    
    # Build with build args
    docker build \
        --build-arg BUILD_DATE="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
        --build-arg VERSION="$IMAGE_TAG" \
        --build-arg VCS_REF="$(git rev-parse --short HEAD 2>/dev/null || echo 'unknown')" \
        -t "$IMAGE_NAME:$IMAGE_TAG" \
        .
    
    log_success "Docker image built successfully"
}

# Deploy locally with Docker Compose
deploy_local() {
    log_info "Deploying locally with Docker Compose"
    
    cd "$PROJECT_DIR"
    
    # Check if .env exists
    if [[ ! -f .env ]]; then
        log_error ".env file not found. Please create it with your configuration."
        exit 1
    fi
    log_info ".env file found"
    
    # Start Redis for development
    log_info "Starting Redis..."
    docker-compose -f docker-compose.dev.yml up -d redis-dev
    
    # Build and start the application
    build_image
    
    log_info "Starting application..."
    docker run -d \
        --name llm-summarizer-local \
        --env-file .env \
        -p 8000:8000 \
        --network "$(docker-compose -f docker-compose.dev.yml ps -q redis-dev | xargs docker inspect --format='{{range .NetworkSettings.Networks}}{{.NetworkID}}{{end}}')" \
        "$IMAGE_NAME:$IMAGE_TAG"
    
    log_success "Application deployed locally"
    log_info "API available at: http://localhost:8000"
    log_info "Health check: http://localhost:8000/v1/healthz"
    log_info "API docs: http://localhost:8000/docs"
}

# Deploy with Docker Compose (full stack)
deploy_docker() {
    log_info "Deploying with Docker Compose"
    
    cd "$PROJECT_DIR"
    
    # Build image
    build_image
    
    # Deploy full stack
    log_info "Starting full stack..."
    docker-compose down --remove-orphans
    docker-compose up -d
    
    # Wait for services to be ready
    log_info "Waiting for services to be ready..."
    sleep 10
    
    # Health check
    if curl -f http://localhost:8000/v1/healthz &>/dev/null; then
        log_success "Application deployed successfully"
        log_info "API available at: http://localhost:8000"
        log_info "Redis Commander: http://localhost:8081"
    else
        log_error "Health check failed"
        docker-compose logs api
        exit 1
    fi
}

# Deploy to Docker Swarm
deploy_swarm() {
    log_info "Deploying to Docker Swarm"
    
    # Check if swarm is initialized
    if ! docker info --format '{{.Swarm.LocalNodeState}}' | grep -q active; then
        log_error "Docker Swarm is not initialized"
        log_info "Initialize with: docker swarm init"
        exit 1
    fi
    
    cd "$PROJECT_DIR"
    
    # Build and push image (in production, use registry)
    build_image
    
    # Create configs
    log_info "Creating Docker configs..."
    if docker config ls --format '{{.Name}}' | grep -q nginx_config; then
        docker config rm nginx_config || true
    fi
    docker config create nginx_config nginx.conf
    
    # Deploy stack
    log_info "Deploying Docker stack..."
    docker stack deploy -c deploy/docker-swarm.yml llm-summarizer
    
    log_success "Stack deployed to Docker Swarm"
    log_info "Check status with: docker stack ps llm-summarizer"
}

# Deploy to Kubernetes
deploy_kubernetes() {
    log_info "Deploying to Kubernetes"
    
    # Check kubectl
    if ! kubectl cluster-info &>/dev/null; then
        log_error "kubectl is not configured or cluster is not accessible"
        exit 1
    fi
    
    cd "$PROJECT_DIR"
    
    # Build and push image (in production, use registry)
    build_image
    
    # Apply Kubernetes manifests
    log_info "Applying Kubernetes manifests..."
    kubectl apply -f deploy/kubernetes.yml
    
    # Wait for deployment
    log_info "Waiting for deployment to be ready..."
    kubectl wait --for=condition=available --timeout=300s deployment/llm-summarizer-api -n llm-summarizer
    
    log_success "Application deployed to Kubernetes"
    log_info "Check status with: kubectl get pods -n llm-summarizer"
}

# Health check function
health_check() {
    local url="$1"
    local max_attempts=30
    local attempt=1
    
    log_info "Performing health check..."
    
    while [[ $attempt -le $max_attempts ]]; do
        if curl -f "$url/v1/healthz" &>/dev/null; then
            log_success "Health check passed"
            return 0
        fi
        
        log_info "Attempt $attempt/$max_attempts failed, retrying in 10s..."
        sleep 10
        ((attempt++))
    done
    
    log_error "Health check failed after $max_attempts attempts"
    return 1
}

# Cleanup function
cleanup() {
    case "$DEPLOYMENT_TARGET" in
        local)
            log_info "Cleaning up local deployment..."
            docker stop llm-summarizer-local 2>/dev/null || true
            docker rm llm-summarizer-local 2>/dev/null || true
            docker-compose -f docker-compose.dev.yml down
            ;;
        docker)
            log_info "Cleaning up Docker Compose deployment..."
            docker-compose down --remove-orphans
            ;;
        swarm)
            log_info "Cleaning up Docker Swarm deployment..."
            docker stack rm llm-summarizer
            ;;
        kubernetes)
            log_info "Cleaning up Kubernetes deployment..."
            kubectl delete -f deploy/kubernetes.yml --ignore-not-found=true
            ;;
    esac
}

# Main deployment logic
main() {
    log_info "LLM Summarizer Service Deployment"
    log_info "Target: $DEPLOYMENT_TARGET"
    
    case "$DEPLOYMENT_TARGET" in
        local)
            check_dependencies docker docker-compose curl
            deploy_local
            ;;
        docker)
            check_dependencies docker docker-compose curl
            deploy_docker
            ;;
        swarm)
            check_dependencies docker curl
            deploy_swarm
            ;;
        kubernetes)
            check_dependencies docker kubectl curl
            deploy_kubernetes
            ;;
        cleanup)
            cleanup
            exit 0
            ;;
        *)
            log_error "Unknown deployment target: $DEPLOYMENT_TARGET"
            echo "Usage: $0 [local|docker|swarm|kubernetes|cleanup]"
            exit 1
            ;;
    esac
    
    log_success "Deployment completed successfully!"
}

# Handle script interruption
trap cleanup EXIT

# Run main function
main "$@"
