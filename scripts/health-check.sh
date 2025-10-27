#!/bin/bash

# Health Check Script for LLM Summarizer Service
# Comprehensive health monitoring and alerting

set -euo pipefail

# Configuration
API_URL="${API_URL:-http://localhost:8000}"
ADMIN_API_KEY="${ADMIN_API_KEY:-admin-key-67890}"
TIMEOUT="${TIMEOUT:-10}"
VERBOSE="${VERBOSE:-false}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Logging
log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error() { echo -e "${RED}[ERROR]${NC} $1"; }

# Health check results
declare -A health_results

# Basic connectivity check
check_connectivity() {
    log_info "Checking API connectivity..."
    
    if curl -f -s --max-time "$TIMEOUT" "$API_URL/" > /dev/null; then
        health_results["connectivity"]="✅ PASS"
        log_success "API is reachable"
        return 0
    else
        health_results["connectivity"]="❌ FAIL"
        log_error "API is not reachable"
        return 1
    fi
}

# Health endpoint check
check_health_endpoint() {
    log_info "Checking health endpoint..."
    
    local response
    response=$(curl -f -s --max-time "$TIMEOUT" "$API_URL/v1/healthz" 2>/dev/null || echo "")
    
    if [[ -n "$response" ]]; then
        local status
        status=$(echo "$response" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
        
        if [[ "$status" == "healthy" ]]; then
            health_results["health_endpoint"]="✅ PASS"
            log_success "Health endpoint reports healthy"
            
            if [[ "$VERBOSE" == "true" ]]; then
                echo "$response" | jq . 2>/dev/null || echo "$response"
            fi
            return 0
        else
            health_results["health_endpoint"]="⚠️ DEGRADED ($status)"
            log_warning "Health endpoint reports: $status"
            return 1
        fi
    else
        health_results["health_endpoint"]="❌ FAIL"
        log_error "Health endpoint not responding"
        return 1
    fi
}

# Cache health check
check_cache_health() {
    log_info "Checking cache health..."
    
    local response
    response=$(curl -f -s --max-time "$TIMEOUT" "$API_URL/v1/admin/cache/health" \
        -H "Authorization: Bearer $ADMIN_API_KEY" 2>/dev/null || echo "")
    
    if [[ -n "$response" ]]; then
        local status
        status=$(echo "$response" | jq -r '.status // "unknown"' 2>/dev/null || echo "unknown")
        
        case "$status" in
            "healthy")
                health_results["cache"]="✅ PASS"
                log_success "Cache is healthy"
                ;;
            "degraded")
                health_results["cache"]="⚠️ DEGRADED"
                log_warning "Cache is degraded"
                ;;
            *)
                health_results["cache"]="❌ FAIL ($status)"
                log_error "Cache is unhealthy: $status"
                ;;
        esac
        
        if [[ "$VERBOSE" == "true" ]]; then
            echo "$response" | jq . 2>/dev/null || echo "$response"
        fi
    else
        health_results["cache"]="❌ FAIL"
        log_error "Cache health check failed"
    fi
}

# API functionality test
test_api_functionality() {
    log_info "Testing API functionality..."
    
    local test_payload='{"text":"This is a test text for health check. It should be summarized properly.","max_tokens":20}'
    local response
    
    response=$(curl -f -s --max-time 30 "$API_URL/v1/summarize" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer demo-key-12345" \
        -d "$test_payload" 2>/dev/null || echo "")
    
    if [[ -n "$response" ]]; then
        local summary
        summary=$(echo "$response" | jq -r '.summary // ""' 2>/dev/null || echo "")
        
        if [[ -n "$summary" && "$summary" != "null" ]]; then
            health_results["api_functionality"]="✅ PASS"
            log_success "API functionality test passed"
            
            if [[ "$VERBOSE" == "true" ]]; then
                log_info "Test summary: $summary"
            fi
            return 0
        else
            health_results["api_functionality"]="❌ FAIL (no summary)"
            log_error "API returned response but no summary"
            return 1
        fi
    else
        health_results["api_functionality"]="❌ FAIL"
        log_error "API functionality test failed"
        return 1
    fi
}

# Performance check
check_performance() {
    log_info "Checking API performance..."
    
    local start_time
    local end_time
    local duration
    
    start_time=$(date +%s%N)
    
    if curl -f -s --max-time "$TIMEOUT" "$API_URL/v1/healthz" > /dev/null; then
        end_time=$(date +%s%N)
        duration=$(( (end_time - start_time) / 1000000 )) # Convert to milliseconds
        
        if [[ $duration -lt 1000 ]]; then
            health_results["performance"]="✅ PASS (${duration}ms)"
            log_success "Performance check passed: ${duration}ms"
        elif [[ $duration -lt 3000 ]]; then
            health_results["performance"]="⚠️ SLOW (${duration}ms)"
            log_warning "Performance is slow: ${duration}ms"
        else
            health_results["performance"]="❌ FAIL (${duration}ms)"
            log_error "Performance is poor: ${duration}ms"
        fi
    else
        health_results["performance"]="❌ FAIL"
        log_error "Performance check failed"
    fi
}

# Memory and resource check
check_resources() {
    log_info "Checking resource usage..."
    
    # This would typically check container stats or system metrics
    # For now, we'll check if the metrics endpoint is available
    
    local response
    response=$(curl -f -s --max-time "$TIMEOUT" "$API_URL/v1/admin/metrics" \
        -H "Authorization: Bearer $ADMIN_API_KEY" 2>/dev/null || echo "")
    
    if [[ -n "$response" ]]; then
        health_results["resources"]="✅ PASS"
        log_success "Resource metrics available"
        
        if [[ "$VERBOSE" == "true" ]]; then
            local uptime
            uptime=$(echo "$response" | jq -r '.uptime_seconds // 0' 2>/dev/null || echo "0")
            log_info "Service uptime: ${uptime}s"
        fi
    else
        health_results["resources"]="⚠️ LIMITED"
        log_warning "Resource metrics not available"
    fi
}

# Database/Redis connectivity
check_redis_connectivity() {
    log_info "Checking Redis connectivity..."
    
    local response
    response=$(curl -f -s --max-time "$TIMEOUT" "$API_URL/v1/admin/cache/stats" \
        -H "Authorization: Bearer $ADMIN_API_KEY" 2>/dev/null || echo "")
    
    if [[ -n "$response" ]]; then
        local cache_type
        cache_type=$(echo "$response" | jq -r '.cache_type // "unknown"' 2>/dev/null || echo "unknown")
        
        case "$cache_type" in
            "redis"|"hybrid")
                health_results["redis"]="✅ PASS"
                log_success "Redis connectivity confirmed"
                ;;
            "memory")
                health_results["redis"]="⚠️ FALLBACK"
                log_warning "Using memory cache (Redis unavailable)"
                ;;
            *)
                health_results["redis"]="❌ UNKNOWN"
                log_error "Unknown cache type: $cache_type"
                ;;
        esac
        
        if [[ "$VERBOSE" == "true" ]]; then
            echo "$response" | jq . 2>/dev/null || echo "$response"
        fi
    else
        health_results["redis"]="❌ FAIL"
        log_error "Cannot check Redis connectivity"
    fi
}

