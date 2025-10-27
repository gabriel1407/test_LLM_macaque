"""
Redis-based cache service implementation.
Provides distributed caching with automatic serialization and TTL management.
"""
import json
import time
import asyncio
from typing import Optional, Dict, Any, List
from datetime import timedelta, datetime
import aioredis
from aioredis import Redis

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import CacheError
from app.domain.interfaces.cache_service import (
    CacheServiceWithStats, 
    CacheServiceWithBulkOps,
    RateLimitService
)
from app.domain.entities.summary_response import SummaryResponse


class RedisCacheService(CacheServiceWithStats, CacheServiceWithBulkOps, LoggerMixin):
    """
    Redis-based cache service with comprehensive features.
    
    Provides caching, bulk operations, and statistics tracking.
    """
    
    def __init__(self, redis_url: Optional[str] = None, default_ttl: int = 3600):
        """
        Initialize Redis cache service.
        
        Args:
            redis_url: Redis connection URL
            default_ttl: Default TTL in seconds
        """
        self.redis_url = redis_url or settings.redis_url
        self.default_ttl = default_ttl
        self.redis: Optional[Redis] = None
        self.connection_pool = None
        
        # Statistics tracking
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0,
            "total_operations": 0
        }
        
        self.logger.info(f"Redis cache service initialized with URL: {self._mask_url(self.redis_url)}")
    
    async def connect(self) -> None:
        """Establish Redis connection."""
        if not self.redis_url:
            raise CacheError("Redis URL not configured")
        
        try:
            # Create connection pool for better performance
            self.connection_pool = aioredis.ConnectionPool.from_url(
                self.redis_url,
                max_connections=20,
                retry_on_timeout=True,
                socket_timeout=5,
                socket_connect_timeout=5
            )
            
            self.redis = Redis(connection_pool=self.connection_pool)
            
            # Test connection
            await self.redis.ping()
            
            self.logger.info("Redis connection established successfully")
            
        except Exception as e:
            self.logger.error(f"Failed to connect to Redis: {e}")
            raise CacheError(f"Redis connection failed: {e}")
    
    async def disconnect(self) -> None:
        """Close Redis connection."""
        if self.redis:
            await self.redis.close()
        if self.connection_pool:
            await self.connection_pool.disconnect()
        
        self.logger.info("Redis connection closed")
    
    async def get_summary(self, cache_key: str) -> Optional[SummaryResponse]:
        """Retrieve a cached summary response."""
        if not self.redis:
            await self.connect()
        
        start_time = time.time()
        
        try:
            # Get data from Redis
            cached_data = await self.redis.get(cache_key)
            
            if cached_data:
                # Deserialize and create SummaryResponse
                data = json.loads(cached_data)
                response = SummaryResponse(**data)
                
                # Update statistics
                self.stats["hits"] += 1
                self.stats["total_operations"] += 1
                
                # Log cache hit
                latency_ms = (time.time() - start_time) * 1000
                log_performance(
                    operation="cache_hit",
                    latency_ms=latency_ms,
                    cache_key=cache_key[:16]  # Truncate for privacy
                )
                
                self.logger.debug(f"Cache hit for key: {cache_key[:16]}...")
                return response
            
            else:
                # Cache miss
                self.stats["misses"] += 1
                self.stats["total_operations"] += 1
                
                self.logger.debug(f"Cache miss for key: {cache_key[:16]}...")
                return None
                
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["total_operations"] += 1
            
            self.logger.error(f"Cache get error: {e}")
            raise CacheError(f"Failed to get from cache: {e}")
    
    async def set_summary(
        self, 
        cache_key: str, 
        response: SummaryResponse, 
        ttl: Optional[timedelta] = None
    ) -> bool:
        """Store a summary response in cache."""
        if not self.redis:
            await self.connect()
        
        start_time = time.time()
        
        try:
            # Serialize response
            data = response.dict()
            serialized_data = json.dumps(data, default=str)
            
            # Set TTL
            ttl_seconds = int(ttl.total_seconds()) if ttl else self.default_ttl
            
            # Store in Redis
            await self.redis.setex(cache_key, ttl_seconds, serialized_data)
            
            # Update statistics
            self.stats["sets"] += 1
            self.stats["total_operations"] += 1
            
            # Log cache set
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="cache_set",
                latency_ms=latency_ms,
                cache_key=cache_key[:16],
                ttl_seconds=ttl_seconds
            )
            
            self.logger.debug(f"Cached response for key: {cache_key[:16]}... (TTL: {ttl_seconds}s)")
            return True
            
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["total_operations"] += 1
            
            self.logger.error(f"Cache set error: {e}")
            raise CacheError(f"Failed to set cache: {e}")
    
    async def delete_summary(self, cache_key: str) -> bool:
        """Delete a cached summary."""
        if not self.redis:
            await self.connect()
        
        try:
            result = await self.redis.delete(cache_key)
            
            # Update statistics
            self.stats["deletes"] += 1
            self.stats["total_operations"] += 1
            
            self.logger.debug(f"Deleted cache key: {cache_key[:16]}...")
            return bool(result)
            
        except Exception as e:
            self.stats["errors"] += 1
            self.stats["total_operations"] += 1
            
            self.logger.error(f"Cache delete error: {e}")
            raise CacheError(f"Failed to delete from cache: {e}")
    
    async def exists(self, cache_key: str) -> bool:
        """Check if a key exists in cache."""
        if not self.redis:
            await self.connect()
        
        try:
            result = await self.redis.exists(cache_key)
            return bool(result)
            
        except Exception as e:
            self.logger.error(f"Cache exists check error: {e}")
            return False
    
    async def get_ttl(self, cache_key: str) -> Optional[int]:
        """Get time to live for a cached item."""
        if not self.redis:
            await self.connect()
        
        try:
            ttl = await self.redis.ttl(cache_key)
            return ttl if ttl > 0 else None
            
        except Exception as e:
            self.logger.error(f"Cache TTL check error: {e}")
            return None
    
    async def get_multiple(self, cache_keys: List[str]) -> Dict[str, Optional[SummaryResponse]]:
        """Retrieve multiple cached summaries."""
        if not self.redis:
            await self.connect()
        
        try:
            # Use pipeline for efficiency
            pipe = self.redis.pipeline()
            for key in cache_keys:
                pipe.get(key)
            
            results = await pipe.execute()
            
            # Process results
            responses = {}
            for i, (key, data) in enumerate(zip(cache_keys, results)):
                if data:
                    try:
                        response_data = json.loads(data)
                        responses[key] = SummaryResponse(**response_data)
                        self.stats["hits"] += 1
                    except Exception as e:
                        self.logger.warning(f"Failed to deserialize cached data for key {key}: {e}")
                        responses[key] = None
                        self.stats["errors"] += 1
                else:
                    responses[key] = None
                    self.stats["misses"] += 1
            
            self.stats["total_operations"] += len(cache_keys)
            return responses
            
        except Exception as e:
            self.stats["errors"] += len(cache_keys)
            self.stats["total_operations"] += len(cache_keys)
            
            self.logger.error(f"Bulk cache get error: {e}")
            raise CacheError(f"Failed to get multiple from cache: {e}")
    
    async def set_multiple(
        self, 
        items: Dict[str, SummaryResponse], 
        ttl: Optional[timedelta] = None
    ) -> Dict[str, bool]:
        """Store multiple summary responses in cache."""
        if not self.redis:
            await self.connect()
        
        try:
            ttl_seconds = int(ttl.total_seconds()) if ttl else self.default_ttl
            
            # Use pipeline for efficiency
            pipe = self.redis.pipeline()
            for key, response in items.items():
                data = response.dict()
                serialized_data = json.dumps(data, default=str)
                pipe.setex(key, ttl_seconds, serialized_data)
            
            results = await pipe.execute()
            
            # Process results
            success_map = {}
            for i, (key, result) in enumerate(zip(items.keys(), results)):
                success_map[key] = bool(result)
                if result:
                    self.stats["sets"] += 1
                else:
                    self.stats["errors"] += 1
            
            self.stats["total_operations"] += len(items)
            return success_map
            
        except Exception as e:
            self.stats["errors"] += len(items)
            self.stats["total_operations"] += len(items)
            
            self.logger.error(f"Bulk cache set error: {e}")
            raise CacheError(f"Failed to set multiple in cache: {e}")
    
    async def delete_multiple(self, cache_keys: List[str]) -> Dict[str, bool]:
        """Delete multiple cached summaries."""
        if not self.redis:
            await self.connect()
        
        try:
            # Use pipeline for efficiency
            pipe = self.redis.pipeline()
            for key in cache_keys:
                pipe.delete(key)
            
            results = await pipe.execute()
            
            # Process results
            success_map = {}
            for key, result in zip(cache_keys, results):
                success_map[key] = bool(result)
                if result:
                    self.stats["deletes"] += 1
            
            self.stats["total_operations"] += len(cache_keys)
            return success_map
            
        except Exception as e:
            self.stats["errors"] += len(cache_keys)
            self.stats["total_operations"] += len(cache_keys)
            
            self.logger.error(f"Bulk cache delete error: {e}")
            raise CacheError(f"Failed to delete multiple from cache: {e}")
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        total_ops = self.stats["total_operations"]
        hit_rate = (self.stats["hits"] / total_ops) if total_ops > 0 else 0
        error_rate = (self.stats["errors"] / total_ops) if total_ops > 0 else 0
        
        # Get Redis info if available
        redis_info = {}
        if self.redis:
            try:
                info = await self.redis.info()
                redis_info = {
                    "connected_clients": info.get("connected_clients", 0),
                    "used_memory_human": info.get("used_memory_human", "unknown"),
                    "keyspace_hits": info.get("keyspace_hits", 0),
                    "keyspace_misses": info.get("keyspace_misses", 0)
                }
            except Exception as e:
                redis_info = {"error": str(e)}
        
        return {
            "cache_type": "redis",
            "hit_rate": round(hit_rate, 4),
            "error_rate": round(error_rate, 4),
            "operations": self.stats.copy(),
            "redis_info": redis_info
        }
    
    async def reset_stats(self) -> None:
        """Reset cache statistics."""
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "errors": 0,
            "total_operations": 0
        }
        self.logger.info("Cache statistics reset")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check cache service health."""
        try:
            if not self.redis:
                await self.connect()
            
            # Test basic operations
            test_key = "health_check_test"
            test_value = json.dumps({"test": True, "timestamp": time.time()})
            
            # Test set
            await self.redis.setex(test_key, 10, test_value)
            
            # Test get
            result = await self.redis.get(test_key)
            
            # Test delete
            await self.redis.delete(test_key)
            
            # Get Redis info
            info = await self.redis.info()
            
            return {
                "status": "healthy",
                "cache_type": "redis",
                "test_operations": "passed",
                "connected_clients": info.get("connected_clients", 0),
                "used_memory": info.get("used_memory_human", "unknown"),
                "uptime_seconds": info.get("uptime_in_seconds", 0)
            }
            
        except Exception as e:
            return {
                "status": "unhealthy",
                "cache_type": "redis",
                "error": str(e)
            }
    
    def _mask_url(self, url: Optional[str]) -> str:
        """Mask sensitive parts of Redis URL for logging."""
        if not url:
            return "None"
        
        # Simple masking - hide password if present
        if "@" in url:
            parts = url.split("@")
            if len(parts) == 2:
                # Format: redis://user:password@host:port
                return f"{parts[0].split(':')[0]}://***@{parts[1]}"
        
        return url


class RedisRateLimitService(RateLimitService, LoggerMixin):
    """
    Redis-based rate limiting service.
    
    Implements distributed rate limiting using Redis.
    """
    
    def __init__(self, redis_cache: RedisCacheService):
        """
        Initialize Redis rate limiter.
        
        Args:
            redis_cache: Redis cache service instance
        """
        self.redis_cache = redis_cache
        self.logger.info("Redis rate limiter initialized")
    
    async def is_allowed(
        self, 
        identifier: str, 
        limit: int, 
        window: timedelta
    ) -> bool:
        """Check if an action is allowed within rate limits."""
        if not self.redis_cache.redis:
            await self.redis_cache.connect()
        
        try:
            current_time = int(time.time())
            window_seconds = int(window.total_seconds())
            
            # Use sliding window with Redis sorted sets
            key = f"rate_limit:{identifier}"
            
            # Remove old entries
            cutoff_time = current_time - window_seconds
            await self.redis_cache.redis.zremrangebyscore(key, 0, cutoff_time)
            
            # Count current requests
            current_count = await self.redis_cache.redis.zcard(key)
            
            if current_count >= limit:
                return False
            
            # Add current request
            await self.redis_cache.redis.zadd(key, {str(current_time): current_time})
            
            # Set expiration for cleanup
            await self.redis_cache.redis.expire(key, window_seconds)
            
            return True
            
        except Exception as e:
            self.logger.error(f"Rate limit check error: {e}")
            # Allow request on error to avoid blocking service
            return True
    
    async def get_remaining(
        self, 
        identifier: str, 
        limit: int, 
        window: timedelta
    ) -> int:
        """Get remaining requests for an identifier."""
        if not self.redis_cache.redis:
            await self.redis_cache.connect()
        
        try:
            current_time = int(time.time())
            window_seconds = int(window.total_seconds())
            
            key = f"rate_limit:{identifier}"
            
            # Remove old entries
            cutoff_time = current_time - window_seconds
            await self.redis_cache.redis.zremrangebyscore(key, 0, cutoff_time)
            
            # Count current requests
            current_count = await self.redis_cache.redis.zcard(key)
            
            return max(0, limit - current_count)
            
        except Exception as e:
            self.logger.error(f"Rate limit remaining check error: {e}")
            return limit  # Return full limit on error
    
    async def get_reset_time(
        self, 
        identifier: str, 
        window: timedelta
    ) -> Optional[int]:
        """Get timestamp when rate limit resets."""
        if not self.redis_cache.redis:
            await self.redis_cache.connect()
        
        try:
            key = f"rate_limit:{identifier}"
            
            # Get oldest entry
            oldest_entries = await self.redis_cache.redis.zrange(key, 0, 0, withscores=True)
            
            if oldest_entries:
                oldest_time = int(oldest_entries[0][1])
                reset_time = oldest_time + int(window.total_seconds())
                return reset_time
            
            return None
            
        except Exception as e:
            self.logger.error(f"Rate limit reset time check error: {e}")
            return None
    
    async def reset_limit(self, identifier: str) -> bool:
        """Reset rate limit for an identifier."""
        if not self.redis_cache.redis:
            await self.redis_cache.connect()
        
        try:
            key = f"rate_limit:{identifier}"
            result = await self.redis_cache.redis.delete(key)
            return bool(result)
            
        except Exception as e:
            self.logger.error(f"Rate limit reset error: {e}")
            return False
