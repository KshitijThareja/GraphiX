import os
import logging
from typing import Dict, List, Optional, Any, Union
import asyncio
import time
import json
import uuid
from pathlib import Path

# Import required for ChromaDB
try:
    import chromadb
    from chromadb.config import Settings
    from chromadb.utils import embedding_functions
    CHROMADB_AVAILABLE = True
except ImportError:
    CHROMADB_AVAILABLE = False

from ...models.base import settings

logger = logging.getLogger(__name__)

class ChromaStore:
    """
    Vector store implementation using ChromaDB.
    
    This service provides vector database capabilities for storing and retrieving
    code embeddings, enabling semantic search and context building for LLM integration.
    """
    
    def __init__(self, 
                 persist_directory: Optional[str] = None, 
                 collection_name: str = "graphix_embeddings",
                 embedding_function_name: str = "openai"):
        """
        Initialize the ChromaDB vector store.
        
        Args:
            persist_directory: Directory to persist ChromaDB data
            collection_name: Name of the collection to use
            embedding_function_name: Name of the embedding function to use
        """
        self.available = CHROMADB_AVAILABLE
        if not self.available:
            logger.warning("ChromaDB is not available. Install it with 'pip install chromadb'")
            return
            
        # Use configured directory or default
        self.persist_directory = persist_directory or settings.VECTOR_STORE_DIR
        if not self.persist_directory:
            self.persist_directory = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))), "vector_data")
            
        # Create directory if it doesn't exist
        os.makedirs(self.persist_directory, exist_ok=True)
        
        self.collection_name = collection_name
        self.client = None
        self.collection = None
        self.embedding_function = None
        self.embedding_function_name = embedding_function_name
        
        # Initialize the client and collection
        self._initialize_client()
        
    def _initialize_client(self) -> None:
        """
        Initialize the ChromaDB client and collection.
        """
        if not self.available:
            return
            
        try:
            # Initialize the client with persistence
            self.client = chromadb.PersistentClient(
                path=self.persist_directory,
                settings=Settings(
                    anonymized_telemetry=False,
                    allow_reset=True
                )
            )
            
            # Set up the embedding function
            self._setup_embedding_function()
            
            # Get or create the collection
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={"description": "GraphiX code embeddings"}
            )
            
            logger.info(f"ChromaDB initialized with collection '{self.collection_name}'")
            
        except Exception as e:
            logger.error(f"Error initializing ChromaDB: {str(e)}")
            self.available = False
            
    def _setup_embedding_function(self) -> None:
        """
        Set up the embedding function based on configuration.
        """
        if self.embedding_function_name == "openai":
            # Check for OpenAI API key
            api_key = settings.OPENAI_API_KEY
            if not api_key:
                logger.warning("OpenAI API key not found, using default embedding function")
                self.embedding_function = None
                return
                
            try:
                self.embedding_function = embedding_functions.OpenAIEmbeddingFunction(
                    api_key=api_key,
                    model_name="text-embedding-3-small"
                )
            except Exception as e:
                logger.error(f"Error setting up OpenAI embedding function: {str(e)}")
                self.embedding_function = None
        elif self.embedding_function_name == "huggingface":
            try:
                self.embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(
                    model_name="all-MiniLM-L6-v2"
                )
            except Exception as e:
                logger.error(f"Error setting up HuggingFace embedding function: {str(e)}")
                self.embedding_function = None
        else:
            # Use default (none)
            self.embedding_function = None
            
    async def add_embeddings(self, items: List[Dict[str, Any]]) -> bool:
        """
        Add embeddings to the vector store.
        
        Args:
            items: List of items to add, each containing:
                - id: Unique identifier
                - text: Text to embed
                - metadata: Additional metadata
                - embedding: Optional pre-computed embedding
                
        Returns:
            True if successful, False otherwise
        """
        if not self.available or not self.collection:
            logger.warning("ChromaDB is not available for adding embeddings")
            return False
            
        try:
            # Prepare items for ChromaDB
            ids = []
            documents = []
            metadatas = []
            embeddings = []
            
            has_embeddings = all("embedding" in item for item in items)
            
            for item in items:
                item_id = item.get("id", str(uuid.uuid4()))
                text = item.get("text", "")
                metadata = item.get("metadata", {})
                
                ids.append(str(item_id))
                documents.append(text)
                metadatas.append(metadata)
                
                if has_embeddings:
                    embeddings.append(item["embedding"])
                    
            # Add items to collection
            if has_embeddings:
                self.collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas,
                    embeddings=embeddings
                )
            else:
                self.collection.add(
                    ids=ids,
                    documents=documents,
                    metadatas=metadatas
                )
                
            logger.info(f"Added {len(items)} embeddings to ChromaDB")
            return True
            
        except Exception as e:
            logger.error(f"Error adding embeddings to ChromaDB: {str(e)}")
            return False
            
    async def query(self, 
                   query_text: str, 
                   n_results: int = 5, 
                   filter_criteria: Optional[Dict] = None) -> List[Dict]:
        """
        Query the vector store for similar items.
        
        Args:
            query_text: Text to search for
            n_results: Number of results to return
            filter_criteria: Filter criteria for the query
            
        Returns:
            List of matching items with similarity scores
        """
        if not self.available or not self.collection:
            logger.warning("ChromaDB is not available for querying")
            return []
            
        try:
            # Perform the query
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results,
                where=filter_criteria
            )
            
            # Format results
            formatted_results = []
            
            if results["documents"]:
                documents = results["documents"][0]
                ids = results["ids"][0]
                metadatas = results["metadatas"][0]
                distances = results["distances"][0] if "distances" in results else None
                
                for i in range(len(documents)):
                    item = {
                        "id": ids[i],
                        "text": documents[i],
                        "metadata": metadatas[i]
                    }
                    
                    if distances:
                        item["score"] = 1.0 - distances[i]  # Convert distance to similarity score
                        
                    formatted_results.append(item)
                    
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error querying ChromaDB: {str(e)}")
            return []
            
    async def delete(self, ids: List[str]) -> bool:
        """
        Delete items from the vector store.
        
        Args:
            ids: List of IDs to delete
            
        Returns:
            True if successful, False otherwise
        """
        if not self.available or not self.collection:
            logger.warning("ChromaDB is not available for deletion")
            return False
            
        try:
            self.collection.delete(ids=ids)
            logger.info(f"Deleted {len(ids)} items from ChromaDB")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting from ChromaDB: {str(e)}")
            return False
            
    async def clear_collection(self) -> bool:
        """
        Clear all items from the collection.
        
        Returns:
            True if successful, False otherwise
        """
        if not self.available or not self.collection:
            logger.warning("ChromaDB is not available for clearing")
            return False
            
        try:
            self.collection.delete()
            # Recreate the collection
            self.collection = self.client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={"description": "GraphiX code embeddings"}
            )
            logger.info(f"Cleared collection '{self.collection_name}'")
            return True
            
        except Exception as e:
            logger.error(f"Error clearing ChromaDB collection: {str(e)}")
            return False
            
    async def get_collection_stats(self) -> Dict:
        """
        Get statistics about the collection.
        
        Returns:
            Dictionary with collection statistics
        """
        if not self.available or not self.collection:
            logger.warning("ChromaDB is not available for stats")
            return {"available": False}
            
        try:
            count = self.collection.count()
            return {
                "available": True,
                "collection_name": self.collection_name,
                "item_count": count,
                "embedding_function": self.embedding_function_name,
                "persist_directory": self.persist_directory
            }
            
        except Exception as e:
            logger.error(f"Error getting ChromaDB stats: {str(e)}")
            return {"available": False, "error": str(e)}
            
    async def health_check(self) -> bool:
        """
        Check if the vector store is healthy.
        
        Returns:
            True if healthy, False otherwise
        """
        if not self.available:
            return False
            
        try:
            # Simple check - see if we can get the collection count
            count = self.collection.count()
            return True
            
        except Exception:
            return False
