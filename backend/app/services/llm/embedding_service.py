import os
import logging
import re
import json
from typing import Dict, List, Set, Optional, Any, Union, Tuple
import asyncio
import uuid
from datetime import datetime

from ..vector_store.chroma_store import ChromaStore
from .llm_manager import LLMManager
from ...models.embeddings import DocumentChunk, CodebaseChunkingConfig

logger = logging.getLogger(__name__)

class EmbeddingService:
    """
    Service for generating and managing embeddings for code and documentation.
    
    This service handles chunking of code elements, generating embeddings, and
    storing them in the vector store for later retrieval.
    """
    
    def __init__(self):
        """Initialize the embedding service with required dependencies"""
        self.vector_store = ChromaStore()
        self.llm_manager = LLMManager()
        
    async def embed_code_elements(self, 
                                 elements: List[Dict], 
                                 repository_id: Optional[str] = None,
                                 chunking_config: Optional[CodebaseChunkingConfig] = None) -> Dict:
        """
        Generate embeddings for code elements and store them in the vector store.
        
        Args:
            elements: List of code elements (functions, classes, modules)
            repository_id: ID of the repository these elements belong to
            chunking_config: Configuration for chunking the code elements
            
        Returns:
            Dictionary with status and statistics
        """
        if not self.vector_store.available:
            logger.warning("Vector store is not available, skipping embedding generation")
            return {
                "status": "error",
                "message": "Vector store is not available",
                "embedded_count": 0
            }
            
        chunking_config = chunking_config or CodebaseChunkingConfig()
        
        chunks = []
        for element in elements:
            element_chunks = await self._chunk_code_element(element, chunking_config)
            chunks.extend(element_chunks)
            
        logger.info(f"Generated {len(chunks)} chunks from {len(elements)} code elements")
        
        # Generate embeddings for chunks
        items_to_embed = []
        for i, chunk in enumerate(chunks):
            item_id = str(uuid.uuid4())
            
            item = {
                "id": item_id,
                "text": chunk.content,
                "metadata": {
                    "repository_id": repository_id,
                    "element_type": chunk.element_type,
                    "element_name": chunk.element_name,
                    "qualified_name": chunk.qualified_name,
                    "chunk_index": chunk.chunk_index,
                    **chunk.metadata
                }
            }
            
            items_to_embed.append(item)
        
        # Store embeddings in vector store
        success = await self.vector_store.add_embeddings(items_to_embed)
        
        return {
            "status": "success" if success else "error",
            "message": "Embeddings generated and stored" if success else "Failed to store embeddings",
            "embedded_count": len(items_to_embed) if success else 0,
            "chunks_count": len(chunks)
        }
    
    async def _chunk_code_element(self, 
                                 element: Dict, 
                                 config: CodebaseChunkingConfig) -> List[DocumentChunk]:
        """
        Split a code element into chunks for embedding.
        
        Args:
            element: Code element to chunk
            config: Chunking configuration
            
        Returns:
            List of document chunks
        """
        chunks = []
        
        element_type = element.get("type", "unknown")
        element_name = element.get("name", "")
        qualified_name = element.get("qualified_name", element.get("id", ""))
        content = ""
        
        # Collect content based on element type
        if element_type == "function" or element_type == "method":
            # Include signature and docstring
            signature = element.get("signature", "")
            docstring = element.get("docstring", "")
            
            content = f"{signature}\n\n{docstring}\n\n"
            
            # Add function body if available and configured
            if config.include_function_bodies and "body" in element:
                content += element["body"]
                
        elif element_type == "class":
            # Include class definition and docstring
            docstring = element.get("docstring", "")
            content = f"class {element_name}:\n\n{docstring}\n\n"
            
            # Add methods if available
            for method in element.get("methods", []):
                method_signature = method.get("signature", "")
                method_docstring = method.get("docstring", "")
                
                content += f"\n{method_signature}\n{method_docstring}\n"
                
                # Add method body if available and configured
                if config.include_function_bodies and "body" in method:
                    content += method["body"]
                    
        elif element_type == "module":
            # Include module docstring
            docstring = element.get("docstring", "")
            content = f"Module: {element_name}\n\n{docstring}\n\n"
            
            # Add list of classes and functions
            if "classes" in element:
                content += "\nClasses:\n"
                for class_name in element["classes"]:
                    content += f"- {class_name}\n"
                    
            if "functions" in element:
                content += "\nFunctions:\n"
                for func_name in element["functions"]:
                    content += f"- {func_name}\n"
        else:
            # Generic handling for other element types
            content = str(element.get("content", ""))
            
        # Extract file path if available
        file_path = element.get("file_path", "")
        
        # Create metadata
        metadata = {
            "file_path": file_path,
            "element_type": element_type,
        }
        
        # Add specific metadata based on element type
        if element_type == "function" or element_type == "method":
            if "args" in element:
                metadata["args"] = element["args"]
            if "return_type" in element:
                metadata["return_type"] = element["return_type"]
            if "dependencies" in element:
                metadata["dependencies"] = element["dependencies"]
                
        elif element_type == "class":
            if "bases" in element:
                metadata["bases"] = element["bases"]
            if "methods" in element:
                metadata["method_count"] = len(element["methods"])
                
        # Create chunks based on content
        if not content:
            return chunks
            
        # Simple chunking strategy - split by character count with overlap
        if len(content) <= config.chunk_size:
            # Content fits in one chunk
            chunks.append(
                DocumentChunk(
                    content=content,
                    metadata=metadata,
                    element_type=element_type,
                    element_name=element_name,
                    qualified_name=qualified_name,
                    chunk_index=0
                )
            )
        else:
            # Split into multiple chunks with overlap
            current_pos = 0
            chunk_index = 0
            
            while current_pos < len(content):
                # Determine end position
                end_pos = min(current_pos + config.chunk_size, len(content))
                
                # Try to find a clean break point (newline) near the end
                if end_pos < len(content):
                    # Look for newline within the last 20% of the chunk
                    search_start = max(current_pos, end_pos - int(config.chunk_size * 0.2))
                    newline_pos = content.rfind("\n", search_start, end_pos)
                    
                    if newline_pos > search_start:
                        end_pos = newline_pos + 1  # Include the newline
                
                # Extract chunk
                chunk_content = content[current_pos:end_pos]
                
                # Create chunk
                chunks.append(
                    DocumentChunk(
                        content=chunk_content,
                        metadata=metadata.copy(),
                        element_type=element_type,
                        element_name=element_name,
                        qualified_name=qualified_name,
                        chunk_index=chunk_index
                    )
                )
                
                # Move position for next chunk
                current_pos = end_pos - config.chunk_overlap
                if current_pos <= 0:
                    current_pos = end_pos  # Avoid infinite loop
                    
                chunk_index += 1
                
        return chunks
    
    async def search_similar_code(self, 
                                 query: str, 
                                 repository_id: Optional[str] = None,
                                 n_results: int = 5,
                                 element_types: Optional[List[str]] = None) -> List[Dict]:
        """
        Search for code similar to the query.
        
        Args:
            query: Search query
            repository_id: Optional repository ID to filter results
            n_results: Number of results to return
            element_types: Optional list of element types to filter by
            
        Returns:
            List of matching code elements with similarity scores
        """
        if not self.vector_store.available:
            logger.warning("Vector store is not available for search")
            return []
            
        # Prepare filter criteria
        filter_criteria = {}
        
        if repository_id:
            filter_criteria["repository_id"] = repository_id
            
        if element_types:
            filter_criteria["element_type"] = {"$in": element_types}
            
        # Perform vector search
        results = await self.vector_store.query(
            query_text=query,
            n_results=n_results,
            filter_criteria=filter_criteria if filter_criteria else None
        )
        
        # Format results
        formatted_results = []
        
        for result in results:
            formatted_results.append({
                "id": result["id"],
                "content": result["text"],
                "element_type": result["metadata"]["element_type"],
                "element_name": result["metadata"]["element_name"],
                "qualified_name": result["metadata"].get("qualified_name", ""),
                "file_path": result["metadata"].get("file_path", ""),
                "repository_id": result["metadata"].get("repository_id", ""),
                "similarity_score": result.get("score", 0.0),
                "metadata": result["metadata"]
            })
            
        return formatted_results
    
    async def clear_embeddings(self, repository_id: Optional[str] = None) -> Dict:
        """
        Clear embeddings from the vector store.
        
        Args:
            repository_id: If provided, only clear embeddings for this repository
            
        Returns:
            Status dictionary
        """
        if not self.vector_store.available:
            logger.warning("Vector store is not available for clearing")
            return {"status": "error", "message": "Vector store is not available"}
            
        if repository_id:
            # TODO: Implement selective clearing based on repository_id
            # This requires fetching all IDs for a repository and then deleting them
            logger.warning("Selective clearing by repository_id is not yet implemented")
            return {"status": "error", "message": "Selective clearing not implemented"}
        else:
            # Clear all embeddings
            success = await self.vector_store.clear_collection()
            
            return {
                "status": "success" if success else "error",
                "message": "All embeddings cleared" if success else "Failed to clear embeddings"
            }
            
    async def get_statistics(self) -> Dict:
        """
        Get statistics about the embeddings.
        
        Returns:
            Dictionary with statistics
        """
        if not self.vector_store.available:
            return {"available": False}
            
        return await self.vector_store.get_collection_stats()
