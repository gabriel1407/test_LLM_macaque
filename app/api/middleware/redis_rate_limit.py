"""
Redis-based rate limiting middleware.
Provides distributed rate limiting using Redis for scalability.
"""
import time
from typing import Dict, Optional, Callable, Tuple
from datetime import timedelta
from fastapi import Request, Response, HTTPException, status

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.domain.interfaces.auth_service import AuthUser
from app.api.middleware.auth import get_current_user_from_request
from app.services.cache.redis_cache import RedisRateLimitService, RedisCacheService
from app.api.middleware.rate_limit import InMemoryRateLimiter


class HybridRateLimitMiddleware(LoggerMixin):
    """
    Hybrid rate limiting middleware with Redis primary and memory fallback.
    
    Uses Redis for distributed rate limiting when available,
    falls back to in-memory rate limiting otherwise.
    """
    
    def __init__(self, app: Callable):
        """
        Initialize hybrid rate limit middleware.
        
        Args:
            app: ASGI application
        """
        self.app = app
        
        # Initialize Redis rate limiter if available
        self.redis_rate_limiter = None
        self.redis_available = False
        
        if settings.redis_url:
            try:
                redis_cache = RedisCacheService(settings.redis_url)
                self.redis_rate_limiter = RedisRateLimitService(redis_cache)
                self.redis_available = True
            except Exception as e:
                self.logger.warning(f"Redis rate limiter unavailable: {e}")
        
        # Always have memory fallback
        self.memory_rate_limiter = InMemoryRateLimiter()
        
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
        
        self.logger.info(f"Hybrid rate limit middleware initialized (Redis: {self.redis_available})")
    
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
            
            # Check rate limits using appropriate service
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
                        "service": rate_limit_result.get("service", "unknown"),
                        "latency_ms": latency_ms
                    }
                )
                
                # Log rate limit exceeded
                log_performance(
                    operation="rate_limit_exceeded",
                    latency_ms=latency_ms,
                    identifier=identifier,
                    path=request.url.path,
                    service=rate_limit_result.get("service")
                )
                
                # Return rate limit error
                headers = {
                    "X-RateLimit-Limit": str(rate_limit_result["limit"]),
                    "X-RateLimit-Remaining": "0",
                    "X-RateLimit-Reset": str(rate_limit_result["reset"]),
                    "Retry-After": str(rate_limit_result["retry_after"]),
                    "X-RateLimit-Service": rate_limit_result.get("service", "unknown")
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
            response.headers["X-RateLimit-Service"] = rate_limit_result.get("service", "unknown")
            
            # Log successful rate limit check
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="rate_limit_check",
                latency_ms=latency_ms,
                identifier=identifier,
                remaining=rate_limit_result["remaining"],
                service=rate_limit_result.get("service")
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
            
            # Get user-specific limits
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
        Check rate limits using Redis or memory fallback.
        
        Args:
            identifier: Rate limit identifier
            limits: Rate limit configuration
            
        Returns:
            Dict with rate limit check results
        """
        # Try Redis first if available
        if self.redis_available and self.redis_rate_limiter:
            try:
                return await self._check_redis_rate_limits(identifier, limits)
            except Exception as e:
                self.logger.warning(f"Redis rate limiting failed, falling back to memory: {e}")
                self.redis_available = False
        
        # Fall back to memory rate limiting
        return await self._check_memory_rate_limits(identifier, limits)
    
    async def _check_redis_rate_limits(
        self, 
        identifier: str, 
        limits: Dict[str, int]
    ) -> Dict[str, any]:
        """Check rate limits using Redis."""
        # Check minute limit
        minute_allowed = await self.redis_rate_limiter.is_allowed(
            f"{identifier}:minute",
            limits["requests_per_minute"],
            timedelta(minutes=1)
        )
        
        # Check hour limit
        hour_allowed = await self.redis_rate_limiter.is_allowed(
            f"{identifier}:hour",
            limits["requests_per_hour"],
            timedelta(hours=1)
        )
        
        # Overall allowed if both limits pass
        allowed = minute_allowed and hour_allowed
        
        # Get remaining counts
        minute_remaining = await self.redis_rate_limiter.get_remaining(
            f"{identifier}:minute",
            limits["requests_per_minute"],
            timedelta(minutes=1)
        )
        
        hour_remaining = await self.redis_rate_limiter.get_remaining(
            f"{identifier}:hour",
            limits["requests_per_hour"],
            timedelta(hours=1)
        )
        
        # Use the most restrictive limit
        if minute_remaining < hour_remaining:
            limit_info = {
                "limit": limits["requests_per_minute"],
                "remaining": minute_remaining,
                "window": "minute"
            }
        else:
            limit_info = {
                "limit": limits["requests_per_hour"],
                "remaining": hour_remaining,
                "window": "hour"
            }
        
        # Get reset time
        reset_time = await self.redis_rate_limiter.get_reset_time(
            f"{identifier}:{limit_info['window']}",
            timedelta(minutes=1) if limit_info['window'] == 'minute' else timedelta(hours=1)
        )
        
        return {
            "allowed": allowed,
            "limit": limit_info["limit"],
            "remaining": limit_info["remaining"],
            "reset": reset_time or int(time.time() + 60),
            "retry_after": 60 if limit_info['window'] == 'minute' else 3600,
            "window": limit_info['window'],
            "service": "redis"
        }
    
    async def _check_memory_rate_limits(
        self, 
        identifier: str, 
        limits: Dict[str, int]
    ) -> Dict[str, any]:
        """Check rate limits using memory fallback."""
        # Check minute limit
        minute_allowed, minute_info = await self.memory_rate_limiter.is_allowed(
            f"{identifier}:minute",
            limits["requests_per_minute"],
            60
        )
        
        # Check hour limit
        hour_allowed, hour_info = await self.memory_rate_limiter.is_allowed(
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
            "window": limit_info.get("window", "minute"),
            "service": "memory"
        }
    
    async def get_rate_limit_status(self, identifier: str) -> Dict[str, Any]:
        """
        Get current rate limit status for an identifier.
        
        Args:
            identifier: Rate limit identifier
            
        Returns:
            Dict with current rate limit status
        """
        try:
            if self.redis_available and self.redis_rate_limiter:
                # Get Redis status
                minute_remaining = await self.redis_rate_limiter.get_remaining(
                    f"{identifier}:minute",
                    self.default_limits["requests_per_minute"],
                    timedelta(minutes=1)
                )
                
                hour_remaining = await self.redis_rate_limiter.get_remaining(
                    f"{identifier}:hour",
                    self.default_limits["requests_per_hour"],
                    timedelta(hours=1)
                )
                
                return {
                    "service": "redis",
                    "minute_remaining": minute_remaining,
                    "hour_remaining": hour_remaining,
                    "limits": self.default_limits
                }
            else:
                # Get memory status
                minute_stats = await self.memory_rate_limiter.get_usage_stats(f"{identifier}:minute")
                hour_stats = await self.memory_rate_limiter.get_usage_stats(f"{identifier}:hour")
                
                return {
                    "service": "memory",
                    "minute_stats": minute_stats,
                    "hour_stats": hour_stats,
                    "limits": self.default_limits
                }
                
        except Exception as e:
            return {
                "service": "error",
                "error": str(e)
            }
