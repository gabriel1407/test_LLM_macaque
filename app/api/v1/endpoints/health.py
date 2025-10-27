"""
Health check endpoint implementation.
Handles GET /v1/healthz requests for service monitoring.
"""
import time
from typing import Dict, Any, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.core.config import settings
from app.core.logging import LoggerMixin
from app.api.v1.dependencies import get_summary_service


router = APIRouter()


class HealthCheckResponse(BaseModel):
    """API model for health check responses."""
    status: str = Field(..., description="Overall health status")
    timestamp: str = Field(..., description="Health check timestamp")
    version: str = Field(..., description="Service version")
    checks: Dict[str, Any] = Field(..., description="Individual component health checks")
    
    class Config:
        schema_extra = {
            "example": {
                "status": "healthy",
                "timestamp": "2024-01-01T12:00:00Z",
                "version": "1.0.0",
                "checks": {
                    "llm_provider": {
                        "status": "healthy",
                        "latency_ms": 150,
                        "provider": "openai",
                        "model": "gpt-3.5-turbo"
                    },
                    "fallback_services": [
                        {
                            "status": "healthy",
                            "algorithm": "textrank"
                        },
                        {
                            "status": "healthy", 
                            "algorithm": "tfidf"
                        }
                    ],
                    "cache_service": {
                        "status": "healthy",
                        "type": "redis"
                    }
                }
            }
        }


class HealthCheckDetailed(BaseModel):
    """Detailed health check model for internal monitoring."""
    status: str
    timestamp: str
    version: str
    environment: str
    uptime_seconds: float
    checks: Dict[str, Any]
    metrics: Optional[Dict[str, Any]] = None


@router.get(
    "/healthz",
    response_model=HealthCheckResponse,
    summary="Health check",
    description="""
    Check the health and availability of the summarization service.
    
    Returns the status of all service components including:
    - LLM provider connectivity and latency
    - Fallback services availability
    - Cache service status (if enabled)
    - Overall service health
    
    **Status Values:**
    - `healthy`: All components are working normally
    - `degraded`: Some non-critical components have issues
    - `unhealthy`: Critical components are failing
    
    This endpoint is typically used by load balancers and monitoring systems.
    """
)
async def health_check(
    summary_service = Depends(get_summary_service)
) -> HealthCheckResponse:
    """
    Perform health check of all service components.
    
    Args:
        summary_service: Summary service dependency
        
    Returns:
        HealthCheckResponse: Health status of all components
    """
    logger = HealthEndpoint().logger
    start_time = time.time()
    
    try:
        logger.info("Health check requested")
        
        # Get health status from summary service
        health_data = await summary_service.health_check()
        
        # Determine overall status
        overall_status = _determine_overall_status(health_data["components"])
        
        # Create response
        response = HealthCheckResponse(
            status=overall_status,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            version="1.0.0",  # In production, this would come from version file
            checks=health_data["components"]
        )
        
        # Log health check completion
        latency_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Health check completed",
            extra={
                "status": overall_status,
                "latency_ms": latency_ms,
                "components_checked": len(health_data["components"])
            }
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        
        # Return unhealthy status if health check itself fails
        return HealthCheckResponse(
            status="unhealthy",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            version="1.0.0",
            checks={
                "error": {
                    "status": "unhealthy",
                    "error": str(e)
                }
            }
        )


@router.get(
    "/healthz/detailed",
    response_model=HealthCheckDetailed,
    summary="Detailed health check",
    description="""
    Get detailed health information including metrics and system information.
    
    This endpoint provides additional information useful for debugging and monitoring:
    - Service uptime
    - Environment information
    - Performance metrics
    - Detailed component status
    
    **Note**: This endpoint may include sensitive information and should be 
    protected in production environments.
    """
)
async def detailed_health_check(
    summary_service = Depends(get_summary_service)
) -> HealthCheckDetailed:
    """
    Perform detailed health check with additional metrics.
    
    Args:
        summary_service: Summary service dependency
        
    Returns:
        HealthCheckDetailed: Detailed health status and metrics
    """
    logger = HealthEndpoint().logger
    start_time = time.time()
    
    try:
        logger.info("Detailed health check requested")
        
        # Get health status from summary service
        health_data = await summary_service.health_check()
        
        # Determine overall status
        overall_status = _determine_overall_status(health_data["components"])
        
        # Calculate uptime (simplified - in production you'd track actual start time)
        uptime_seconds = time.time() - health_data.get("timestamp", time.time())
        
        # Gather additional metrics
        metrics = {
            "memory_usage_mb": _get_memory_usage(),
            "active_connections": _get_active_connections(),
            "requests_processed": _get_request_count(),
            "cache_hit_rate": _get_cache_hit_rate()
        }
        
        response = HealthCheckDetailed(
            status=overall_status,
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            version="1.0.0",
            environment=settings.environment.value,
            uptime_seconds=uptime_seconds,
            checks=health_data["components"],
            metrics=metrics
        )
        
        # Log detailed health check completion
        latency_ms = (time.time() - start_time) * 1000
        logger.info(
            f"Detailed health check completed",
            extra={
                "status": overall_status,
                "latency_ms": latency_ms,
                "uptime_seconds": uptime_seconds
            }
        )
        
        return response
        
    except Exception as e:
        logger.error(f"Detailed health check failed: {e}")
        
        return HealthCheckDetailed(
            status="unhealthy",
            timestamp=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            version="1.0.0",
            environment=settings.environment.value,
            uptime_seconds=0,
            checks={
                "error": {
                    "status": "unhealthy",
                    "error": str(e)
                }
            }
        )


def _determine_overall_status(components: Dict[str, Any]) -> str:
    """
    Determine overall health status based on component statuses.
    
    Args:
        components: Dictionary of component health statuses
        
    Returns:
        str: Overall status (healthy, degraded, unhealthy)
    """
    if not components:
        return "unhealthy"
    
    statuses = []
    
    # Check LLM provider status
    llm_status = components.get("llm_provider", {}).get("status", "unhealthy")
    statuses.append(llm_status)
    
    # Check fallback services (at least one should be healthy)
    fallback_services = components.get("fallback_services", [])
    if fallback_services:
        fallback_healthy = any(
            service.get("status") == "healthy" 
            for service in fallback_services
        )
        statuses.append("healthy" if fallback_healthy else "degraded")
    
    # Check cache service (optional, so degraded if failed)
    cache_status = components.get("cache_service", {}).get("status")
    if cache_status and cache_status != "healthy":
        statuses.append("degraded")
    
    # Determine overall status
    if all(status == "healthy" for status in statuses):
        return "healthy"
    elif any(status == "unhealthy" for status in statuses):
        # If LLM is unhealthy but fallback is available, it's degraded
        if llm_status == "unhealthy" and len(fallback_services) > 0:
            return "degraded"
        return "unhealthy"
    else:
        return "degraded"


def _get_memory_usage() -> float:
    """Get current memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return process.memory_info().rss / 1024 / 1024
    except ImportError:
        return 0.0


def _get_active_connections() -> int:
    """Get number of active connections."""
    # This would be implemented with actual connection tracking
    return 0


def _get_request_count() -> int:
    """Get total number of requests processed."""
    # This would be implemented with actual metrics collection
    return 0


def _get_cache_hit_rate() -> float:
    """Get cache hit rate percentage."""
    # This would be implemented with actual cache metrics
    return 0.0


class HealthEndpoint(LoggerMixin):
    """Helper class for logging."""
    pass
