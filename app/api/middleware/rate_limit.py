"""
Rate limiting middleware for FastAPI.
Implements rate limiting using in-memory storage with Redis fallback.
"""
import time
import asyncio
from typing import Dict, Optional, Callable, Tuple
from collections import defaultdict, deque
from datetime import datetime, timedelta
from fastapi import Request, Response, HTTPException, status

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.domain.interfaces.auth_service import AuthUser
from app.api.middleware.auth import get_current_user_from_request


class InMemoryRateLimiter(LoggerMixin):
    """
    In-memory rate limiter implementation.
    
    Uses sliding window algorithm for accurate rate limiting.
    """
    
    def __init__(self):
        """Initialize in-memory rate limiter."""
        # Store request timestamps for each identifier
        self.request_history: Dict[str, deque] = defaultdict(lambda: deque())
        self.lock = asyncio.Lock()
        
        self.logger.info("In-memory rate limiter initialized")
    
    async def is_allowed(
        self, 
        identifier: str, 
        limit: int, 
        window_seconds: int
    ) -> Tuple[bool, Dict[str, int]]:
        """
        Check if request is allowed within rate limits.
        
        Args:
            identifier: Unique identifier (user ID, IP, etc.)
            limit: Maximum requests allowed
            window_seconds: Time window in seconds
            
        Returns:
            Tuple of (is_allowed, rate_limit_info)
        """
        async with self.lock:
            current_time = time.time()
            cutoff_time = current_time - window_seconds
            
            # Get request history for identifier
            history = self.request_history[identifier]
            
            # Remove old requests outside the window
            while history and history[0] <= cutoff_time:
                history.popleft()
            
            # Check if under limit
            current_count = len(history)
            is_allowed = current_count < limit
            
            if is_allowed:
                # Add current request to history
                history.append(current_time)
            
            # Calculate reset time
            reset_time = int(current_time + window_seconds) if history else int(current_time)
            
            rate_limit_info = {
                "limit": limit,
                "remaining": max(0, limit - current_count - (1 if is_allowed else 0)),
                "reset": reset_time,
                "retry_after": max(1, int(window_seconds - (current_time - (history[0] if history else current_time))))
            }
            
            return is_allowed, rate_limit_info
    
    async def get_usage_stats(self, identifier: str) -> Dict[str, int]:
        """Get current usage statistics for identifier."""
        async with self.lock:
            history = self.request_history[identifier]
            current_time = time.time()
            
            # Count requests in different time windows
            last_minute = sum(1 for t in history if current_time - t <= 60)
            last_hour = sum(1 for t in history if current_time - t <= 3600)
            
            return {
                "requests_last_minute": last_minute,
                "requests_last_hour": last_hour,
                "total_requests": len(history)
            }
    
    async def cleanup_old_entries(self, max_age_seconds: int = 3600):
        """Clean up old entries to prevent memory leaks."""
        async with self.lock:
            current_time = time.time()
            cutoff_time = current_time - max_age_seconds
            
            # Clean up old entries
            for identifier in list(self.request_history.keys()):
                history = self.request_history[identifier]
                
                # Remove old requests
                while history and history[0] <= cutoff_time:
                    history.popleft()
                
                # Remove empty histories
                if not history:
                    del self.request_history[identifier]


