import abc
import logging
import time
import asyncio
from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class Message(BaseModel):
    """Message model for LLM conversation"""
    role: str  # 'system', 'user', 'assistant'
    content: str
    
class LLMResponse(BaseModel):
    """Response model for LLM providers"""
    text: str
    model: str
    usage: Dict[str, int] = {}
    finish_reason: Optional[str] = None
    metadata: Dict[str, Any] = {}

class BaseLLMProvider(abc.ABC):
    """
    Abstract base class for LLM providers.
    
    All LLM providers must implement this interface to ensure
    consistent access across different backend implementations.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the LLM provider.
        
        Args:
            api_key: API key for the provider
            model: Default model to use for generation
        """
        self.api_key = api_key
        self.model = model
        self.last_call_time = 0
        self.min_call_interval = 1.0  # seconds between API calls
    
    @property
    def provider_name(self) -> str:
        """Get the name of the provider"""
        return self.__class__.__name__.replace("Provider", "")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return []
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        return 4096
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.api_key is not None
    
    async def _rate_limit(self) -> None:
        """Apply rate limiting to avoid hitting API limits"""
        current_time = time.time()
        elapsed = current_time - self.last_call_time
        
        if elapsed < self.min_call_interval:
            wait_time = self.min_call_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)
            
        self.last_call_time = time.time()
    
    @abc.abstractmethod
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        pass
    
    @abc.abstractmethod
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        pass
    
    @abc.abstractmethod
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Check if the provider is healthy and responding.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            # Try a simple completion with minimal tokens
            response = await self.generate_text(
                prompt="Hello",
                max_tokens=5,
                temperature=0.0
            )
            return response is not None and hasattr(response, 'text')
        except Exception as e:
            logger.error(f"Health check failed for {self.provider_name}: {str(e)}")
            return False
