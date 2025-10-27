"""
Configuration management following 12-factor app principles.
Handles all environment variables and application settings.
"""
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import List, Optional
from enum import Enum


class Environment(str, Enum):
    """Application environment types."""
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    TESTING = "testing"


class LLMProvider(str, Enum):
    """Supported LLM providers."""
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    AZURE_OPENAI = "azure_openai"


class ToneType(str, Enum):
    """Supported summary tones."""
    NEUTRAL = "neutral"
    CONCISE = "concise"
    BULLET = "bullet"


class Settings(BaseSettings):
    """Application settings with environment variable support."""
    
    # Application
    app_name: str = Field(default="LLM Summarizer Service", env="APP_NAME")
    environment: Environment = Field(default=Environment.DEVELOPMENT, env="ENVIRONMENT")
    debug: bool = Field(default=False, env="DEBUG")
    
    # API Configuration
    api_host: str = Field(default="0.0.0.0", env="API_HOST")
    api_port: int = Field(default=8000, env="API_PORT")
    api_keys_allowed: List[str] = Field(default=[], env="API_KEYS_ALLOWED")
    
    # LLM Provider Configuration
    llm_provider: LLMProvider = Field(default=LLMProvider.OPENAI, env="LLM_PROVIDER")
    provider_api_key: str = Field(default="", env="PROVIDER_API_KEY")
    provider_base_url: Optional[str] = Field(default=None, env="PROVIDER_BASE_URL")
    
    # Summary Configuration
    summary_max_tokens: int = Field(default=150, env="SUMMARY_MAX_TOKENS")
    lang_default: str = Field(default="auto", env="LANG_DEFAULT")
    max_text_length: int = Field(default=50000, env="MAX_TEXT_LENGTH")
    
    # Timeout and Retry Configuration
    request_timeout_ms: int = Field(default=10000, env="REQUEST_TIMEOUT_MS")
    llm_timeout_ms: int = Field(default=8000, env="LLM_TIMEOUT_MS")
    max_retries: int = Field(default=2, env="MAX_RETRIES")
    retry_delay_ms: int = Field(default=1000, env="RETRY_DELAY_MS")
    
    # Rate Limiting
    enable_rate_limit: bool = Field(default=False, env="ENABLE_RATE_LIMIT")
    rate_limit_requests: int = Field(default=100, env="RATE_LIMIT_REQUESTS")
    rate_limit_window: int = Field(default=3600, env="RATE_LIMIT_WINDOW")  # seconds
    
    # Redis Configuration (Optional)
    redis_url: Optional[str] = Field(default=None, env="REDIS_URL")
    redis_ttl: int = Field(default=3600, env="REDIS_TTL")  # Cache TTL in seconds
    
    # Security
    cors_origins: List[str] = Field(default=["*"], env="CORS_ORIGINS")
    max_payload_size: int = Field(default=1048576, env="MAX_PAYLOAD_SIZE")  # 1MB
    
    # Logging
    log_level: str = Field(default="INFO", env="LOG_LEVEL")
    log_format: str = Field(default="json", env="LOG_FORMAT")  # json or text
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    def get_request_timeout_seconds(self) -> float:
        """Convert request timeout from milliseconds to seconds."""
        return self.request_timeout_ms / 1000.0
    
    def get_llm_timeout_seconds(self) -> float:
        """Convert LLM timeout from milliseconds to seconds."""
        return self.llm_timeout_ms / 1000.0
    
    def get_retry_delay_seconds(self) -> float:
        """Convert retry delay from milliseconds to seconds."""
        return self.retry_delay_ms / 1000.0


# Global settings instance
settings = Settings()
