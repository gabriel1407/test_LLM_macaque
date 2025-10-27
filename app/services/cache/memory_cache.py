"""
In-memory cache service implementation.
Provides local caching with TTL management as fallback for Redis.
"""
import time
import asyncio
from typing import Optional, Dict, Any, List
from datetime import timedelta, datetime
from collections import OrderedDict
import threading

from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import CacheError
from app.domain.interfaces.cache_service import CacheServiceWithStats
from app.domain.entities.summary_response import SummaryResponse


class CacheEntry:
    """Cache entry with TTL support."""
    
    def __init__(self, value: SummaryResponse, ttl_seconds: int):
        """
        Initialize cache entry.
        
        Args:
            value: Cached response
            ttl_seconds: Time to live in seconds
        """
        self.value = value
        self.created_at = time.time()
        self.expires_at = self.created_at + ttl_seconds
        self.access_count = 0
        self.last_accessed = self.created_at
    
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        return time.time() > self.expires_at
    
    def access(self) -> SummaryResponse:
        """Access the cached value and update statistics."""
        self.access_count += 1
        self.last_accessed = time.time()
        return self.value
    
    def get_ttl(self) -> int:
        """Get remaining TTL in seconds."""
        remaining = self.expires_at - time.time()
        return max(0, int(remaining))


