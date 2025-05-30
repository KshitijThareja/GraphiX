import os
import logging
from typing import Dict, List, Optional, Any
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Path
from fastapi.responses import FileResponse, JSONResponse

from ..models.documentation import (
    DocumentationRequest,
    DocumentationResponse,
    DocumentationSearchRequest,
    DocumentationElement,
    FunctionDocumentation,
    ClassDocumentation,
    ModuleDocumentation
)
from ..services.documentation_service import DocumentationService
from ..services.llm.embedding_service import EmbeddingService

router = APIRouter(
    prefix="/documentation", # Changed from /api/documentation to match frontend
    tags=["documentation"],
    responses={404: {"description": "Not found"}},
)

# In-memory store for documentation results (in production, this would be in a database)
documentation_store = {}

@router.get("/{repo_identifier}", response_model=Dict[str, Any])
async def get_documentation_by_repo(repo_identifier: str):
    """
    Get documentation for a repository by its URL or ID.
    If the documentation is not found, returns a 404 error.
    """
    logger = logging.getLogger(__name__)
    logger.info(f"Fetching documentation for repository: {repo_identifier}")
    
    # First, check if the identifier is a UUID (documentation_id)
    try:
        uuid.UUID(repo_identifier)
        # If it's a valid UUID, look for direct match
        if repo_identifier in documentation_store:
            return documentation_store[repo_identifier]
    except ValueError:
        # Not a UUID, so might be a repository URL or name
        pass
        
    # Search by repository URL or ID in the documentation store
    for doc_id, doc in documentation_store.items():
        if doc.get('repository_url') == repo_identifier or doc.get('repository_id') == repo_identifier:
            logger.info(f"Found documentation with ID: {doc_id}")
            return doc
    
    # If we get here, the documentation was not found
    logger.warning(f"Documentation not found for repository: {repo_identifier}")
    raise HTTPException(status_code=404, detail=f"Documentation not found for repository: {repo_identifier}")

@router.post("/generate", response_model=DocumentationResponse)
async def generate_documentation(
    request: DocumentationRequest,
    background_tasks: BackgroundTasks
):
    """
    Generate documentation for a repository.
    This is an asynchronous operation that will run in the background.
    """
    # Create a documentation ID
    documentation_id = str(uuid.uuid4())
    
    # Store initial response
    documentation_store[documentation_id] = {
        "documentation_id": documentation_id,
        "repository_id": request.repository_id,
        "status": "processing",
        "generated_at": datetime.now().isoformat(),
        "modules_count": 0,
        "classes_count": 0,
        "functions_count": 0
    }
    
    # Add the documentation generation task to background tasks
    background_tasks.add_task(
        _generate_documentation_task,
        documentation_id,
        request.repository_id,
        request.framework_hint,
        request.include_docstring_generation
    )
    
    return DocumentationResponse(
        documentation_id=documentation_id,
        repository_id=request.repository_id,
        generated_at=datetime.now(),
        modules_count=0,
        classes_count=0,
        functions_count=0,
        framework=request.framework_hint
    )

async def _generate_documentation_task(
    documentation_id: str,
    repository_id: str,
    framework_hint: Optional[str] = None,
    include_docstring_generation: bool = False
):
    """
    Background task to generate documentation.
    """
    try:
        # Create documentation service
        documentation_service = DocumentationService(framework_hint=framework_hint)
        
        # Clone and analyze repository
        # Assuming repository_id is the repository URL or a reference to a stored repository
        doc_result = await documentation_service.analyze_repository(
            repo_path=repository_id,
            timeout=600,
            clone=True
        )
        
        # Generate missing docstrings if requested
        if include_docstring_generation:
            # Get all elements without docstrings
            elements_without_docstrings = []
            
            for func in doc_result.get("functions", []):
                if not func.get("docstring"):
                    elements_without_docstrings.append(func)
                    
            for cls in doc_result.get("classes", []):
                if not cls.get("docstring"):
                    elements_without_docstrings.append(cls)
                
            # Generate docstrings
            if elements_without_docstrings:
                generated_docstrings = await documentation_service.generate_docstrings_for_elements(
                    elements_without_docstrings,
                    use_llm=True
                )
                
                # Update elements with generated docstrings
                for func in doc_result.get("functions", []):
                    if func.get("qualified_name") in generated_docstrings:
                        func["docstring"] = generated_docstrings[func["qualified_name"]]
                        
                for cls in doc_result.get("classes", []):
                    if cls.get("qualified_name") in generated_docstrings:
                        cls["docstring"] = generated_docstrings[cls["qualified_name"]]
        
        # Generate markdown documentation
        markdown_files = await documentation_service.generate_markdown_documentation()
        
        # Generate embeddings for documentation elements
        embedding_service = EmbeddingService()
        elements_to_embed = doc_result.get("functions", []) + doc_result.get("classes", [])
        
        await embedding_service.embed_code_elements(
            elements=elements_to_embed,
            repository_id=repository_id
        )
        
        # Update documentation store with results
        documentation_store[documentation_id] = {
            "documentation_id": documentation_id,
            "repository_id": repository_id,
            "status": "completed",
            "generated_at": datetime.now().isoformat(),
            "modules_count": len(doc_result.get("modules", [])),
            "classes_count": len(doc_result.get("classes", [])),
            "functions_count": len(doc_result.get("functions", [])),
            "framework": doc_result.get("metadata", {}).get("framework_analyzed_as"),
            "documentation": doc_result,
            "markdown_files": markdown_files
        }
        
    except Exception as e:
        logging.error(f"Error generating documentation: {str(e)}")
        # Update documentation store with error
        documentation_store[documentation_id] = {
            "documentation_id": documentation_id,
            "repository_id": repository_id,
            "status": "error",
            "error": str(e),
            "generated_at": datetime.now().isoformat()
        }

