from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
import datetime
from uuid import UUID, uuid4

class EmbeddingBase(BaseModel):
    """Base model for embeddings with common fields"""
    text: str = Field(..., description="The text content that was embedded")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata about the embedding")

class EmbeddingCreate(EmbeddingBase):
    """Model for creating a new embedding"""
    repository_id: Optional[str] = Field(None, description="ID of the repository this embedding belongs to")
    file_path: Optional[str] = Field(None, description="Path to the file within the repository")
    element_type: str = Field(..., description="Type of code element (function, class, module, etc.)")
    element_name: str = Field(..., description="Name of the code element")
    qualified_name: Optional[str] = Field(None, description="Fully qualified name of the code element")
    embedding_model: Optional[str] = Field("openai", description="Model used to generate the embedding")

class EmbeddingDB(EmbeddingBase):
    """Database model for an embedding"""
    id: UUID = Field(default_factory=uuid4, description="Unique identifier")
    repository_id: Optional[str] = Field(None, description="ID of the repository this embedding belongs to")
    file_path: Optional[str] = Field(None, description="Path to the file within the repository")
    element_type: str = Field(..., description="Type of code element (function, class, module, etc.)")
    element_name: str = Field(..., description="Name of the code element")
    qualified_name: Optional[str] = Field(None, description="Fully qualified name of the code element")
    embedding_model: str = Field("openai", description="Model used to generate the embedding")
    embedding_vector: Optional[List[float]] = Field(None, description="The actual embedding vector")
    created_at: datetime.datetime = Field(default_factory=datetime.datetime.now, description="When the embedding was created")
    updated_at: Optional[datetime.datetime] = Field(None, description="When the embedding was last updated")

    class Config:
        from_attributes = True

class EmbeddingResponse(BaseModel):
    """Response model for embedding queries"""
    id: UUID = Field(..., description="Unique identifier")
    text: str = Field(..., description="The text content that was embedded")
    element_type: str = Field(..., description="Type of code element")
    element_name: str = Field(..., description="Name of the code element")
    qualified_name: Optional[str] = Field(None, description="Fully qualified name of the code element")
    file_path: Optional[str] = Field(None, description="Path to the file within the repository")
    repository_id: Optional[str] = Field(None, description="ID of the repository this embedding belongs to")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional metadata")
    similarity_score: Optional[float] = Field(None, description="Similarity score from vector search")

class DocumentChunk(BaseModel):
    """Model for a chunk of a document to be embedded"""
    content: str = Field(..., description="The text content of the chunk")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Metadata about the chunk")
    element_type: str = Field(..., description="Type of code element this chunk belongs to")
    element_name: str = Field(..., description="Name of the code element this chunk belongs to")
    qualified_name: Optional[str] = Field(None, description="Fully qualified name of the code element")
    chunk_index: int = Field(0, description="Index of this chunk within the document")

class CodebaseChunkingConfig(BaseModel):
    """Configuration for chunking a codebase"""
    chunk_size: int = Field(1000, description="Target size of each chunk in characters")
    chunk_overlap: int = Field(200, description="Overlap between chunks in characters")
    include_docstrings: bool = Field(True, description="Whether to include docstrings in chunks")
    include_comments: bool = Field(True, description="Whether to include comments in chunks")
    include_function_bodies: bool = Field(True, description="Whether to include function bodies in chunks")
    separate_functions: bool = Field(True, description="Whether to chunk functions separately")
    separate_classes: bool = Field(True, description="Whether to chunk classes separately")
    separate_modules: bool = Field(True, description="Whether to chunk modules separately")
