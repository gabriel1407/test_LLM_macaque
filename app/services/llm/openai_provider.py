"""
OpenAI LLM provider implementation.
Handles communication with OpenAI's API for text summarization.
"""
import asyncio
import time
from typing import Dict, Any, Optional
import openai
from openai import AsyncOpenAI

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


class OpenAIProvider(LLMProvider, LoggerMixin):
    """
    OpenAI implementation of LLM provider.
    
    Supports GPT-3.5-turbo and GPT-4 models for text summarization.
    """
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-3.5-turbo",
        base_url: Optional[str] = None,
        max_retries: int = 2,
        timeout: float = 8.0
    ):
        """
        Initialize OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Model to use (gpt-3.5-turbo, gpt-4, etc.)
            base_url: Custom base URL (for Azure OpenAI)
            max_retries: Maximum number of retries
            timeout: Request timeout in seconds
        """
        if not api_key:
            raise ConfigurationError("OpenAI API key is required")
        
        self.model = model
        self.max_retries = max_retries
        self.timeout = timeout
        
        # Initialize OpenAI client
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
            max_retries=max_retries
        )
        
        # Model capabilities
        self.model_limits = {
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-16k": 16384,
            "gpt-4": 8192,
            "gpt-4-32k": 32768,
            "gpt-4-turbo": 128000,
            "gpt-4o": 128000
        }
        
        self.logger.info(f"OpenAI provider initialized with model: {model}")
    
    async def generate_summary(self, request: SummaryRequest) -> SummaryResponse:
        """Generate summary using OpenAI's API."""
        start_time = time.time()
        
        try:
            self.logger.info(f"Generating summary with OpenAI: {request}")
            
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
            completion = await self._make_api_call(prompt, request.max_tokens)
            
            # Extract response data
            summary_text = completion.choices[0].message.content.strip()
            usage = completion.usage
            
            # Calculate latency
            latency_ms = (time.time() - start_time) * 1000
            
            # Create response
            response = SummaryResponse(
                summary=summary_text,
                usage=TokenUsage(
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens
                ),
                model=self.model,
                latency_ms=latency_ms,
                source=SummarySource.LLM,
                request_id=request.request_id
            )
            
            # Log performance
            log_performance(
                operation="openai_summary_generation",
                latency_ms=latency_ms,
                tokens_used=usage.total_tokens,
                model=self.model
            )
            
            self.logger.info(f"Summary generated successfully: {response}")
            return response
            
        except openai.RateLimitError as e:
            self.logger.warning(f"OpenAI rate limit exceeded: {e}")
            raise LLMProviderQuotaError(f"Rate limit exceeded: {e}")
        
        except openai.APITimeoutError as e:
            self.logger.warning(f"OpenAI API timeout: {e}")
            raise LLMProviderTimeoutError(f"API timeout: {e}")
        
        except openai.APIConnectionError as e:
            self.logger.error(f"OpenAI API connection error: {e}")
            raise LLMProviderUnavailableError(f"API connection failed: {e}")
        
        except openai.AuthenticationError as e:
            self.logger.error(f"OpenAI authentication error: {e}")
            raise LLMProviderError(f"Authentication failed: {e}")
        
        except Exception as e:
            self.logger.error(f"Unexpected error in OpenAI provider: {e}")
            raise LLMProviderError(f"Unexpected error: {e}")
    
    async def _make_api_call(self, prompt: str, max_tokens: int) -> Any:
        """Make API call with retry logic."""
        for attempt in range(self.max_retries + 1):
            try:
                completion = await self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "You are a helpful assistant that creates concise, accurate summaries."
                        },
                        {
                            "role": "user", 
                            "content": prompt
                        }
                    ],
                    max_tokens=max_tokens,
                    temperature=0.3,  # Low temperature for consistent summaries
                    top_p=1.0,
                    frequency_penalty=0.0,
                    presence_penalty=0.0
                )
                return completion
                
            except (openai.RateLimitError, openai.APITimeoutError) as e:
                if attempt < self.max_retries:
                    wait_time = (2 ** attempt) * settings.get_retry_delay_seconds()
                    self.logger.warning(f"Retrying OpenAI API call in {wait_time}s (attempt {attempt + 1})")
                    await asyncio.sleep(wait_time)
                    continue
                raise e
    
    def _build_prompt(self, request: SummaryRequest) -> str:
        """Build optimized prompt for OpenAI."""
        # Use the domain entity's prompt generation logic
        base_prompt = request.to_llm_prompt()
        
        # Add OpenAI-specific optimizations
        if request.tone.value == "bullet":
            base_prompt += "\n\nFormat your response as clear bullet points (•)."
        
        return base_prompt
    
    async def health_check(self) -> Dict[str, Any]:
        """Check OpenAI API health."""
        try:
            start_time = time.time()
            
            # Simple test request
            await self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "Test"}],
                max_tokens=1
            )
            
            latency_ms = (time.time() - start_time) * 1000
            
            return {
                "status": "healthy",
                "latency_ms": round(latency_ms, 2),
                "model_available": True,
                "provider": "openai",
                "model": self.model
            }
            
        except openai.RateLimitError:
            return {
                "status": "degraded",
                "error": "Rate limit exceeded",
                "provider": "openai",
                "model": self.model
            }
        
        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "provider": "openai",
                "model": self.model
            }
    
    def get_provider_name(self) -> str:
        """Get provider name."""
        return "openai"
    
    def get_model_name(self) -> str:
        """Get model name."""
        return self.model
    
    async def estimate_tokens(self, text: str) -> int:
        """
        Estimate tokens for OpenAI models.
        
        This is a rough estimation. For production, you'd use tiktoken library.
        """
        # Rough estimation: 1 token ≈ 4 characters for English
        # This varies by language and model
        return max(1, len(text) // 4)
    
    def get_max_tokens_limit(self) -> int:
        """Get maximum tokens for the current model."""
        return self.model_limits.get(self.model, 4096)
    
    def supports_language(self, language_code: str) -> bool:
        """Check if language is supported."""
        # OpenAI models support most major languages
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
