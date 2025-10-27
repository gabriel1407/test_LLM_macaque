"""
Interface for LLM providers following Interface Segregation Principle.
Defines the contract for all LLM implementations.
"""
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, AsyncContextManager
from contextlib import asynccontextmanager

from app.domain.entities.summary_request import SummaryRequest
from app.domain.entities.summary_response import SummaryResponse, TokenUsage


class LLMProvider(ABC):
    """
    Abstract base class for LLM providers.
    
    This interface follows the Interface Segregation Principle by providing
    only the methods that LLM providers need to implement.
    """
    
    @abstractmethod
    async def generate_summary(self, request: SummaryRequest) -> SummaryResponse:
        """
        Generate a summary for the given request.
        
        Args:
            request: The summary request containing text and parameters
            
        Returns:
            SummaryResponse: The generated summary with metadata
            
        Raises:
            LLMProviderError: If generation fails
            LLMProviderTimeoutError: If request times out
            LLMProviderQuotaError: If quota is exceeded
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Check the health and availability of the LLM provider.
        
        Returns:
            Dict containing health status information
            
        Example:
            {
                "status": "healthy|unhealthy|degraded",
                "latency_ms": 150,
                "model_available": True,
                "quota_remaining": 1000,
                "last_error": None
            }
        """
        pass
    
    @abstractmethod
    def get_provider_name(self) -> str:
        """
        Get the name of the LLM provider.
        
        Returns:
            str: Provider name (e.g., "openai", "anthropic")
        """
        pass
    
    @abstractmethod
    def get_model_name(self) -> str:
        """
        Get the name of the model being used.
        
        Returns:
            str: Model name (e.g., "gpt-3.5-turbo", "claude-3-sonnet")
        """
        pass
    
    @abstractmethod
    async def estimate_tokens(self, text: str) -> int:
        """
        Estimate the number of tokens for the given text.
        
        Args:
            text: The text to estimate tokens for
            
        Returns:
            int: Estimated number of tokens
        """
        pass
    
    @abstractmethod
    def get_max_tokens_limit(self) -> int:
        """
        Get the maximum number of tokens supported by this provider.
        
        Returns:
            int: Maximum token limit
        """
        pass
    
    @abstractmethod
    def supports_language(self, language_code: str) -> bool:
        """
        Check if the provider supports the given language.
        
        Args:
            language_code: Language code to check (e.g., "en", "es")
            
        Returns:
            bool: True if language is supported
        """
        pass


class LLMProviderWithStreaming(LLMProvider):
    """
    Extended interface for LLM providers that support streaming responses.
    
    This follows ISP by separating streaming capabilities into a separate interface.
    """
    
    @abstractmethod
    async def generate_summary_stream(self, request: SummaryRequest) -> AsyncContextManager[Any]:
        """
        Generate a summary with streaming response.
        
        Args:
            request: The summary request
            
        Returns:
            AsyncContextManager that yields partial responses
        """
        pass


class LLMProviderWithBatch(LLMProvider):
    """
    Extended interface for LLM providers that support batch processing.
    
    This follows ISP by separating batch capabilities into a separate interface.
    """
    
    @abstractmethod
    async def generate_summaries_batch(self, requests: list[SummaryRequest]) -> list[SummaryResponse]:
        """
        Generate summaries for multiple requests in batch.
        
        Args:
            requests: List of summary requests
            
        Returns:
            List of summary responses
        """
        pass


class LLMProviderFactory(ABC):
    """
    Factory interface for creating LLM providers.
    
    This follows the Factory pattern and Dependency Inversion Principle.
    """
    
    @abstractmethod
    def create_provider(self, provider_type: str, **kwargs) -> LLMProvider:
        """
        Create an LLM provider instance.
        
        Args:
            provider_type: Type of provider to create (e.g., "openai", "anthropic")
            **kwargs: Additional configuration parameters
            
        Returns:
            LLMProvider: Configured provider instance
            
        Raises:
            ConfigurationError: If provider type is unsupported or configuration is invalid
        """
        pass
    
    @abstractmethod
    def get_supported_providers(self) -> list[str]:
        """
        Get list of supported provider types.
        
        Returns:
            List of supported provider type strings
        """
        pass


class LLMProviderMetrics(ABC):
    """
    Interface for LLM provider metrics collection.
    
    Separate interface following ISP for metrics concerns.
    """
    
    @abstractmethod
    async def record_request(self, request: SummaryRequest, response: SummaryResponse) -> None:
        """
        Record metrics for a completed request.
        
        Args:
            request: The original request
            response: The generated response
        """
        pass
    
    @abstractmethod
    async def record_error(self, request: SummaryRequest, error: Exception) -> None:
        """
        Record metrics for a failed request.
        
        Args:
            request: The original request
            error: The error that occurred
        """
        pass
    
    @abstractmethod
    async def get_metrics_summary(self) -> Dict[str, Any]:
        """
        Get summary of collected metrics.
        
        Returns:
            Dict containing metrics summary
        """
        pass
