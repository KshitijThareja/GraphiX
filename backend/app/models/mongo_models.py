from pydantic import BaseModel, Field
from typing import Dict, Any, Optional
import datetime

class DocumentationMetadata(BaseModel):
    documentation_id: str = Field(..., description="Unique ID for the documentation")
    repository_id: str = Field(..., description="ID of the repository")
    modules_count: int = Field(0, description="Number of modules documented")
    classes_count: int = Field(0, description="Number of classes documented")
    functions_count: int = Field(0, description="Number of functions documented")
    generated_at: datetime.datetime = Field(default_factory=datetime.datetime.now, description="When the documentation was generated")
    framework: Optional[str] = Field(None, description="Detected framework")

class DocumentationContent(BaseModel):
    documentation_id: str = Field(..., description="Unique ID for the documentation")
    content: Dict[str, Any] = Field(..., description="The actual documentation content, mapping qualified names to documentation elements")