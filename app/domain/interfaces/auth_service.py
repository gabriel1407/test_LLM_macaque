"""
Interface for authentication and authorization services.
Handles API key validation and user management.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

from app.core.exceptions import AuthenticationError, AuthorizationError


class UserRole(str, Enum):
    """User roles for authorization."""
    ADMIN = "admin"
    USER = "user"
    READONLY = "readonly"


class APIKeyStatus(str, Enum):
    """API Key status types."""
    ACTIVE = "active"
    INACTIVE = "inactive"
    EXPIRED = "expired"
    REVOKED = "revoked"


class AuthUser:
    """
    Domain entity representing an authenticated user.
    
    This is a simple value object for user information.
    """
    
    def __init__(
        self,
        user_id: str,
        api_key: str,
        role: UserRole = UserRole.USER,
        metadata: Optional[Dict[str, Any]] = None
    ):
        self.user_id = user_id
        self.api_key = api_key
        self.role = role
        self.metadata = metadata or {}
        self.authenticated_at = datetime.utcnow()
    
    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        # Simple role-based permissions
        role_permissions = {
            UserRole.ADMIN: ["read", "write", "admin"],
            UserRole.USER: ["read", "write"],
            UserRole.READONLY: ["read"]
        }
        
        return permission in role_permissions.get(self.role, [])
    
    def is_admin(self) -> bool:
        """Check if user is an admin."""
        return self.role == UserRole.ADMIN
    
    def __str__(self) -> str:
        return f"AuthUser(id={self.user_id}, role={self.role})"


class AuthService(ABC):
    """
    Abstract base class for authentication services.
    
    Handles API key validation and user authentication.
    """
    
    @abstractmethod
    async def authenticate(self, api_key: str) -> AuthUser:
        """
        Authenticate a user by API key.
        
        Args:
            api_key: The API key to validate
            
        Returns:
            AuthUser: Authenticated user information
            
        Raises:
            AuthenticationError: If authentication fails
        """
        pass
    
    @abstractmethod
    async def validate_api_key(self, api_key: str) -> bool:
        """
        Validate if an API key is valid and active.
        
        Args:
            api_key: The API key to validate
            
        Returns:
            bool: True if API key is valid
        """
        pass
    
    @abstractmethod
    async def get_api_key_info(self, api_key: str) -> Dict[str, Any]:
        """
        Get information about an API key.
        
        Args:
            api_key: The API key to get info for
            
        Returns:
            Dict containing API key information
            
        Example:
            {
                "user_id": "user123",
                "status": "active",
                "created_at": "2024-01-01T00:00:00Z",
                "last_used": "2024-01-01T12:00:00Z",
                "usage_count": 150,
                "rate_limit": 1000
            }
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check authentication service health.
        
        Returns:
            Dict containing health information
        """
        pass


class AuthServiceWithRoles(AuthService):
    """
    Extended auth interface with role-based authorization.
    
    Follows ISP by separating role management into a separate interface.
    """
    
    @abstractmethod
    async def authorize(self, user: AuthUser, permission: str) -> bool:
        """
        Check if user is authorized for a specific permission.
        
        Args:
            user: Authenticated user
            permission: Permission to check
            
        Returns:
            bool: True if user is authorized
        """
        pass
    
    @abstractmethod
    async def get_user_permissions(self, user: AuthUser) -> List[str]:
        """
        Get all permissions for a user.
        
        Args:
            user: Authenticated user
            
        Returns:
            List of permission strings
        """
        pass
    
    @abstractmethod
    async def update_user_role(self, user_id: str, new_role: UserRole) -> bool:
        """
        Update a user's role.
        
        Args:
            user_id: User identifier
            new_role: New role to assign
            
        Returns:
            bool: True if role was updated successfully
        """
        pass


class AuthServiceWithAPIKeyManagement(AuthService):
    """
    Extended auth interface with API key management capabilities.
    
    Follows ISP by separating key management into a separate interface.
    """
    
    @abstractmethod
    async def create_api_key(
        self, 
        user_id: str, 
        description: Optional[str] = None,
        expires_at: Optional[datetime] = None
    ) -> str:
        """
        Create a new API key for a user.
        
        Args:
            user_id: User identifier
            description: Optional description for the key
            expires_at: Optional expiration date
            
        Returns:
            str: The generated API key
        """
        pass
    
    @abstractmethod
    async def revoke_api_key(self, api_key: str) -> bool:
        """
        Revoke an API key.
        
        Args:
            api_key: The API key to revoke
            
        Returns:
            bool: True if key was revoked successfully
        """
        pass
    
    @abstractmethod
    async def list_api_keys(self, user_id: str) -> List[Dict[str, Any]]:
        """
        List all API keys for a user.
        
        Args:
            user_id: User identifier
            
        Returns:
            List of API key information dicts
        """
        pass
    
    @abstractmethod
    async def update_api_key_status(self, api_key: str, status: APIKeyStatus) -> bool:
        """
        Update the status of an API key.
        
        Args:
            api_key: The API key to update
            status: New status
            
        Returns:
            bool: True if status was updated successfully
        """
        pass


class AuthServiceWithUsageTracking(AuthService):
    """
    Extended auth interface with usage tracking capabilities.
    
    Follows ISP by separating usage tracking into a separate interface.
    """
    
    @abstractmethod
    async def record_api_usage(
        self, 
        api_key: str, 
        endpoint: str,
        tokens_used: Optional[int] = None
    ) -> None:
        """
        Record API usage for an API key.
        
        Args:
            api_key: The API key used
            endpoint: The endpoint accessed
            tokens_used: Number of tokens consumed (if applicable)
        """
        pass
    
    @abstractmethod
    async def get_usage_stats(
        self, 
        api_key: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, Any]:
        """
        Get usage statistics for an API key.
        
        Args:
            api_key: The API key to get stats for
            start_date: Start date for stats (optional)
            end_date: End date for stats (optional)
            
        Returns:
            Dict containing usage statistics
        """
        pass
    
    @abstractmethod
    async def check_usage_limits(self, api_key: str) -> Dict[str, Any]:
        """
        Check if API key is within usage limits.
        
        Args:
            api_key: The API key to check
            
        Returns:
            Dict containing limit information and current usage
        """
        pass


class AuthServiceFactory(ABC):
    """
    Factory interface for creating authentication services.
    
    Follows the Factory pattern and Dependency Inversion Principle.
    """
    
    @abstractmethod
    def create_service(self, auth_type: str, **kwargs) -> AuthService:
        """
        Create an authentication service instance.
        
        Args:
            auth_type: Type of auth service (e.g., "simple", "database", "external")
            **kwargs: Additional configuration parameters
            
        Returns:
            AuthService: Configured auth service instance
        """
        pass
    
    @abstractmethod
    def get_supported_auth_types(self) -> List[str]:
        """
        Get list of supported authentication types.
        
        Returns:
            List of supported auth type strings
        """
        pass
