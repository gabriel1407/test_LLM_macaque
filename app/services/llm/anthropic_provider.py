"""
Anthropic LLM provider implementation.
Handles communication with Anthropic's Claude API for text summarization.
"""
import asyncio
import time
from typing import Dict, Any, Optional
import anthropic

from app.core.config import settings
from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import (
    LLMProviderError, 
    LLMProviderTimeoutError, 
    LLMProviderQuotaError,
    LLMProviderUnavailableError,
    ConfigurationError
)
from app.domain.interfaces.llm_provider import LLMProvider
from app.domain.entities.summary_request import SummaryRequest, LanguageCode
from app.domain.entities.summary_response import SummaryResponse, TokenUsage, SummarySource


class AnthropicProvider(LLMProvider, LoggerMixin):
    """
    Anthropic Claude implementation of LLM provider.
    
    Supports Claude-3 models for text summarization.
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "claude-3-sonnet-20240229",
        max_retries: int = 2,
        timeout: float = 8.0
    ):
        """
        Initialize Anthropic provider.
        
        Args:
            api_key: Anthropic API key
            model: Model to use (claude-3-sonnet, claude-3-haiku, etc.)
            max_retries: Maximum number of retries
            timeout: Request timeout in seconds
        """
        if not api_key:
            raise ConfigurationError("Anthropic API key is required")
        
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        
        # Initialize Anthropic client
        self.client = anthropic.AsyncAnthropic(
            api_key=api_key,
            timeout=timeout,
            max_retries=max_retries
        )
        
        # Model capabilities
        self.model_limits = {
            "claude-3-haiku-20240307": 200000,
            "claude-3-sonnet-20240229": 200000,
            "claude-3-opus-20240229": 200000,
            "claude-3-5-sonnet-20241022": 200000
        }
        
        self.logger.info(f"Anthropic provider initialized with model: {model}")
    
    async def generate_summary(self, request: SummaryRequest) -> SummaryResponse:
        """Generate summary using Anthropic's API."""
        start_time = time.time()
        
        try:
            self.logger.info(f"Generating summary with Anthropic: {request}")
            
            # Prepare the prompt
            prompt = self._build_prompt(request)
            
            # Estimate input tokens
            estimated_tokens = await self.estimate_tokens(prompt)
            
            # Check if request fits within model limits
            if estimated_tokens > self.get_max_tokens_limit():
                raise LLMProviderError(
                    f"Text too long for model {self.model}. "
                    f"Estimated {estimated_tokens} tokens, limit is {self.get_max_tokens_limit()}"
                )
            
            # Make API call with retry logic
            response = await self._make_api_call(prompt, request.max_tokens)
            
            # Extract response data
            summary_text = response.content[0].text.strip()
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            # Create response (Anthropic doesn't provide detailed token usage in the same way)
            # We'll estimate the tokens
            prompt_tokens = estimated_tokens
            completion_tokens = await self.estimate_tokens(summary_text)
            
            response_obj = SummaryResponse(
                summary=summary_text,
                usage=TokenUsage(
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens
                ),
                model=self.model,
                latency_ms=latency_ms,
                source=SummarySource.LLM,
                request_id=request.request_id
            )
            
            # Log performance
            log_performance(
                operation="anthropic_summary_generation",
                latency_ms=latency_ms,
                tokens_used=prompt_tokens + completion_tokens,
                model=self.model
            )
            
            self.logger.info(f"Summary generated successfully: {response_obj}")
            return response_obj
            
        except anthropic.RateLimitError as e:
            self.logger.warning(f"Anthropic rate limit exceeded: {e}")
            raise LLMProviderQuotaError(f"Rate limit exceeded: {e}")
        
        except anthropic.APITimeoutError as e:
            self.logger.warning(f"Anthropic API timeout: {e}")
            raise LLMProviderTimeoutError(f"API timeout: {e}")
        
        except anthropic.APIConnectionError as e:
            self.logger.error(f"Anthropic API connection error: {e}")
            raise LLMProviderUnavailableError(f"API connection failed: {e}")
        
        except anthropic.AuthenticationError as e:
            self.logger.error(f"Anthropic authentication error: {e}")
            raise LLMProviderError(f"Authentication failed: {e}")
        
        except Exception as e:
            self.logger.error(f"Unexpected error in Anthropic provider: {e}")
            raise LLMProviderError(f"Unexpected error: {e}")
    
    async def _make_api_call(self, prompt: str, max_tokens: int) -> Any:
        """Make API call with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                response = await self.client.messages.create(
                    model=self.model,
                    max_tokens=max_tokens,
                    temperature=0.3,  # Low temperature for consistent summaries
                    messages=[
                        {
                            "role": "user",
                            "content": prompt
                        }
                    ]
                )
                return response
                
            except (anthropic.RateLimitError, anthropic.APITimeoutError) as e:
                if attempt < self.max_retries:
                    wait_time = (2 ** attempt) * settings.get_retry_delay_seconds()
                    self.logger.warning(f"Retrying Anthropic API call in {wait_time}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait_time)
                    continue
                raise e
    
    def _build_prompt(self, request: SummaryRequest) -> str:
        """Build optimized prompt for Anthropic."""
        # Use the domain entity's prompt generation logic
        base_prompt = request.to_llm_prompt()
        
        # Add Anthropic-specific optimizations
        anthropic_prompt = f"""Human: {base_prompt}

Please provide a high-quality summary that captures the key points and main ideas of the text.

Assistant: I'll provide a concise and accurate summary of the text."""
        
        return anthropic_prompt
    
    async def health_check(self) -> Dict[str, Any]:
        """Check Anthropic API health."""
        try:
            start_time = time.time()
            
            # Simple test request
            await self.client.messages.create(
                model=self.model,
                max_tokens=1,
                messages=[{"role": "user", "content": "Test"}]
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "model_available": True,
                "provider": "anthropic",
                "model": self.model
            }
            
        except anthropic.RateLimitError:
            return {
                "status": "degraded",
                "error": "Rate limit exceeded",
                "provider": "anthropic",
                "model": self.model
            }
        
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "provider": "anthropic",
                "model": self.model
            }
    
    def get_provider_name(self) -> str:
        """Get provider name."""
        return "anthropic"
    
    def get_model_name(self) -> str:
        """Get model name."""
        return self.model
    
    async def estimate_tokens(self, text: str) -> int:
        """
        Estimate tokens for Anthropic models.
        
        This is a rough estimation. For production, you'd use Anthropic's tokenizer.
        """
        # Rough estimation: 1 token ≈ 3.5 characters for Claude
        return max(1, len(text) // 4)
    
    def get_max_tokens_limit(self) -> int:
        """Get maximum tokens for the current model."""
        return self.model_limits.get(self.model, 200000)
    
    def supports_language(self, language_code: str) -> bool:
        """Check if language is supported."""
        # Anthropic models support most major languages
        supported_languages = {
            LanguageCode.AUTO, LanguageCode.ENGLISH, LanguageCode.SPANISH,
            LanguageCode.FRENCH, LanguageCode.GERMAN, LanguageCode.ITALIAN,
            LanguageCode.PORTUGUESE, LanguageCode.RUSSIAN, LanguageCode.CHINESE,
            LanguageCode.JAPANESE, LanguageCode.KOREAN
        }
        
        try:
            lang_enum = LanguageCode(language_code)
            return lang_enum in supported_languages
        except ValueError:
            return False
