"""
FastAPI dependencies for dependency injection.
Implements Dependency Inversion Principle with FastAPI's DI system.
"""
from typing import Optional
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from app.core.config import settings
from app.core.logging import LoggerMixin
from app.core.exceptions import AuthenticationError, ConfigurationError
from app.domain.interfaces.auth_service import AuthUser
from app.services.summary_service import SummaryService
from app.services.llm.factory import create_default_provider
from app.services.cache.cache_factory import create_cache_service


# Security scheme for API key authentication
security = HTTPBearer(
    scheme_name="Bearer Token",
    description="API Key authentication using Bearer token"
)


class DependencyProvider(LoggerMixin):
    """
    Dependency provider following Singleton pattern.
    
    Manages service instances and provides them to FastAPI endpoints.
    """
    
    _instance = None
    _summary_service = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def get_summary_service(self) -> SummaryService:
        """Get or create summary service instance."""
        if self._summary_service is None:
            try:
                # Create LLM provider
                llm_provider = create_default_provider()
                
                # Create cache service
                cache_service = create_cache_service()
                
                # Create summary service with cache
                self._summary_service = SummaryService(
                    llm_provider=llm_provider,
                    cache_service=cache_service
                )
                
                self.logger.info("Summary service initialized with cache")
                
            except Exception as e:
                self.logger.error(f"Failed to initialize summary service: {e}")
                raise ConfigurationError(f"Service initialization failed: {e}")
        
        return self._summary_service


# Global dependency provider instance
_dependency_provider = DependencyProvider()


async def get_summary_service() -> SummaryService:
    """
    FastAPI dependency to get summary service.
    
    Returns:
        SummaryService: Configured summary service instance
    """
    return _dependency_provider.get_summary_service()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> AuthUser:
    """
    FastAPI dependency to get current authenticated user.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        AuthUser: Authenticated user information
        
    Raises:
        HTTPException: If authentication fails
    """
    try:
        # Extract API key from Bearer token
        api_key = credentials.credentials
        
        # Simple API key validation (will be enhanced in Phase 5)
        if not _validate_api_key(api_key):
            raise AuthenticationError("Invalid API key")
        
        # Create user object (simplified for now)
        user = AuthUser(
            user_id=f"user_{hash(api_key) % 10000}",  # Simple user ID generation
            api_key=api_key,
            role="user"
        )
        
        return user
        
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Invalid authentication credentials",
                "error_code": "AUTHENTICATION_FAILED"
            },
            headers={"WWW-Authenticate": "Bearer"}
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": "Authentication error",
                "error_code": "AUTHENTICATION_ERROR"
            },
            headers={"WWW-Authenticate": "Bearer"}
        )


def _validate_api_key(api_key: str) -> bool:
    """
    Simple API key validation.
    
    This is a basic implementation that will be enhanced in Phase 5
    with proper authentication service.
    
    Args:
        api_key: API key to validate
        
    Returns:
        bool: True if API key is valid
    """
    if not api_key:
        return False
    
    # Check against configured allowed keys
    allowed_keys = settings.api_keys_allowed
    
    if not allowed_keys:
        # If no keys are configured, allow any non-empty key for development
        return len(api_key) >= 10
    
    return api_key in allowed_keys


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(
        HTTPBearer(auto_error=False)
    )
) -> Optional[AuthUser]:
    """
    FastAPI dependency to get optional authenticated user.
    
    This dependency doesn't raise an error if no credentials are provided,
    useful for endpoints that work with or without authentication.
    
    Args:
        credentials: Optional HTTP Bearer token credentials
        
    Returns:
        Optional[AuthUser]: Authenticated user or None
    """
    if not credentials:
        return None
    
    try:
        return await get_current_user(credentials)
    except HTTPException:
        return None


class RateLimitDependency:
    """
    Rate limiting dependency (placeholder for Phase 5).
    
    This will be implemented with Redis in Phase 5.
    """
    
    def __init__(self, requests_per_minute: int = 60):
        self.requests_per_minute = requests_per_minute
    
    async def __call__(
        self, 
        user: AuthUser = Depends(get_current_user)
    ) -> None:
        """
        Check rate limits for the user.
        
        Args:
            user: Authenticated user
            
        Raises:
            HTTPException: If rate limit is exceeded
        """
        # Placeholder implementation
        # In Phase 5, this will check Redis for rate limiting
        pass


# Pre-configured rate limit dependencies
rate_limit_standard = RateLimitDependency(requests_per_minute=60)
rate_limit_premium = RateLimitDependency(requests_per_minute=300)


async def validate_request_size(request_body: bytes) -> None:
    """
    Validate request body size.
    
    Args:
        request_body: Raw request body
        
    Raises:
        HTTPException: If request is too large
    """
    max_size = settings.max_payload_size
    
    if len(request_body) > max_size:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": f"Request body too large. Maximum size is {max_size} bytes.",
                "error_code": "PAYLOAD_TOO_LARGE"
            }
        )


class HealthCheckDependency:
    """
    Dependency for health check endpoints.
    
    Provides additional context and logging for health checks.
    """
    
    async def __call__(self) -> dict:
        """
        Prepare health check context.
        
        Returns:
            dict: Health check context
        """
        return {
            "timestamp": "utc_now",
            "environment": settings.environment,
            "version": "1.0.0"
        }


# Health check dependency instance
health_check_context = HealthCheckDependency()
