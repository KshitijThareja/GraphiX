from datetime import datetime, timezone
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
    Request,
    BackgroundTasks,
)
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional, List
from pydantic import HttpUrl, BaseModel
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from sqlalchemy.orm import Session
import os
import logging
import time
import json
import asyncio
from ..services.callgraph import CallgraphGenerator
from ..services.enhanced_callgraph import EnhancedCallgraphGenerator
from ..services.research_callgraph import ResearchCallgraphGenerator
from ..services.scope_manager import ScopeManager
from ..services.definition_manager import DefinitionManager
from ..services.context_flow_analysis import ContextFlowAnalyzer, TypeInferenceEngine
from ..models.user import User
from ..services.auth import get_current_user
from ..models.base import Base, oauth2_scheme, settings, get_db
import traceback
import google.generativeai as genai

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/analysis")
GEMINI_API_KEY = settings.GEMINI_API_KEY
genai.configure(api_key=GEMINI_API_KEY)
try:
    flash_model = genai.GenerativeModel("gemini-2.0-flash-lite")
    pro_model = genai.GenerativeModel("gemini-2.0-flash-lite")
except Exception as e:
    logger.error(f"Failed to initialize Gemini models: {str(e)}")
    flash_model = None
    pro_model = None


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl
    advanced_analysis: bool = False
    advancedAnalysis: bool = False
    research_grade: bool = False
    context_sensitivity: int = 2
    framework_hint: Optional[str] = "generic"

    class Config:
        extra = "allow"


class AnalysisResult(Base):
    __tablename__ = "analysis_results"
    id = Column(Integer, primary_key=True)
    repo_url = Column(String)
    callgraph = Column(JSON)
    runtime = Column(Float)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))


class DatasetRequest(BaseModel):
    language: str = "python"
    repo_count: int = 10
    metrics: List[str] = ["complexity", "coupling", "cohesion"]


class ChatRequest(BaseModel):
    query: str
    repo_url: Optional[HttpUrl] = None


@router.post("/generate-callgraph")
async def generate_simple_callgraph(
    request: Request,
    background_tasks: BackgroundTasks,
    current_user: User = Depends(get_current_user),
):
    try:
        data = await request.json()
        repo_url = data.get("repoUrl", "")
        advanced_analysis = data.get("advancedAnalysis", False)
        if advanced_analysis:
            logger.info(f"Using enhanced callgraph generator for {repo_url}")
            generator = EnhancedCallgraphGenerator()
        else:
            logger.info(f"Using standard callgraph generator for {repo_url}")
            generator = CallgraphGenerator()
        result = await generator.analyze_repository(repo_url)
        return result
    except Exception as e:
        logger.error(f"Error generating callgraph: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/callgraph/stream", response_class=StreamingResponse)
async def stream_callgraph(
    repo_url: str,
    research_grade: bool = False,
    framework_hint: str = "generic",
    context_sensitivity: int = 2,
):
    """Stream callgraph analysis updates via SSE."""

    async def event_generator():
        start_time = time.time()
        try:
            if research_grade:
                generator = ResearchCallgraphGenerator(framework=framework_hint)
                yield f"data: {json.dumps({'status': 'Starting research-grade analysis...'})}\n\n"
            else:
                generator = EnhancedCallgraphGenerator()
                yield f"data: {json.dumps({'status': 'Starting enhanced analysis...'})}\n\n"
            analysis_task = asyncio.create_task(
                generator.analyze_repository(repo_url, clone=True)
            )
            while not analysis_task.done():
                if hasattr(generator, "status"):
                    yield f"data: {json.dumps({'status': generator.status})}\n\n"
                await asyncio.sleep(0.5)
            result = await analysis_task
            endpoint_runtime = time.time() - start_time
            if not result.get("metadata"):
                result["metadata"] = {}
            result["metadata"]["endpoint_runtime_seconds"] = round(endpoint_runtime, 2)
            yield f"data: {json.dumps(result)}\n\n"
        except Exception as e:
            logger.error(f"Error in stream_callgraph: {str(e)}")
            yield f"data: {json.dumps({'error': str(e)})}\n\n"
        finally:
            yield "event: close\ndata: {}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        },
    )


