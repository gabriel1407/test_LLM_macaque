"""
Factory for creating LLM providers.
Implements Factory pattern following SOLID principles.
"""
from typing import Dict, Type, List
from app.core.config import settings, LLMProvider as LLMProviderType
from app.core.exceptions import ConfigurationError
from app.core.logging import LoggerMixin
from app.domain.interfaces.llm_provider import LLMProvider, LLMProviderFactory
from app.services.llm.openai_provider import OpenAIProvider
from app.services.llm.anthropic_provider import AnthropicProvider


class LLMProviderFactoryImpl(LLMProviderFactory, LoggerMixin):
    """
    Concrete implementation of LLM provider factory.
    
    Creates and configures LLM providers based on configuration.
    """
    
    def __init__(self):
        """Initialize the factory with provider mappings."""
        self._providers: Dict[str, Type[LLMProvider]] = {
            "openai": OpenAIProvider,
            "anthropic": AnthropicProvider,
        }
        
        # Model mappings for each provider
        self._model_mappings = {
            "openai": {
                "gpt-3.5-turbo": "gpt-3.5-turbo",
                "gpt-3.5-turbo-16k": "gpt-3.5-turbo-16k", 
                "gpt-4": "gpt-4",
                "gpt-4-turbo": "gpt-4-turbo-preview",
                "gpt-4o": "gpt-4o"
            },
            "anthropic": {
                "claude-3-haiku": "claude-3-haiku-20240307",
                "claude-3-sonnet": "claude-3-sonnet-20240229",
                "claude-3-opus": "claude-3-opus-20240229",
                "claude-3.5-sonnet": "claude-3-5-sonnet-20241022"
            }
        }
        
        self.logger.info("LLM Provider Factory initialized")
    
    def create_provider(self, provider_type: str, **kwargs) -> LLMProvider:
        """
        Create an LLM provider instance.
        
        Args:
            provider_type: Type of provider ("openai", "anthropic")
            **kwargs: Additional configuration parameters
            
        Returns:
            LLMProvider: Configured provider instance
        """
        provider_type = provider_type.lower()
        
        if provider_type not in self._providers:
            raise ConfigurationError(
                f"Unsupported LLM provider: {provider_type}. "
                f"Supported providers: {list(self._providers.keys())}"
            )
        
        provider_class = self._providers[provider_type]
        
        try:
            # Get configuration from settings and kwargs
            config = self._get_provider_config(provider_type, **kwargs)
            
            # Create provider instance
            provider = provider_class(**config)
            
            self.logger.info(f"Created {provider_type} provider with model: {config.get('model')}")
            return provider
            
        except Exception as e:
            self.logger.error(f"Failed to create {provider_type} provider: {e}")
            raise ConfigurationError(f"Failed to create {provider_type} provider: {e}")
    
    def _get_provider_config(self, provider_type: str, **kwargs) -> Dict:
        """Get configuration for a specific provider."""
        base_config = {
            "api_key": kwargs.get("api_key") or settings.provider_api_key,
            "max_retries": kwargs.get("max_retries") or settings.max_retries,
            "timeout": kwargs.get("timeout") or settings.get_llm_timeout_seconds()
        }
        
        # Add provider-specific configuration
        if provider_type == "openai":
            model = kwargs.get("model") or "gpt-3.5-turbo"
            base_config.update({
                "model": self._resolve_model_name(provider_type, model),
                "base_url": kwargs.get("base_url") or settings.provider_base_url
            })
        
        elif provider_type == "anthropic":
            model = kwargs.get("model") or "claude-3-sonnet"
            base_config.update({
                "model": self._resolve_model_name(provider_type, model)
            })
        
        # Validate required configuration
        if not base_config["api_key"]:
            raise ConfigurationError(f"API key is required for {provider_type} provider")
        
        return base_config
    
    def _resolve_model_name(self, provider_type: str, model_name: str) -> str:
        """Resolve model name to full model identifier."""
        mappings = self._model_mappings.get(provider_type, {})
        return mappings.get(model_name, model_name)
    
    def get_supported_providers(self) -> List[str]:
        """Get list of supported provider types."""
        return list(self._providers.keys())
    
    def get_supported_models(self, provider_type: str) -> List[str]:
        """Get list of supported models for a provider."""
        return list(self._model_mappings.get(provider_type, {}).keys())
    
    def register_provider(self, provider_type: str, provider_class: Type[LLMProvider]) -> None:
        """
        Register a new provider type.
        
        Args:
            provider_type: Name of the provider type
            provider_class: Provider class to register
        """
        self._providers[provider_type] = provider_class
        self.logger.info(f"Registered new provider type: {provider_type}")


def create_default_provider() -> LLMProvider:
    """
    Create the default LLM provider based on settings.
    
    Returns:
        LLMProvider: Configured default provider
    """
    factory = LLMProviderFactoryImpl()
    return factory.create_provider(settings.llm_provider.value)


def create_provider_from_config(provider_config: Dict) -> LLMProvider:
    """
    Create provider from configuration dictionary.
    
    Args:
        provider_config: Configuration dictionary
        
    Returns:
        LLMProvider: Configured provider
    """
    factory = LLMProviderFactoryImpl()
    provider_type = provider_config.pop("type", settings.llm_provider.value)
    return factory.create_provider(provider_type, **provider_config)
