import os
import logging
import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Union, Tuple
import httpx

from .base_provider import BaseLLMProvider, Message, LLMResponse

logger = logging.getLogger(__name__)

class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI LLM provider implementation.
    
    Supports text generation, chat completion, and embeddings using OpenAI's API.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "gpt-3.5-turbo",
                 embedding_model: str = "text-embedding-3-small"):
        """
        Initialize the OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Default model to use for text generation and chat
            embedding_model: Model to use for embeddings
        """
        super().__init__(api_key=api_key, model=model)
        self.embedding_model = embedding_model
        self.api_base = "https://api.openai.com/v1"
        self.min_call_interval = 1.0  # seconds between API calls
        
        # Use environment variable if no API key provided
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return [
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k"
        ]
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        model_limits = {
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-16k": 16384
        }
        return model_limits.get(self.model, 4096)
    
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
        Generate text based on a prompt using OpenAI's API.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the OpenAI API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format as a chat message for consistency
        messages = [{"role": "user", "content": prompt}]
        
        # Prepare API request
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or min(1024, self.max_tokens // 2)
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ["model"]:  # Skip ones we've already processed
                payload[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                text = result["choices"][0]["message"]["content"]
                finish_reason = result["choices"][0]["finish_reason"]
                usage = result.get("usage", {})
                
                return LLMResponse(
                    text=text,
                    model=payload["model"],
                    usage=usage,
                    finish_reason=finish_reason,
                    metadata={"response": result}
                )
                
        except Exception as e:
            logger.error(f"Error generating text with OpenAI: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=payload["model"],
                metadata={"error": str(e)}
            )
    
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation using OpenAI's API.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the OpenAI API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format messages for OpenAI API
        formatted_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        # Prepare API request
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or min(1024, self.max_tokens // 2)
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ["model"]:  # Skip ones we've already processed
                payload[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                text = result["choices"][0]["message"]["content"]
                finish_reason = result["choices"][0]["finish_reason"]
                usage = result.get("usage", {})
                
                return LLMResponse(
                    text=text,
                    model=payload["model"],
                    usage=usage,
                    finish_reason=finish_reason,
                    metadata={"response": result}
                )
                
        except Exception as e:
            logger.error(f"Error with OpenAI chat completion: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=payload["model"],
                metadata={"error": str(e)}
            )
    
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text using OpenAI's embeddings API.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Prepare API request
        url = f"{self.api_base}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Format input
        if isinstance(text, str):
            input_texts = [text]
        else:
            input_texts = text
        
        payload = {
            "model": self.embedding_model,
            "input": input_texts
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                embeddings = [item["embedding"] for item in result["data"]]
                
                # Return single embedding or list based on input
                if isinstance(text, str):
                    return embeddings[0]
                else:
                    return embeddings
                
        except Exception as e:
            logger.error(f"Error generating embeddings with OpenAI: {str(e)}")
            # Return empty embedding with appropriate dimensionality
            # OpenAI's text-embedding-3-small has 1536 dimensions
            empty_embedding = [0.0] * 1536
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(input_texts)
