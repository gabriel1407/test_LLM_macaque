"""
Interface for cache services following Interface Segregation Principle.
Defines contracts for caching operations.
"""
from abc import ABC, abstractmethod
from typing import Optional, Any, Dict, List
from datetime import timedelta

from app.domain.entities.summary_request import SummaryRequest
from app.domain.entities.summary_response import SummaryResponse


class CacheService(ABC):
    """
    Abstract base class for cache services.
    
    This interface provides caching capabilities for summary responses
    and other data that can benefit from caching.
    """
    
    @abstractmethod
    async def get_summary(self, cache_key: str) -> Optional[SummaryResponse]:
        """
        Retrieve a cached summary response.
        
        Args:
            cache_key: Unique key for the cached summary
            
        Returns:
            SummaryResponse if found in cache, None otherwise
        """
        pass
    
    @abstractmethod
    async def set_summary(
        self, 
        cache_key: str, 
        response: SummaryResponse, 
        ttl: Optional[timedelta] = None
    ) -> bool:
        """
        Store a summary response in cache.
        
        Args:
            cache_key: Unique key for the summary
            response: Summary response to cache
            ttl: Time to live for the cached item
            
        Returns:
            bool: True if successfully cached
        """
        pass
    
    @abstractmethod
    async def delete_summary(self, cache_key: str) -> bool:
        """
        Delete a cached summary.
        
        Args:
            cache_key: Key of the summary to delete
            
        Returns:
            bool: True if successfully deleted
        """
        pass
    
    @abstractmethod
    async def exists(self, cache_key: str) -> bool:
        """
        Check if a key exists in cache.
        
        Args:
            cache_key: Key to check
            
        Returns:
            bool: True if key exists
        """
        pass
    
    @abstractmethod
    async def get_ttl(self, cache_key: str) -> Optional[int]:
        """
        Get time to live for a cached item.
        
        Args:
            cache_key: Key to check TTL for
            
        Returns:
            int: TTL in seconds, None if key doesn't exist or no TTL
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check cache service health.
        
        Returns:
            Dict containing health information
        """
        pass


class CacheServiceWithStats(CacheService):
    """
    Extended cache interface with statistics capabilities.
    
    Follows ISP by separating statistics into a separate interface.
    """
    
    @abstractmethod
    async def get_stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.
        
        Returns:
            Dict containing cache statistics like hit rate, miss rate, etc.
        """
        pass
    
    @abstractmethod
    async def reset_stats(self) -> None:
        """Reset cache statistics."""
        pass


class CacheServiceWithBulkOps(CacheService):
    """
    Extended cache interface with bulk operations.
    
    Follows ISP by separating bulk operations into a separate interface.
    """
    
    @abstractmethod
    async def get_multiple(self, cache_keys: List[str]) -> Dict[str, Optional[SummaryResponse]]:
        """
        Retrieve multiple cached summaries.
        
        Args:
            cache_keys: List of cache keys
            
        Returns:
            Dict mapping cache keys to responses (None if not found)
        """
        pass
    
    @abstractmethod
    async def set_multiple(
        self, 
        items: Dict[str, SummaryResponse], 
        ttl: Optional[timedelta] = None
    ) -> Dict[str, bool]:
        """
        Store multiple summary responses in cache.
        
        Args:
            items: Dict mapping cache keys to responses
            ttl: Time to live for all items
            
        Returns:
            Dict mapping cache keys to success status
        """
        pass
    
    @abstractmethod
    async def delete_multiple(self, cache_keys: List[str]) -> Dict[str, bool]:
        """
        Delete multiple cached summaries.
        
        Args:
            cache_keys: List of keys to delete
            
        Returns:
            Dict mapping cache keys to deletion success status
        """
        pass


class CacheServiceWithPatterns(CacheService):
    """
    Extended cache interface with pattern-based operations.
    
    Follows ISP by separating pattern operations into a separate interface.
    """
    
    @abstractmethod
    async def delete_pattern(self, pattern: str) -> int:
        """
        Delete all keys matching a pattern.
        
        Args:
            pattern: Pattern to match (e.g., "summary:*")
            
        Returns:
            int: Number of keys deleted
        """
        pass
    
    @abstractmethod
    async def get_keys_by_pattern(self, pattern: str) -> List[str]:
        """
        Get all keys matching a pattern.
        
        Args:
            pattern: Pattern to match
            
        Returns:
            List of matching keys
        """
        pass


class RateLimitService(ABC):
    """
    Interface for rate limiting services.
    
    Separate from cache service following Single Responsibility Principle.
    """
    
    @abstractmethod
    async def is_allowed(
        self, 
        identifier: str, 
        limit: int, 
        window: timedelta
    ) -> bool:
        """
        Check if an action is allowed within rate limits.
        
        Args:
            identifier: Unique identifier (e.g., API key, IP address)
            limit: Maximum number of requests allowed
            window: Time window for the limit
            
        Returns:
            bool: True if action is allowed
        """
        pass
    
    @abstractmethod
    async def get_remaining(
        self, 
        identifier: str, 
        limit: int, 
        window: timedelta
    ) -> int:
        """
        Get remaining requests for an identifier.
        
        Args:
            identifier: Unique identifier
            limit: Maximum number of requests allowed
            window: Time window for the limit
            
        Returns:
            int: Number of remaining requests
        """
        pass
    
    @abstractmethod
    async def get_reset_time(
        self, 
        identifier: str, 
        window: timedelta
    ) -> Optional[int]:
        """
        Get timestamp when rate limit resets.
        
        Args:
            identifier: Unique identifier
            window: Time window for the limit
            
        Returns:
            int: Unix timestamp when limit resets, None if no limit set
        """
        pass
    
    @abstractmethod
    async def reset_limit(self, identifier: str) -> bool:
        """
        Reset rate limit for an identifier.
        
        Args:
            identifier: Unique identifier
            
        Returns:
            bool: True if successfully reset
        """
        pass
