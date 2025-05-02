from datetime import datetime, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, List
from pydantic import HttpUrl, BaseModel
from sqlalchemy import JSON, Column, DateTime, Float, Integer, String
from ..services.callgraph import CallgraphGenerator
from ..models.base import Base, oauth2_scheme, Settings, get_db
from ..models.user import User
from jose import JWTError, jwt
from sqlalchemy.orm import Session
import time
from transformers import pipeline, AutoModelForSeq2SeqLM, AutoTokenizer
import logging

router = APIRouter(prefix="/analysis")
settings = Settings()
logger = logging.getLogger(__name__)

# Load the CodeT5 model at startup to avoid reloading for each request
try:
    checkpoint = "Salesforce/codet5-base"
    tokenizer = AutoTokenizer.from_pretrained(checkpoint)
    model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint)
    llm_pipeline = pipeline(
        "text2text-generation",
        model=model,
        tokenizer=tokenizer,
        device=-1,  # CPU
    )
    logger.info(f"Successfully loaded model for LLM: {checkpoint}")
except Exception as e:
    logger.error(f"Failed to load model {checkpoint}: {str(e)}")
    raise Exception(f"Model loading failed: {str(e)}")

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

async def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
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
        repo_path = await generator.clone_repository(str(request.repo_url), current_user.access_token)
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
    framework: Optional[str] = Query(None, description="Framework to detect (django, flask, fastapi)"),
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
    dataset = [{"repo_url": r.repo_url, "callgraph": r.callgraph, "runtime": r.runtime, "created_at": r.created_at.isoformat()} for r in results]
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
        # Simulate fetching repositories (replace with actual GitHub API call in production)
        repo_urls = [f"https://github.com/{i}" for i in range(request.repo_count)]  # Placeholder
        for url in repo_urls:
            repo_path = await generator.clone_repository(url, current_user.access_token)
            callgraph = await generator.analyze_repository(repo_path)
            dataset.append({
                "repo_url": url,
                "callgraph": callgraph,
                "metrics": {metric: _calculate_metric(callgraph, metric) for metric in request.metrics}
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
    request: dict,
    current_user: User = Depends(get_current_user)
):
    try:
        query = request.get("query")
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Query is required"
            )
        # Adjust prompt for CodeT5 (encoder-decoder model)
        prompt = f"Answer the following question: {query}"
        response = llm_pipeline(prompt, max_length=150)[0]['generated_text']
        return {"response": response}
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
        repo_path = await generator.clone_repository(str(request.repo_url), current_user.access_token)
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()

        doc = f"# Repository Documentation\n\n## Overview\nThis repository contains a codebase analyzed with GraphiX.\n\n## Functions\n"
        for node in callgraph['nodes']:
            doc += f"### {node['id'].split('.')[-1]}()\n"
            doc += f"**Description**: {node['metadata'].get('docstring', 'No description available.')}\n"
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
        repo_path = await generator.clone_repository(str(request.repo_url), current_user.access_token)
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()

        suggestions = []
        for node in callgraph['nodes']:
            if node['complexity'] > 5:
                # Adjust prompt for CodeT5
                prompt = f"Refactor this function with complexity {node['complexity']}:\nFunction: {node['id']}\nFile: {node['file']}\nProvide before and after code snippets."
                response = llm_pipeline(prompt, max_length=300)[0]['generated_text']
                suggestions.append({
                    "id": f"REF-{node['id'].replace('.', '-')}",
                    "title": f"Refactor {node['id'].split('.')[-1]}",
                    "description": response.split('.')[0] + '.',
                    "severity": "high" if node['complexity'] > 7 else "medium",
                    "location": f"{node['file']}:{node['metadata'].get('lineno', 1)}",
                    "before": response.split("After:")[0].split("Before:")[1] if "Before:" in response else "N/A",
                    "after": response.split("After:")[1] if "After:" in response else "N/A"
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
        return sum(node['complexity'] for node in callgraph['nodes']) / len(callgraph['nodes']) if callgraph['nodes'] else 0
    elif metric == "coupling":
        return len(callgraph['links']) / len(callgraph['nodes']) if callgraph['nodes'] else 0
    elif metric == "cohesion":
        return 1.0  # Placeholder, requires deeper analysis
    return 0.0