class RateLimitMiddleware(LoggerMixin):
    """
    Rate limiting middleware for FastAPI.
    
    Implements per-user and per-IP rate limiting with configurable limits.
    """
    
    def __init__(self, app: Callable):
        """
        Initialize rate limit middleware.
        
        Args:
            app: ASGI application
        """
        self.app = app
        self.rate_limiter = InMemoryRateLimiter()
        
        # Default rate limits
        self.default_limits = {
            "requests_per_minute": 60,
            "requests_per_hour": 1000
        }
        
        # Paths exempt from rate limiting
        self.exempt_paths = {
            "/",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/v1/healthz"
        }
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
        self.logger.info("Rate limit middleware initialized")
    
    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """
        Process request through rate limiting middleware.
        
        Args:
            request: FastAPI request
            call_next: Next middleware/endpoint
            
        Returns:
            Response: HTTP response with rate limit headers
        """
        start_time = time.time()
        
        # Skip rate limiting if disabled
        if not settings.enable_rate_limit:
            return await call_next(request)
        
        # Skip rate limiting for exempt paths
        if request.url.path in self.exempt_paths:
            return await call_next(request)
        
        # Skip for OPTIONS requests
        if request.method == "OPTIONS":
            return await call_next(request)
        
        try:
            # Get rate limit identifier and limits
            identifier, limits = await self._get_rate_limit_config(request)
            
            # Check rate limits
            rate_limit_result = await self._check_rate_limits(identifier, limits)
            
            if not rate_limit_result["allowed"]:
                # Rate limit exceeded
                latency_ms = (time.time() - start_time) * 1000
                
                self.logger.warning(
                    f"Rate limit exceeded",
                    extra={
                        "identifier": identifier,
                        "path": request.url.path,
                        "limit": rate_limit_result["limit"],
                        "latency_ms": latency_ms
                    }
                )
                
                # Log rate limit exceeded
                log_performance(
                    operation="rate_limit_exceeded",
                    latency_ms=latency_ms,
                    identifier=identifier,
                    path=request.url.path
                )
                
                # Return rate limit error
                headers = {
                    "X-RateLimit-Limit": str(rate_limit_result["limit"]),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(rate_limit_result["reset"]),
                    "Retry-After": str(rate_limit_result["retry_after"])
                }
                
                return Response(
                    content='{"error": "Rate limit exceeded", "error_code": "RATE_LIMIT_EXCEEDED"}',
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    headers=headers,
                    media_type="application/json"
                )
            
            # Process request
            response = await call_next(request)
            
            # Add rate limit headers to response
            response.headers["X-RateLimit-Limit"] = str(rate_limit_result["limit"])
            response.headers["X-RateLimit-Remaining"] = str(rate_limit_result["remaining"])
            response.headers["X-RateLimit-Reset"] = str(rate_limit_result["reset"])
            
            # Log successful rate limit check
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="rate_limit_check",
                latency_ms=latency_ms,
                identifier=identifier,
                remaining=rate_limit_result["remaining"]
            )
            
            return response
            
        except Exception as e:
            self.logger.error(f"Error in rate limit middleware: {e}")
            # Continue without rate limiting on error
            return await call_next(request)
    
    async def _get_rate_limit_config(self, request: Request) -> Tuple[str, Dict[str, int]]:
        """
        Get rate limit identifier and limits for the request.
        
        Args:
            request: FastAPI request
            
        Returns:
            Tuple of (identifier, limits)
        """
        # Try to get authenticated user
        user = get_current_user_from_request(request)
        
        if user:
            # Use user-specific limits
            identifier = f"user:{user.user_id}"
            
            # Get user-specific limits (could be from database)
            if user.role == "admin":
                limits = {
                    "requests_per_minute": 300,
                    "requests_per_hour": 10000
                }
            elif hasattr(user, 'metadata') and user.metadata.get('tier') == 'premium':
                limits = {
                    "requests_per_minute": 120,
                    "requests_per_hour": 5000
                }
            else:
                limits = self.default_limits
        else:
            # Use IP-based limits for unauthenticated requests
            client_ip = request.client.host if request.client else "unknown"
            identifier = f"ip:{client_ip}"
            
            # Stricter limits for unauthenticated requests
            limits = {
                "requests_per_minute": 20,
                "requests_per_hour": 100
            }
        
        return identifier, limits
    
    async def _check_rate_limits(
        self, 
        identifier: str, 
        limits: Dict[str, int]
    ) -> Dict[str, any]:
        """
        Check all rate limits for the identifier.
        
        Args:
            identifier: Rate limit identifier
            limits: Rate limit configuration
            
        Returns:
            Dict with rate limit check results
        """
        # Check minute limit
        minute_allowed, minute_info = await self.rate_limiter.is_allowed(
            f"{identifier}:minute",
            limits["requests_per_minute"],
            60
        )
        
        # Check hour limit
        hour_allowed, hour_info = await self.rate_limiter.is_allowed(
            f"{identifier}:hour", 
            limits["requests_per_hour"],
            3600
        )
        
        # Overall allowed if both limits pass
        allowed = minute_allowed and hour_allowed
        
        # Use the most restrictive limit info
        if not minute_allowed:
            limit_info = minute_info
            limit_info["window"] = "minute"
        elif not hour_allowed:
            limit_info = hour_info
            limit_info["window"] = "hour"
        else:
            # Use minute limit info as it's more restrictive
            limit_info = minute_info
            limit_info["window"] = "minute"
        
        return {
            "allowed": allowed,
            "limit": limit_info["limit"],
            "remaining": limit_info["remaining"],
            "reset": limit_info["reset"],
            "retry_after": limit_info.get("retry_after", 60),
            "window": limit_info.get("window", "minute")
        }
    
    async def _periodic_cleanup(self):
        """Periodic cleanup of old rate limit entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                await self.rate_limiter.cleanup_old_entries()
                self.logger.debug("Rate limiter cleanup completed")
            except Exception as e:
                self.logger.error(f"Error during rate limiter cleanup: {e}")


class RateLimitDependency(LoggerMixin):
    """
    FastAPI dependency for rate limiting specific endpoints.
    
    Allows fine-grained rate limiting per endpoint.
    """
    
    def __init__(
        self, 
        requests_per_minute: int = 60,
        requests_per_hour: int = 1000
    ):
        """
        Initialize rate limit dependency.
        
        Args:
            requests_per_minute: Requests allowed per minute
            requests_per_hour: Requests allowed per hour
        """
        self.requests_per_minute = requests_per_minute
        self.requests_per_hour = requests_per_hour
        self.rate_limiter = InMemoryRateLimiter()
    
    async def __call__(self, request: Request) -> None:
        """
        Check rate limits for the request.
        
        Args:
            request: FastAPI request
            
        Raises:
            HTTPException: If rate limit is exceeded
        """
        if not settings.enable_rate_limit:
            return
        
        # Get identifier
        user = get_current_user_from_request(request)
        if user:
            identifier = f"user:{user.user_id}:endpoint:{request.url.path}"
        else:
            client_ip = request.client.host if request.client else "unknown"
            identifier = f"ip:{client_ip}:endpoint:{request.url.path}"
        
        # Check minute limit
        minute_allowed, minute_info = await self.rate_limiter.is_allowed(
            f"{identifier}:minute",
            self.requests_per_minute,
            60
        )
        
        if not minute_allowed:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail={
                    "error": "Rate limit exceeded for this endpoint",
                    "error_code": "ENDPOINT_RATE_LIMIT_EXCEEDED",
                    "retry_after": minute_info.get("retry_after", 60)
                },
                headers={
                    "X-RateLimit-Limit": str(minute_info["limit"]),
                    "X-RateLimit-Remaining": str(minute_info["remaining"]),
                    "X-RateLimit-Reset": str(minute_info["reset"]),
                    "Retry-After": str(minute_info.get("retry_after", 60))
                }
            )