@router.get("/{documentation_id}", response_model=DocumentationResponse)
async def get_documentation_status(
    documentation_id: str = Path(..., description="The ID of the documentation")
):
    """
    Get the status of a documentation generation task.
    """
    if documentation_id not in documentation_store:
        raise HTTPException(status_code=404, detail="Documentation not found")
        
    doc_info = documentation_store[documentation_id]
    
    return DocumentationResponse(
        documentation_id=documentation_id,
        repository_id=doc_info["repository_id"],
        modules_count=doc_info.get("modules_count", 0),
        classes_count=doc_info.get("classes_count", 0),
        functions_count=doc_info.get("functions_count", 0),
        generated_at=datetime.fromisoformat(doc_info["generated_at"]),
        framework=doc_info.get("framework")
    )

@router.get("/{documentation_id}/download")
async def download_documentation(
    documentation_id: str = Path(..., description="The ID of the documentation"),
    format: str = Query("markdown", description="Documentation format (markdown, html, pdf)")
):
    """
    Download documentation in the specified format.
    """
    if documentation_id not in documentation_store:
        raise HTTPException(status_code=404, detail="Documentation not found")
        
    doc_info = documentation_store[documentation_id]
    
    if doc_info["status"] != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Documentation generation is not complete. Current status: {doc_info['status']}"
        )
        
    if format == "markdown":
        # Return the README.md content for now
        if "markdown_files" in doc_info and "README.md" in doc_info["markdown_files"]:
            return JSONResponse(content={"content": doc_info["markdown_files"]["README.md"]})
        else:
            raise HTTPException(status_code=404, detail="Markdown documentation not found")
    elif format == "html":
        # HTML export not implemented yet
        raise HTTPException(status_code=501, detail="HTML export not implemented yet")
    elif format == "pdf":
        # PDF export not implemented yet
        raise HTTPException(status_code=501, detail="PDF export not implemented yet")
    else:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")

@router.get("/{documentation_id}/elements")
async def get_documentation_elements(
    documentation_id: str = Path(..., description="The ID of the documentation"),
    element_type: Optional[str] = Query(None, description="Filter by element type (module, class, function)"),
    module: Optional[str] = Query(None, description="Filter by module name")
):
    """
    Get documentation elements, optionally filtered by type and module.
    """
    if documentation_id not in documentation_store:
        raise HTTPException(status_code=404, detail="Documentation not found")
        
    doc_info = documentation_store[documentation_id]
    
    if doc_info["status"] != "completed":
        raise HTTPException(
            status_code=400, 
            detail=f"Documentation generation is not complete. Current status: {doc_info['status']}"
        )
        
    if "documentation" not in doc_info:
        raise HTTPException(status_code=404, detail="Documentation content not found")
        
    elements = []
    
    # Filter modules
    if element_type is None or element_type == "module":
        modules = doc_info["documentation"].get("modules", [])
        if module:
            modules = [m for m in modules if m["name"] == module or module in m["name"]]
        elements.extend(modules)
        
    # Filter classes
    if element_type is None or element_type == "class":
        classes = doc_info["documentation"].get("classes", [])
        if module:
            classes = [c for c in classes if c["module"] == module or module in c["module"]]
        elements.extend(classes)
        
    # Filter functions
    if element_type is None or element_type == "function":
        functions = doc_info["documentation"].get("functions", [])
        if module:
            functions = [f for f in functions if f["module"] == module or module in f["module"]]
        elements.extend(functions)
        
    return {"elements": elements, "count": len(elements)}

@router.post("/search")
async def search_documentation(
    search_request: DocumentationSearchRequest
):
    """
    Search documentation using vector search.
    """
    # Use embedding service to search for similar code
    embedding_service = EmbeddingService()
    
    element_types = search_request.element_types or ["function", "class", "module"]
    
    results = await embedding_service.search_similar_code(
        query=search_request.query,
        repository_id=search_request.repository_id,
        n_results=search_request.limit,
        element_types=element_types
    )
    
    return {"results": results, "count": len(results)}
