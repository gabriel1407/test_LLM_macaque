"""
Main summary service that orchestrates LLM providers and fallback mechanisms.
Implements the core business logic following SOLID principles.
"""
import asyncio
import time
from typing import Optional, List

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import (
    LLMProviderError, 
    LLMProviderTimeoutError, 
    LLMProviderQuotaError,
    LLMProviderUnavailableError,
    FallbackError,
    CacheError
)
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.interfaces.fallback_service import FallbackService
from app.domain.interfaces.cache_service import CacheService
from app.domain.entities.summary_request import SummaryRequest
from app.domain.entities.summary_response import SummaryResponse, SummarySource
from app.services.llm.factory import create_default_provider
from app.services.fallback.textrank_summarizer import TextRankSummarizer
from app.services.fallback.tfidf_summarizer import TFIDFSummarizer


class SummaryService(LoggerMixin):
    """
    Main service for text summarization.
    
    Orchestrates LLM providers, fallback mechanisms, and caching.
    Implements circuit breaker pattern for resilience.
    """
    
    def __init__(
        self,
        llm_provider: Optional[LLMProvider] = None,
        fallback_services: Optional[List[FallbackService]] = None,
        cache_service: Optional[CacheService] = None
    ):
        """
        Initialize summary service.
        
        Args:
            llm_provider: Primary LLM provider
            fallback_services: List of fallback services
            cache_service: Cache service for responses
        """
        self.llm_provider = llm_provider or create_default_provider()
        self.fallback_services = fallback_services or [
            TextRankSummarizer(),
            TFIDFSummarizer()
        ]
        self.cache_service = cache_service
        
        # Circuit breaker state
        self.circuit_breaker = CircuitBreaker(
            failure_threshold=3,
            recovery_timeout=60,
            expected_exception=LLMProviderError
        )
        
        self.logger.info("Summary service initialized")
    
    async def generate_summary(self, request: SummaryRequest) -> SummaryResponse:
        """
        Generate summary for the given request.
        
        Implements the following flow:
        1. Check cache for existing summary
        2. Try LLM provider (with circuit breaker)
        3. Fall back to extractive summarization
        4. Cache successful responses
        """
        start_time = time.time()
        
        try:
            self.logger.info(f"Processing summary request: {request}")
            
            # Step 1: Check cache
            if self.cache_service:
                cached_response = await self._try_cache_lookup(request)
                if cached_response:
                    return cached_response
            
            # Step 2: Try LLM provider
            try:
                response = await self._try_llm_generation(request)
                
                # Cache successful LLM response
                if self.cache_service:
                    await self._try_cache_store(request, response)
                
                return response
                
            except (LLMProviderError, LLMProviderTimeoutError, LLMProviderUnavailableError) as e:
                self.logger.warning(f"LLM provider failed: {e}. Falling back to extractive summarization.")
                
                # Step 3: Fall back to extractive summarization
                response = await self._try_fallback_generation(request)
                
                # Cache fallback response with shorter TTL
                if self.cache_service:
                    await self._try_cache_store(request, response, ttl_seconds=300)  # 5 minutes
                
                return response
            
        except Exception as e:
            total_latency = (time.time() - start_time) * 1000
            self.logger.error(f"Summary generation failed completely: {e}")
            
            # Log failure metrics
            log_performance(
                operation="summary_generation_failed",
                latency_ms=total_latency,
                error=str(e)
            )
            
            raise e
    
    async def _try_cache_lookup(self, request: SummaryRequest) -> Optional[SummaryResponse]:
        """Try to get summary from cache."""
        try:
            cache_key = request.get_cache_key()
            cached_response = await self.cache_service.get_summary(cache_key)
            
            if cached_response:
                # Mark as cache hit
                cached_response.cache_hit = True
                cached_response.source = SummarySource.CACHE
                
                self.logger.info(f"Cache hit for request: {cache_key}")
                
                # Log cache hit
                log_performance(
                    operation="cache_hit",
                    latency_ms=0,
                    cache_key=cache_key
                )
                
                return cached_response
            
            return None
            
        except CacheError as e:
            self.logger.warning(f"Cache lookup failed: {e}")
            return None
    
    async def _try_cache_store(
        self, 
        request: SummaryRequest, 
        response: SummaryResponse,
        ttl_seconds: Optional[int] = None
    ) -> None:
        """Try to store summary in cache."""
        try:
            from datetime import timedelta
            
            cache_key = request.get_cache_key()
            ttl_value = ttl_seconds if ttl_seconds is not None else settings.redis_ttl
            
            # Convert int seconds to timedelta
            ttl = timedelta(seconds=ttl_value) if isinstance(ttl_value, int) else ttl_value
            
            await self.cache_service.set_summary(
                cache_key, 
                response, 
                ttl=ttl
            )
            
            self.logger.info(f"Cached response for key: {cache_key}")
            
        except CacheError as e:
            self.logger.warning(f"Cache store failed: {e}")
    
    async def _try_llm_generation(self, request: SummaryRequest) -> SummaryResponse:
        """Try to generate summary using LLM provider."""
        async with self.circuit_breaker:
            # Add timeout to LLM call
            try:
                response = await asyncio.wait_for(
                    self.llm_provider.generate_summary(request),
                    timeout=settings.get_llm_timeout_seconds()
                )
                
                self.logger.info(f"LLM generation successful: {response}")
                return response
                
            except asyncio.TimeoutError:
                raise LLMProviderTimeoutError("LLM provider timed out")
    
    async def _try_fallback_generation(self, request: SummaryRequest) -> SummaryResponse:
        """Try to generate summary using fallback services."""
        last_error = None
        
        for fallback_service in self.fallback_services:
            try:
                # Check if service supports the language
                if not fallback_service.supports_language(request.lang):
                    continue
                
                self.logger.info(f"Trying fallback service: {fallback_service.get_algorithm_name()}")
                
                response = await fallback_service.generate_summary(request)
                
                self.logger.info(f"Fallback generation successful: {response}")
                return response
                
            except FallbackError as e:
                last_error = e
                self.logger.warning(f"Fallback service {fallback_service.get_algorithm_name()} failed: {e}")
                continue
        
        # If all fallback services failed
        raise FallbackError(f"All fallback services failed. Last error: {last_error}")
    
    async def health_check(self) -> dict:
        """Check health of all components."""
        health_status = {
            "status": "healthy",
            "components": {},
            "timestamp": time.time()
        }
        
        # Check LLM provider
        try:
            llm_health = await self.llm_provider.health_check()
            health_status["components"]["llm_provider"] = llm_health
        except Exception as e:
            health_status["components"]["llm_provider"] = {
                "status": "unhealthy",
                "error": str(e)
            }
            health_status["status"] = "degraded"
        
        # Check fallback services
        fallback_health = []
        for service in self.fallback_services:
            try:
                service_health = await service.health_check()
                fallback_health.append(service_health)
            except Exception as e:
                fallback_health.append({
                    "status": "unhealthy",
                    "algorithm": service.get_algorithm_name(),
                    "error": str(e)
                })
        
        health_status["components"]["fallback_services"] = fallback_health
        
        # Check cache service
        if self.cache_service:
            try:
                cache_health = await self.cache_service.health_check()
                health_status["components"]["cache_service"] = cache_health
            except Exception as e:
                health_status["components"]["cache_service"] = {
                    "status": "unhealthy",
                    "error": str(e)
                }
        
        # Check circuit breaker
        health_status["components"]["circuit_breaker"] = {
            "status": "open" if self.circuit_breaker.is_open else "closed",
            "failure_count": self.circuit_breaker.failure_count
        }
        
        return health_status


class CircuitBreaker:
    """
    Circuit breaker implementation for LLM provider resilience.
    
    Prevents cascading failures by temporarily disabling failed services.
    """
    
    def __init__(
        self, 
        failure_threshold: int = 3,
        recovery_timeout: int = 60,
        expected_exception: type = Exception
    ):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            recovery_timeout: Seconds to wait before trying again
            expected_exception: Exception type that triggers circuit breaker
        """
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.is_open = False
    
    async def __aenter__(self):
        """Async context manager entry."""
        if self.is_open:
            if self._should_attempt_reset():
                self.is_open = False
                self.failure_count = 0
            else:
                raise LLMProviderUnavailableError("Circuit breaker is open")
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        if exc_type is None:
            # Success - reset failure count
            self.failure_count = 0
            return False
        
        if isinstance(exc_val, self.expected_exception):
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.is_open = True
        
        # Don't suppress the exception
        return False
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt reset."""
        if self.last_failure_time is None:
            return True
        
        return (time.time() - self.last_failure_time) >= self.recovery_timeout
