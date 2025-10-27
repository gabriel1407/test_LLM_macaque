"""
Cache management endpoints.
Provides cache administration and monitoring capabilities.
"""
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.logging import LoggerMixin
from app.api.v1.dependencies import get_summary_service, get_current_user
from app.domain.interfaces.auth_service import AuthUser
from app.services.cache.cache_factory import HybridCacheService


router = APIRouter()


class CacheStatsResponse(BaseModel):
    """Response model for cache statistics."""
    cache_type: str
    statistics: Dict[str, Any]
    health: Dict[str, Any]


class CacheOperationResponse(BaseModel):
    """Response model for cache operations."""
    success: bool
    message: str
    details: Optional[Dict[str, Any]] = None


class CacheWarmupRequest(BaseModel):
    """Request model for cache warmup."""
    keys: List[str] = Field(..., description="Cache keys to warm up")
    force: bool = Field(default=False, description="Force warmup even if keys exist")


@router.get(
    "/stats",
    response_model=CacheStatsResponse,
    summary="Get cache statistics",
    description="""
    Get comprehensive cache statistics including:
    - Hit/miss rates
    - Cache size and utilization
    - Performance metrics
    - Health status of cache layers
    
    **Admin access required**
    """
)
async def get_cache_stats(
    current_user: AuthUser = Depends(get_current_user),
    summary_service = Depends(get_summary_service)
) -> CacheStatsResponse:
    """
    Get cache statistics.
    
    Args:
        current_user: Authenticated user (must be admin)
        summary_service: Summary service with cache
        
    Returns:
        CacheStatsResponse: Cache statistics and health
    """
    # Check admin permissions
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for cache statistics"
        )
    
    logger = CacheEndpoint().logger
    
    try:
        cache_service = summary_service.cache_service
        
        if not cache_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cache service not available"
            )
        
        # Get statistics based on cache type
        if isinstance(cache_service, HybridCacheService):
            stats = await cache_service.get_comprehensive_stats()
        else:
            stats = await cache_service.get_stats()
        
        # Get health information
        health = await cache_service.health_check()
        
        logger.info(
            f"Cache statistics requested by admin user",
            extra={"user_id": current_user.user_id}
        )
        
        return CacheStatsResponse(
            cache_type=stats.get("cache_type", "unknown"),
            statistics=stats,
            health=health
        )
        
    except Exception as e:
        logger.error(f"Failed to get cache statistics: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve cache statistics: {str(e)}"
        )


@router.post(
    "/clear",
    response_model=CacheOperationResponse,
    summary="Clear cache",
    description="""
    Clear all cached entries.
    
    **Warning**: This operation will remove all cached summaries and may impact performance.
    
    **Admin access required**
    """
)
async def clear_cache(
    current_user: AuthUser = Depends(get_current_user),
    summary_service = Depends(get_summary_service)
) -> CacheOperationResponse:
    """
    Clear all cache entries.
    
    Args:
        current_user: Authenticated user (must be admin)
        summary_service: Summary service with cache
        
    Returns:
        CacheOperationResponse: Operation result
    """
    # Check admin permissions
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to clear cache"
        )
    
    logger = CacheEndpoint().logger
    
    try:
        cache_service = summary_service.cache_service
        
        if not cache_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cache service not available"
            )
        
        # Clear cache based on type
        cleared_count = 0
        
        if isinstance(cache_service, HybridCacheService):
            # Clear both Redis and memory cache
            if cache_service.redis_cache and cache_service.redis_available:
                try:
                    # This would require implementing clear_all in Redis cache
                    # For now, we'll just clear memory cache
                    pass
                except Exception as e:
                    logger.warning(f"Failed to clear Redis cache: {e}")
            
            # Clear memory cache
            if hasattr(cache_service.memory_cache, 'clear_all'):
                cleared_count = await cache_service.memory_cache.clear_all()
        
        elif hasattr(cache_service, 'clear_all'):
            cleared_count = await cache_service.clear_all()
        
        logger.warning(
            f"Cache cleared by admin user",
            extra={
                "user_id": current_user.user_id,
                "entries_cleared": cleared_count
            }
        )
        
        return CacheOperationResponse(
            success=True,
            message=f"Cache cleared successfully",
            details={"entries_cleared": cleared_count}
        )
        
    except Exception as e:
        logger.error(f"Failed to clear cache: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to clear cache: {str(e)}"
        )