@router.post("/callgraph")
async def generate_callgraph(
    request_model: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not flash_model or not pro_model:
        error_detail = "Gemini API is not properly configured"
        logger.error(f"/callgraph endpoint error: {error_detail}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "status": "error",
                "message": error_detail,
                "data": None,
                "status_log": [],
            },
        )
    status_log = []
    generator = None
    try:
        advanced_analysis = (
            request_model.advanced_analysis or request_model.advancedAnalysis
        )
        research_grade = request_model.research_grade
        context_sensitivity = request_model.context_sensitivity
        framework_hint = request_model.framework_hint
        status_log.append(f"Received request for {request_model.repo_url}")
        if research_grade:
            generator = ResearchCallgraphGenerator(framework=framework_hint)
            status_log.append(
                f"Initializing research-grade analysis with hint: {framework_hint}"
            )
            status_log.append(
                f"Using research-grade generator (actual context sensitivity determined by builder)"
            )
        elif advanced_analysis:
            generator = EnhancedCallgraphGenerator()
            status_log.append("Initializing enhanced analysis.")
        else:
            generator = CallgraphGenerator()
            status_log.append("Initializing standard analysis.")
            logger.info(
                f"Using standard callgraph generator for {request_model.repo_url}"
            )
        repo_url = str(request_model.repo_url)
        is_remote = any(
            repo_url.startswith(prefix) for prefix in ("http://", "https://", "git@")
        )
        start_time = time.time()
        status_log.append("Starting repository analysis...")
        callgraph = await generator.analyze_repository(
            repo_path=repo_url, timeout=600, clone=is_remote
        )
        status_log.append("Repository analysis finished.")
        endpoint_runtime = time.time() - start_time
        if not callgraph.get("metadata"):
            callgraph["metadata"] = {}
        generator_metadata = callgraph.get("metadata", {})
        final_metadata = {
            "research_grade_requested": request_model.research_grade,
            "requested_context_sensitivity_k": request_model.context_sensitivity,
            "endpoint_runtime_seconds": round(endpoint_runtime, 2),
            "status_log_from_backend": status_log,
        }
        merged_metadata = {**generator_metadata, **final_metadata}
        callgraph["metadata"] = merged_metadata
        logger.info(
            f"Completed callgraph generation. Type: {'research-grade' if research_grade else ('advanced' if advanced_analysis else 'standard')}. "
            f"Framework hint: {framework_hint}. Endpoint Runtime: {endpoint_runtime:.2f}s. "
            f"Generator analysis time: {generator_metadata.get('analysis_time_seconds', 'N/A')}s. "
            f"Detected framework: {generator_metadata.get('framework_analyzed_as', 'N/A')}."
        )
        max_nodes_limit = 500
        if len(callgraph.get("nodes", [])) > max_nodes_limit:
            callgraph["nodes"] = callgraph["nodes"][:max_nodes_limit]
            callgraph["links"] = [
                link
                for link in callgraph.get("links", [])
                if link.get("source") < max_nodes_limit
                and link.get("target") < max_nodes_limit
            ]
            warning_msg = (
                f"Truncated callgraph to {max_nodes_limit} nodes due to size limit."
            )
            logger.warning(warning_msg)
            callgraph["metadata"]["warning"] = warning_msg
            status_log.append(warning_msg)
        final_response_data = {
            "status": "completed",
            "data": callgraph,
            "metrics": {
                "node_count": len(callgraph.get("nodes", [])),
                "edge_count": len(callgraph.get("links", [])),
            },
            "status_log": status_log,
        }
        logger.info(
            f"Full JSON response for {request_model.repo_url}: {json.dumps(final_response_data, indent=2, default=str)}"
        )
        return JSONResponse(content=final_response_data)
    except asyncio.TimeoutError:
        error_msg = "Analysis timed out after 10 minutes"
        logger.error(f"{error_msg} for {request_model.repo_url}")
        status_log.append(error_msg)
        return JSONResponse(
            status_code=status.HTTP_408_REQUEST_TIMEOUT,
            content={
                "status": "error",
                "message": error_msg,
                "data": None,
                "status_log": status_log,
            },
        )
    except Exception as e:
        error_msg = f"Error generating callgraph: {str(e)}"
        logger.error(
            f"{error_msg}\n{traceback.format_exc()} for {request_model.repo_url}"
        )
        status_log.append(error_msg)
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={
                "status": "error",
                "message": error_msg,
                "data": None,
                "status_log": status_log,
            },
        )
    finally:
        if generator:
            await generator.cleanup()
        status_log.append("Cleanup complete.")


