"""
Summarization endpoint implementation.
Handles POST /v1/summarize requests with validation and error handling.
"""
import time
import uuid
from typing import Dict, Any
from fastapi import APIRouter, HTTPException, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field, validator

from app.core.config import settings, ToneType
from app.core.logging import LoggerMixin, log_performance
from app.core.exceptions import (
    ValidationError,
    LLMProviderError,
    LLMProviderTimeoutError,
    LLMProviderQuotaError,
    FallbackError
)
from app.domain.entities.summary_request import SummaryRequest, LanguageCode
from app.domain.entities.summary_response import SummaryResponse
from app.api.v1.dependencies import get_summary_service, get_current_user
from app.domain.interfaces.auth_service import AuthUser


router = APIRouter()


class SummarizeRequestModel(BaseModel):
    """
    API model for summarization requests.
    
    Validates input according to API specification.
    """
    text: str = Field(
        ..., 
        description="Text to be summarized",
        min_length=10,
        max_length=50000,
        example="This is a long text that needs to be summarized. It contains multiple sentences and paragraphs that should be condensed into a shorter, more concise version while preserving the key information and main points."
    )
    lang: str = Field(
        default="auto",
        description="Language of the text (auto, es, en, fr, de, it, pt, ru, zh, ja, ko)",
        example="auto"
    )
    max_tokens: int = Field(
        default=100,
        ge=10,
        le=500,
        description="Maximum tokens for the summary",
        example=100
    )
    tone: str = Field(
        default="neutral",
        description="Tone of the summary (neutral, concise, bullet)",
        example="neutral"
    )
    
    @validator('lang')
    def validate_language(cls, v: str) -> str:
        """Validate language code."""
        try:
            LanguageCode(v)
            return v
        except ValueError:
            raise ValueError(f"Unsupported language code: {v}")
    
    @validator('tone')
    def validate_tone(cls, v: str) -> str:
        """Validate tone."""
        try:
            ToneType(v)
            return v
        except ValueError:
            raise ValueError(f"Unsupported tone: {v}. Must be one of: neutral, concise, bullet")
    
    @validator('max_tokens')
    def validate_max_tokens(cls, v: int) -> int:
        """Validate max_tokens against global settings."""
        if v > settings.summary_max_tokens:
            raise ValueError(f"max_tokens ({v}) exceeds limit ({settings.summary_max_tokens})")
        return v


class SummarizeResponseModel(BaseModel):
    """
    API model for summarization responses.
    
    Matches the required API specification format.
    """
    summary: str = Field(..., description="Generated summary text")
    usage: Dict[str, int] = Field(..., description="Token usage information")
    model: str = Field(..., description="Model used for generation")
    latency_ms: float = Field(..., description="Response latency in milliseconds")
    
    class Config:
        schema_extra = {
            "example": {
                "summary": "This is a concise summary of the input text highlighting the main points and key information.",
                "usage": {
                    "prompt_tokens": 120,
                    "completion_tokens": 40
                },
                "model": "gpt-3.5-turbo",
                "latency_ms": 900.5
            }
        }


class ErrorResponseModel(BaseModel):
    """API model for error responses."""
    error: str = Field(..., description="Error message")
    error_code: str = Field(..., description="Error code")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional error details")