class MemoryCacheService(CacheServiceWithStats, LoggerMixin):
    """
    In-memory cache service with LRU eviction and TTL support.
    
    Provides local caching as fallback when Redis is unavailable.
    """
    
    def __init__(self, max_size: int = 1000, default_ttl: int = 3600):
        """
        Initialize memory cache service.
        
        Args:
            max_size: Maximum number of entries to cache
            default_ttl: Default TTL in seconds
        """
        self.max_size = max_size
        self.default_ttl = default_ttl
        
        # Thread-safe cache storage
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.RLock()
        
        # Statistics tracking
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "evictions": 0,
            "expired_cleanups": 0,
            "total_operations": 0
        }
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._periodic_cleanup())
        
        self.logger.info(f"Memory cache service initialized (max_size: {max_size}, default_ttl: {default_ttl}s)")
    
    async def get_summary(self, cache_key: str) -> Optional[SummaryResponse]:
        """Retrieve a cached summary response."""
        start_time = time.time()
        
        with self._lock:
            entry = self._cache.get(cache_key)
            
            if entry is None:
                # Cache miss
                self.stats["misses"] += 1
                self.stats["total_operations"] += 1
                
                self.logger.debug(f"Cache miss for key: {cache_key[:16]}...")
                return None
            
            if entry.is_expired():
                # Entry expired
                del self._cache[cache_key]
                self.stats["misses"] += 1
                self.stats["expired_cleanups"] += 1
                self.stats["total_operations"] += 1
                
                self.logger.debug(f"Cache entry expired for key: {cache_key[:16]}...")
                return None
            
            # Cache hit - move to end (LRU)
            self._cache.move_to_end(cache_key)
            response = entry.access()
            
            # Update statistics
            self.stats["hits"] += 1
            self.stats["total_operations"] += 1
            
            # Log cache hit
            latency_ms = (time.time() - start_time) * 1000
            log_performance(
                operation="memory_cache_hit",
                latency_ms=latency_ms,
                cache_key=cache_key[:16]
            )
            
            self.logger.debug(f"Memory cache hit for key: {cache_key[:16]}...")
            return response
    
    async def set_summary(
        self, 
        cache_key: str, 
        response: SummaryResponse, 
        ttl: Optional[timedelta] = None
    ) -> bool:
        """Store a summary response in cache."""
        start_time = time.time()
        
        try:
            ttl_seconds = int(ttl.total_seconds()) if ttl else self.default_ttl
            
            with self._lock:
                # Create cache entry
                entry = CacheEntry(response, ttl_seconds)
                
                # Check if we need to evict entries
                if cache_key not in self._cache and len(self._cache) >= self.max_size:
                    self._evict_lru()
                
                # Store entry
                self._cache[cache_key] = entry
                self._cache.move_to_end(cache_key)  # Mark as most recently used
                
                # Update statistics
                self.stats["sets"] += 1
                self.stats["total_operations"] += 1
                
                # Log cache set
                latency_ms = (time.time() - start_time) * 1000
                log_performance(
                    operation="memory_cache_set",
                    latency_ms=latency_ms,
                    cache_key=cache_key[:16],
                    ttl_seconds=ttl_seconds
                )
                
                self.logger.debug(f"Memory cached response for key: {cache_key[:16]}... (TTL: {ttl_seconds}s)")
                return True
                
        except Exception as e:
            self.logger.error(f"Memory cache set error: {e}")
            raise CacheError(f"Failed to set memory cache: {e}")
    
    async def delete_summary(self, cache_key: str) -> bool:
        """Delete a cached summary."""
        with self._lock:
            if cache_key in self._cache:
                del self._cache[cache_key]
                self.stats["deletes"] += 1
                self.stats["total_operations"] += 1
                
                self.logger.debug(f"Deleted memory cache key: {cache_key[:16]}...")
                return True
            
            return False
    
    async def exists(self, cache_key: str) -> bool:
        """Check if a key exists in cache."""
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                return True
            elif entry and entry.is_expired():
                # Clean up expired entry
                del self._cache[cache_key]
                self.stats["expired_cleanups"] += 1
            
            return False
    
    async def get_ttl(self, cache_key: str) -> Optional[int]:
        """Get time to live for a cached item."""
        with self._lock:
            entry = self._cache.get(cache_key)
            if entry and not entry.is_expired():
                return entry.get_ttl()
            
            return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        with self._lock:
            total_ops = self.stats["total_operations"]
            hit_rate = (self.stats["hits"] / total_ops) if total_ops > 0 else 0
            
            # Calculate memory usage estimation
            cache_size = len(self._cache)
            
            # Get entry age statistics
            current_time = time.time()
            ages = []
            access_counts = []
            
            for entry in self._cache.values():
                if not entry.is_expired():
                    ages.append(current_time - entry.created_at)
                    access_counts.append(entry.access_count)
            
            avg_age = sum(ages) / len(ages) if ages else 0
            avg_access_count = sum(access_counts) / len(access_counts) if access_counts else 0
            
            return {
                "cache_type": "memory",
                "hit_rate": round(hit_rate, 4),
                "cache_size": cache_size,
                "max_size": self.max_size,
                "utilization": round(cache_size / self.max_size, 4),
                "avg_entry_age_seconds": round(avg_age, 2),
                "avg_access_count": round(avg_access_count, 2),
                "operations": self.stats.copy()
            }
    
    async def reset_stats(self) -> None:
        """Reset cache statistics."""
        self.stats = {
            "hits": 0,
            "misses": 0,
            "sets": 0,
            "deletes": 0,
            "evictions": 0,
            "expired_cleanups": 0,
            "total_operations": 0
        }
        self.logger.info("Memory cache statistics reset")
    
    async def health_check(self) -> Dict[str, Any]:
        """Check cache service health."""
        try:
            with self._lock:
                cache_size = len(self._cache)
                
                # Test basic operations
                test_key = "health_check_test"
                test_response = SummaryResponse(
                    summary="Health check test",
                    usage={"prompt_tokens": 1, "completion_tokens": 1},
                    model="test",
                    latency_ms=1.0
                )
                
                # Test set
                await self.set_summary(test_key, test_response, timedelta(seconds=1))
                
                # Test get
                result = await self.get_summary(test_key)
                
                # Test delete
                await self.delete_summary(test_key)
                
                return {
                    "status": "healthy",
                    "cache_type": "memory",
                    "cache_size": cache_size,
                    "max_size": self.max_size,
                    "test_operations": "passed" if result else "failed"
                }
                
        except Exception as e:
            return {
                "status": "unhealthy",
                "cache_type": "memory",
                "error": str(e)
            }
    
    def _evict_lru(self) -> None:
        """Evict least recently used entry."""
        if self._cache:
            # Remove oldest entry (first in OrderedDict)
            evicted_key = next(iter(self._cache))
            del self._cache[evicted_key]
            
            self.stats["evictions"] += 1
            self.logger.debug(f"Evicted LRU entry: {evicted_key[:16]}...")
    
    async def _periodic_cleanup(self) -> None:
        """Periodic cleanup of expired entries."""
        while True:
            try:
                await asyncio.sleep(300)  # Clean up every 5 minutes
                
                with self._lock:
                    current_time = time.time()
                    expired_keys = []
                    
                    for key, entry in self._cache.items():
                        if entry.is_expired():
                            expired_keys.append(key)
                    
                    # Remove expired entries
                    for key in expired_keys:
                        del self._cache[key]
                        self.stats["expired_cleanups"] += 1
                    
                    if expired_keys:
                        self.logger.debug(f"Cleaned up {len(expired_keys)} expired entries")
                        
            except Exception as e:
                self.logger.error(f"Error during cache cleanup: {e}")
    
    async def clear_all(self) -> int:
        """Clear all cached entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            self.logger.info(f"Cleared all {count} cache entries")
            return count
    
    def get_cache_info(self) -> Dict[str, Any]:
        """Get detailed cache information."""
        with self._lock:
            current_time = time.time()
            
            entries_info = []
            for key, entry in list(self._cache.items())[:10]:  # Show top 10
                entries_info.append({
                    "key": key[:16] + "..." if len(key) > 16 else key,
                    "age_seconds": round(current_time - entry.created_at, 2),
                    "ttl_seconds": entry.get_ttl(),
                    "access_count": entry.access_count,
                    "last_accessed": round(current_time - entry.last_accessed, 2)
                })
            
            return {
                "total_entries": len(self._cache),
                "max_size": self.max_size,
                "sample_entries": entries_info
            }
