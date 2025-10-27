"""
Authentication middleware for FastAPI.
Handles API key validation and user context.
"""
import time
from typing import Optional, Callable
from fastapi import Request, Response, HTTPException, status
from fastapi.security.utils import get_authorization_scheme_param

from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import AuthenticationError
from app.services.auth.api_key_auth import APIKeyAuthService
from app.domain.interfaces.auth_service import AuthUser


class AuthenticationMiddleware(LoggerMixin):
    """
    Authentication middleware for API key validation.
    
    Validates API keys and adds user context to requests.
    """
    
    def __init__(self, app: Callable):
        """
        Initialize authentication middleware.
        
        Args:
            app: ASGI application
        """
        self.app = app
        self.auth_service = APIKeyAuthService()
        
        # Paths that don't require authentication
        self.public_paths = {
            "/",
            "/docs",
            "/redoc", 
            "/openapi.json",
            "/v1/healthz"  # Health check is public
        }
        
        self.logger.info("Authentication middleware initialized")
    
    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """
        Process request through authentication middleware.
        
        Args:
            request: FastAPI request
            call_next: Next middleware/endpoint
            
        Returns:
            Response: HTTP response
        """
        start_time = time.time()
        
        # Skip authentication for public paths
        if request.url.path in self.public_paths:
            return await call_next(request)
        
        # Skip authentication for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)
        
        try:
            # Extract and validate API key
            user = await self._authenticate_request(request)
            
            # Add user to request state
            request.state.user = user
            
            # Record API usage
            await self.auth_service.record_api_usage(
                user.api_key,
                request.url.path,
                tokens_used=None  # Will be updated after response
            )
            
            # Process request
            response = await call_next(request)
            
            # Log successful authentication
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="auth_middleware_success",
                latency_ms=latency_ms,
                user_id=user.user_id,
                path=request.url.path
            )
            
            return response
            
        except AuthenticationError as e:
            latency_ms = (time.time() - start_time) * 1000
            
            self.logger.warning(
                f"Authentication failed in middleware: {e}",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "latency_ms": latency_ms
                }
            )
            
            # Log failed authentication
            log_performance(
                operation="auth_middleware_failed",
                latency_ms=latency_ms,
                path=request.url.path,
                error=str(e)
            )
            
            return Response(
                content='{"error": "Authentication required", "error_code": "AUTHENTICATION_REQUIRED"}',
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Bearer"},
                media_type="application/json"
            )
        
        except Exception as e:
            latency_ms = (time.time() - start_time) * 1000
            
            self.logger.error(
                f"Unexpected error in auth middleware: {e}",
                extra={
                    "path": request.url.path,
                    "method": request.method,
                    "latency_ms": latency_ms
                }
            )
            
            return Response(
                content='{"error": "Internal authentication error", "error_code": "AUTH_ERROR"}',
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                media_type="application/json"
            )
    
    async def _authenticate_request(self, request: Request) -> AuthUser:
        """
        Extract and validate API key from request.
        
        Args:
            request: FastAPI request
            
        Returns:
            AuthUser: Authenticated user
            
        Raises:
            AuthenticationError: If authentication fails
        """
        # Get Authorization header
        authorization = request.headers.get("Authorization")
        if not authorization:
            raise AuthenticationError("Authorization header missing")
        
        # Parse Bearer token
        scheme, credentials = get_authorization_scheme_param(authorization)
        if scheme.lower() != "bearer":
            raise AuthenticationError("Invalid authentication scheme. Use Bearer token.")
        
        if not credentials:
            raise AuthenticationError("API key missing")
        
        # Authenticate with auth service
        user = await self.auth_service.authenticate(credentials)
        
        return user


def get_current_user_from_request(request: Request) -> Optional[AuthUser]:
    """
    Get current user from request state.
    
    Args:
        request: FastAPI request
        
    Returns:
        Optional[AuthUser]: Current user if authenticated
    """
    return getattr(request.state, "user", None)


class OptionalAuthenticationMiddleware(LoggerMixin):
    """
    Optional authentication middleware.
    
    Attempts authentication but doesn't fail if no credentials provided.
    Useful for endpoints that work with or without authentication.
    """
    
    def __init__(self, app: Callable):
        """Initialize optional auth middleware."""
        self.app = app
        self.auth_service = APIKeyAuthService()
        self.logger.info("Optional authentication middleware initialized")
    
    async def __call__(self, request: Request, call_next: Callable) -> Response:
        """Process request with optional authentication."""
        try:
            # Try to authenticate
            authorization = request.headers.get("Authorization")
            if authorization:
                scheme, credentials = get_authorization_scheme_param(authorization)
                if scheme.lower() == "bearer" and credentials:
                    user = await self.auth_service.authenticate(credentials)
                    request.state.user = user
        
        except Exception:
            # Ignore authentication errors for optional auth
            pass
        
        return await call_next(request)
