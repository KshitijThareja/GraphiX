from typing import Dict, List, Optional, Any, Union, Set
from pydantic import BaseModel, Field
import datetime
from uuid import UUID, uuid4

class DocumentationElement(BaseModel):
    """Base model for documentation elements"""
    name: str = Field(..., description="Name of the element")
    qualified_name: str = Field(..., description="Fully qualified name of the element")
    docstring: Optional[str] = Field(None, description="Documentation string for the element")
    file_path: Optional[str] = Field(None, description="Path to the file containing this element")
    element_type: str = Field(..., description="Type of element (module, class, function, method)")

class FunctionDocumentation(DocumentationElement):
    """Model for function documentation"""
    signature: str = Field(..., description="Function signature")
    args: List[Dict[str, str]] = Field(default_factory=list, description="Function arguments with types")
    return_type: Optional[str] = Field(None, description="Return type of the function")
    is_async: bool = Field(False, description="Whether the function is asynchronous")
    dependencies: Optional[List[Dict[str, str]]] = Field(None, description="Function dependencies")

class ClassDocumentation(DocumentationElement):
    """Model for class documentation"""
    bases: List[str] = Field(default_factory=list, description="Base classes")
    methods: List[FunctionDocumentation] = Field(default_factory=list, description="Class methods")
    attributes: Optional[List[Dict[str, Any]]] = Field(None, description="Class attributes")

class ModuleDocumentation(DocumentationElement):
    """Model for module documentation"""
    classes: List[str] = Field(default_factory=list, description="Classes in this module")
    functions: List[str] = Field(default_factory=list, description="Functions in this module")

class DocumentationRequest(BaseModel):
    """Request model for generating documentation"""
    repository_id: str = Field(..., description="ID of the repository to document")
    framework_hint: Optional[str] = Field(None, description="Optional hint about the framework used")
    include_docstring_generation: bool = Field(False, description="Whether to generate missing docstrings with LLM")

class DocumentationResponse(BaseModel):
    """Response model for documentation generation"""
    documentation_id: str = Field(..., description="Unique ID for the documentation")
    repository_id: str = Field(..., description="ID of the repository")
    modules_count: int = Field(0, description="Number of modules documented")
    classes_count: int = Field(0, description="Number of classes documented")
    functions_count: int = Field(0, description="Number of functions documented")
    generated_at: datetime.datetime = Field(default_factory=datetime.datetime.now, description="When the documentation was generated")
    framework: Optional[str] = Field(None, description="Detected framework")

class DocumentationSearchRequest(BaseModel):
    """Request model for searching documentation"""
    repository_id: str = Field(..., description="ID of the repository")
    query: str = Field(..., description="Search query")
    element_types: Optional[List[str]] = Field(None, description="Types of elements to search for")
    limit: int = Field(10, description="Maximum number of results to return")
