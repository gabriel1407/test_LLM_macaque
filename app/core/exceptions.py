"""
Custom exceptions for the LLM Summarizer service.
Following clean code principles with specific, meaningful exception types.
"""
from typing import Optional, Dict, Any


class LLMSummarizerException(Exception):
    """Base exception for all LLM Summarizer errors."""
    
    def __init__(
        self, 
        message: str, 
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None
    ):
        super().__init__(message)
        self.message = message
        self.error_code = error_code or self.__class__.__name__
        self.details = details or {}


class ValidationError(LLMSummarizerException):
    """Raised when input validation fails."""
    pass


class AuthenticationError(LLMSummarizerException):
    """Raised when authentication fails."""
    pass


class AuthorizationError(LLMSummarizerException):
    """Raised when authorization fails."""
    pass


class RateLimitExceededError(LLMSummarizerException):
    """Raised when rate limit is exceeded."""
    pass


class LLMProviderError(LLMSummarizerException):
    """Base exception for LLM provider errors."""
    pass


class LLMProviderTimeoutError(LLMProviderError):
    """Raised when LLM provider times out."""
    pass


class LLMProviderQuotaError(LLMProviderError):
    """Raised when LLM provider quota is exceeded."""
    pass


class LLMProviderUnavailableError(LLMProviderError):
    """Raised when LLM provider is unavailable."""
    pass


class FallbackError(LLMSummarizerException):
    """Raised when fallback summarization fails."""
    pass


class CacheError(LLMSummarizerException):
    """Raised when cache operations fail."""
    pass


class ConfigurationError(LLMSummarizerException):
    """Raised when configuration is invalid."""
    pass


class TextProcessingError(LLMSummarizerException):
    """Raised when text processing fails."""
    pass
