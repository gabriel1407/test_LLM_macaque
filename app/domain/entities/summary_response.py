"""
Domain entities for summary responses.
Rich domain models with business logic and validation.
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum

from app.core.exceptions import ValidationError


class SummarySource(str, Enum):
    """Source of the summary generation."""
    LLM = "llm"
    FALLBACK_TEXTRANK = "fallback_textrank"
    FALLBACK_TFIDF = "fallback_tfidf"
    CACHE = "cache"


class TokenUsage(BaseModel):
    """Token usage information for the summary generation."""
    prompt_tokens: int = Field(..., ge=0, description="Number of tokens in the prompt")
    completion_tokens: int = Field(..., ge=0, description="Number of tokens in the completion")
    total_tokens: Optional[int] = Field(default=None, description="Total tokens used")
    
    def __init__(self, **data):
        super().__init__(**data)
        if self.total_tokens is None:
            self.total_tokens = self.prompt_tokens + self.completion_tokens
    
    @validator('total_tokens')
    def validate_total_tokens(cls, v: Optional[int], values: Dict[str, Any]) -> int:
        """Ensure total_tokens matches sum of prompt and completion tokens."""
        if v is None:
            return values.get('prompt_tokens', 0) + values.get('completion_tokens', 0)
        
        expected_total = values.get('prompt_tokens', 0) + values.get('completion_tokens', 0)
        if v != expected_total:
            raise ValidationError(
                f"total_tokens ({v}) doesn't match sum of prompt_tokens + completion_tokens ({expected_total})"
            )
        return v
    
    def get_cost_estimate(self, prompt_cost_per_1k: float = 0.001, completion_cost_per_1k: float = 0.002) -> float:
        """
        Estimate cost based on token usage.
        Default rates are approximate for GPT-3.5-turbo.
        """
        prompt_cost = (self.prompt_tokens / 1000) * prompt_cost_per_1k
        completion_cost = (self.completion_tokens / 1000) * completion_cost_per_1k
        return prompt_cost + completion_cost


class SummaryQuality(BaseModel):
    """Quality metrics for the generated summary."""
    compression_ratio: Optional[float] = Field(default=None, description="Text compression ratio")
    readability_score: Optional[float] = Field(default=None, description="Readability score")
    coherence_score: Optional[float] = Field(default=None, description="Coherence score")
    relevance_score: Optional[float] = Field(default=None, description="Relevance score")
    
    @validator('compression_ratio')
    def validate_compression_ratio(cls, v: Optional[float]) -> Optional[float]:
        """Validate compression ratio is between 0 and 1."""
        if v is not None and (v < 0 or v > 1):
            raise ValidationError("Compression ratio must be between 0 and 1")
        return v


class SummaryResponse(BaseModel):
    """
    Domain entity representing a summary response.
    Contains the generated summary and associated metadata.
    """
    summary: str = Field(..., description="Generated summary text")
    usage: TokenUsage = Field(..., description="Token usage information")
    model: str = Field(..., description="Model used for generation")
    latency_ms: float = Field(..., ge=0, description="Response latency in milliseconds")
    
    # Source and quality information
    source: SummarySource = Field(default=SummarySource.LLM, description="Source of the summary")
    quality: Optional[SummaryQuality] = Field(default=None, description="Quality metrics")
    
    # Metadata
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Response timestamp")
    request_id: Optional[str] = Field(default=None, description="Associated request ID")
    cache_hit: bool = Field(default=False, description="Whether response came from cache")
    
    # Additional metadata
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat() + 'Z'
        }
    
    @validator('summary')
    def validate_summary(cls, v: str) -> str:
        """Validate summary content."""
        if not v or not v.strip():
            raise ValidationError("Summary cannot be empty")
        
        # Clean up the summary
        cleaned_summary = v.strip()
        
        # Basic length validation
        if len(cleaned_summary) < 5:
            raise ValidationError("Summary is too short")
        
        return cleaned_summary
    
    @validator('latency_ms')
    def validate_latency(cls, v: float) -> float:
        """Validate latency is reasonable."""
        if v < 0:
            raise ValidationError("Latency cannot be negative")
        
        # Warn if latency is very high (but don't fail)
        if v > 30000:  # 30 seconds
            # In a real application, you might want to log this
            pass
        
        return v
    
    def get_summary_length(self) -> int:
        """Get character length of the summary."""
        return len(self.summary)
    
    def get_summary_word_count(self) -> int:
        """Get word count of the summary."""
        return len(self.summary.split())
    
    def calculate_compression_ratio(self, original_text: str) -> float:
        """
        Calculate compression ratio compared to original text.
        Returns ratio of summary length to original length.
        """
        if not original_text:
            return 0.0
        
        ratio = len(self.summary) / len(original_text)
        
        # Update quality metrics if available
        if self.quality is None:
            self.quality = SummaryQuality()
        self.quality.compression_ratio = ratio
        
        return ratio
    
    def is_fast_response(self, threshold_ms: float = 2000) -> bool:
        """Check if response was generated quickly."""
        return self.latency_ms <= threshold_ms
    
    def is_from_cache(self) -> bool:
        """Check if response came from cache."""
        return self.cache_hit or self.source == SummarySource.CACHE
    
    def is_fallback_response(self) -> bool:
        """Check if response came from fallback mechanism."""
        return self.source in [SummarySource.FALLBACK_TEXTRANK, SummarySource.FALLBACK_TFIDF]
    
    def get_performance_category(self) -> str:
        """
        Categorize performance based on latency and source.
        Useful for monitoring and analytics.
        """
        if self.is_from_cache():
            return "excellent"  # Cache hit
        elif self.is_fast_response(1000):
            return "good"  # Fast LLM response
        elif self.is_fast_response(3000):
            return "acceptable"  # Normal LLM response
        elif self.is_fallback_response():
            return "degraded"  # Fallback used
        else:
            return "poor"  # Slow response
    
    def to_api_response(self) -> Dict[str, Any]:
        """
        Convert to API response format as specified in requirements.
        This encapsulates the transformation logic.
        """
        return {
            "summary": self.summary,
            "usage": {
                "prompt_tokens": self.usage.prompt_tokens,
                "completion_tokens": self.usage.completion_tokens
            },
            "model": self.model,
            "latency_ms": round(self.latency_ms, 2)
        }
    
    def __str__(self) -> str:
        """String representation for logging."""
        return (
            f"SummaryResponse(length={len(self.summary)}, "
            f"latency={self.latency_ms:.0f}ms, "
            f"source={self.source}, "
            f"tokens={self.usage.total_tokens})"
        )
