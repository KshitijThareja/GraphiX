import os
import logging
import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Union

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from .base_provider import BaseLLMProvider, Message, LLMResponse

logger = logging.getLogger(__name__)

class GeminiProvider(BaseLLMProvider):
    """
    Gemini LLM provider implementation.
    
    Supports text generation, chat completion, and basic embeddings using Google's Gemini models.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "gemini-2.0-flash-lite"):
        """
        Initialize the Gemini provider.
        
        Args:
            api_key: Gemini API key
            model: Default model to use
        """
        super().__init__(api_key=api_key, model=model)
        self.available = GENAI_AVAILABLE
        self.min_call_interval = 1.0  # seconds between API calls
        
        # Use environment variable if no API key provided
        if not self.api_key:
            self.api_key = os.environ.get("GEMINI_API_KEY")
            
        # Initialize the Gemini client
        if self.available and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel(self.model)
                logger.info(f"Initialized Gemini provider with model {self.model}")
            except Exception as e:
                logger.error(f"Error initializing Gemini provider: {str(e)}")
                self.available = False
        else:
            if not self.available:
                logger.warning("Gemini SDK not available. Install it with 'pip install google-generativeai'")
            elif not self.api_key:
                logger.warning("No Gemini API key provided")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.0-pro",
            "gemini-1.0-pro-vision"
        ]
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        model_limits = {
            "gemini-1.5-pro": 1000000,  # 1M tokens
            "gemini-1.5-flash": 1000000,
            "gemini-1.0-pro": 32000,
            "gemini-1.0-pro-vision": 32000
        }
        return model_limits.get(self.model, 32000)
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.available and self.api_key is not None
    
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt using Gemini's API.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Gemini API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        if not self.is_available:
            logger.error("Gemini provider is not available")
            return LLMResponse(
                text="Error: Gemini provider is not available",
                model=self.model,
                metadata={"error": "Provider not available"}
            )
            
        try:
            # Configure generation parameters
            generation_config = {
                "temperature": temperature,
                "top_p": kwargs.get("top_p", 0.95),
                "top_k": kwargs.get("top_k", 40),
            }
            
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens
                
            # Generate text
            response = await asyncio.to_thread(
                self.client.generate_content,
                prompt,
                generation_config=generation_config
            )
            
            # Extract text from response
            if hasattr(response, 'text'):
                text = response.text
            else:
                # Try to get text from parts if available
                text = ""
                for part in getattr(response, 'parts', []):
                    if hasattr(part, 'text'):
                        text += part.text
                        
            # Get usage information if available
            usage = {}
            if hasattr(response, 'usage'):
                usage = response.usage
                
            return LLMResponse(
                text=text,
                model=self.model,
                usage=usage,
                metadata={"response": str(response)}
            )
                
        except Exception as e:
            logger.error(f"Error generating text with Gemini: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=self.model,
                metadata={"error": str(e)}
            )
    
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation using Gemini's API.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Gemini API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        if not self.is_available:
            logger.error("Gemini provider is not available")
            return LLMResponse(
                text="Error: Gemini provider is not available",
                model=self.model,
                metadata={"error": "Provider not available"}
            )
        
        logger.info(f"Processing chat completion with Gemini model: {self.model}")
        logger.info(f"Received {len(messages)} messages")
            
        try:
            # For simplicity and reliability, convert the conversation to a single prompt
            prompt = ""
            for msg in messages:
                role_prefix = ""
                if msg.role == "system":
                    role_prefix = "SYSTEM: "
                elif msg.role == "user":
                    role_prefix = "USER: "
                elif msg.role == "assistant":
                    role_prefix = "ASSISTANT: "
                    
                prompt += f"{role_prefix}{msg.content}\n\n"
                
            # Add a final assistant prefix to prompt the model to respond
            prompt += "ASSISTANT: "
            
            logger.info(f"Simplified prompt approach for Gemini: {prompt[:100]}...")
            
            # Generate content with the simplified approach
            generation_config = {
                "temperature": temperature,
                "top_p": kwargs.get("top_p", 0.95),
                "top_k": kwargs.get("top_k", 40),
            }
            
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens
            
            # Use the simpler generate_content approach instead of chat
            response = await asyncio.to_thread(
                self.client.generate_content,
                prompt,
                generation_config=generation_config
            )
            
            # Debug response
            logger.info(f"Gemini response type: {type(response)}")
            
            # Extract text from response
            if hasattr(response, 'text'):
                text = response.text
                logger.info(f"Found response.text: {text[:100]}...")
            else:
                # Try to get text from parts if available
                text = ""
                logger.info(f"No direct text attribute, checking parts")
                for part in getattr(response, 'parts', []):
                    if hasattr(part, 'text'):
                        text += part.text
                        
                # If still empty, try candidates
                if not text and hasattr(response, 'candidates'):
                    logger.info("Checking candidates")
                    for candidate in response.candidates:
                        if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                            for part in candidate.content.parts:
                                if hasattr(part, 'text'):
                                    text += part.text
                
            # Debug the extracted text
            if text:
                logger.info(f"Successfully extracted text: {text[:100]}...")
            else:
                logger.error("Failed to extract any text from the Gemini response")
                logger.error(f"Raw response: {str(response)}")
            
            # Get usage information if available
            usage = {}
            if hasattr(response, 'usage'):
                usage = response.usage
                
            return LLMResponse(
                text=text or "I apologize, but I couldn't generate a response. Please try again.",
                model=self.model,
                usage=usage,
                metadata={"response": str(response)}
            )
                
        except Exception as e:
            logger.error(f"Error with Gemini chat completion: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=self.model,
                metadata={"error": str(e)}
            )
    
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text using Gemini's embedding model.
        Note: This is a basic implementation as Gemini's embedding capabilities are evolving.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        # Apply rate limiting
        await self._rate_limit()
        
        if not self.is_available:
            logger.error("Gemini provider is not available for embeddings")
            # Return empty embedding with a reasonable dimensionality
            empty_embedding = [0.0] * 768
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(text)
                
        try:
            # Format input
            if isinstance(text, str):
                input_texts = [text]
            else:
                input_texts = text
                
            # Get embeddings
            embeddings = []
            for input_text in input_texts:
                # Use embedding model if available, otherwise use a workaround
                try:
                    embedding_model = genai.get_model("embedding-001")
                    embedding = await asyncio.to_thread(
                        embedding_model.embed_content,
                        input_text
                    )
                    
                    # Extract the values
                    if hasattr(embedding, 'embedding'):
                        embeddings.append(embedding.embedding)
                    else:
                        # Fallback to a reasonable dimensionality
                        logger.warning("Could not extract embedding values from Gemini response")
                        embeddings.append([0.0] * 768)
                except Exception as e:
                    logger.error(f"Error getting embedding from Gemini: {str(e)}")
                    embeddings.append([0.0] * 768)
                    
            # Return single embedding or list based on input
            if isinstance(text, str):
                return embeddings[0]
            else:
                return embeddings
                
        except Exception as e:
            logger.error(f"Error generating embeddings with Gemini: {str(e)}")
            # Return empty embedding with a reasonable dimensionality
            empty_embedding = [0.0] * 768
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(input_texts)
