import os
import logging
import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Union

import httpx

from .base_provider import BaseLLMProvider, Message, LLMResponse

logger = logging.getLogger(__name__)

class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic LLM provider implementation.
    
    Supports text generation and chat completion using Anthropic's Claude models.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "claude-3-sonnet-20240229"):
        """
        Initialize the Anthropic provider.
        
        Args:
            api_key: Anthropic API key
            model: Default model to use
        """
        super().__init__(api_key=api_key, model=model)
        self.api_base = "https://api.anthropic.com/v1"
        self.min_call_interval = 1.0  # seconds between API calls
        
        # Use environment variable if no API key provided
        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        model_limits = {
            "claude-3-opus-20240229": 200000,
            "claude-3-sonnet-20240229": 200000,
            "claude-3-haiku-20240307": 200000
        }
        return model_limits.get(self.model, 100000)
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.api_key is not None
    
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt using Anthropic's API.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Anthropic API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format as a chat message for Anthropic API
        messages = [{"role": "user", "content": prompt}]
        
        # Call chat completion for consistency
        return await self.chat_completion(
            messages=[Message(role="user", content=prompt)],
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
    
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation using Anthropic's API.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Anthropic API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format messages for Anthropic API
        formatted_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        # Prepare API request
        url = f"{self.api_base}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or min(4000, self.max_tokens // 4),
            "system": kwargs.get("system", "You are a helpful assistant for coding tasks.")
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ["model", "system"]:  # Skip ones we've already processed
                payload[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                text = result["content"][0]["text"]
                
                # Anthropic doesn't provide finish_reason and usage in the same format as OpenAI
                # Extract what we can
                usage = {}
                if "usage" in result:
                    usage = result["usage"]
                
                return LLMResponse(
                    text=text,
                    model=payload["model"],
                    usage=usage,
                    finish_reason=result.get("stop_reason", None),
                    metadata={"response": result}
                )
                
        except Exception as e:
            logger.error(f"Error with Anthropic chat completion: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=payload["model"],
                metadata={"error": str(e)}
            )
    
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text.
        
        Note: Anthropic doesn't provide a public embeddings API.
        This is a placeholder that returns empty embeddings.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Empty embeddings as list of floats or list of list of floats
        """
        logger.warning("Anthropic does not provide a public embeddings API. Returning empty embeddings.")
        
        # Return empty embedding with a reasonable dimensionality
        empty_embedding = [0.0] * 1024
        
        if isinstance(text, str):
            return empty_embedding
        else:
            return [empty_embedding] * len(text)
