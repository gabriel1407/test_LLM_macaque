"""
FastAPI application entry point.
Configures the application, middleware, and routing.
"""
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app.core.config import settings
from app.core.logging import setup_logging, get_logger, log_performance
from app.core.exceptions import LLMSummarizerException
from app.api.v1.endpoints import summarize, health, cache


# Setup logging before creating the app
setup_logging()
logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.
    
    Handles startup and shutdown events.
    """
    # Startup
    logger.info(f"Starting {settings.app_name}")
    logger.info(f"Environment: {settings.environment}")
    logger.info(f"Debug mode: {settings.debug}")
    logger.info(f"LLM Provider: {settings.llm_provider}")
    
    # Log configuration (without sensitive data)
    logger.info(
        "Service configuration loaded",
        extra={
            "environment": settings.environment,
            "llm_provider": settings.llm_provider,
            "max_tokens": settings.summary_max_tokens,
            "timeout_ms": settings.request_timeout_ms,
            "rate_limit_enabled": settings.enable_rate_limit
        }
    )
    
    yield
    
    # Shutdown
    logger.info(f"Shutting down {settings.app_name}")


# Create FastAPI application
app = FastAPI(
    title="LLM Summarizer Service",
    description="""
    A high-performance microservice for text summarization using Large Language Models.
    
    ## Features
    
    * **Multiple LLM Providers**: OpenAI, Anthropic with automatic fallback
    * **Extractive Fallback**: TextRank and TF-IDF algorithms when LLMs fail
    * **High Availability**: Circuit breakers, retries, and timeouts
    * **Caching**: Redis-based caching for improved performance
    * **Rate Limiting**: Configurable rate limits per API key
    * **Monitoring**: Comprehensive health checks and metrics
    * **Security**: API key authentication and request validation
    
    ## Authentication
    
    All endpoints require authentication using an API key in the Authorization header:
    ```
    Authorization: Bearer your-api-key-here
    ```
    
    ## Rate Limits
    
    API calls are subject to rate limits based on your API key tier:
    - Standard: 60 requests per minute
    - Premium: 300 requests per minute
    
    ## Error Handling
    
    The API uses standard HTTP status codes and returns detailed error information:
    - 400: Bad Request (validation errors)
    - 401: Unauthorized (invalid API key)
    - 429: Too Many Requests (rate limit exceeded)
    - 500: Internal Server Error
    - 503: Service Unavailable (LLM provider issues)
    """,
    version="1.0.0",
    contact={
        "name": "API Support",
        "email": "support@example.com",
    },
    license_info={
        "name": "MIT License",
        "url": "https://opensource.org/licenses/MIT",
    },
    lifespan=lifespan,
    docs_url="/docs" if settings.environment != "production" else None,
    redoc_url="/redoc" if settings.environment != "production" else None,
    openapi_url="/openapi.json" if settings.environment != "production" else None,
)


# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# Add trusted host middleware for security
if settings.environment == "production":
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=["*"]  # Configure with actual allowed hosts in production
    )


# Request logging middleware
@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests with timing information."""
    start_time = time.time()
    
    # Log request start
    logger.info(
        f"Request started: {request.method} {request.url.path}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "query_params": str(request.query_params),
            "client_ip": request.client.host if request.client else None,
            "user_agent": request.headers.get("user-agent"),
        }
    )
    
    # Process request
    response = await call_next(request)
    
    # Calculate duration
    duration_ms = (time.time() - start_time) * 1000
    
    # Log request completion
    logger.info(
        f"Request completed: {request.method} {request.url.path}",
        extra={
            "method": request.method,
            "path": request.url.path,
            "status_code": response.status_code,
            "duration_ms": round(duration_ms, 2),
        }
    )
    
    # Log performance metrics
    log_performance(
        operation="http_request",
        latency_ms=duration_ms,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code
    )
    
    return response


# Global exception handler
@app.exception_handler(LLMSummarizerException)
async def llm_summarizer_exception_handler(request: Request, exc: LLMSummarizerException):
    """Handle custom LLM Summarizer exceptions."""
    logger.error(
        f"LLM Summarizer error: {exc.message}",
        extra={
            "error_code": exc.error_code,
            "details": exc.details,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    # Map exception types to HTTP status codes
    status_code_map = {
        "ValidationError": 400,
        "AuthenticationError": 401,
        "AuthorizationError": 403,
        "RateLimitExceededError": 429,
        "LLMProviderTimeoutError": 504,
        "LLMProviderQuotaError": 429,
        "LLMProviderUnavailableError": 503,
        "FallbackError": 503,
        "CacheError": 500,
        "ConfigurationError": 500,
        "TextProcessingError": 400,
    }
    
    status_code = status_code_map.get(exc.error_code, 500)
    
    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.message,
            "error_code": exc.error_code,
            "details": exc.details
        }
    )


# Global HTTP exception handler
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """Handle HTTP exceptions with consistent format."""
    logger.warning(
        f"HTTP exception: {exc.detail}",
        extra={
            "status_code": exc.status_code,
            "path": request.url.path,
            "method": request.method
        }
    )
    
    return JSONResponse(
        status_code=exc.status_code,
        content=exc.detail if isinstance(exc.detail, dict) else {"error": exc.detail}
    )


# Global unhandled exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions."""
    logger.error(
        f"Unhandled exception: {str(exc)}",
        extra={
            "exception_type": type(exc).__name__,
            "path": request.url.path,
            "method": request.method
        },
        exc_info=True
    )
    
    return JSONResponse(
        status_code=500,
        content={
            "error": "Internal server error",
            "error_code": "INTERNAL_ERROR"
        }
    )


# Include routers
app.include_router(
    summarize.router,
    prefix="/v1",
    tags=["Summarization"]
)

app.include_router(
    health.router,
    prefix="/v1",
    tags=["Health"]
)

app.include_router(
    cache.router,
    prefix="/v1/admin/cache",
    tags=["Cache Management"]
)


# Root endpoint
@app.get(
    "/",
    summary="Service information",
    description="Get basic information about the LLM Summarizer service"
)
async def root():
    """Get service information."""
    return {
        "service": settings.app_name,
        "version": "1.0.0",
        "environment": settings.environment,
        "status": "running",
        "docs_url": "/docs" if settings.environment != "production" else None,
        "health_check": "/v1/healthz"
    }


# Custom OpenAPI schema
def custom_openapi():
    """Generate custom OpenAPI schema."""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = get_openapi(
        title="LLM Summarizer API",
        version="1.0.0",
        description=app.description,
        routes=app.routes,
    )
    
    # Add security scheme
    openapi_schema["components"]["securitySchemes"] = {
        "BearerAuth": {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "API Key",
            "description": "API Key authentication using Bearer token"
        }
    }
    
    # Add global security requirement
    openapi_schema["security"] = [{"BearerAuth": []}]
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi


if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
        log_level=settings.log_level.lower()
    )
