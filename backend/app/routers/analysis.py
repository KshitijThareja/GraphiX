from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, List
from pydantic import HttpUrl, BaseModel
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from ..services.callgraph import CallgraphGenerator
from ..models.base import Base, oauth2_scheme, settings, get_db
from ..models.user import User
from jose import JWTError, jwt
from sqlalchemy.orm import Session
import time
import google.generativeai as genai
import logging

router = APIRouter(prefix="/analysis")
logger = logging.getLogger(__name__)

# Configure Gemini API
GEMINI_API_KEY = settings.GEMINI_API_KEY
genai.configure(api_key=GEMINI_API_KEY)

# Initialize Gemini models
flash_model = genai.GenerativeModel("gemini-1.5-flash")
pro_model = genai.GenerativeModel("gemini-1.5-pro")


class AnalyzeRequest(BaseModel):
    repo_url: HttpUrl


class AnalysisResult(Base):
    __tablename__ = 'analysis_results'
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


async def get_current_user(token: str = Depends(oauth2_scheme),
                           db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token,
                             settings.SECRET_KEY,
                             algorithms=[settings.ALGORITHM])
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception

    user = db.query(User).filter(User.login == username).first()
    if user is None:
        raise credentials_exception
    return user


@router.post("/callgraph")
async def generate_callgraph(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    generator = CallgraphGenerator()
    try:
        start_time = time.time()
        repo_path = await generator.clone_repository(str(request.repo_url),
                                                     current_user.access_token)
        callgraph = await generator.analyze_repository(repo_path)
        runtime = time.time() - start_time

        analysis = AnalysisResult(
            repo_url=str(request.repo_url),
            callgraph=callgraph,
            runtime=runtime
        )
        db.add(analysis)
        db.commit()

        await generator.cleanup()
        return callgraph
    except Exception as e:
        await generator.cleanup()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate callgraph: {str(e)}"
        )


@router.post("/enrich")
async def enrich_callgraph(
    callgraph: dict,
    framework: Optional[str] = Query(
        None, description="Framework to detect (django, flask, fastapi)"
    ),
    current_user: User = Depends(get_current_user)
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
            detail=f"Failed to enrich callgraph: {str(e)}"
        )


@router.get("/dataset")
async def export_dataset(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    results = db.query(AnalysisResult).all()
    dataset = [{"repo_url": r.repo_url,
                "callgraph": r.callgraph,
                "runtime": r.runtime,
                "created_at": r.created_at.isoformat()} for r in results]
    return {"dataset": dataset}


@router.post("/dataset")
async def generate_dataset(
    request: DatasetRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    generator = CallgraphGenerator()
    dataset = []
    try:
        repo_urls = [
            f"https://github.com/{i}"
            for i in range(request.repo_count)
        ]
        for url in repo_urls:
            repo_path = await generator.clone_repository(
                url, current_user.access_token
            )
            callgraph = await generator.analyze_repository(repo_path)
            dataset.append({
                "repo_url": url,
                "callgraph": callgraph,
                "metrics": {metric: _calculate_metric(callgraph, metric)
                            for metric in request.metrics}
            })
            await generator.cleanup()

        return {"dataset": dataset}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate dataset: {str(e)}"
        )


@router.post("/benchmark")
async def benchmark(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    try:
        start_time = time.time()
        await generate_callgraph(request, current_user=current_user, db=db)
        runtime = time.time() - start_time
        return {"runtime": runtime, "tool": "GraphiX"}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to benchmark: {str(e)}"
        )


@router.post("/chat")
async def chat_with_llm(
    request: ChatRequest,
    current_user: User = Depends(get_current_user)
):
    try:
        query = request.query
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query is required"
            )

        context = "No codebase context provided."
        if request.repo_url:
            generator = CallgraphGenerator()
            try:
                repo_path = await generator.clone_repository(
                    str(request.repo_url),
                    current_user.access_token
                )
                callgraph = await generator.analyze_repository(repo_path)
                await generator.cleanup()

                context = "Codebase Context:\n"
                for node in callgraph['nodes']:
                    func_name = node['id'].split('.')[-1]
                    docstring = node['metadata'].get('docstring',
                                                     'No docstring available.')
                    complexity = node['complexity']
                    context += (f"- Function: {func_name}\n"
                                f"  Docstring: {docstring}\n"
                                f"  Complexity: {complexity}\n")
            except Exception as e:
                logger.error("Failed to analyze repository for context: "
                             f"{str(e)}")
                context = f"Failed to analyze repository: {str(e)}"
        prompt = (
                f"Given the following codebase context:\n{context}\n\n"
                f"Answer the following question about the codebase:\n{query}"
        )
        response = flash_model.generate_content(
            prompt,
            generation_config=genai.types.GenerationConfig(
                max_output_tokens=150
            )
        )
        return {"response": response.text}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process chat query: {str(e)}"
        )


