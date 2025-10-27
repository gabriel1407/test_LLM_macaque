"""
Cache service factory with automatic fallback.
Provides Redis cache with memory cache fallback for high availability.
"""
import asyncio
from typing import Optional, Dict, Any, List
from datetime import timedelta

from app.core.config import settings
from app.core.logging import LoggerMixin
from app.core.exceptions import CacheError
from app.domain.interfaces.cache_service import CacheService
from app.domain.entities.summary_response import SummaryResponse
from app.services.cache.redis_cache import RedisCacheService
from app.services.cache.memory_cache import MemoryCacheService


class HybridCacheService(CacheService, LoggerMixin):
    """
    Hybrid cache service with Redis primary and memory fallback.
    
    Automatically falls back to memory cache when Redis is unavailable.
    """
    
    def __init__(
        self, 
        redis_url: Optional[str] = None,
        memory_max_size: int = 1000,
        default_ttl: int = 3600
    ):
        """
        Initialize hybrid cache service.
        
        Args:
            redis_url: Redis connection URL
            memory_max_size: Maximum memory cache entries
            default_ttl: Default TTL in seconds
        """
        self.redis_cache = None
        self.memory_cache = MemoryCacheService(memory_max_size, default_ttl)
        self.default_ttl = default_ttl
        
        # Track which cache is currently active
        self.redis_available = False
        self.last_redis_check = 0
        self.redis_check_interval = 30  # Check Redis every 30 seconds
        
        # Initialize Redis cache if URL is provided
        if redis_url or settings.redis_url:
            self.redis_cache = RedisCacheService(redis_url, default_ttl)
            asyncio.create_task(self._initialize_redis())
        
        self.logger.info("Hybrid cache service initialized")
    
    async def _initialize_redis(self) -> None:
        """Initialize Redis connection with error handling."""
        try:
            await self.redis_cache.connect()
            self.redis_available = True
            self.logger.info("Redis cache is available")
        except Exception as e:
            self.redis_available = False
            self.logger.warning(f"Redis cache unavailable, using memory cache: {e}")
    
    async def _check_redis_availability(self) -> bool:
        """Check if Redis is available and reconnect if needed."""
        import time
        
        current_time = time.time()
        
        # Only check periodically to avoid overhead
        if current_time - self.last_redis_check < self.redis_check_interval:
            return self.redis_available
        
        self.last_redis_check = current_time
        
        if not self.redis_cache:
            return False
        
        try:
            # Simple ping to check connectivity
            if not self.redis_cache.redis:
                await self.redis_cache.connect()
            else:
                await self.redis_cache.redis.ping()
            
            if not self.redis_available:
                self.logger.info("Redis cache is now available")
            
            self.redis_available = True
            return True
            
        except Exception as e:
            if self.redis_available:
                self.logger.warning(f"Redis cache became unavailable: {e}")
            
            self.redis_available = False
            return False
    
    async def get_summary(self, cache_key: str) -> Optional[SummaryResponse]:
        """Retrieve cached summary with fallback logic."""
        # Try Redis first if available
        if await self._check_redis_availability():
            try:
                result = await self.redis_cache.get_summary(cache_key)
                if result:
                    # Also cache in memory for faster subsequent access
                    await self.memory_cache.set_summary(
                        cache_key, result, timedelta(seconds=300)  # 5 min in memory
                    )
                return result
            except CacheError as e:
                self.logger.warning(f"Redis get failed, falling back to memory: {e}")
                self.redis_available = False
        
        # Fall back to memory cache
        return await self.memory_cache.get_summary(cache_key)
    
    async def set_summary(
        self, 
        cache_key: str, 
        response: SummaryResponse, 
        ttl: Optional[timedelta] = None
    ) -> bool:
        """Store summary in cache with fallback logic."""
        ttl = ttl or timedelta(seconds=self.default_ttl)
        success = False
        
        # Try Redis first if available
        if await self._check_redis_availability():
            try:
                success = await self.redis_cache.set_summary(cache_key, response, ttl)
            except CacheError as e:
                self.logger.warning(f"Redis set failed, falling back to memory: {e}")
                self.redis_available = False
        
        # Always cache in memory as well (with shorter TTL)
        memory_ttl = min(ttl, timedelta(seconds=1800))  # Max 30 min in memory
        memory_success = await self.memory_cache.set_summary(cache_key, response, memory_ttl)
        
        return success or memory_success
    
    async def delete_summary(self, cache_key: str) -> bool:
        """Delete summary from both caches."""
        redis_success = False
        memory_success = False
        
        # Try Redis if available
        if await self._check_redis_availability():
            try:
                redis_success = await self.redis_cache.delete_summary(cache_key)
            except CacheError as e:
                self.logger.warning(f"Redis delete failed: {e}")
        
        # Always try memory cache
        memory_success = await self.memory_cache.delete_summary(cache_key)
        
        return redis_success or memory_success
    
    async def exists(self, cache_key: str) -> bool:
        """Check if key exists in any cache."""
        # Check Redis first if available
        if await self._check_redis_availability():
            try:
                if await self.redis_cache.exists(cache_key):
                    return True
            except CacheError:
                pass
        
        # Check memory cache
        return await self.memory_cache.exists(cache_key)
    
    async def get_ttl(self, cache_key: str) -> Optional[int]:
        """Get TTL from primary cache."""
        # Check Redis first if available
        if await self._check_redis_availability():
            try:
                ttl = await self.redis_cache.get_ttl(cache_key)
                if ttl is not None:
                    return ttl
            except CacheError:
                pass
        
        # Fall back to memory cache
        return await self.memory_cache.get_ttl(cache_key)
    
    async def health_check(self) -> Dict[str, Any]:
        """Check health of both cache layers."""
        redis_health = {"status": "unavailable", "error": "not configured"}
        memory_health = await self.memory_cache.health_check()
        
        if self.redis_cache:
            redis_health = await self.redis_cache.health_check()
        
        overall_status = "healthy"
        if redis_health["status"] == "unhealthy" and memory_health["status"] == "unhealthy":
            overall_status = "unhealthy"
        elif redis_health["status"] == "unhealthy" or memory_health["status"] == "unhealthy":
            overall_status = "degraded"
        
        return {
            "status": overall_status,
            "cache_type": "hybrid",
            "redis_available": self.redis_available,
            "redis_health": redis_health,
            "memory_health": memory_health
        }
    
    async def get_comprehensive_stats(self) -> Dict[str, Any]:
        """Get statistics from both cache layers."""
        stats = {
            "cache_type": "hybrid",
            "redis_available": self.redis_available,
            "memory_stats": await self.memory_cache.get_stats()
        }
        
        if self.redis_cache and self.redis_available:
            try:
                stats["redis_stats"] = await self.redis_cache.get_stats()
            except Exception as e:
                stats["redis_stats"] = {"error": str(e)}
        
        return stats
    
    async def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate cache entries matching pattern (Redis only)."""
        if not await self._check_redis_availability():
            self.logger.warning("Pattern invalidation requires Redis")
            return 0
        
        try:
            # This would require implementing pattern deletion in Redis cache
            # For now, return 0 as not implemented
            return 0
        except Exception as e:
            self.logger.error(f"Pattern invalidation failed: {e}")
            return 0
    
    async def warm_cache(self, cache_data: Dict[str, SummaryResponse]) -> Dict[str, bool]:
        """Warm cache with pre-computed data."""
        results = {}
        
        for key, response in cache_data.items():
            try:
                success = await self.set_summary(key, response)
                results[key] = success
            except Exception as e:
                self.logger.error(f"Failed to warm cache for key {key}: {e}")
                results[key] = False
        
        self.logger.info(f"Cache warming completed: {sum(results.values())}/{len(results)} successful")
        return results


def create_cache_service() -> CacheService:
    """
    Create appropriate cache service based on configuration.
    
    Returns:
        CacheService: Configured cache service
    """
    if settings.redis_url:
        # Use hybrid cache with Redis primary and memory fallback
        return HybridCacheService(
            redis_url=settings.redis_url,
            memory_max_size=1000,
            default_ttl=settings.redis_ttl
        )
    else:
        # Use memory cache only
        return MemoryCacheService(
            max_size=1000,
            default_ttl=settings.redis_ttl
        )


def create_redis_cache_service() -> Optional[RedisCacheService]:
    """
    Create Redis cache service if configured.
    
    Returns:
        Optional[RedisCacheService]: Redis cache service or None
    """
    if settings.redis_url:
        return RedisCacheService(
            redis_url=settings.redis_url,
            default_ttl=settings.redis_ttl
        )
    return None