@router.post("/enrich")
async def enrich_callgraph(
    callgraph: dict,
    framework: Optional[str] = Query(
        None, description="Framework to detect (django, flask, fastapi)"
    ),
    current_user: User = Depends(get_current_user),
):
    try:
        if framework == "django":
            return _enrich_django(callgraph)
        elif framework == "flask":
            return _enrich_flask(callgraph)
        return callgraph
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to enrich callgraph: {str(e)}",
        )


@router.get("/dataset")
async def export_dataset(
    current_user: User = Depends(get_current_user), db: Session = Depends(get_db)
):
    results = db.query(AnalysisResult).all()
    dataset = [
        {
            "repo_url": r.repo_url,
            "callgraph": r.callgraph,
            "runtime": r.runtime,
            "created_at": r.created_at.isoformat(),
        }
        for r in results
    ]
    return {"dataset": dataset}


@router.post("/dataset")
async def generate_dataset(
    request: DatasetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    generator = CallgraphGenerator()
    dataset = []
    try:
        repo_urls = [f"https://github.com/{i}" for i in range(request.repo_count)]
        for url in repo_urls:
            repo_path = await generator.clone_repository(url, current_user.access_token)
            callgraph = await generator.analyze_repository(repo_path)
            dataset.append(
                {
                    "repo_url": url,
                    "callgraph": callgraph,
                    "metrics": {
                        metric: _calculate_metric(callgraph, metric)
                        for metric in request.metrics
                    },
                }
            )
            await generator.cleanup()
        return {"dataset": dataset}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate dataset: {str(e)}",
        )


@router.post("/benchmark")
async def benchmark(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    try:
        start_time = time.time()
        await generate_callgraph(request, current_user=current_user, db=db)
        runtime = time.time() - start_time
        return {"runtime": runtime, "tool": "GraphiX"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to benchmark: {str(e)}",
        )


@router.post("/chat")
async def chat_with_llm(
    request: ChatRequest, current_user: User = Depends(get_current_user)
):
    try:
        query = request.query
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Query is required"
            )
        context = "No codebase context provided."
        if request.repo_url:
            generator = CallgraphGenerator()
            try:
                repo_path = await generator.clone_repository(
                    str(request.repo_url), current_user.access_token
                )
                callgraph = await generator.analyze_repository(repo_path)
                await generator.cleanup()
                context = "Codebase Context:\n"
                for node in callgraph["nodes"]:
                    func_name = node["id"].split(".")[-1]
                    docstring = node["metadata"].get(
                        "docstring", "No docstring available."
                    )
                    complexity = node["complexity"]
                    context += (
                        f"- Function: {func_name}\n"
                        f"  Docstring: {docstring}\n"
                        f"  Complexity: {complexity}\n"
                    )
            except Exception as e:
                logger.error("Failed to analyze repository for context: " f"{str(e)}")
                context = f"Failed to analyze repository: {str(e)}"
        prompt = (
            f"Given the following codebase context:\n{context}\n\n"
            f"Answer the following question about the codebase:\n{query}"
        )
        response = flash_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(max_output_tokens=150),
        )
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat query: {str(e)}",
        )