@router.post("/documentation")
async def generate_documentation(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user)
):
    try:
        generator = CallgraphGenerator()
        repo_path = await generator.clone_repository(str(request.repo_url),
                                                     current_user.access_token)
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()

        doc = ("# Repository Documentation\n\n"
               "## Overview\n"
               "This repository contains a codebase analyzed with GraphiX.\n\n"
               "## Functions\n")
        for node in callgraph['nodes']:
            doc += f"### {node['id'].split('.')[-1]}()\n"
            doc += (f"**Description**: "
                    f"{node['metadata'].get('docstring',
                                            'No description available.')}\n")
            doc += "**Parameters**: None\n"
            doc += "**Returns**: None\n"
            doc += f"**Complexity**: {node['complexity']}\n\n"

        doc += "## Architecture\nThe application structure is derived from the callgraph.\n\n## Recommendations\n"
        for node in callgraph['nodes']:
            if node['complexity'] > 7:
                doc += f"- The {node['id']} function has high complexity ({node['complexity']}). Consider refactoring.\n"
        return {"documentation": doc}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate documentation: {str(e)}"
        )


@router.post("/refactoring")
async def generate_refactoring(
    request: AnalyzeRequest,
    current_user: User = Depends(get_current_user)
):
    try:
        generator = CallgraphGenerator()
        repo_path = await generator.clone_repository(str(request.repo_url),
                                                     current_user.access_token)
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()

        suggestions = []
        for node in callgraph['nodes']:
            if node['complexity'] > 5:
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
                    )
                )
                response_text = response.text
                suggestions.append({
                    "id": f"REF-{node['id'].replace('.', '-')}",
                    "title": f"Refactor {node['id'].split('.')[-1]}",
                    "description": response_text.split('.')[0] + '.',
                    "severity": "high" if node['complexity'] > 7 else "medium",
                    "location": f"{node['file']}:{node['metadata'].get('lineno', 1)}",
                    "before": (response_text.split("After:")[0].split("Before:")[1].strip()
                               if "Before:" in response_text else "N/A"),
                    "after": (response_text.split("After:")[1].strip()
                              if "After:" in response_text else "N/A")
                })
        return {"suggestions": suggestions}
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate refactoring suggestions: {str(e)}"
        )


def _enrich_django(callgraph: dict) -> dict:
    for node in callgraph['nodes']:
        if 'views.' in node['id']:
            node['framework'] = 'django'
            node['type'] = 'view'
            if node['id'].endswith('View'):
                node['tags'] = ['class-based-view']
            elif 'api_' in node['id']:
                node['tags'] = ['api-view']
    return callgraph


def _enrich_flask(callgraph: dict) -> dict:
    for node in callgraph['nodes']:
        if 'routes.' in node['id'] or 'blueprints.' in node['id']:
            node['framework'] = 'flask'
            node['type'] = 'route'
            if 'get_' in node['id']:
                node['tags'] = ['http-get']
            elif 'post_' in node['id']:
                node['tags'] = ['http-post']
    return callgraph


def _calculate_metric(callgraph: dict, metric: str) -> float:
    if metric == "complexity":
        return (sum(node['complexity'] for node in callgraph['nodes']) /
                len(callgraph['nodes'])) if callgraph['nodes'] else 0
    elif metric == "coupling":
        return (len(callgraph['links']) /
                len(callgraph['nodes'])) if callgraph['nodes'] else 0
    elif metric == "cohesion":
        return 1.0
    return 0.0
    return 0.0
