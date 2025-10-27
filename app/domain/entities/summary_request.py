"""
Domain entities for summary requests.
Following DDD principles with rich domain models.
"""
from pydantic import BaseModel, Field, validator
from typing import Optional, Dict, Any
from enum import Enum
import hashlib
import json

from app.core.config import ToneType
from app.core.exceptions import ValidationError


class LanguageCode(str, Enum):
    """Supported language codes for summarization."""
    AUTO = "auto"
    SPANISH = "es"
    ENGLISH = "en"
    FRENCH = "fr"
    GERMAN = "de"
    ITALIAN = "it"
    PORTUGUESE = "pt"
    RUSSIAN = "ru"
    CHINESE = "zh"
    JAPANESE = "ja"
    KOREAN = "ko"


class SummaryRequest(BaseModel):
    """
    Domain entity representing a summary request.
    Contains business logic for validation and processing.
    """
    text: str = Field(..., description="Text to be summarized")
    lang: LanguageCode = Field(default=LanguageCode.AUTO, description="Language of the text")
    max_tokens: int = Field(default=100, ge=10, le=500, description="Maximum tokens for summary")
    tone: ToneType = Field(default=ToneType.NEUTRAL, description="Tone of the summary")
    
    # Optional metadata
    user_id: Optional[str] = Field(default=None, description="User identifier")
    request_id: Optional[str] = Field(default=None, description="Request identifier")
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Additional metadata")
    
    class Config:
        use_enum_values = True
        validate_assignment = True
    
    @validator('text')
    def validate_text(cls, v: str) -> str:
        """Validate text content and length."""
        if not v or not v.strip():
            raise ValidationError("Text cannot be empty")
        
        # Remove excessive whitespace
        cleaned_text = ' '.join(v.split())
        
        # Check length constraints
        from app.core.config import settings
        if len(cleaned_text) > settings.max_text_length:
            raise ValidationError(
                f"Text length ({len(cleaned_text)}) exceeds maximum allowed ({settings.max_text_length})"
            )
        
        if len(cleaned_text) < 10:
            raise ValidationError("Text is too short for meaningful summarization (minimum 10 characters)")
        
        return cleaned_text
    
    @validator('max_tokens')
    def validate_max_tokens(cls, v: int) -> int:
        """Validate max_tokens against configuration."""
        from app.core.config import settings
        if v > settings.summary_max_tokens:
            raise ValidationError(
                f"max_tokens ({v}) exceeds configured limit ({settings.summary_max_tokens})"
            )
        return v
    
    def get_cache_key(self) -> str:
        """
        Generate a unique cache key for this request.
        Uses content hash for consistent caching.
        """
        # Create a deterministic hash based on content
        content = {
            "text": self.text,
            "lang": self.lang,
            "max_tokens": self.max_tokens,
            "tone": self.tone
        }
        
        content_str = json.dumps(content, sort_keys=True)
        return f"summary:{hashlib.sha256(content_str.encode()).hexdigest()[:16]}"
    
    def get_word_count(self) -> int:
        """Get approximate word count of the text."""
        return len(self.text.split())
    
    def get_character_count(self) -> int:
        """Get character count of the text."""
        return len(self.text)
    
    def is_long_text(self, threshold: int = 1000) -> bool:
        """Check if text is considered long (for processing decisions)."""
        return len(self.text) > threshold
    
    def get_estimated_tokens(self) -> int:
        """
        Estimate input tokens for the request.
        Rough approximation: 1 token ≈ 4 characters for English.
        """
        # This is a rough estimation - in production you'd use the actual tokenizer
        return max(1, len(self.text) // 4)
    
    def to_llm_prompt(self) -> str:
        """
        Convert request to LLM prompt based on tone and language.
        This encapsulates the business logic for prompt generation.
        """
        base_prompt = f"Please summarize the following text in {self.max_tokens} tokens or less"
        
        # Add language instruction if not auto
        if self.lang != LanguageCode.AUTO:
            base_prompt += f" in {self.lang}"
        
        # Add tone-specific instructions
        tone_instructions = {
            ToneType.NEUTRAL: "Provide a balanced and objective summary.",
            ToneType.CONCISE: "Be extremely concise and focus only on the most important points.",
            ToneType.BULLET: "Format the summary as bullet points highlighting key information."
        }
        
        instruction = tone_instructions.get(self.tone, tone_instructions[ToneType.NEUTRAL])
        
        return f"{base_prompt}. {instruction}\n\nText to summarize:\n{self.text}"
    
    def __str__(self) -> str:
        """String representation for logging."""
        return f"SummaryRequest(chars={len(self.text)}, lang={self.lang}, tokens={self.max_tokens}, tone={self.tone})"