# Generate health report
generate_report() {
    echo ""
    echo "=================================="
    echo "   HEALTH CHECK REPORT"
    echo "=================================="
    echo "Timestamp: $(date)"
    echo "API URL: $API_URL"
    echo ""
    
    local overall_status="✅ HEALTHY"
    local has_failures=false
    local has_warnings=false
    
    for check in connectivity health_endpoint cache api_functionality performance resources redis; do
        local result="${health_results[$check]:-❌ NOT_CHECKED}"
        printf "%-20s: %s\n" "$check" "$result"
        
        if [[ "$result" == *"❌"* ]]; then
            has_failures=true
        elif [[ "$result" == *"⚠️"* ]]; then
            has_warnings=true
        fi
    done
    
    echo ""
    
    if [[ "$has_failures" == "true" ]]; then
        overall_status="❌ UNHEALTHY"
    elif [[ "$has_warnings" == "true" ]]; then
        overall_status="⚠️ DEGRADED"
    fi
    
    echo "Overall Status: $overall_status"
    echo "=================================="
    
    # Return appropriate exit code
    if [[ "$has_failures" == "true" ]]; then
        return 1
    elif [[ "$has_warnings" == "true" ]]; then
        return 2
    else
        return 0
    fi
}

# Send alert (webhook, email, etc.)
send_alert() {
    local status="$1"
    local webhook_url="${WEBHOOK_URL:-}"
    
    if [[ -n "$webhook_url" ]]; then
        log_info "Sending alert to webhook..."
        
        local payload
        payload=$(cat <<EOF
{
    "text": "LLM Summarizer Health Check Alert",
    "attachments": [
        {
            "color": "$([[ "$status" == *"UNHEALTHY"* ]] && echo "danger" || echo "warning")",
            "fields": [
                {
                    "title": "Status",
                    "value": "$status",
                    "short": true
                },
                {
                    "title": "API URL",
                    "value": "$API_URL",
                    "short": true
                },
                {
                    "title": "Timestamp",
                    "value": "$(date)",
                    "short": false
                }
            ]
        }
    ]
}
EOF
        )
        
        curl -X POST -H "Content-Type: application/json" -d "$payload" "$webhook_url" || true
    fi
}

# Main function
main() {
    echo "LLM Summarizer Service Health Check"
    echo "===================================="
    
    # Run all health checks
    check_connectivity
    check_health_endpoint
    check_cache_health
    check_performance
    check_resources
    check_redis_connectivity
    
    # Test API functionality if basic checks pass
    if [[ "${health_results[connectivity]}" == *"✅"* ]]; then
        test_api_functionality
    fi
    
    # Generate and display report
    if generate_report; then
        exit_code=0
    else
        exit_code=$?
    fi
    
    # Send alert if unhealthy
    if [[ $exit_code -ne 0 ]]; then
        local status
        case $exit_code in
            1) status="❌ UNHEALTHY" ;;
            2) status="⚠️ DEGRADED" ;;
        esac
        send_alert "$status"
    fi
    
    exit $exit_code
}

# Handle command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        --url)
            API_URL="$2"
            shift 2
            ;;
        --admin-key)
            ADMIN_API_KEY="$2"
            shift 2
            ;;
        --timeout)
            TIMEOUT="$2"
            shift 2
            ;;
        --verbose)
            VERBOSE="true"
            shift
            ;;
        --help)
            echo "Usage: $0 [options]"
            echo "Options:"
            echo "  --url URL          API URL (default: http://localhost:8000)"
            echo "  --admin-key KEY    Admin API key for advanced checks"
            echo "  --timeout SECONDS  Request timeout (default: 10)"
            echo "  --verbose          Show detailed output"
            echo "  --help             Show this help"
            exit 0
            ;;
        *)
            log_error "Unknown option: $1"
            exit 1
            ;;
    esac
done

# Run main function
main
