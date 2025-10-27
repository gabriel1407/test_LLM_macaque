"""
Advanced logging middleware for FastAPI.
Provides structured logging with request/response details and performance metrics.
"""
import time
import uuid
import json
from typing import Callable, Dict, Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.api.middleware.auth import get_current_user_from_request


class LoggingMiddleware(BaseHTTPMiddleware, LoggerMixin):
    """
    Advanced logging middleware for comprehensive request/response logging.
    
    Logs request details, response status, timing, and user context.
    """
    
    def __init__(self, app: Callable):
        """
        Initialize logging middleware.
        
        Args:
            app: ASGI application
        """
        super().__init__(app)
        
        # Paths to exclude from detailed logging
        self.exclude_paths = {
            "/docs",
            "/redoc", 
            "/openapi.json",
            "/favicon.ico"
        }
        
        # Sensitive headers to redact
        self.sensitive_headers = {
            "authorization",
            "x-api-key",
            "cookie",
            "x-auth-token"
        }
        
        self.logger.info("Advanced logging middleware initialized")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Process request through logging middleware.
        
        Args:
            request: FastAPI request
            call_next: Next middleware/endpoint
            
        Returns:
            Response: HTTP response
        """
        # Generate request ID
        request_id = str(uuid.uuid4())
        request.state.request_id = request_id
        
        start_time = time.time()
        
        # Skip detailed logging for excluded paths
        if request.url.path in self.exclude_paths:
            response = await call_next(request)
            return response
        
        # Log request start
        await self._log_request_start(request, request_id)
        
        try:
            # Process request
            response = await call_next(request)
            
            # Calculate timing
            duration_ms = (time.time() - start_time) * 1000
            
            # Log request completion
            await self._log_request_completion(
                request, response, request_id, duration_ms
            )
            
            # Add request ID to response headers
            response.headers["X-Request-ID"] = request_id
            
            return response
            
        except Exception as e:
            # Calculate timing for failed requests
            duration_ms = (time.time() - start_time) * 1000
            
            # Log request failure
            await self._log_request_failure(
                request, e, request_id, duration_ms
            )
            
            raise
    
    async def _log_request_start(self, request: Request, request_id: str) -> None:
        """
        Log request start with details.
        
        Args:
            request: FastAPI request
            request_id: Unique request identifier
        """
        # Get user context if available
        user = get_current_user_from_request(request)
        user_id = user.user_id if user else None
        
        # Prepare request details
        request_details = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query_params": dict(request.query_params),
            "user_id": user_id,
            "client_ip": self._get_client_ip(request),
            "user_agent": request.headers.get("user-agent"),
            "content_type": request.headers.get("content-type"),
            "content_length": request.headers.get("content-length"),
            "headers": self._sanitize_headers(dict(request.headers))
        }
        
        self.logger.info(
            f"Request started: {request.method} {request.url.path}",
            extra=request_details
        )
    
    async def _log_request_completion(
        self, 
        request: Request, 
        response: Response, 
        request_id: str,
        duration_ms: float
    ) -> None:
        """
        Log successful request completion.
        
        Args:
            request: FastAPI request
            response: FastAPI response
            request_id: Unique request identifier
            duration_ms: Request duration in milliseconds
        """
        # Get user context
        user = get_current_user_from_request(request)
        user_id = user.user_id if user else None
        
        # Prepare response details
        response_details = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
            "user_id": user_id,
            "response_size": len(response.body) if hasattr(response, 'body') else None,
            "content_type": response.headers.get("content-type")
        }
        
        # Determine log level based on status code
        if response.status_code >= 500:
            log_level = "error"
        elif response.status_code >= 400:
            log_level = "warning"
        else:
            log_level = "info"
        
        # Log with appropriate level
        getattr(self.logger, log_level)(
            f"Request completed: {request.method} {request.url.path} - {response.status_code}",
            extra=response_details
        )
        
        # Log performance metrics
        log_performance(
            operation="http_request_completed",
            latency_ms=duration_ms,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            user_id=user_id,
            request_id=request_id
        )
        
        # Log slow requests
        if duration_ms > 5000:  # 5 seconds
            self.logger.warning(
                f"Slow request detected: {duration_ms:.2f}ms",
                extra={
                    "request_id": request_id,
                    "duration_ms": duration_ms,
                    "path": request.url.path,
                    "method": request.method
                }
            )
    
    async def _log_request_failure(
        self, 
        request: Request, 
        exception: Exception, 
        request_id: str,
        duration_ms: float
    ) -> None:
        """
        Log failed request.
        
        Args:
            request: FastAPI request
            exception: Exception that occurred
            request_id: Unique request identifier
            duration_ms: Request duration in milliseconds
        """
        # Get user context
        user = get_current_user_from_request(request)
        user_id = user.user_id if user else None
        
        # Prepare failure details
        failure_details = {
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "duration_ms": round(duration_ms, 2),
            "user_id": user_id,
            "exception_type": type(exception).__name__,
            "exception_message": str(exception)
        }
        
        self.logger.error(
            f"Request failed: {request.method} {request.url.path} - {type(exception).__name__}",
            extra=failure_details,
            exc_info=True
        )
        
        # Log performance metrics for failures
        log_performance(
            operation="http_request_failed",
            latency_ms=duration_ms,
            method=request.method,
            path=request.url.path,
            user_id=user_id,
            request_id=request_id,
            error=str(exception)
        )
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """
        Get client IP address from request.
        
        Args:
            request: FastAPI request
            
        Returns:
            Optional[str]: Client IP address
        """
        # Check for forwarded headers (load balancer/proxy)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(",")[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fall back to direct client IP
        return request.client.host if request.client else None
    
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """
        Sanitize headers by redacting sensitive information.
        
        Args:
            headers: Request headers
            
        Returns:
            Dict[str, str]: Sanitized headers
        """
        sanitized = {}
        
        for key, value in headers.items():
            if key.lower() in self.sensitive_headers:
                # Redact sensitive headers
                if value:
                    sanitized[key] = f"{value[:8]}***REDACTED***"
                else:
                    sanitized[key] = "***REDACTED***"
            else:
                sanitized[key] = value
        
        return sanitized


class MetricsMiddleware(BaseHTTPMiddleware, LoggerMixin):
    """
    Middleware for collecting application metrics.
    
    Tracks request counts, response times, and error rates.
    """
    
    def __init__(self, app: Callable):
        """Initialize metrics middleware."""
        super().__init__(app)
        
        # In-memory metrics storage (in production, use Redis/Prometheus)
        self.metrics = {
            "request_count": 0,
            "error_count": 0,
            "total_response_time": 0.0,
            "response_times": [],
            "status_codes": {},
            "endpoints": {},
            "users": {}
        }
        
        self.logger.info("Metrics middleware initialized")
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request through metrics middleware."""
        start_time = time.time()
        
        try:
            response = await call_next(request)
            duration_ms = (time.time() - start_time) * 1000
            
            # Update metrics
            await self._update_metrics(request, response, duration_ms)
            
            return response
            
        except Exception as e:
            duration_ms = (time.time() - start_time) * 1000
            
            # Update error metrics
            await self._update_error_metrics(request, e, duration_ms)
            
            raise
    
    async def _update_metrics(
        self, 
        request: Request, 
        response: Response, 
        duration_ms: float
    ) -> None:
        """Update metrics for successful requests."""
        # Update counters
        self.metrics["request_count"] += 1
        self.metrics["total_response_time"] += duration_ms
        
        # Track response times (keep last 1000)
        self.metrics["response_times"].append(duration_ms)
        if len(self.metrics["response_times"]) > 1000:
            self.metrics["response_times"].pop(0)
        
        # Track status codes
        status_code = str(response.status_code)
        self.metrics["status_codes"][status_code] = \
            self.metrics["status_codes"].get(status_code, 0) + 1
        
        # Track endpoints
        endpoint = f"{request.method} {request.url.path}"
        if endpoint not in self.metrics["endpoints"]:
            self.metrics["endpoints"][endpoint] = {
                "count": 0,
                "total_time": 0.0,
                "errors": 0
            }
        
        self.metrics["endpoints"][endpoint]["count"] += 1
        self.metrics["endpoints"][endpoint]["total_time"] += duration_ms
        
        # Track users
        user = get_current_user_from_request(request)
        if user:
            user_id = user.user_id
            if user_id not in self.metrics["users"]:
                self.metrics["users"][user_id] = {
                    "requests": 0,
                    "errors": 0,
                    "total_time": 0.0
                }
            
            self.metrics["users"][user_id]["requests"] += 1
            self.metrics["users"][user_id]["total_time"] += duration_ms
    
    async def _update_error_metrics(
        self, 
        request: Request, 
        exception: Exception, 
        duration_ms: float
    ) -> None:
        """Update metrics for failed requests."""
        self.metrics["error_count"] += 1
        
        # Track endpoint errors
        endpoint = f"{request.method} {request.url.path}"
        if endpoint in self.metrics["endpoints"]:
            self.metrics["endpoints"][endpoint]["errors"] += 1
        
        # Track user errors
        user = get_current_user_from_request(request)
        if user and user.user_id in self.metrics["users"]:
            self.metrics["users"][user.user_id]["errors"] += 1
    
    def get_metrics_summary(self) -> Dict[str, Any]:
        """Get current metrics summary."""
        response_times = self.metrics["response_times"]
        
        if response_times:
            avg_response_time = sum(response_times) / len(response_times)
            p95_response_time = sorted(response_times)[int(len(response_times) * 0.95)]
        else:
            avg_response_time = 0
            p95_response_time = 0
        
        return {
            "total_requests": self.metrics["request_count"],
            "total_errors": self.metrics["error_count"],
            "error_rate": (
                self.metrics["error_count"] / self.metrics["request_count"] 
                if self.metrics["request_count"] > 0 else 0
            ),
            "avg_response_time_ms": round(avg_response_time, 2),
            "p95_response_time_ms": round(p95_response_time, 2),
            "status_codes": self.metrics["status_codes"],
            "top_endpoints": self._get_top_endpoints(),
            "active_users": len(self.metrics["users"])
        }
    
    def _get_top_endpoints(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top endpoints by request count."""
        endpoints = []
        
        for endpoint, data in self.metrics["endpoints"].items():
            avg_time = data["total_time"] / data["count"] if data["count"] > 0 else 0
            
            endpoints.append({
                "endpoint": endpoint,
                "requests": data["count"],
                "errors": data["errors"],
                "avg_response_time_ms": round(avg_time, 2),
                "error_rate": data["errors"] / data["count"] if data["count"] > 0 else 0
            })
        
        # Sort by request count
        endpoints.sort(key=lambda x: x["requests"], reverse=True)
        
        return endpoints[:limit]