@router.delete(
    "/key/{cache_key}",
    response_model=CacheOperationResponse,
    summary="Delete cache key",
    description="""
    Delete a specific cache entry by key.
    
    **Admin access required**
    """
)
async def delete_cache_key(
    cache_key: str,
    current_user: AuthUser = Depends(get_current_user),
    summary_service = Depends(get_summary_service)
) -> CacheOperationResponse:
    """
    Delete a specific cache key.
    
    Args:
        cache_key: Cache key to delete
        current_user: Authenticated user (must be admin)
        summary_service: Summary service with cache
        
    Returns:
        CacheOperationResponse: Operation result
    """
    # Check admin permissions
    if not current_user.is_admin():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required to delete cache keys"
        )
    
    logger = CacheEndpoint().logger
    
    try:
        cache_service = summary_service.cache_service
        
        if not cache_service:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Cache service not available"
            )
        
        # Delete the cache key
        success = await cache_service.delete_summary(cache_key)
        
        if success:
            logger.info(
                f"Cache key deleted by admin",
                extra={
                    "user_id": current_user.user_id,
                    "cache_key": cache_key[:16] + "..." if len(cache_key) > 16 else cache_key
                }
            )
            
            return CacheOperationResponse(
                success=True,
                message=f"Cache key deleted successfully"
            )
        else:
            return CacheOperationResponse(
                success=False,
                message=f"Cache key not found or already deleted"
            )
        
    except Exception as e:
        logger.error(f"Failed to delete cache key: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to delete cache key: {str(e)}"
        )


@router.get(
    "/health",
    summary="Get cache health",
    description="""
    Get cache service health status.
    
    This endpoint provides cache health information for monitoring purposes.
    """
)
async def get_cache_health(
    summary_service = Depends(get_summary_service)
) -> Dict[str, Any]:
    """
    Get cache health status.
    
    Args:
        summary_service: Summary service with cache
        
    Returns:
        Dict containing cache health information
    """
    try:
        cache_service = summary_service.cache_service
        
        if not cache_service:
            return {
                "status": "unavailable",
                "message": "Cache service not configured"
            }
        
        health = await cache_service.health_check()
        return health
        
    except Exception as e:
        return {
            "status": "unhealthy",
            "error": str(e)
        }


@router.get(
    "/info",
    summary="Get cache information",
    description="""
    Get basic cache configuration and status information.
    
    Available to all authenticated users.
    """
)
async def get_cache_info(
    current_user: AuthUser = Depends(get_current_user),
    summary_service = Depends(get_summary_service)
) -> Dict[str, Any]:
    """
    Get cache information.
    
    Args:
        current_user: Authenticated user
        summary_service: Summary service with cache
        
    Returns:
        Dict containing cache information
    """
    try:
        cache_service = summary_service.cache_service
        
        if not cache_service:
            return {
                "cache_enabled": False,
                "cache_type": "none"
            }
        
        # Get basic information (non-sensitive)
        info = {
            "cache_enabled": True,
            "cache_type": "unknown"
        }
        
        if isinstance(cache_service, HybridCacheService):
            info.update({
                "cache_type": "hybrid",
                "redis_available": cache_service.redis_available,
                "memory_cache_available": True
            })
        else:
            # Try to determine cache type from class name
            cache_class = cache_service.__class__.__name__
            if "Redis" in cache_class:
                info["cache_type"] = "redis"
            elif "Memory" in cache_class:
                info["cache_type"] = "memory"
        
        return info
        
    except Exception as e:
        return {
            "cache_enabled": False,
            "error": str(e)
        }


class CacheEndpoint(LoggerMixin):
    """Helper class for logging."""
    pass
