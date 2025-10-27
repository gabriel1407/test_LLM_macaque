"""
Structured logging configuration for the LLM Summarizer service.
Provides JSON logging with proper formatting and security considerations.
"""
import logging
import logging.config
import json
import sys
from datetime import datetime
from typing import Dict, Any, Optional
from pythonjsonlogger import jsonlogger

from .config import settings


class SecurityFilter(logging.Filter):
    """Filter to remove sensitive data from logs."""
    
    SENSITIVE_FIELDS = {
        'api_key', 'token', 'password', 'secret', 'authorization',
        'bearer', 'x-api-key', 'provider_api_key'
    }
    
    def filter(self, record: logging.LogRecord) -> bool:
        """Filter sensitive information from log records."""
        if hasattr(record, 'args') and record.args:
            # Clean args if they contain sensitive data
            if isinstance(record.args, dict):
                record.args = self._clean_dict(record.args)
        
        # Clean the message itself
        if hasattr(record, 'getMessage'):
            message = record.getMessage()
            record.msg = self._clean_string(message)
        
        return True
    
    def _clean_dict(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Clean sensitive data from dictionary."""
        cleaned = {}
        for key, value in data.items():
            if key.lower() in self.SENSITIVE_FIELDS:
                cleaned[key] = "***REDACTED***"
            elif isinstance(value, dict):
                cleaned[key] = self._clean_dict(value)
            else:
                cleaned[key] = value
        return cleaned
    
    def _clean_string(self, text: str) -> str:
        """Clean sensitive data from string."""
        # This is a simple implementation - in production you might want
        # more sophisticated pattern matching
        for field in self.SENSITIVE_FIELDS:
            if field in text.lower():
                # Replace potential API keys or tokens
                import re
                pattern = rf'{field}["\s]*[:=]["\s]*[a-zA-Z0-9_-]+'
                text = re.sub(pattern, f'{field}=***REDACTED***', text, flags=re.IGNORECASE)
        return text


class CustomJsonFormatter(jsonlogger.JsonFormatter):
    """Custom JSON formatter with additional fields."""
    
    def add_fields(self, log_record: Dict[str, Any], record: logging.LogRecord, message_dict: Dict[str, Any]) -> None:
        """Add custom fields to log record."""
        super().add_fields(log_record, record, message_dict)
        
        # Add timestamp in ISO format
        log_record['timestamp'] = datetime.utcnow().isoformat() + 'Z'
        
        # Add service information
        log_record['service'] = settings.app_name
        log_record['environment'] = settings.environment
        
        # Add request ID if available
        if hasattr(record, 'request_id'):
            log_record['request_id'] = record.request_id
        
        # Add user ID if available
        if hasattr(record, 'user_id'):
            log_record['user_id'] = record.user_id
        
        # Add latency if available
        if hasattr(record, 'latency_ms'):
            log_record['latency_ms'] = record.latency_ms


def setup_logging() -> None:
    """Setup logging configuration based on settings."""
    
    # Create security filter
    security_filter = SecurityFilter()
    
    if settings.log_format.lower() == "json":
        # JSON logging configuration
        formatter = CustomJsonFormatter(
            fmt='%(timestamp)s %(level)s %(name)s %(message)s'
        )
    else:
        # Text logging configuration
        formatter = logging.Formatter(
            fmt='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
    
    # Configure handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)
    handler.addFilter(security_filter)
    
    # Configure root logger
    logging.root.setLevel(getattr(logging, settings.log_level.upper()))
    logging.root.handlers = [handler]
    
    # Disable some noisy loggers in production
    if settings.environment == "production":
        logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
        logging.getLogger("httpx").setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    """Get a logger instance with the given name."""
    return logging.getLogger(name)


class LoggerMixin:
    """Mixin class to add logging capabilities to any class."""
    
    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class."""
        return get_logger(self.__class__.__name__)


def log_function_call(func_name: str, **kwargs) -> None:
    """Log function call with parameters (excluding sensitive data)."""
    logger = get_logger("function_calls")
    
    # Filter sensitive parameters
    security_filter = SecurityFilter()
    clean_kwargs = security_filter._clean_dict(kwargs)
    
    logger.info(
        f"Function called: {func_name}",
        extra={
            "function": func_name,
            "parameters": clean_kwargs
        }
    )


def log_performance(operation: str, latency_ms: float, **metadata) -> None:
    """Log performance metrics."""
    logger = get_logger("performance")
    
    logger.info(
        f"Operation completed: {operation}",
        extra={
            "operation": operation,
            "latency_ms": latency_ms,
            **metadata
        }
    )