@router.post(
    "/summarize",
    response_model=SummarizeResponseModel,
    responses={
        400: {"model": ErrorResponseModel, "description": "Bad Request - Invalid input"},
        401: {"model": ErrorResponseModel, "description": "Unauthorized - Invalid API key"},
        429: {"model": ErrorResponseModel, "description": "Too Many Requests - Rate limit exceeded"},
        500: {"model": ErrorResponseModel, "description": "Internal Server Error"},
        503: {"model": ErrorResponseModel, "description": "Service Unavailable - LLM provider down"}
    },
    summary="Generate text summary",
    description="""
    Generate a summary of the provided text using AI models.
    
    The service will attempt to use the primary LLM provider (OpenAI/Anthropic) and fall back 
    to extractive summarization (TextRank/TF-IDF) if the primary provider fails.
    
    **Authentication**: Requires valid API key in Authorization header as Bearer token.
    
    **Rate Limiting**: Subject to rate limits based on your API key tier.
    
    **Caching**: Responses may be cached to improve performance for identical requests.
    """
)
async def create_summary(
    request_data: SummarizeRequestModel,
    request: Request,
    current_user: AuthUser = Depends(get_current_user),
    summary_service = Depends(get_summary_service)
) -> SummarizeResponseModel:
    """
    Create a summary of the provided text.
    
    Args:
        request_data: Summary request data
        request: FastAPI request object
        current_user: Authenticated user
        summary_service: Summary service dependency
        
    Returns:
        SummarizeResponseModel: Generated summary with metadata
        
    Raises:
        HTTPException: Various HTTP errors based on failure type
    """
    start_time = time.time()
    request_id = str(uuid.uuid4())
    
    logger = SummarizeEndpoint().logger
    
    try:
        logger.info(
            f"Summary request received",
            extra={
                "request_id": request_id,
                "user_id": current_user.user_id,
                "text_length": len(request_data.text),
                "language": request_data.lang,
                "max_tokens": request_data.max_tokens,
                "tone": request_data.tone
            }
        )
        
        # Convert API model to domain entity
        summary_request = SummaryRequest(
            text=request_data.text,
            lang=LanguageCode(request_data.lang),
            max_tokens=request_data.max_tokens,
            tone=ToneType(request_data.tone),
            user_id=current_user.user_id,
            request_id=request_id
        )
        
        # Generate summary
        summary_response = await summary_service.generate_summary(summary_request)
        
        # Convert domain response to API model
        api_response = SummarizeResponseModel(**summary_response.to_api_response())
        
        # Log successful completion
        total_latency = (time.time() - start_time) * 1000
        log_performance(
            operation="api_summarize_success",
            latency_ms=total_latency,
            user_id=current_user.user_id,
            request_id=request_id,
            tokens_used=summary_response.usage.total_tokens,
            source=summary_response.source
        )
        
        logger.info(
            f"Summary generated successfully",
            extra={
                "request_id": request_id,
                "user_id": current_user.user_id,
                "latency_ms": total_latency,
                "summary_length": len(summary_response.summary),
                "source": summary_response.source
            }
        )
        
        return api_response
        
    except ValidationError as e:
        logger.warning(f"Validation error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=400,
            detail={
                "error": str(e),
                "error_code": "VALIDATION_ERROR",
                "details": {"request_id": request_id}
            }
        )
    
    except LLMProviderQuotaError as e:
        logger.warning(f"Rate limit exceeded: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Rate limit exceeded. Please try again later.",
                "error_code": "RATE_LIMIT_EXCEEDED",
                "details": {"request_id": request_id}
            }
        )
    
    except LLMProviderTimeoutError as e:
        logger.error(f"Request timeout: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=504,
            detail={
                "error": "Request timed out. Please try again.",
                "error_code": "TIMEOUT_ERROR",
                "details": {"request_id": request_id}
            }
        )
    
    except (LLMProviderError, FallbackError) as e:
        logger.error(f"Service error: {e}", extra={"request_id": request_id})
        raise HTTPException(
            status_code=503,
            detail={
                "error": "Service temporarily unavailable. Please try again later.",
                "error_code": "SERVICE_UNAVAILABLE",
                "details": {"request_id": request_id}
            }
        )
    
    except Exception as e:
        total_latency = (time.time() - start_time) * 1000
        logger.error(
            f"Unexpected error: {e}",
            extra={
                "request_id": request_id,
                "user_id": current_user.user_id if 'current_user' in locals() else None,
                "latency_ms": total_latency
            }
        )
        
        # Log error metrics
        log_performance(
            operation="api_summarize_error",
            latency_ms=total_latency,
            error=str(e),
            request_id=request_id
        )
        
        raise HTTPException(
            status_code=500,
            detail={
                "error": "Internal server error. Please try again later.",
                "error_code": "INTERNAL_ERROR",
                "details": {"request_id": request_id}
            }
        )


class SummarizeEndpoint(LoggerMixin):
    """Helper class for logging."""
    pass
