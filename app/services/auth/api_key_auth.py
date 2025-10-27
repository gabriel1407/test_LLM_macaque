"""
API Key authentication service implementation.
Handles API key validation, user management, and usage tracking.
"""
import time
import hashlib
from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
from collections import defaultdict

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import AuthenticationError, AuthorizationError
from app.domain.interfaces.auth_service import (
    AuthService, 
    AuthServiceWithUsageTracking,
    AuthUser, 
    UserRole, 
    APIKeyStatus
)


class APIKeyAuthService(AuthServiceWithUsageTracking, LoggerMixin):
    """
    API Key authentication service implementation.
    
    Provides authentication, authorization, and usage tracking capabilities.
    """
    
    def __init__(self):
        """Initialize the authentication service."""
        self.api_keys = self._load_api_keys()
        self.usage_stats = defaultdict(lambda: defaultdict(int))
        self.last_usage = {}
        
        self.logger.info(f"API Key auth service initialized with {len(self.api_keys)} keys")
    
    def _load_api_keys(self) -> Dict[str, Dict[str, Any]]:
        """Load API keys from configuration."""
        api_keys = {}
        
        # Load from settings
        for i, key in enumerate(settings.api_keys_allowed):
            if key and len(key) >= 10:  # Basic validation
                user_id = f"user_{hashlib.md5(key.encode()).hexdigest()[:8]}"
                api_keys[key] = {
                    "user_id": user_id,
                    "status": APIKeyStatus.ACTIVE,
                    "role": UserRole.USER,
                    "created_at": datetime.utcnow(),
                    "last_used": None,
                    "usage_count": 0,
                    "rate_limit": 100,  # Default rate limit
                    "metadata": {
                        "name": f"API Key {i+1}",
                        "tier": "standard"
                    }
                }
        
        # Add some predefined keys for testing/demo
        if settings.environment == "development":
            demo_keys = {
                "demo-key-12345": {
                    "user_id": "demo_user",
                    "status": APIKeyStatus.ACTIVE,
                    "role": UserRole.USER,
                    "created_at": datetime.utcnow(),
                    "last_used": None,
                    "usage_count": 0,
                    "rate_limit": 60,
                    "metadata": {"name": "Demo Key", "tier": "demo"}
                },
                "admin-key-67890": {
                    "user_id": "admin_user",
                    "status": APIKeyStatus.ACTIVE,
                    "role": UserRole.ADMIN,
                    "created_at": datetime.utcnow(),
                    "last_used": None,
                    "usage_count": 0,
                    "rate_limit": 1000,
                    "metadata": {"name": "Admin Key", "tier": "admin"}
                }
            }
            api_keys.update(demo_keys)
        
        return api_keys
    
    async def authenticate(self, api_key: str) -> AuthUser:
        """Authenticate a user by API key."""
        start_time = time.time()
        
        try:
            if not await self.validate_api_key(api_key):
                raise AuthenticationError("Invalid or inactive API key")
            
            key_info = self.api_keys[api_key]
            
            # Update last used timestamp
            key_info["last_used"] = datetime.utcnow()
            self.last_usage[api_key] = time.time()
            
            # Create user object
            user = AuthUser(
                user_id=key_info["user_id"],
                api_key=api_key,
                role=key_info["role"],
                metadata=key_info["metadata"]
            )
            
            # Log successful authentication
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="authentication_success",
                latency_ms=latency_ms,
                user_id=user.user_id
            )
            
            self.logger.info(
                f"User authenticated successfully",
                extra={
                    "user_id": user.user_id,
                    "role": user.role,
                    "latency_ms": latency_ms
                }
            )
            
            return user
            
        except AuthenticationError:
            # Log failed authentication
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="authentication_failed",
                latency_ms=latency_ms,
                api_key_prefix=api_key[:8] if api_key else "none"
            )
            
            self.logger.warning(
                f"Authentication failed",
                extra={
                    "api_key_prefix": api_key[:8] if api_key else "none",
                    "latency_ms": latency_ms
                }
            )
            raise
    
    async def validate_api_key(self, api_key: str) -> bool:
        """Validate if an API key is valid and active."""
        if not api_key or api_key not in self.api_keys:
            return False
        
        key_info = self.api_keys[api_key]
        
        # Check if key is active
        if key_info["status"] != APIKeyStatus.ACTIVE:
            return False
        
        # Check if key has expired (if expiration is set)
        expires_at = key_info.get("expires_at")
        if expires_at and datetime.utcnow() > expires_at:
            key_info["status"] = APIKeyStatus.EXPIRED
            return False
        
        return True
    
    async def get_api_key_info(self, api_key: str) -> Dict[str, Any]:
        """Get information about an API key."""
        if api_key not in self.api_keys:
            raise AuthenticationError("API key not found")
        
        key_info = self.api_keys[api_key].copy()
        
        # Remove sensitive information
        safe_info = {
            "user_id": key_info["user_id"],
            "status": key_info["status"].value,
            "role": key_info["role"].value,
            "created_at": key_info["created_at"].isoformat(),
            "last_used": key_info["last_used"].isoformat() if key_info["last_used"] else None,
            "usage_count": key_info["usage_count"],
            "rate_limit": key_info["rate_limit"],
            "metadata": key_info["metadata"]
        }
        
        return safe_info
    
    async def record_api_usage(
        self, 
        api_key: str, 
        endpoint: str,
        tokens_used: Optional[int] = None
    ) -> None:
        """Record API usage for an API key."""
        if api_key in self.api_keys:
            # Update usage count
            self.api_keys[api_key]["usage_count"] += 1
            
            # Track usage by endpoint
            today = datetime.utcnow().date().isoformat()
            self.usage_stats[api_key][f"{today}:{endpoint}"] += 1
            
            if tokens_used:
                self.usage_stats[api_key][f"{today}:tokens"] += tokens_used
            
            self.logger.debug(
                f"API usage recorded",
                extra={
                    "api_key_prefix": api_key[:8],
                    "endpoint": endpoint,
                    "tokens_used": tokens_used
                }
            )
    
    async def get_usage_stats(
        self, 
        api_key: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """Get usage statistics for an API key."""
        if api_key not in self.api_keys:
            raise AuthenticationError("API key not found")
        
        key_info = self.api_keys[api_key]
        stats = self.usage_stats[api_key]
        
        # Filter by date range if provided
        if start_date or end_date:
            filtered_stats = {}
            for key, value in stats.items():
                if ":" in key:
                    date_str = key.split(":")[0]
                    try:
                        stat_date = datetime.fromisoformat(date_str).date()
                        if start_date and stat_date < start_date.date():
                            continue
                        if end_date and stat_date > end_date.date():
                            continue
                        filtered_stats[key] = value
                    except ValueError:
                        continue
            stats = filtered_stats
        
        return {
            "user_id": key_info["user_id"],
            "total_requests": key_info["usage_count"],
            "rate_limit": key_info["rate_limit"],
            "usage_by_endpoint": dict(stats),
            "last_used": key_info["last_used"].isoformat() if key_info["last_used"] else None
        }
    
    async def check_usage_limits(self, api_key: str) -> Dict[str, Any]:
        """Check if API key is within usage limits."""
        if api_key not in self.api_keys:
            raise AuthenticationError("API key not found")
        
        key_info = self.api_keys[api_key]
        
        # Check rate limits (simplified - in production use Redis)
        current_time = time.time()
        last_used = self.last_usage.get(api_key, 0)
        
        # Simple rate limiting check
        rate_limit = key_info["rate_limit"]
        time_window = 60  # 1 minute window
        
        within_limits = (current_time - last_used) > (60 / rate_limit)
        
        return {
            "within_limits": within_limits,
            "rate_limit": rate_limit,
            "time_window_seconds": time_window,
            "next_allowed_time": last_used + (60 / rate_limit) if not within_limits else None
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check authentication service health."""
        try:
            # Count active keys
            active_keys = sum(
                1 for key_info in self.api_keys.values()
                if key_info["status"] == APIKeyStatus.ACTIVE
            )
            
            # Check if we can validate a dummy key
            test_result = await self.validate_api_key("non-existent-key")
            
            return {
                "status": "healthy",
                "active_api_keys": active_keys,
                "total_api_keys": len(self.api_keys),
                "validation_test": "passed" if not test_result else "failed"
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e)
            }


class SimpleAPIKeyAuth(AuthService, LoggerMixin):
    """
    Simplified API key authentication for basic use cases.
    
    This is a lighter version without usage tracking.
    """
    
    def __init__(self):
        """Initialize simple auth service."""
        self.allowed_keys = set(settings.api_keys_allowed)
        self.logger.info(f"Simple API auth initialized with {len(self.allowed_keys)} keys")
    
    async def authenticate(self, api_key: str) -> AuthUser:
        """Authenticate using simple key validation."""
        if not await self.validate_api_key(api_key):
            raise AuthenticationError("Invalid API key")
        
        # Generate consistent user ID from API key
        user_id = f"user_{hashlib.md5(api_key.encode()).hexdigest()[:8]}"
        
        return AuthUser(
            user_id=user_id,
            api_key=api_key,
            role=UserRole.USER
        )
    
    async def validate_api_key(self, api_key: str) -> bool:
        """Simple API key validation."""
        if not self.allowed_keys:
            # If no keys configured, allow any key with minimum length
            return api_key and len(api_key) >= 10
        
        return api_key in self.allowed_keys
    
    async def get_api_key_info(self, api_key: str) -> Dict[str, Any]:
        """Get basic API key information."""
        if not await self.validate_api_key(api_key):
            raise AuthenticationError("Invalid API key")
        
        user_id = f"user_{hashlib.md5(api_key.encode()).hexdigest()[:8]}"
        
        return {
            "user_id": user_id,
            "status": "active",
            "role": "user",
            "created_at": datetime.utcnow().isoformat(),
            "usage_count": 0,
            "rate_limit": 100
        }
    
    async def health_check(self) -> Dict[str, Any]:
        """Check simple auth service health."""
        return {
            "status": "healthy",
            "configured_keys": len(self.allowed_keys),
            "type": "simple"
        }
