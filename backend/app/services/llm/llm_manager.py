import os
import logging
import asyncio
from typing import Dict, List, Any, Optional, Union, Type
import importlib

from ..llm_providers.base_provider import BaseLLMProvider, Message, LLMResponse
from ...models.base import settings

logger = logging.getLogger(__name__)

class LLMManager:
    """
    Manager for LLM providers.
    
    This service orchestrates access to different LLM providers and handles
    fallbacks, caching, and provider selection based on the task requirements.
    """
    
    def __init__(self):
        """Initialize the LLM manager"""
        self.providers = {}
        self.default_provider = None
        self._load_providers()
    
    def _load_providers(self) -> None:
        """Load all available LLM providers based on configuration"""
        # Define provider configurations
        provider_configs = {
            "openai": {
                "module": "app.services.llm_providers.openai_provider",
                "class": "OpenAIProvider",
                "api_key": settings.OPENAI_API_KEY,
                "default_model": settings.OPENAI_MODEL or "gpt-3.5-turbo"
            },
            "anthropic": {
                "module": "app.services.llm_providers.anthropic_provider",
                "class": "AnthropicProvider",
                "api_key": settings.ANTHROPIC_API_KEY,
                "default_model": settings.ANTHROPIC_MODEL or "claude-3-sonnet-20240229"
            },
            "gemini": {
                "module": "app.services.llm_providers.gemini_provider",
                "class": "GeminiProvider",
                "api_key": settings.GEMINI_API_KEY,
                "default_model": "gemini-2.0-flash-lite"
            }
        }
        
        # Initialize each provider if API key is available
        for provider_name, config in provider_configs.items():
            try:
                if not config.get("api_key"):
                    logger.info(f"No API key found for {provider_name}, skipping")
                    continue
                    
                # Dynamically import the provider module and class
                module = importlib.import_module(config["module"])
                provider_class = getattr(module, config["class"])
                
                # Initialize the provider
                provider_instance = provider_class(
                    api_key=config["api_key"],
                    model=config["default_model"]
                )
                
                self.providers[provider_name] = provider_instance
                logger.info(f"Loaded {provider_name} provider with model {config['default_model']}")
                
                # Set as default provider if none is set
                if self.default_provider is None:
                    self.default_provider = provider_name
                    
            except Exception as e:
                logger.error(f"Error loading {provider_name} provider: {str(e)}")
        
        # Set default provider based on configuration if available
        if settings.DEFAULT_LLM_PROVIDER and settings.DEFAULT_LLM_PROVIDER in self.providers:
            self.default_provider = settings.DEFAULT_LLM_PROVIDER
            
        logger.info(f"Default LLM provider: {self.default_provider}")
    
    @property
    def available_providers(self) -> List[str]:
        """Get list of available provider names"""
        return list(self.providers.keys())
    
    def get_provider(self, provider_name: Optional[str] = None) -> Optional[BaseLLMProvider]:
        """
        Get a specific provider by name, or the default provider.
        
        Args:
            provider_name: Name of the provider to get
            
        Returns:
            Provider instance or None if not available
        """
        if provider_name is not None and provider_name in self.providers:
            return self.providers[provider_name]
            
        if self.default_provider is not None:
            return self.providers[self.default_provider]
            
        return None
    
    async def generate_text(self,
                           prompt: str,
                           provider_name: Optional[str] = None,
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text using the specified provider.
        
        Args:
            prompt: The prompt to generate text from
            provider_name: Name of the provider to use (uses default if None)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        provider = self.get_provider(provider_name)
        
        if provider is None:
            logger.error(f"No LLM provider available for text generation")
            return LLMResponse(
                text="Error: No LLM provider available",
                model="none",
                metadata={"error": "No provider available"}
            )
            
        return await provider.generate_text(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
    
    async def chat_completion(self,
                             messages: List[Message],
                             provider_name: Optional[str] = None,
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation.
        
        Args:
            messages: List of messages in the conversation
            provider_name: Name of the provider to use (uses default if None)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        provider = self.get_provider(provider_name)
        
        if provider is None:
            logger.error(f"No LLM provider available for chat completion")
            return LLMResponse(
                text="Error: No LLM provider available",
                model="none",
                metadata={"error": "No provider available"}
            )
            
        return await provider.chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
    
    async def get_embeddings(self,
                            text: Union[str, List[str]],
                            provider_name: Optional[str] = None) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text.
        
        Args:
            text: Text or list of texts to generate embeddings for
            provider_name: Name of the provider to use (uses default if None)
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        provider = self.get_provider(provider_name)
        
        if provider is None:
            logger.error(f"No LLM provider available for embeddings")
            # Return empty embedding with a reasonable dimensionality
            empty_embedding = [0.0] * 1536
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(text)
                
        return await provider.get_embeddings(text)
    
    async def health_check(self) -> Dict[str, bool]:
        """
        Check health of all providers.
        
        Returns:
            Dictionary mapping provider names to health status
        """
        health_status = {}
        
        for name, provider in self.providers.items():
            try:
                is_healthy = await provider.health_check()
                health_status[name] = is_healthy
            except Exception as e:
                logger.error(f"Error checking health of {name}: {str(e)}")
                health_status[name] = False
                
        return health_status
