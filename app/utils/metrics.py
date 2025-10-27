"""
Metrics collection and monitoring utilities.
Provides endpoints and utilities for application monitoring.
"""
import time
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends
from pydantic import BaseModel

from app.core.logging import LoggerMixin
from app.api.middleware.logging import MetricsMiddleware
from app.api.v1.dependencies import get_current_user
from app.domain.interfaces.auth_service import AuthUser


router = APIRouter()


class MetricsResponse(BaseModel):
    """Response model for metrics data."""
    timestamp: float
    uptime_seconds: float
    metrics: Dict[str, Any]


class HealthMetricsResponse(BaseModel):
    """Response model for health metrics."""
    status: str
    metrics: Dict[str, Any]
    components: Dict[str, Any]


class MetricsCollector(LoggerMixin):
    """
    Centralized metrics collector.
    
    Aggregates metrics from various sources and provides monitoring endpoints.
    """
    
    def __init__(self):
        """Initialize metrics collector."""
        self.start_time = time.time()
        self.metrics_middleware: Optional[MetricsMiddleware] = None
        
        self.logger.info("Metrics collector initialized")
    
    def set_metrics_middleware(self, middleware: MetricsMiddleware) -> None:
        """Set reference to metrics middleware."""
        self.metrics_middleware = middleware
    
    def get_system_metrics(self) -> Dict[str, Any]:
        """Get system-level metrics."""
        try:
            import psutil
            
            # Get memory usage
            memory = psutil.virtual_memory()
            
            # Get CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            
            # Get disk usage
            disk = psutil.disk_usage('/')
            
            return {
                "memory": {
                    "total_mb": round(memory.total / 1024 / 1024, 2),
                    "available_mb": round(memory.available / 1024 / 1024, 2),
                    "used_mb": round(memory.used / 1024 / 1024, 2),
                    "percent": memory.percent
                },
                "cpu": {
                    "percent": cpu_percent,
                    "count": psutil.cpu_count()
                },
                "disk": {
                    "total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
                    "used_gb": round(disk.used / 1024 / 1024 / 1024, 2),
                    "free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
                    "percent": round((disk.used / disk.total) * 100, 2)
                }
            }
        
        except ImportError:
            return {
                "memory": {"error": "psutil not available"},
                "cpu": {"error": "psutil not available"},
                "disk": {"error": "psutil not available"}
            }
        except Exception as e:
            return {
                "error": f"Failed to collect system metrics: {str(e)}"
            }
    
    def get_application_metrics(self) -> Dict[str, Any]:
        """Get application-level metrics."""
        uptime = time.time() - self.start_time
        
        base_metrics = {
            "uptime_seconds": round(uptime, 2),
            "start_time": self.start_time
        }
        
        # Add middleware metrics if available
        if self.metrics_middleware:
            middleware_metrics = self.metrics_middleware.get_metrics_summary()
            base_metrics.update(middleware_metrics)
        
        return base_metrics
    
    def get_comprehensive_metrics(self) -> Dict[str, Any]:
        """Get comprehensive metrics including system and application data."""
        return {
            "timestamp": time.time(),
            "system": self.get_system_metrics(),
            "application": self.get_application_metrics()
        }


# Global metrics collector instance
metrics_collector = MetricsCollector()


@router.get(
    "/metrics",
    response_model=MetricsResponse,
    summary="Get application metrics",
    description="""
    Get comprehensive application metrics including:
    - Request counts and response times
    - Error rates and status code distribution
    - System resource usage (CPU, memory, disk)
    - Top endpoints by usage
    - Active user statistics
    
    **Note**: This endpoint requires authentication and may contain sensitive information.
    """
)
async def get_metrics(
    current_user: AuthUser = Depends(get_current_user)
) -> MetricsResponse:
    """
    Get comprehensive application metrics.
    
    Args:
        current_user: Authenticated user (admin access recommended)
        
    Returns:
        MetricsResponse: Comprehensive metrics data
    """
    # Check if user has admin access for detailed metrics
    if not current_user.is_admin():
        # Return limited metrics for non-admin users
        metrics_data = {
            "requests_processed": metrics_collector.get_application_metrics().get("total_requests", 0),
            "uptime_seconds": time.time() - metrics_collector.start_time,
            "status": "healthy"
        }
    else:
        # Return full metrics for admin users
        metrics_data = metrics_collector.get_comprehensive_metrics()
    
    return MetricsResponse(
        timestamp=time.time(),
        uptime_seconds=time.time() - metrics_collector.start_time,
        metrics=metrics_data
    )


@router.get(
    "/metrics/health",
    response_model=HealthMetricsResponse,
    summary="Get health metrics",
    description="""
    Get health-focused metrics for monitoring and alerting:
    - Service health status
    - Error rates and response times
    - Component availability
    - Performance indicators
    
    This endpoint provides a subset of metrics focused on service health.
    """
)
async def get_health_metrics() -> HealthMetricsResponse:
    """
    Get health-focused metrics.
    
    Returns:
        HealthMetricsResponse: Health metrics data
    """
    app_metrics = metrics_collector.get_application_metrics()
    
    # Determine health status based on metrics
    error_rate = app_metrics.get("error_rate", 0)
    avg_response_time = app_metrics.get("avg_response_time_ms", 0)
    
    if error_rate > 0.1:  # 10% error rate
        status = "unhealthy"
    elif error_rate > 0.05 or avg_response_time > 5000:  # 5% error rate or 5s response time
        status = "degraded"
    else:
        status = "healthy"
    
    health_metrics = {
        "error_rate": error_rate,
        "avg_response_time_ms": avg_response_time,
        "total_requests": app_metrics.get("total_requests", 0),
        "uptime_seconds": app_metrics.get("uptime_seconds", 0)
    }
    
    components = {
        "api": {"status": status},
        "metrics_collection": {"status": "healthy"}
    }
    
    return HealthMetricsResponse(
        status=status,
        metrics=health_metrics,
        components=components
    )


@router.get(
    "/metrics/endpoints",
    summary="Get endpoint metrics",
    description="Get detailed metrics for individual API endpoints"
)
async def get_endpoint_metrics(
    current_user: AuthUser = Depends(get_current_user)
) -> Dict[str, Any]:
    """
    Get detailed endpoint metrics.
    
    Args:
        current_user: Authenticated user
        
    Returns:
        Dict containing endpoint metrics
    """
    if not metrics_collector.metrics_middleware:
        return {"error": "Metrics middleware not available"}
    
    summary = metrics_collector.metrics_middleware.get_metrics_summary()
    
    return {
        "endpoints": summary.get("top_endpoints", []),
        "total_endpoints": len(metrics_collector.metrics_middleware.metrics.get("endpoints", {})),
        "timestamp": time.time()
    }


def setup_metrics_middleware(app, middleware: MetricsMiddleware) -> None:
    """
    Setup metrics middleware reference.
    
    Args:
        app: FastAPI application
        middleware: Metrics middleware instance
    """
    metrics_collector.set_metrics_middleware(middleware)
    
    # Add metrics router to app
    app.include_router(
        router,
        prefix="/v1/admin",
        tags=["Metrics"]
    )
