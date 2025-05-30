from typing import Dict, List, Optional, Any
from pydantic import Field, BaseModel
from datetime import datetime

class CallgraphNode(BaseModel):
    """Node representation in a callgraph."""
    id: str
    type: str
    name: Optional[str] = None
    file: Optional[str] = None
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    complexity: Optional[float] = None
    class_name: Optional[str] = None
    docstring: Optional[str] = None
    signature: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class CallgraphLink(BaseModel):
    """Link representation in a callgraph."""
    source: str
    target: str
    type: str
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)


class CallgraphMetadata(BaseModel):
    """Metadata for a callgraph."""
    framework_analyzed_as: Optional[str] = None
    analysis_time_seconds: Optional[float] = None
    files_analyzed: Optional[int] = None
    total_files_found: Optional[int] = None
    context_sensitivity_k: Optional[int] = None
    metrics: Optional[Dict[str, Any]] = Field(default_factory=dict)
    status: str = "completed"
    status_log: List[str] = Field(default_factory=list)


class CallgraphData(BaseModel):
    """Complete callgraph data structure."""
    repository_id: str
    nodes: List[CallgraphNode]
    links: List[CallgraphLink]
    metadata: CallgraphMetadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        json_schema_extra = {
            "example": {
                "repository_id": "user/repo",
                "nodes": [
                    {
                        "id": "module.function",
                        "type": "function",
                        "name": "function",
                        "file": "path/to/file.py",
                        "line_start": 10,
                        "line_end": 20,
                        "complexity": 5.0,
                        "docstring": "Function documentation.",
                        "signature": "def function(arg1, arg2=None):",
                        "metadata": {"is_public": True}
                    }
                ],
                "links": [
                    {
                        "source": "module.function",
                        "target": "module.other_function",
                        "type": "FUNCTION_CALL",
                        "metadata": {"lineno": 15}
                    }
                ],
                "metadata": {
                    "framework_analyzed_as": "django",
                    "analysis_time_seconds": 30.5,
                    "files_analyzed": 100,
                    "context_sensitivity_k": 2,
                    "status": "completed"
                }
            }
        }


class CallgraphDataDB(CallgraphData):
    """Database model for callgraph data."""
    id: str = None

    class Config:
        from_attributes = True


class CallgraphDataCreate(BaseModel):
    """Model for creating callgraph data."""
    repository_id: str
    nodes: List[Dict[str, Any]]
    links: List[Dict[str, Any]]
    metadata: Dict[str, Any]