@router.post("/documentation")
async def generate_documentation(
    request: AnalyzeRequest, current_user: User = Depends(get_current_user)
):
    try:
        generator = CallgraphGenerator()
        repo_path = await generator.clone_repository(
            str(request.repo_url), current_user.access_token
        )
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()
        doc = "This repository contains a codebase analyzed with GraphiX.\n\n"
        for node in callgraph["nodes"]:
            doc += f"Function: {node['id']}\n"
            doc += f"**Description**: {node['metadata'].get('docstring', 'No description available.')}\n"
            doc += "**Parameters**: None\n"
            doc += "**Returns**: None\n"
            doc += f"**Complexity**: {node['complexity']}\n\n"
        doc += "\n"
        doc += f"Total Functions: {len(callgraph['nodes'])}\n"
        doc += f"Total Function Calls: {len(callgraph['links'])}\n"
        for node in callgraph["nodes"]:
            if node["complexity"] > 7:
                doc += f"- The {node['id']} function has high complexity ({node['complexity']}). Consider refactoring.\n"
        return {"documentation": doc}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate documentation: {str(e)}",
        )


@router.post("/refactoring")
async def generate_refactoring(
    request: AnalyzeRequest, current_user: User = Depends(get_current_user)
):
    try:
        generator = CallgraphGenerator()
        repo_path = await generator.clone_repository(
            str(request.repo_url), current_user.access_token
        )
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()
        suggestions = []
        for node in callgraph["nodes"]:
            if node["complexity"] > 5:
                prompt = (
                    f"Refactor this function with complexity {node['complexity']}:\n"
                    f"Function: {node['id']}\n"
                    f"File: {node['file']}\n"
                    "Provide before and after code snippets."
                )
                response = pro_model.generate_content(
                    prompt,
                    generation_config=genai.types.GenerationConfig(
                        max_output_tokens=300
                    ),
                )
                response_text = response.text
                suggestions.append(
                    {
                        "id": f"REF-{node['id'].replace('.', '-')}",
                        "title": f"Refactor {node['id'].split('.')[-1]}",
                        "description": response_text.split(".")[0] + ".",
                        "severity": "high" if node["complexity"] > 7 else "medium",
                        "location": f"{node['file']}:{node['metadata'].get('lineno', 1)}",
                        "before": (
                            response_text.split("After:")[0].split("Before:")[1].strip()
                            if "Before:" in response_text
                            else "N/A"
                        ),
                        "after": (
                            response_text.split("After:")[1].strip()
                            if "After:" in response_text
                            else "N/A"
                        ),
                    }
                )
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate refactoring suggestions: {str(e)}",
        )


def _enrich_django(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "views." in node["id"]:
            node["framework"] = "django"
            node["type"] = "view"
            if node["id"].endswith("View"):
                node["tags"] = ["class-based-view"]
            elif "api_" in node["id"]:
                node["tags"] = ["api-view"]
    return callgraph


def _enrich_flask(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "routes." in node["id"] or "blueprints." in node["id"]:
            node["framework"] = "flask"
            node["type"] = "route"
            if "get_" in node["id"]:
                node["tags"] = ["http-get"]
            elif "post_" in node["id"]:
                node["tags"] = ["http-post"]
    return callgraph


def _calculate_metric(callgraph: dict, metric: str) -> float:
    if metric == "complexity":
        return (
            (
                sum(node["complexity"] for node in callgraph["nodes"])
                / len(callgraph["nodes"])
            )
            if callgraph["nodes"]
            else 0
        )
    elif metric == "coupling":
        return (
            (len(callgraph["links"]) / len(callgraph["nodes"]))
            if callgraph["nodes"]
            else 0
        )
    elif metric == "cohesion":
        return 1.0
    return 0.0
