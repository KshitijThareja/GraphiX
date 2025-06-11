# ==============================\n# Filename: db\dependencies.py\n# ==============================\n\nfrom sqlalchemy.orm import Session
from ..models.base import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
\n\n# ==============================\n# Filename: db\init_db.py\n# ==============================\n\nfrom ..models.base import Base, engine


def init_db():
    print("Creating database tables...")
    Base.metadata.create_all(bind=engine)
    print("Database tables created!")


if __name__ == "__main__":
    init_db()
\n\n# ==============================\n# Filename: main.py\n# ==============================\n\nimport os
import logging
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2AuthorizationCodeBearer
from .models.base import Base, engine, settings, get_db
from .routers import auth, analysis, documentation, chat
from sqlalchemy.orm import Session
from jose import JWTError, jwt
from .models.user import User

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
Base.metadata.create_all(bind=engine)
app = FastAPI(
    title="GraphiX API",
    description="GitHub Codebase Evaluation Tool with Callgraphs and LLMs",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl=f"{settings.GITHUB_CLIENT_ID}",
    tokenUrl="token",
    scopes={"repo": "Access repositories", "user:email": "Get user email"},
)
app.include_router(auth.router)
app.include_router(analysis.router)
app.include_router(documentation.router)
app.include_router(chat.router)


@app.on_event("startup")
async def startup_event():
    try:
        engine.connect()
        logger.info("✅ Database connection established")
        
        # Initialize vector store directory if configured
        if settings.VECTOR_STORE_DIR:
            os.makedirs(settings.VECTOR_STORE_DIR, exist_ok=True)
            logger.info(f"✅ Vector store directory initialized: {settings.VECTOR_STORE_DIR}")
            
        # Log LLM provider configuration
        if settings.OPENAI_API_KEY:
            logger.info("✅ OpenAI API key configured")
        if settings.ANTHROPIC_API_KEY:
            logger.info("✅ Anthropic API key configured")
        if settings.GEMINI_API_KEY:
            logger.info("✅ Gemini API key configured")
            
        logger.info(f"✅ Default LLM provider: {settings.DEFAULT_LLM_PROVIDER}")
    except Exception as e:
        logger.error(f"Failed to connect to database: {str(e)}")
        raise RuntimeError("Failed to connect to database")


@app.on_event("shutdown")
async def shutdown_event():
    engine.dispose()
    logger.info("❌ Database connection closed")


@app.get("/")
async def root():
    return {
        "message": "GraphiX API is running",
        "version": app.version,
        "environment": os.getenv("ENVIRONMENT", "development"),
    }


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.login == username).first()
    if user is None:
        raise credentials_exception
    return user


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        workers=1,
        timeout_keep_alive=120,
    )
\n\n# ==============================\n# Filename: models\analysis.py\n# ==============================\n\nfrom fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional
from ..services.callgraph import CallgraphGenerator
from ..models.base import oauth2_scheme, Settings
from pydantic import HttpUrl
from jose import JWTError, jwt

router = APIRouter(prefix="/analysis")
settings = Settings()


from ..services.callgraph_enrichment_service import enrich_django, enrich_flask

async def get_current_user(token: str = Depends(oauth2_scheme)):
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
        return username
    except JWTError:
        raise credentials_exception


@router.post("/callgraph")
async def generate_callgraph(
    repo_url: HttpUrl,
    token: str = Depends(oauth2_scheme),
    current_user: str = Depends(get_current_user),
):
    generator = CallgraphGenerator()
    try:
        repo_path = await generator.clone_repository(str(repo_url), token)
        callgraph = await generator.analyze_repository(repo_path)
        await generator.cleanup()
        return callgraph
    except Exception as e:
        await generator.cleanup()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate callgraph: {str(e)}",
        )


@router.post("/enrich")
async def enrich_callgraph(
    callgraph: dict,
    framework: Optional[str] = Query(
        None, description="Framework to detect (django, flask, fastapi)"
    ),
    current_user: str = Depends(get_current_user),
):
    try:
        if framework == "django":
            return enrich_django(callgraph)
        elif framework == "flask":
            return enrich_flask(callgraph)
        return callgraph
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to enrich callgraph: {str(e)}",
        )
\n\n# ==============================\n# Filename: models\base.py\n# ==============================\n\nfrom sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import Optional
from fastapi.security import OAuth2AuthorizationCodeBearer
from pathlib import Path

env_path = Path(__file__).parent.parent.parent / ".env"


class Settings(BaseSettings):
    DATABASE_URL: str = Field(
        default="sqlite:///./graphix.db",
        description="Database connection URL (SQLite or PostgreSQL)",
    )
    GITHUB_CLIENT_ID: Optional[str] = Field(None, description="GitHub OAuth Client ID")
    GITHUB_CLIENT_SECRET: Optional[str] = Field(
        None, description="GitHub OAuth Client Secret"
    )
    SECRET_KEY: str = Field(
        default="dev-secret-key-change-me-in-prod",
        description="Secret key for JWT token signing",
    )
    ALGORITHM: str = Field(default="HS256", description="JWT signing algorithm")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = Field(
        default=60 * 24 * 7, description="JWT token expiration time in minutes"
    )
    OAUTH2_REDIRECT_URI: str = Field(
        default="http://localhost:3000/api/auth/callback/github",
        description="OAuth2 redirect URI",
    )
    GEMINI_API_KEY: str = Field(None, description="Gemini API key")
    
    # LLM Provider settings
    OPENAI_API_KEY: Optional[str] = Field(None, description="OpenAI API key")
    OPENAI_MODEL: Optional[str] = Field("gpt-3.5-turbo", description="Default OpenAI model")
    ANTHROPIC_API_KEY: Optional[str] = Field(None, description="Anthropic API key")
    ANTHROPIC_MODEL: Optional[str] = Field("claude-3-sonnet-20240229", description="Default Anthropic model")
    DEFAULT_LLM_PROVIDER: Optional[str] = Field("openai", description="Default LLM provider to use")
    
    # Vector store settings
    VECTOR_STORE_DIR: Optional[str] = Field(None, description="Directory to store vector embeddings")
    VECTOR_STORE_PROVIDER: Optional[str] = Field("chroma", description="Vector store provider")

    class Config:
        env_file = env_path if env_path.exists() else None
        env_file_encoding = "utf-8"
        extra = "allow"


settings = Settings()
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://github.com/login/oauth/authorize",
    tokenUrl="token",
    scopes={"repo": "Access repositories", "user:email": "Get user email"},
)
if "sqlite" in settings.DATABASE_URL.lower():
    engine = create_engine(
        settings.DATABASE_URL,
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )
else:
    engine = create_engine(
        settings.DATABASE_URL, pool_pre_ping=True, pool_size=20, max_overflow=30
    )
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


Base.metadata.create_all(bind=engine)
\n\n# ==============================\n# Filename: models\callgraph.py\n# ==============================\n\nfrom typing import Dict, List, Optional, Any
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
\n\n# ==============================\n# Filename: models\chat.py\n# ==============================\n\nfrom typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field
import datetime
from uuid import UUID, uuid4

class ChatMessage(BaseModel):
    """Model for a chat message"""
    role: str = Field(..., description="Role of the message sender ('user', 'assistant', 'system')")
    content: str = Field(..., description="Content of the message")
    timestamp: datetime.datetime = Field(default_factory=datetime.datetime.now, description="When the message was sent")

class ChatMessageCreate(BaseModel):
    """Model for creating a new chat message"""
    content: str = Field(..., description="Content of the message")
    highlighted_code: Optional[str] = Field(None, description="Optional highlighted code snippet")
    code_elements: Optional[List[Dict[str, Any]]] = Field(None, description="Optional code elements in focus")

class ChatSessionCreate(BaseModel):
    """Model for creating a new chat session"""
    repository_id: Optional[str] = Field(None, description="ID of the repository for this chat")
    callgraph_id: Optional[str] = Field(None, description="ID of the callgraph analysis for context")
    initial_message: Optional[str] = Field(None, description="Optional initial message to start the conversation")

class ChatSessionResponse(BaseModel):
    """Response model for a chat session"""
    session_id: str = Field(..., description="Unique ID for the chat session")
    repository_id: Optional[str] = Field(None, description="ID of the repository for this chat")
    messages_count: int = Field(0, description="Number of messages in the session")
    created_at: datetime.datetime = Field(..., description="When the session was created")
    last_active: datetime.datetime = Field(..., description="When the session was last active")

class ChatResponse(BaseModel):
    """Response model for a chat message"""
    response: str = Field(..., description="Response text from the assistant")
    session_id: str = Field(..., description="ID of the chat session")
    context_used: List[str] = Field(default_factory=list, description="Types of context used for the response")
    model: str = Field(..., description="Model used for the response")
    usage: Dict[str, Any] = Field(default_factory=dict, description="Token usage information")

class ChatHistoryResponse(BaseModel):
    """Response model for chat history"""
    session_id: str = Field(..., description="ID of the chat session")
    repository_id: Optional[str] = Field(None, description="ID of the repository for this chat")
    messages: List[ChatMessage] = Field(default_factory=list, description="List of messages in the session")
    created_at: datetime.datetime = Field(..., description="When the session was created")
    last_active: datetime.datetime = Field(..., description="When the session was last active")
\n\n# ==============================\n# Filename: models\documentation.py\n# ==============================\n\nfrom typing import Dict, List, Optional, Any, Union, Set
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
\n\n# ==============================\n# Filename: models\embeddings.py\n# ==============================\n\nfrom typing import Dict, List, Optional, Any, Union
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
\n\n# ==============================\n# Filename: models\mongo_models.py\n# ==============================\n\nfrom pydantic import BaseModel, Field
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
    content: Dict[str, Any] = Field(..., description="The actual documentation content, mapping qualified names to documentation elements")\n\n# ==============================\n# Filename: models\user.py\n# ==============================\n\nfrom sqlalchemy import Column, Integer, String, Boolean
from ..models.base import Base


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    github_id = Column(Integer, unique=True, index=True)
    login = Column(String, unique=True, index=True)
    name = Column(String)
    email = Column(String)
    avatar_url = Column(String)
    access_token = Column(String)
    is_active = Column(Boolean, default=True)
\n\n# ==============================\n# Filename: routers\analysis.py\n# ==============================\n\nfrom datetime import datetime, timezone
import uuid
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
from ..services.documentation_service import DocumentationService
from ..models.user import User
from ..services.auth import get_current_user
from ..models.base import Base, oauth2_scheme, settings, get_db
import traceback
import google.generativeai as genai
import shutil

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
    callgraph_data: Optional[dict] = None
    documentation_data: Optional[dict] = None


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
    background_tasks: BackgroundTasks = None,
):
    status_log = []
    status_log.append(f"Received request for {request_model.repo_url}")

    try:
        start_time = time.time()
        repo_url = str(request_model.repo_url)
        is_remote = not os.path.exists(repo_url)
        # Use the normalize_repository_id function for consistent repository ID generation
        from ..utils.repository import normalize_repository_id
        repository_id = normalize_repository_id(repo_url)
        
        # Determine the type of generator to use
        if request_model.research_grade:
            logger.info(f"Using research-grade callgraph generator for {repo_url}")
            generator = ResearchCallgraphGenerator(framework=request_model.framework_hint)
        elif request_model.advanced_analysis or request_model.advancedAnalysis:
            logger.info(f"Using enhanced callgraph generator for {repo_url}")
            generator = EnhancedCallgraphGenerator()
        else:
            logger.info(f"Using standard callgraph generator for {repo_url}")
            generator = CallgraphGenerator()

        # Generate callgraph
        # The generator's analyze_repository now handles cloning internally
        callgraph = await generator.analyze_repository(
            repo_path=repo_url, timeout=600
        )

        # Store the result in the database
        result = AnalysisResult(
            repo_url=repo_url,
            callgraph=callgraph,
            runtime=time.time() - start_time,
        )
        db.add(result)
        db.commit()
        
        # Store in chat service cache for future sessions
        from ..routers.chat import callgraph_cache
        callgraph_id = str(result.id) if result.id else str(time.time())
        callgraph_cache[callgraph_id] = callgraph
        callgraph_cache[repo_url] = callgraph
        
        # Auto-generate documentation (this needs to happen in the same request to ensure
        # the documentation is available immediately after callgraph generation)
        from ..services.documentation_service import DocumentationService
        from ..routers.documentation import documentation_store
        
        # Create documentation ID
        documentation_id = str(uuid.uuid4())
        
        # Store initial response in documentation store
        documentation_store[documentation_id] = {
            "documentation_id": documentation_id,
            "repository_id": repository_id,
            "status": "processing",
            "generated_at": datetime.now().isoformat(),
            "modules_count": 0,
            "classes_count": 0,
            "functions_count": 0
        }
        
        # Create documentation service and analyze asynchronously
        documentation_service = DocumentationService(framework_hint=request_model.framework_hint)
        
        # Add documentation generation to background tasks if available
        if background_tasks:
            logger.info(f"Scheduling documentation generation for {repo_url}")
            background_tasks.add_task(
                _generate_documentation_background,
                documentation_id,
                repository_id,
                repo_url,
                callgraph,
                request_model.framework_hint,
                generator.temp_repo_path # Pass the temporary path for cleanup
            )
        else:
            # If no background_tasks available, start a task directly
            logger.info(f"Starting documentation generation for {repo_url}")
            asyncio.create_task(
                _generate_documentation_background(
                    documentation_id,
                    repository_id,
                    repo_url,
                    callgraph,
                    request_model.framework_hint,
                    generator.temp_repo_path # Pass the temporary path for cleanup
                )
            )
        
        # Rest of the function remains the same
        status_log = []
        if not flash_model or not pro_model:
            error_detail = "Gemini API is not properly configured"
            logger.error(f"/callgraph endpoint error: {error_detail}")
            return JSONResponse(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                content={
                    "status": "error",
                    "message": error_detail,
                    "data": None,
                    "status_log": status_log,
                },
            )
        advanced_analysis = (
            request_model.advanced_analysis or request_model.advancedAnalysis
        )
        research_grade = request_model.research_grade
        context_sensitivity = request_model.context_sensitivity
        framework_hint = request_model.framework_hint
        status_log.append(f"Received request for {request_model.repo_url}")
        if research_grade:
            status_log.append(
                f"Initializing research-grade analysis with hint: {framework_hint}"
            )
            status_log.append(
                f"Using research-grade generator (actual context sensitivity determined by builder)"
            )
        elif advanced_analysis:
            status_log.append("Initializing enhanced analysis.")
        else:
            status_log.append("Initializing standard analysis.")
            logger.info(
                f"Using standard callgraph generator for {request_model.repo_url}"
            )
        start_time = time.time()
        status_log.append("Starting repository analysis...")
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
            "documentation_id": documentation_id  # <-- CRUCIAL: Ensure this line is here
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
        # Cleanup is now handled by the background task
        status_log.append("Initial request processing complete. Documentation generation and cleanup in background.")

from ..services.callgraph_enrichment_service import enrich_django, enrich_flask

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
            return enrich_django(callgraph)
        elif framework == "flask":
            return enrich_flask(callgraph)
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
    request: ChatRequest, context:Context, current_user: User = Depends(get_current_user)
):
    try:
        query = request.query
        if not query:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail="Query is required"
            )
        context = Context
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


async def _generate_documentation_background(
    documentation_id: str,
    repository_id: str,
    repo_url: str,
    callgraph: dict = None,
    framework_hint: str = "generic",
    temp_repo_path: Optional[str] = None # Add temp_repo_path for cleanup
):
    """
    Background task to generate documentation based on callgraph data.
    This function should be called either as a background task or as a new task.
    """
    from ..routers.documentation import documentation_store
    from ..services.documentation_service import DocumentationService
    
    try:
        logger.info(f"Starting documentation generation for {repo_url}")
        documentation_service = DocumentationService(
            framework_hint=framework_hint, 
            repository_id=repository_id # Ensure this is passed
        )
        # Use the callgraph data if provided, otherwise analyze the repository
        if callgraph:
            logger.info("Using existing callgraph data for documentation")
            # Extract documentation from callgraph
            if "metadata" not in callgraph:
                callgraph["metadata"] = {}
            if "repository_id" not in callgraph["metadata"]:
                callgraph["metadata"]["repository_id"] = repository_id

            documentation_result = await documentation_service.generate_from_callgraph(
                callgraph_result=callgraph
            )
        # If callgraph generation failed, documentation_result will be None or an error.
        # The direct documentation generation from repo_path by DocumentationService was removed.
        # We now rely on generate_from_callgraph which uses in-memory data.
        
        # Count the elements by type
        modules_count = len(documentation_result.get("modules", []))
        classes_count = len(documentation_result.get("classes", []))
        functions_count = len(documentation_result.get("functions", []))
        
        # Update documentation store with results
        if documentation_id in documentation_store:
            documentation_store[documentation_id].update({
                "status": "completed",
                "documentation": documentation_result,
                "modules_count": modules_count,
                "classes_count": classes_count,
                "functions_count": functions_count,
                "repository_url": repo_url,
                "repository_id": repository_id,  # Make sure repository_id is included
                "framework": framework_hint,
                "completed_at": datetime.now().isoformat()
            })
            
            # Generate markdown documentation
            try:
                markdown_doc = await documentation_service.generate_markdown_documentation(documentation_result)
                documentation_store[documentation_id]["markdown_files"] = {"README.md": markdown_doc}
                
                # Add a summary for frontend display
                modules_count = len(documentation_result.get("modules", []))
                classes_count = len(documentation_result.get("classes", []))
                functions_count = len(documentation_result.get("functions", []))
                
                documentation_store[documentation_id]["summary"] = {
                    "modules": modules_count,
                    "classes": classes_count,
                    "functions": functions_count,
                    "framework": callgraph.get("metadata", {}).get("framework_analyzed_as", framework_hint)
                }
                
                # Ensure the documentation is marked as available
                documentation_store[documentation_id]["has_documentation"] = True
            except Exception as e:
                logger.error(f"Error generating markdown documentation: {str(e)}")
                documentation_store[documentation_id]["markdown_files"] = {"README.md": f"# Documentation Generation Error\n\nThere was an error generating detailed documentation: {str(e)}\n\nHowever, basic documentation data is available."}
                documentation_store[documentation_id]["has_documentation"] = True
            
            logger.info(f"Documentation generation completed for {repo_url}")
        else:
            logger.warning(f"Documentation ID {documentation_id} not found in store")
    
    except Exception as e:
        logger.error(f"Error generating documentation: {str(e)}\n{traceback.format_exc()}")
        if documentation_id in documentation_store:
            documentation_store[documentation_id].update({
                "status": "failed",
                "error": str(e)
            })
    finally:
        if temp_repo_path and os.path.exists(temp_repo_path):
            logger.info(f"Background task cleaning up temporary directory: {temp_repo_path}")
            try:
                shutil.rmtree(temp_repo_path)
            except Exception as e_cleanup:
                logger.error(f"Error during background cleanup of {temp_repo_path}: {e_cleanup}")



@router.post("/documentation")
async def generate_documentation(
    request: AnalyzeRequest, 
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = None
):
    try:
        repo_url = str(request.repo_url)
        # Use the normalize_repository_id function for consistent repository ID generation
        from ..utils.repository import normalize_repository_id
        repository_id = normalize_repository_id(repo_url)
        is_remote = not os.path.exists(repo_url)
        
        # Create documentation ID
        documentation_id = str(uuid.uuid4())
        
        # Store initial response in documentation store
        from ..routers.documentation import documentation_store
        documentation_store[documentation_id] = {
            "documentation_id": documentation_id,
            "repository_id": repository_id,
            "status": "processing",
            "generated_at": datetime.now().isoformat(),
            "modules_count": 0,
            "classes_count": 0,
            "functions_count": 0
        }
        
        # Start documentation generation in background
        if background_tasks:
            background_tasks.add_task(
                _generate_documentation_background,
                documentation_id,
                repository_id,
                repo_url,
                is_remote,
                None,  # No callgraph, will generate as needed
                request.framework_hint,
                None # No temp_repo_path for this path, as callgraph is not generated here
            )
        else:
            # If no background_tasks available, start a task directly
            asyncio.create_task(
                _generate_documentation_background(
                    documentation_id,
                    repository_id,
                    repo_url,
                    is_remote,
                    None,  # No callgraph, will generate as needed
                request.framework_hint,
                None # No temp_repo_path for this path, as callgraph is not generated here
                )
            )
        
        return {
            "documentation_id": documentation_id,
            "repository_id": repository_id,
            "status": "processing",
            "message": "Documentation generation started"
        }
    except Exception as e:
        logger.error(f"Error initiating documentation generation: {str(e)}")
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


@router.get("/callgraph/status")
async def get_callgraph_status(
    repo_url: str
):
    """
    Check the status of a callgraph analysis for a repository.
    This endpoint is used by the frontend to poll for completion of analysis.
    """
    try:
        logger.info(f"Checking status for repository: {repo_url}")
        
        # Check if documentation has been generated for this repository
        # We'll check the documentation_store in the documentation router
        # Since we don't have direct DB access here, we'll use the database check below
        
        # Check if there's a completed callgraph without documentation
        # This would indicate the analysis is done but documentation generation is not
        db = next(get_db())
        analysis_result = db.query(AnalysisResult).filter(
            AnalysisResult.repo_url == repo_url
        ).order_by(AnalysisResult.created_at.desc()).first()
        
        if analysis_result:
            # If we have callgraph data, consider the analysis complete
            logger.info(f"Found callgraph for {repo_url}, analysis is complete")
            return {
                "status": "completed",
                "message": "Analysis is complete, data is available",
                "callgraph_id": analysis_result.id
            }
        
        # Check if there's an ongoing analysis
        # This is a simplified check - you might want to implement a proper
        # tracking system for in-progress analyses
        # For now, we'll just assume it's processing if we didn't find completed results
        
        logger.info(f"No completed analysis found for {repo_url}")
        return {
            "status": "not_found",
            "message": "No completed analysis found for this repository."
        }
        
    except Exception as e:
        logger.error(f"Error checking callgraph status: {str(e)}\n{traceback.format_exc()}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check analysis status: {str(e)}"
        )
\n\n# ==============================\n# Filename: routers\auth.py\n# ==============================\n\nfrom fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2AuthorizationCodeBearer
from jose import jwt
from pydantic import BaseModel
import httpx
from ..models.base import settings, get_db
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy.orm import Session
from ..models.user import User

router = APIRouter(prefix="/auth")
oauth2_scheme = OAuth2AuthorizationCodeBearer(
    authorizationUrl="https://github.com/login/oauth/authorize",
    tokenUrl="https://github.com/login/oauth/access_token",
    scopes={"repo": "Access repositories", "user:email": "Get user email"},
)


class Token(BaseModel):
    access_token: str
    token_type: str
    expires_in: int


class GitHubUser(BaseModel):
    id: int
    login: str
    name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None
    access_token: str


class UserResponse(BaseModel):
    login: str
    name: Optional[str]
    email: Optional[str]
    avatar_url: Optional[str]


GITHUB_CLIENT_ID = settings.GITHUB_CLIENT_ID
GITHUB_CLIENT_SECRET = settings.GITHUB_CLIENT_SECRET
OAUTH2_REDIRECT_URI = settings.OAUTH2_REDIRECT_URI
SECRET_KEY = settings.SECRET_KEY
ALGORITHM = settings.ALGORITHM
ACCESS_TOKEN_EXPIRE_MINUTES = 30


async def get_github_access_token(code: str) -> str:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            "https://github.com/login/oauth/access_token",
            headers={"Accept": "application/json"},
            data={
                "client_id": GITHUB_CLIENT_ID,
                "client_secret": GITHUB_CLIENT_SECRET,
                "code": code,
                "redirect_uri": OAUTH2_REDIRECT_URI,
            },
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get access token from GitHub",
            )
        return response.json().get("access_token")


async def get_github_user(access_token: str) -> GitHubUser:
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.github.com/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/json",
            },
        )
        if response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to get user info from GitHub",
            )
        user_data = response.json()
        return GitHubUser(
            id=user_data.get("id"),
            login=user_data.get("login"),
            name=user_data.get("name"),
            email=user_data.get("email"),
            avatar_url=user_data.get("avatar_url"),
            access_token=access_token,
        )


def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.utcnow() + expires_delta
    else:
        expire = datetime.utcnow() + timedelta(minutes=15)
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt


@router.get("/login")
async def login_github():
    url = (
        f"https://github.com/login/oauth/authorize"
        f"?client_id={GITHUB_CLIENT_ID}"
        f"&redirect_uri={OAUTH2_REDIRECT_URI}"
        f"&scope=repo"
    )
    return {"url": url}


@router.get("/callback")
async def callback(code: str, db: Session = Depends(get_db)):
    try:
        if not code:
            raise HTTPException(
                status_code=400, detail="Authorization code not provided"
            )
        async with httpx.AsyncClient() as client:
            response = await client.post(
                "https://github.com/login/oauth/access_token",
                data={
                    "client_id": settings.GITHUB_CLIENT_ID,
                    "client_secret": settings.GITHUB_CLIENT_SECRET,
                    "code": code,
                    "redirect_uri": settings.OAUTH2_REDIRECT_URI,
                },
                headers={"Accept": "application/json"},
            )
        if response.status_code != 200 or "access_token" not in response.json():
            raise HTTPException(
                status_code=400, detail="Failed to obtain access token from GitHub"
            )
        access_token = response.json()["access_token"]
        async with httpx.AsyncClient() as client:
            user_response = await client.get(
                "https://api.github.com/user",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            if user_response.status_code != 200:
                raise HTTPException(status_code=400, detail="Failed to fetch user data")
            user_data = user_response.json()
            email_response = await client.get(
                "https://api.github.com/user/emails",
                headers={
                    "Authorization": f"Bearer {access_token}",
                    "Accept": "application/vnd.github.v3+json",
                },
            )
            email = None
            if email_response.status_code == 200:
                emails = email_response.json()
                primary_email = next(
                    (e["email"] for e in emails if e["primary"] and e["verified"]), None
                )
                email = primary_email or user_data.get("email")
        user = db.query(User).filter(User.login == user_data["login"]).first()
        if not user:
            user = User(
                login=user_data["login"],
                email=email,
                avatar_url=user_data.get("avatar_url"),
                access_token=access_token,
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        else:
            user.email = email
            user.avatar_url = user_data.get("avatar_url")
            user.access_token = access_token
            db.commit()
            db.refresh(user)
        token_data = {"sub": user.login}
        token = jwt.encode(
            token_data, settings.SECRET_KEY, algorithm=settings.ALGORITHM
        )
        return {
            "access_token": token,
            "user": {
                "login": user.login,
                "email": user.email,
                "avatar_url": user.avatar_url,
            },
        }
    except Exception as e:
        db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to process callback: {str(e)}",
        )
\n\n# ==============================\n# Filename: routers\chat.py\n# ==============================\n\nimport os
import logging
from typing import Dict, List, Optional, Any
import asyncio
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Query, Path, Body
from fastapi.responses import JSONResponse

from ..models.chat import (
    ChatSessionCreate,
    ChatSessionResponse,
    ChatMessageCreate,
    ChatResponse,
    ChatHistoryResponse,
    ChatMessage
)
from ..services.llm.chat_service import ChatService
from ..services.research_callgraph import ResearchCallgraphGenerator

router = APIRouter(
    prefix="/api/chat",
    tags=["chat"],
    responses={404: {"description": "Not found"}},
)

# In-memory callgraph cache (in production, this would be in a database)
callgraph_cache = {}

# Create a singleton chat service
chat_service = ChatService()

@router.post("/sessions", response_model=ChatSessionResponse)
async def create_chat_session(
    session_request: ChatSessionCreate
):
    """
    Create a new chat session.
    """
    # Get callgraph data if available
    callgraph_data = None
    if session_request.callgraph_id and session_request.callgraph_id in callgraph_cache:
        callgraph_data = callgraph_cache[session_request.callgraph_id]
    elif session_request.repository_id and session_request.repository_id in callgraph_cache:
        # Try using repository_id as fallback
        callgraph_data = callgraph_cache[session_request.repository_id]
    
    # Create a new session
    session = await chat_service.create_session(
        repository_id=session_request.repository_id,
        callgraph_data=callgraph_data
    )
    
    # Add initial message if provided
    if session_request.initial_message:
        await chat_service.process_message(
            session_id=session.session_id,
            message=session_request.initial_message
        )
    
    return ChatSessionResponse(
        session_id=session.session_id,
        repository_id=session.repository_id,
        messages_count=len(session.messages),
        created_at=session.created_at,
        last_active=session.last_active
    )

@router.get("/sessions", response_model=List[ChatSessionResponse])
async def list_chat_sessions(
    repository_id: Optional[str] = Query(None, description="Filter by repository ID")
):
    """
    List all chat sessions, optionally filtered by repository.
    """
    sessions = chat_service.list_sessions(repository_id=repository_id)
    
    return [
        ChatSessionResponse(
            session_id=session["session_id"],
            repository_id=session["repository_id"],
            messages_count=session["messages_count"],
            created_at=datetime.fromisoformat(session["created_at"]),
            last_active=datetime.fromisoformat(session["last_active"])
        )
        for session in sessions
    ]

@router.get("/sessions/{session_id}", response_model=ChatHistoryResponse)
async def get_chat_session(
    session_id: str = Path(..., description="The ID of the chat session"),
    limit: Optional[int] = Query(None, description="Limit the number of messages returned")
):
    """
    Get a chat session with its history.
    """
    session = chat_service.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    messages = session.get_messages(limit)
    
    return ChatHistoryResponse(
        session_id=session.session_id,
        repository_id=session.repository_id,
        messages=[
            ChatMessage(
                role=msg["role"],
                content=msg["content"],
                timestamp=datetime.fromisoformat(msg["timestamp"])
            )
            for msg in messages
        ],
        created_at=session.created_at,
        last_active=session.last_active
    )

@router.post("/sessions/{session_id}/messages", response_model=ChatResponse)
async def send_message(
    message: ChatMessageCreate,
    session_id: str = Path(..., description="The ID of the chat session")
):
    """
    Send a message to a chat session and get a response.
    """
    session = chat_service.get_session(session_id)
    
    if not session:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    response = await chat_service.process_message(
        session_id=session_id,
        message=message.content,
        code_elements=message.code_elements,
        highlighted_code=message.highlighted_code
    )
    
    if "error" in response:
        raise HTTPException(status_code=400, detail=response["error"])
    
    return ChatResponse(
        response=response["response"],
        session_id=session_id,
        context_used=response["context_used"],
        model=response["model"],
        usage=response["usage"]
    )

@router.delete("/sessions/{session_id}")
async def delete_chat_session(
    session_id: str = Path(..., description="The ID of the chat session")
):
    """
    Delete a chat session.
    """
    success = await chat_service.delete_session(session_id)
    
    if not success:
        raise HTTPException(status_code=404, detail="Chat session not found")
    
    return {"success": True, "message": "Chat session deleted"}

@router.post("/analyze-repository")
async def analyze_repository_for_chat(
    repository_url: str = Body(..., embed=True, description="URL of the repository to analyze"),
    framework_hint: Optional[str] = Body("generic", embed=True, description="Framework hint for analysis"),
    timeout: int = Body(600, embed=True, description="Timeout for analysis in seconds")
):
    """
    Analyze a repository to prepare for chat. This creates a callgraph for context.
    """
    try:
        # Create a research callgraph generator
        generator = ResearchCallgraphGenerator(framework=framework_hint)
        
        # Analyze the repository
        callgraph = await generator.analyze_repository(
            repo_path=repository_url,
            timeout=timeout,
            clone=True
        )
        
        # Generate a unique ID for this callgraph
        callgraph_id = str(uuid.uuid4())
        
        # Store the callgraph in cache
        callgraph_cache[callgraph_id] = callgraph
        
        # Also store by repository URL for convenience
        callgraph_cache[repository_url] = callgraph
        
        return {
            "callgraph_id": callgraph_id,
            "repository_url": repository_url,
            "framework": callgraph.get("metadata", {}).get("framework_analyzed_as", framework_hint),
            "nodes_count": len(callgraph.get("nodes", [])),
            "links_count": len(callgraph.get("links", [])),
            "status": "completed"
        }
        
    except Exception as e:
        logging.error(f"Error analyzing repository for chat: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error analyzing repository: {str(e)}")
\n\n# ==============================\n# Filename: routers\documentation.py\n# ==============================\n\nimport os
import logging
from typing import Dict, List, Optional, Any
import asyncio
import uuid
from fastapi import Depends, BackgroundTasks, Query, Path
from datetime import datetime

from fastapi import APIRouter, HTTPException
from ..services.documentation_service import DocumentationService
from ..services.codebase_data_service import CodebaseDataService

router = APIRouter(prefix="/documentation")

@router.get("/by-callgraph/{callgraph_id}")
async def get_docs_by_callgraph(callgraph_id: str):
    docs = await CodebaseDataService().get_documentation(callgraph_id)
    return docs if docs else {"status": "not_generated"}, HTTPException
from ..services.documentation_service import DocumentationService
from ..services.codebase_data_service import CodebaseDataService

router = APIRouter(prefix="/documentation")

@router.get("/{callgraph_id}")
async def get_documentation(callgraph_id: str):
    docs = await CodebaseDataService().get_documentation(callgraph_id)
    if not docs:
        raise HTTPException(status_code=404, detail="Documentation not found")
    return docs, Depends, HTTPException, BackgroundTasks, Query, Path
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
\n\n# ==============================\n# Filename: services\abstract_interpretation.py\n# ==============================\n\nimport ast
import logging
import os
from typing import Dict, Set, List, Tuple, Optional, Any, Union
from enum import Enum
import itertools
from contextlib import contextmanager


class AbstractValue:
    class ValueType(Enum):
        TOP = "⊤"
        INT = "Int"
        FLOAT = "Float"
        STR = "Str"
        BOOL = "Bool"
        LIST = "List"
        DICT = "Dict"
        SET = "Set"
        TUPLE = "Tuple"
        FUNCTION = "Function"
        CLASS = "Class"
        INSTANCE = "Instance"
        MODULE = "Module"
        NONE = "None"
        BOTTOM = "⊥"

    def __init__(
        self,
        value_type: ValueType = ValueType.TOP,
        concrete_values: Optional[Set[Any]] = None,
        origin: Optional[ast.AST] = None,
        is_tainted: bool = False,
    ):
        self.value_type = value_type
        self.concrete_values = concrete_values or set()
        self.origin = origin
        self.is_tainted = is_tainted

    def __str__(self) -> str:
        if self.concrete_values:
            return f"{self.value_type.value}: {self.concrete_values}"
        return self.value_type.value

    def __repr__(self) -> str:
        return self.__str__()

    def join(self, other: "AbstractValue") -> "AbstractValue":
        if self.value_type == AbstractValue.ValueType.BOTTOM:
            return other
        if other.value_type == AbstractValue.ValueType.BOTTOM:
            return self
        if (
            self.value_type == AbstractValue.ValueType.TOP
            or other.value_type == AbstractValue.ValueType.TOP
        ):
            return AbstractValue(AbstractValue.ValueType.TOP)
        if self.value_type == other.value_type:
            concrete_values = self.concrete_values.union(other.concrete_values)
            if len(concrete_values) > 10:
                concrete_values = set()
            return AbstractValue(
                self.value_type,
                concrete_values,
                self.origin or other.origin,
                self.is_tainted or other.is_tainted,
            )
        return AbstractValue(
            AbstractValue.ValueType.TOP,
            set(),
            None,
            self.is_tainted or other.is_tainted,
        )

    @staticmethod
    def from_literal(node: ast.AST) -> "AbstractValue":
        if isinstance(node, ast.Num):
            if isinstance(node.n, int):
                return AbstractValue(AbstractValue.ValueType.INT, {node.n}, node)
            else:
                return AbstractValue(AbstractValue.ValueType.FLOAT, {node.n}, node)
        elif isinstance(node, ast.Str):
            return AbstractValue(AbstractValue.ValueType.STR, {node.s}, node)
        elif isinstance(node, ast.NameConstant):
            if node.value is None:
                return AbstractValue(AbstractValue.ValueType.NONE, {None}, node)
            elif isinstance(node.value, bool):
                return AbstractValue(AbstractValue.ValueType.BOOL, {node.value}, node)
        elif isinstance(node, ast.List):
            return AbstractValue(AbstractValue.ValueType.LIST, set(), node)
        elif isinstance(node, ast.Dict):
            return AbstractValue(AbstractValue.ValueType.DICT, set(), node)
        elif isinstance(node, ast.Set):
            return AbstractValue(AbstractValue.ValueType.SET, set(), node)
        elif isinstance(node, ast.Tuple):
            return AbstractValue(AbstractValue.ValueType.TUPLE, set(), node)
        return AbstractValue(AbstractValue.ValueType.TOP, set(), node)


class AbstractState:
    def __init__(
        self,
        environment: Optional[Dict[str, AbstractValue]] = None,
        call_context: Optional[Tuple[str, ...]] = None,
        path_constraints: Optional[List[ast.AST]] = None,
    ):
        self.environment = environment or {}
        self.call_context = call_context or tuple()
        self.path_constraints = path_constraints or []

    def copy(self) -> "AbstractState":
        return AbstractState(
            environment={k: v for k, v in self.environment.items()},
            call_context=self.call_context,
            path_constraints=list(self.path_constraints),
        )

    def join(self, other: "AbstractState") -> "AbstractState":
        result = AbstractState(call_context=self.call_context)
        all_vars = set(self.environment.keys()).union(other.environment.keys())
        for var in all_vars:
            if var in self.environment and var in other.environment:
                result.environment[var] = self.environment[var].join(
                    other.environment[var]
                )
            elif var in self.environment:
                result.environment[var] = self.environment[var]
            else:
                result.environment[var] = other.environment[var]
        result.path_constraints = [
            c for c in self.path_constraints if c in other.path_constraints
        ]
        return result

    def assign(self, name: str, value: AbstractValue) -> None:
        self.environment[name] = value

    def lookup(self, name: str) -> AbstractValue:
        return self.environment.get(name, AbstractValue(AbstractValue.ValueType.TOP))

    def add_constraint(self, constraint: ast.AST) -> None:
        self.path_constraints.append(constraint)

    def extend_context(self, function_name: str, k: int) -> "AbstractState":
        new_state = self.copy()
        if k <= 0:
            new_state.call_context = tuple()
        else:
            new_ctx = self.call_context + (function_name,)
            if len(new_ctx) > k:
                new_ctx = new_ctx[-k:]
            new_state.call_context = new_ctx
        return new_state


class AbstractInterpreter:
    def __init__(self, max_depth: int = 15, k: int = 2):
        self.max_depth = max_depth
        self.k = k
        self.function_cache = {}
        self.callgraph = {}
        self.depth = 0
        self.scope_stack = []
        self.definitions = {}
        self.class_hierarchy = {}
        self.imported_modules = set()
        self.type_constraints = {}
        self.flow_sensitive_state = {
            "variables": {},
            "return_values": {},
            "yield_values": {},
            "exceptions": set(),
        }

    def analyze_module(self, node: ast.Module, filename: str):
        if self.depth > self.max_depth:
            logging.warning(f"Max depth {self.max_depth} reached in {filename}")
            return {}
        self.depth += 1
        module_name = os.path.splitext(os.path.basename(filename))[0]
        state = AbstractState()
        self.imported_modules.add(module_name)
        try:
            imports, other_nodes = self._extract_imports(node.body)
            for import_node in imports:
                self._analyze_import(import_node, state, filename)
            with self._enter_scope("module", module_name):
                self._analyze_statements(
                    other_nodes, state, filename, is_module_level=True
                )
                self._process_deferred_analysis()
        except Exception as e:
            logging.error(
                f"Error analyzing module {module_name}: {str(e)}", exc_info=True
            )
        self.depth -= 1
        return self.callgraph

    def _extract_imports(self, nodes):
        imports = []
        other = []
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(node)
            else:
                other.append(node)
        return imports, other

    def _analyze_import(self, node, state, filename):
        if isinstance(node, ast.Import):
            for name in node.names:
                module_name = name.name
                alias = name.asname or module_name.split(".")[-1]
                self.imported_modules.add(module_name)
                self.definitions[alias] = {
                    "type": "module",
                    "name": module_name,
                    "node": node,
                }
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in node.names:
                full_name = f"{module}.{name.name}" if module else name.name
                alias = name.asname or name.name
                self.definitions[alias] = {
                    "type": "import",
                    "name": full_name,
                    "node": node,
                }

    @contextmanager
    def _enter_scope(self, scope_type, name):
        self.scope_stack.append((scope_type, name))
        try:
            yield
        finally:
            self.scope_stack.pop()

    def _process_deferred_analysis(self):
        pass

    def _analyze_statements(
        self,
        statements: List[ast.AST],
        state: AbstractState,
        filename: str,
        is_module_level: bool = False,
    ) -> AbstractState:
        current_state = state.copy()
        for stmt in statements:
            if isinstance(stmt, ast.FunctionDef):
                self._analyze_function_def(stmt, current_state, filename)
            elif isinstance(stmt, ast.ClassDef):
                self._analyze_class_def(stmt, current_state, filename)
            elif isinstance(stmt, ast.Assign):
                self._analyze_assignment(stmt, current_state)
            elif isinstance(stmt, ast.If):
                self._analyze_if(stmt, current_state, filename)
            elif isinstance(stmt, ast.While):
                self._analyze_while(stmt, current_state, filename)
            elif isinstance(stmt, ast.For):
                self._analyze_for(stmt, current_state, filename)
            elif isinstance(stmt, ast.Try):
                self._analyze_try(stmt, current_state, filename)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                self._analyze_call_expr(stmt.value, current_state, filename)
            elif isinstance(stmt, ast.Return) and is_module_level:
                if stmt.value:
                    return_value = self._evaluate_expression(stmt.value, current_state)
                    return current_state
        return current_state

    def _analyze_function_def(
        self, node: ast.FunctionDef, state: AbstractState, filename: str
    ):
        if self.depth > self.max_depth:
            return
        func_name = node.name
        context_key = self._context_key(func_name, state.call_context)
        if context_key not in self.callgraph:
            self.callgraph[context_key] = set()
        func_def = {
            "type": "function",
            "name": func_name,
            "node": node,
            "args": [arg.arg for arg in node.args.args],
            "returns": (
                self._extract_return_type(node.returns) if node.returns else None
            ),
            "decorators": [self._expr_to_str(d) for d in node.decorator_list],
        }
        self.definitions[func_name] = func_def
        with self._enter_scope("function", func_name):
            for decorator in node.decorator_list:
                self._analyze_decorator(decorator, state, filename)
            param_types = {}
            for arg in node.args.args:
                param_types[arg.arg] = AbstractValue(AbstractValue.ValueType.TOP)
                state.assign(arg.arg, param_types[arg.arg])
            self._process_annotations(node, state)
            new_state = state.copy()
            new_state.call_context = self._extend_context(state.call_context, func_name)
            return_values = []
            try:
                self._analyze_statements(
                    node.body, new_state, filename, is_function_body=True
                )
            except Exception as e:
                logging.warning(f"Error analyzing function {func_name}: {e}")
            if return_values:
                func_def["return_type"] = self._unify_types(return_values)

    def _analyze_decorator(self, decorator, state, filename):
        if isinstance(decorator, ast.Call):
            self._analyze_call_expr(decorator, state, filename)
        elif isinstance(decorator, ast.Name):
            self._resolve_name_reference(decorator.id, state.call_context)

    def _process_annotations(self, node, state):
        if node.returns:
            return_type = self._extract_annotation(node.returns)
            if return_type:
                self.type_constraints[f"return:{node.name}"] = return_type
        for arg in node.args.args:
            if arg.annotation:
                param_type = self._extract_annotation(arg.annotation)
                if param_type:
                    self.type_constraints[f"param:{arg.arg}"] = param_type

    def _extract_annotation(self, node):
        self.depth += 1
        body_state = self._analyze_statements(node.body, func_state, filename, True)
        self.depth -= 1
        self.function_cache[func_key] = {
            "params": {arg.arg: func_state.lookup(arg.arg) for arg in node.args.args},
            "body_state": body_state,
        }

    def _analyze_class_def(
        self, node: ast.ClassDef, state: AbstractState, filename: str
    ) -> None:
        class_name = node.name
        context_key = self._context_key(class_name, state.call_context)
        class_def = {
            "type": "class",
            "name": class_name,
            "node": node,
            "bases": [],
            "methods": {},
            "class_attributes": {},
            "instance_attributes": set(),
            "mro": [],
        }
        self.definitions[class_name] = class_def
        base_classes = []
        for base in node.bases:
            base_name = self._expr_to_str(base)
            if base_name:
                base_classes.append(base_name)
                class_def["bases"].append(base_name)
        self._build_mro(class_def, base_classes)
        with self._enter_scope("class", class_name):
            for decorator in node.decorator_list:
                self._analyze_decorator(decorator, state, filename)
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_def["methods"][stmt.name] = stmt
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    class_def["class_attributes"][stmt.target.id] = {
                        "annotation": (
                            self._expr_to_str(stmt.annotation)
                            if stmt.annotation
                            else None
                        ),
                        "value": self._expr_to_str(stmt.value) if stmt.value else None,
                    }
            for method_name, method_node in class_def["methods"].items():
                self._analyze_method(method_node, class_def, state, filename)

    def _build_mro(self, class_def, base_classes):
        mro = [class_def["name"]]
        for base in base_classes:
            if base in self.definitions and "mro" in self.definitions[base]:
                mro.extend([b for b in self.definitions[base]["mro"] if b not in mro])
            else:
                mro.append(base)
        class_def["mro"] = mro

    def _analyze_method(self, node, class_def, state, filename):
        method_name = node.name
        is_static = any(
            isinstance(d, ast.Name) and d.id == "staticmethod"
            for d in node.decorator_list
        )
        is_classmethod = any(
            isinstance(d, ast.Name) and d.id == "classmethod"
            for d in node.decorator_list
        )
        method_def = {
            "type": "method",
            "name": method_name,
            "node": node,
            "is_static": is_static,
            "is_classmethod": is_classmethod,
            "class_name": class_def["name"],
            "args": [arg.arg for arg in node.args.args],
            "returns": (
                self._extract_return_type(node.returns) if node.returns else None
            ),
            "decorators": [self._expr_to_str(d) for d in node.decorator_list],
        }
        class_def["methods"][method_name] = method_def
        if not is_static:
            first_param = "cls" if is_classmethod else "self"
            if node.args.args and node.args.args[0].arg not in ("self", "cls"):
                node.args.args.insert(0, ast.arg(arg=first_param, annotation=None))
        with self._enter_scope("method", f"{class_def['name']}.{method_name}"):
            for decorator in node.decorator_list:
                self._analyze_decorator(decorator, state, filename)
            method_state = state.copy()
            for arg in node.args.args:
                method_state.assign(arg.arg, AbstractValue(AbstractValue.ValueType.TOP))
            self._process_annotations(node, method_state)
            try:
                self._analyze_statements(
                    node.body, method_state, filename, is_function_body=True
                )
            except Exception as e:
                logging.warning(
                    f"Error analyzing method {class_def['name']}.{method_name}: {e}"
                )

    def _analyze_assignment(self, node: ast.Assign, state: AbstractState) -> None:
        value = self._evaluate_expression(node.value, state)
        for target in node.targets:
            if isinstance(target, ast.Name):
                state.assign(target.id, value)
            elif isinstance(target, ast.Attribute):
                pass
            elif isinstance(target, ast.Subscript):
                pass

    def _analyze_if(self, node: ast.If, state: AbstractState, filename: str) -> None:
        condition_value = self._evaluate_expression(node.test, state)
        true_state = state.copy()
        true_state.add_constraint(node.test)
        true_result = self._analyze_statements(node.body, true_state, filename)
        false_state = state.copy()
        false_state.add_constraint(ast.UnaryOp(op=ast.Not(), operand=node.test))
        false_result = self._analyze_statements(node.orelse, false_state, filename)
        joined_state = true_result.join(false_result)
        state.environment.update(joined_state.environment)

    def _analyze_while(
        self, node: ast.While, state: AbstractState, filename: str
    ) -> None:
        loop_state = state.copy()
        loop_state.add_constraint(node.test)
        after_first = self._analyze_statements(node.body, loop_state, filename)
        after_second = self._analyze_statements(node.body, after_first, filename)
        exit_state = state.copy()
        exit_state.add_constraint(ast.UnaryOp(op=ast.Not(), operand=node.test))
        joined_state = after_second.join(exit_state)
        state.environment.update(joined_state.environment)

    def _analyze_for(self, node: ast.For, state: AbstractState, filename: str) -> None:
        iterable_value = self._evaluate_expression(node.iter, state)
        loop_state = state.copy()
        if isinstance(node.target, ast.Name):
            element_type = AbstractValue(AbstractValue.ValueType.TOP)
            loop_state.assign(node.target.id, element_type)
        after_first = self._analyze_statements(node.body, loop_state, filename)
        after_second = self._analyze_statements(node.body, after_first, filename)
        joined_state = state.join(after_second)
        state.environment.update(joined_state.environment)

    def _analyze_try(self, node: ast.Try, state: AbstractState, filename: str) -> None:
        try_state = state.copy()
        try_result = self._analyze_statements(node.body, try_state, filename)
        except_states = []
        for handler in node.handlers:
            handler_state = state.copy()
            if handler.name:
                exception_value = AbstractValue(
                    AbstractValue.ValueType.INSTANCE, set(), handler
                )
                handler_state.assign(handler.name, exception_value)
            except_result = self._analyze_statements(
                handler.body, handler_state, filename
            )
            except_states.append(except_result)
        else_result = None
        if node.orelse:
            else_state = try_result.copy()
            else_result = self._analyze_statements(node.orelse, else_state, filename)
        if node.finalbody:
            finally_state = state.copy()
            finally_result = self._analyze_statements(
                node.finalbody, finally_state, filename
            )
        all_results = [try_result] + except_states
        if else_result:
            all_results.append(else_result)
        result = all_results[0]
        for other in all_results[1:]:
            result = result.join(other)
        state.environment.update(result.environment)

    def _analyze_call_expr(
        self, node: ast.Call, state: AbstractState, filename: str
    ) -> None:
        try:
            if isinstance(node.func, ast.Name):
                self._analyze_direct_call(node.func.id, node, state, filename)
            elif isinstance(node.func, ast.Attribute):
                self._analyze_method_call(node.func, node, state, filename)
            elif isinstance(node.func, ast.Call):
                self._analyze_call_expr(node.func, state, filename)
            for arg in node.args:
                self._evaluate_expression(arg, state)
        except Exception as e:
            logging.warning(f"Error analyzing call expression: {e}")

    def _analyze_direct_call(
        self, func_name: str, call_node: ast.Call, state: AbstractState, filename: str
    ) -> None:
        context_key = self._context_key(func_name, state.call_context)
        if context_key not in self.callgraph:
            self.callgraph[context_key] = set()
        if func_name in __builtins__:
            return
        if (
            func_name in self.definitions
            and self.definitions[func_name].get("type") == "class"
        ):
            self._analyze_constructor_call(func_name, call_node, state, filename)

    def _analyze_method_call(
        self,
        attr_node: ast.Attribute,
        call_node: ast.Call,
        state: AbstractState,
        filename: str,
    ) -> None:
        if not isinstance(attr_node.value, (ast.Name, ast.Attribute)):
            return
        obj_expr = attr_node.value
        method_name = attr_node.attr
        obj_type = self._resolve_expression_type(obj_expr, state)
        if obj_type and isinstance(obj_type, str):
            if (
                obj_type in self.definitions
                and self.definitions[obj_type].get("type") == "class"
            ):
                class_def = self.definitions[obj_type]
                method_def = class_def.get("methods", {}).get(method_name)
                if method_def:
                    method_key = self._context_key(
                        f"{obj_type}.{method_name}", state.call_context
                    )
                    if method_key not in self.callgraph:
                        self.callgraph[method_key] = set()
                    caller_context = (
                        state.call_context[-self.k :] if state.call_context else ()
                    )
                    callee_context = self._extend_context(
                        caller_context, f"{obj_type}.{method_name}"
                    )
                    caller_key = self._context_key(filename, caller_context)
                    if caller_key not in self.callgraph:
                        self.callgraph[caller_key] = set()
                    self.callgraph[caller_key].add(method_key)
                    if "node" in method_def and method_key not in self.function_cache:
                        self._analyze_function_def(method_def["node"], state, filename)
                        self.function_cache[method_key] = True

    def _analyze_constructor_call(
        self, class_name: str, call_node: ast.Call, state: AbstractState, filename: str
    ) -> None:
        new_key = self._context_key(f"{class_name}.__new__", state.call_context)
        if new_key not in self.callgraph:
            self.callgraph[new_key] = set()
        init_key = self._context_key(f"{class_name}.__init__", state.call_context)
        if init_key not in self.callgraph:
            self.callgraph[init_key] = set()
        caller_context = state.call_context[-self.k :] if state.call_context else ()
        caller_key = self._context_key(filename, caller_context)
        if caller_key not in self.callgraph:
            self.callgraph[caller_key] = set()
        self.callgraph[caller_key].update([new_key, init_key])

    def _resolve_expression_type(
        self, node: ast.AST, state: AbstractState
    ) -> Optional[str]:
        if isinstance(node, ast.Name):
            if node.id in self.definitions:
                return self.definitions[node.id].get("type")
        elif isinstance(node, ast.Attribute):
            obj_type = self._resolve_expression_type(node.value, state)
            if obj_type and obj_type in self.definitions:
                class_def = self.definitions[obj_type]
                if "methods" in class_def and node.attr in class_def["methods"]:
                    return "method"
                elif (
                    "class_attributes" in class_def
                    and node.attr in class_def["class_attributes"]
                ):
                    return class_def["class_attributes"][node.attr].get("type")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in self.definitions:
                func_def = self.definitions[node.func.id]
                if "returns" in func_def:
                    return func_def["returns"]
        return None

    def _evaluate_expression(
        self, node: ast.AST, state: AbstractState
    ) -> AbstractValue:
        if isinstance(node, ast.Name):
            return state.lookup(node.id)
        elif (
            isinstance(node, ast.Num)
            or isinstance(node, ast.Str)
            or isinstance(node, ast.NameConstant)
        ):
            return AbstractValue.from_literal(node)
        elif (
            isinstance(node, ast.List)
            or isinstance(node, ast.Dict)
            or isinstance(node, ast.Set)
            or isinstance(node, ast.Tuple)
        ):
            return AbstractValue.from_literal(node)
        elif isinstance(node, ast.BinOp):
            left = self._evaluate_expression(node.left, state)
            right = self._evaluate_expression(node.right, state)
            return AbstractValue(AbstractValue.ValueType.TOP)
        elif isinstance(node, ast.Compare):
            left = self._evaluate_expression(node.left, state)
            return AbstractValue(AbstractValue.ValueType.BOOL)
        elif isinstance(node, ast.Call):
            return AbstractValue(AbstractValue.ValueType.TOP)
        elif isinstance(node, ast.Attribute):
            value = self._evaluate_expression(node.value, state)
            return AbstractValue(AbstractValue.ValueType.TOP)
        return AbstractValue(AbstractValue.ValueType.TOP)

    def _extract_function_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            base = self._extract_function_name(node.value)
            if base:
                return f"{base}.{node.attr}"
            return node.attr
        return None

    def _context_key(self, function_name: str, context: Tuple[str, ...]) -> str:
        if not context:
            return function_name
        return f"{':'.join(context)}:{function_name}"

    def _extend_context(
        self, context: Tuple[str, ...], function_name: str
    ) -> Tuple[str, ...]:
        if self.k <= 0:
            return tuple()
        new_ctx = context + (function_name,)
        if len(new_ctx) > self.k:
            new_ctx = new_ctx[-self.k :]
        return new_ctx


class KCFACallGraphBuilder:
    def __init__(self, k: int = 2, max_depth: int = 10):
        self.k = k
        self.max_depth = max_depth
        self.interpreter = AbstractInterpreter(max_depth, k)
        self.context_callgraph = {}
        self.collapsed_callgraph = {}

    def analyze_file(self, file_path: str, file_content: str) -> Dict:
        try:
            tree = ast.parse(file_content)
            results = self.interpreter.analyze_module(tree, file_path)
            self.context_callgraph.update(results["callgraph"])
            self._collapse_callgraph()
            return {
                "context_callgraph": self.context_callgraph,
                "callgraph": self.collapsed_callgraph,
                "function_summaries": results["function_summaries"],
            }
        except SyntaxError as e:
            logging.error(f"Syntax error in {file_path}: {e}")
            return {"error": str(e)}

    def _collapse_callgraph(self) -> None:
        self.collapsed_callgraph = {}
        for caller_key, callees in self.context_callgraph.items():
            caller_function = caller_key.split(":")[-1]
            if caller_function not in self.collapsed_callgraph:
                self.collapsed_callgraph[caller_function] = set()
            for callee_key in callees:
                callee_function = callee_key.split(":")[-1]
                self.collapsed_callgraph[caller_function].add(callee_function)

    def get_context_sensitive_edges(self) -> List[Dict]:
        edges = []
        for caller, callees in self.context_callgraph.items():
            for callee in callees:
                caller_parts = caller.split(":")
                callee_parts = callee.split(":")
                caller_context = caller_parts[:-1]
                caller_function = caller_parts[-1]
                callee_context = callee_parts[:-1]
                callee_function = callee_parts[-1]
                edges.append(
                    {
                        "source": caller_function,
                        "target": callee_function,
                        "source_context": caller_context,
                        "target_context": callee_context,
                    }
                )
        return edges

    def get_context_sensitive_edges(self, callgraph: Dict) -> List[Dict]:
        for node in callgraph["nodes"]:
            node_id = node["id"]
            metadata = node.get("metadata", {})
            if metadata.get("polymorphic", False):
                node["highPolymorphism"] = True
            if "inferred_types" in metadata:
                confidence = self._calculate_type_confidence(metadata["inferred_types"])
                node["confidence"] = confidence
                if confidence < 0.3:
                    node["group"] = 10
                elif confidence < 0.7:
                    node["group"] = 11
                else:
                    node["group"] = 12
\n\n# ==============================\n# Filename: services\advanced_analysis\__init__.py\n# ==============================\n\n\n\n# ==============================\n# Filename: services\advanced_analysis\context_sensitive_analyzer.py\n# ==============================\n\nimport ast
from typing import List, Set, Dict
import networkx as nx


class TypeLattice:
    def __init__(self):
        self.types = {"Any", "int", "str", "list", "dict", "CustomType"}

    def get_least_upper_bound(self, type1: str, type2: str) -> str:
        if type1 == type2:
            return type1
        return "Any"


class ContextSensitiveAnalyzer:
    def __init__(self, k: int = 2):
        self.k = k
        self.call_graph = nx.MultiDiGraph()
        self.type_lattice = TypeLattice()
        self.resolved_calls: Dict[tuple, Set[str]] = {}

    def _get_call_site_hash(self, call_site_node: ast.Call) -> int:
        return hash(
            (
                getattr(call_site_node, "lineno", 0),
                getattr(call_site_node, "col_offset", 0),
            )
        )

    def analyze_method_call(
        self,
        call_site: ast.Call,
        current_context: List[str],
        available_types: Dict[str, str],
    ) -> Set[str]:
        """
        Analyzes a method call in a context-sensitive manner.
        'current_context' is a list of function/method names representing the call stack.
        'available_types' is a dictionary mapping variable names to their inferred types.
        Returns a set of possible target function/method names.
        """
        effective_context = (
            tuple(current_context[-self.k :])
            if len(current_context) > self.k
            else tuple(current_context)
        )
        call_site_id = self._get_call_site_hash(call_site)
        cache_key = (call_site_id, effective_context)
        if cache_key in self.resolved_calls:
            return self.resolved_calls[cache_key]
        possible_targets = self._resolve_call_targets(
            call_site, effective_context, available_types
        )
        self.resolved_calls[cache_key] = possible_targets
        return possible_targets

    def _resolve_call_targets(
        self, call_site: ast.Call, context: tuple, available_types: Dict[str, str]
    ) -> Set[str]:
        """
        Placeholder for the actual call target resolution logic.
        This would typically involve Abstract Interpretation, type analysis, etc.
        """
        if isinstance(call_site.func, ast.Attribute):
            obj_name_node = call_site.func.value
            method_name = call_site.func.attr
            obj_name = ast.unparse(obj_name_node)
            obj_type = available_types.get(obj_name, "Any")
            if obj_type != "Any":
                return {f"{obj_type}.{method_name}"}
            else:
                return {f"<UnknownClass>.{method_name}"}
        elif isinstance(call_site.func, ast.Name):
            return {call_site.func.id}
        return {f"<complex_target_for_{ast.unparse(call_site.func)}>"}

    def get_call_graph(self):
        return self.call_graph

    def update_type_information(
        self, variable_name: str, inferred_type: str, context: List[str]
    ):
        pass


if __name__ == "__main__":
    csa = ContextSensitiveAnalyzer(k=1)
    call_node_example = ast.Call(
        func=ast.Attribute(
            value=ast.Name(id="x", ctx=ast.Load()), attr="do_something", ctx=ast.Load()
        ),
        args=[],
        keywords=[],
    )
    setattr(call_node_example, "lineno", 10)
    setattr(call_node_example, "col_offset", 0)
    current_call_stack = ["main_function", "caller_function"]
    inferred_variable_types = {"x": "MyClass"}
    targets = csa.analyze_method_call(
        call_node_example, current_call_stack, inferred_variable_types
    )
    print(
        f"Possible targets for 'x.do_something()' in context {current_call_stack[-1:]}: {targets}"
    )
    call_node_example_2 = ast.Call(
        func=ast.Attribute(
            value=ast.Name(id="y", ctx=ast.Load()), attr="process_data", ctx=ast.Load()
        ),
        args=[],
        keywords=[],
    )
    setattr(call_node_example_2, "lineno", 15)
    setattr(call_node_example_2, "col_offset", 0)
    inferred_variable_types_2 = {"y": "AnotherClass"}
    targets_2 = csa.analyze_method_call(
        call_node_example_2, current_call_stack, inferred_variable_types_2
    )
    print(
        f"Possible targets for 'y.process_data()' in context {current_call_stack[-1:]}: {targets_2}"
    )
    current_call_stack_3 = ["another_main", "different_caller"]
    targets_3 = csa.analyze_method_call(
        call_node_example, current_call_stack_3, inferred_variable_types
    )
    print(
        f"Possible targets for 'x.do_something()' in context {current_call_stack_3[-1:]}: {targets_3}"
    )
    print("Built Call Graph Edges:")
    for edge in csa.get_call_graph().edges(data=True):
        print(edge)
\n\n# ==============================\n# Filename: services\advanced_analysis\type_inference_engine.py\n# ==============================\n\nimport ast
from typing import Dict, List, Any, Set, Tuple, Union

PyType = Union[str, "TypeVariable", "FunctionType"]


class TypeVariable:
    _count = 0

    def __init__(self):
        self.id = TypeVariable._count
        TypeVariable._count += 1

    def __repr__(self):
        return f"T{self.id}"

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, TypeVariable) and self.id == other.id


class FunctionType:
    def __init__(self, arg_types: List[PyType], return_type: PyType):
        self.arg_types = arg_types
        self.return_type = return_type

    def __repr__(self):
        return f"({', '.join(map(str, self.arg_types))}) -> {self.return_type}"


class TypeInferenceEngine:
    def __init__(self):
        self.constraints: List[Tuple[PyType, PyType]] = []
        self.environment: Dict[str, PyType] = {}
        self.substitutions: Dict[TypeVariable, PyType] = {}

    def new_type_variable(self) -> TypeVariable:
        return TypeVariable()

    def infer_types(self, ast_root: ast.AST) -> Dict[str, PyType]:
        """Public method to start type inference on an AST.
        Returns a simplified environment of inferred types for names.
        """
        self.constraints = []
        self.environment = {}
        self.substitutions = {}
        self._collect_constraints(ast_root, self.environment)
        self._solve_constraints()
        final_types = {}
        for name, type_val in self.environment.items():
            final_types[name] = self._apply_substitutions(type_val)
        return final_types

    def _collect_constraints(self, node: ast.AST, env: Dict[str, PyType]) -> PyType:
        """Recursively traverses the AST to collect type constraints."""
        node_type_name = type(node).__name__
        handler_method_name = f"_visit_{node_type_name.lower()}"
        handler = getattr(self, handler_method_name, self._visit_default)
        return handler(node, env)

    def _visit_default(self, node: ast.AST, env: Dict[str, PyType]) -> PyType:
        """Default visitor for AST nodes not explicitly handled."""
        for child_node in ast.iter_child_nodes(node):
            self._collect_constraints(child_node, env)
        return self.new_type_variable()

    def _visit_name(self, node: ast.Name, env: Dict[str, PyType]) -> PyType:
        if node.id not in env:
            env[node.id] = self.new_type_variable()
        return env[node.id]

    def _visit_constant(self, node: ast.Constant, env: Dict[str, PyType]) -> PyType:
        if isinstance(node.value, int):
            return "int"
        elif isinstance(node.value, str):
            return "str"
        elif isinstance(node.value, float):
            return "float"
        elif isinstance(node.value, bool):
            return "bool"
        return self.new_type_variable()

    def _visit_assign(self, node: ast.Assign, env: Dict[str, PyType]):
        value_type = self._collect_constraints(node.value, env)
        for target in node.targets:
            if isinstance(target, ast.Name):
                target_type = self._visit_name(target, env)
                self.constraints.append((target_type, value_type))
        return value_type

    def _visit_functiondef(
        self, node: ast.FunctionDef, env: Dict[str, PyType]
    ) -> PyType:
        func_env = env.copy()
        arg_types = []
        for arg in node.args.args:
            arg_type = self.new_type_variable()
            func_env[arg.arg] = arg_type
            arg_types.append(arg_type)
        body_type = self.new_type_variable()
        for stmt in node.body:
            self._collect_constraints(stmt, func_env)
            if isinstance(stmt, ast.Return) and stmt.value:
                return_value_type = self._collect_constraints(stmt.value, func_env)
                self.constraints.append((body_type, return_value_type))
        func_type = FunctionType(arg_types, body_type)
        env[node.name] = func_type
        return func_type

    def _visit_call(self, node: ast.Call, env: Dict[str, PyType]) -> PyType:
        func_type_var = self._collect_constraints(node.func, env)
        arg_expr_types = [self._collect_constraints(arg, env) for arg in node.args]
        call_return_type = self.new_type_variable()
        expected_func_type = FunctionType(arg_expr_types, call_return_type)
        self.constraints.append((func_type_var, expected_func_type))
        return call_return_type

    def _visit_binop(self, node: ast.BinOp, env: Dict[str, PyType]) -> PyType:
        left_type = self._collect_constraints(node.left, env)
        right_type = self._collect_constraints(node.right, env)
        if isinstance(node.op, ast.Add):
            self.constraints.append((left_type, right_type))
            return left_type
        return self.new_type_variable()

    def _unify(self, type1: PyType, type2: PyType):
        """Unifies two types. Modifies self.substitutions."""
        t1 = self._apply_substitutions(type1)
        t2 = self._apply_substitutions(type2)
        if t1 == t2:
            return
        elif isinstance(t1, TypeVariable):
            self._add_substitution(t1, t2)
        elif isinstance(t2, TypeVariable):
            self._add_substitution(t2, t1)
        elif isinstance(t1, FunctionType) and isinstance(t2, FunctionType):
            if len(t1.arg_types) != len(t2.arg_types):
                raise TypeError("Function arity mismatch")
            for arg1_t, arg2_t in zip(t1.arg_types, t2.arg_types):
                self._unify(arg1_t, arg2_t)
            self._unify(t1.return_type, t2.return_type)
        elif isinstance(t1, str) and isinstance(t2, str) and t1 != t2:
            raise TypeError(f"Type mismatch: cannot unify {t1} and {t2}")
        else:
            raise TypeError(
                f"Cannot unify {t1} and {t2}. Unhandled type structure or mismatch."
            )

    def _add_substitution(self, var: TypeVariable, type_val: PyType):
        """Adds a substitution, checking for circular dependencies."""
        if self._occurs_in(var, type_val):
            raise TypeError(f"Circular type detected: {var} occurs in {type_val}")
        self.substitutions[var] = type_val

    def _apply_substitutions(self, type_val: PyType) -> PyType:
        """Applies current substitutions to a type, resolving it as much as possible."""
        if isinstance(type_val, TypeVariable):
            if type_val in self.substitutions:
                self.substitutions[type_val] = self._apply_substitutions(
                    self.substitutions[type_val]
                )
                return self.substitutions[type_val]
            return type_val
        elif isinstance(type_val, FunctionType):
            return FunctionType(
                [self._apply_substitutions(arg_t) for arg_t in type_val.arg_types],
                self._apply_substitutions(type_val.return_type),
            )
        return type_val

    def _occurs_in(self, var: TypeVariable, type_val: PyType) -> bool:
        """Checks if a type variable occurs in a type expression (for cycle detection)."""
        resolved_type = self._apply_substitutions(type_val)
        if var == resolved_type:
            return True
        elif isinstance(resolved_type, FunctionType):
            return any(
                self._occurs_in(var, arg_t) for arg_t in resolved_type.arg_types
            ) or self._occurs_in(var, resolved_type.return_type)
        return False

    def _solve_constraints(self):
        """Iteratively solves the collected type constraints using unification."""
        changed = True
        iterations = 0
        max_iterations = 500
        while changed and iterations < max_iterations:
            changed = False
            iterations += 1
            for i in range(len(self.constraints)):
                t1, t2 = self.constraints[i]
                try:
                    current_subs_snapshot = self.substitutions.copy()
                    self._unify(t1, t2)
                    if self.substitutions != current_subs_snapshot:
                        changed = True
                except TypeError as e:
                    pass
            if not changed and iterations > 1:
                break
        if iterations >= max_iterations:
            print(
                "Warning: Type inference reached max iterations. Results may be incomplete."
            )


if __name__ == "__main__":
    engine = TypeInferenceEngine()
    source_code = """
def foo(a):
  return a + 1
b = foo(10)
c = foo('hello')
"""
    ast_example = ast.parse(source_code)
    inferred_types = engine.infer_types(ast_example)
    print("Inferred Types:")
    for name, var_type in inferred_types.items():
        print(f"  {name}: {engine._apply_substitutions(var_type)}")
    print("\nSubstitutions:")
    for var, type_val in engine.substitutions.items():
        print(f"  {var}: {engine._apply_substitutions(type_val)}")
    source_code_func_call = """
def add(x, y):
    return x + y
result = add(1, 2)
"""
    ast_fc = ast.parse(source_code_func_call)
    types_fc = engine.infer_types(ast_fc)
    print("\nInferred Types (Function Call Example):")
    for name, var_type in types_fc.items():
        print(f"  {name}: {engine._apply_substitutions(var_type)}")
    source_code_error = """
def identity(x):
    return x
a = identity(5)
b = identity('text')
"""
    ast_err = ast.parse(source_code_error)
    types_err = engine.infer_types(ast_err)
    print("\nInferred Types (Potential Error Example):")
    for name, var_type in types_err.items():
        print(f"  {name}: {engine._apply_substitutions(var_type)}")
\n\n# ==============================\n# Filename: services\auth.py\n# ==============================\n\nfrom fastapi import Depends, HTTPException, status
from jose import JWTError, jwt
from sqlalchemy.orm import Session
from typing import Optional
from ..models.user import User
from ..models.base import oauth2_scheme, settings, get_db


async def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        username: str = payload.get("sub")
        if username is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception
    user = db.query(User).filter(User.login == username).first()
    if user is None:
        raise credentials_exception
    return user
\n\n# ==============================\n# Filename: services\callgraph.py\n# ==============================\n\nimport os
import ast
from typing import Dict, List, Set, Optional, Any, Union
import tempfile
import shutil
from git import Repo
from fastapi import HTTPException
from pydantic import AnyUrl
import google.generativeai as genai
import logging
import traceback
import time
import asyncio
from functools import wraps
from datetime import datetime, timedelta
import json
import re # Ensure re is imported at the top of the file if not already present

from ..models.base import settings
from ..models.callgraph import CallgraphDataCreate
from .codebase_data_service import CodebaseDataService


def rate_limited(max_per_minute: int):
    if max_per_minute <= 0:
        # Default to 1 call per minute if max_per_minute is not positive
        actual_min_interval = 60.0
        logger.warning(f"rate_limited: max_per_minute was {max_per_minute}, defaulting to 1 call per minute.")
    else:
        actual_min_interval = 60.0 / max_per_minute
    
    # last_called is specific to each instance of the decorator created by calling rate_limited(N)
    last_called = 0

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            nonlocal last_called
            
            elapsed = time.time() - last_called
            if elapsed < actual_min_interval:
                wait_time = actual_min_interval - elapsed
                # Adding a log for when rate limiting is active
                logger.debug(f"Rate limiting active for {func.__name__}: waiting for {wait_time:.2f}s. Interval: {actual_min_interval:.2f}s.")
                await asyncio.sleep(wait_time)
            
            last_called = time.time()
            return await func(self, *args, **kwargs)
        return wrapper
    return decorator


logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


class CallgraphGenerator:
    def __init__(self):
        self.nodes = []
        self.links = []
        self.functions = {}
        self.classes = {}
        self.imports = {}
        self.complexity_scores = {}
        self.repo_path = ""
        self.detected_framework_name = "generic"
        self.analysis_start_time = None
        self.codebase_data_service = CodebaseDataService()
        self.repository_id = None
        self.callgraph_id = None
        self.metrics = {}
        self.status_log = []
        
        # Initialize Gemini for AI-enhanced analysis
        GEMINI_API_KEY = settings.GEMINI_API_KEY
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash-lite")
        self.last_api_call = 0
        self.min_interval = 2.0

    def is_valid_url(self, url: str) -> bool:
        """
        Check if a URL is valid for Git cloning.
        
        Args:
            url: The URL to check
            
        Returns:
            bool: True if the URL appears to be a valid Git repository URL
        """
        # Simple check for common Git URL patterns
        if url.startswith(("http://", "https://", "git@", "ssh://", "git://")):
            # Check for common Git hosting domains or .git suffix
            if (
                ".git" in url or
                "github.com" in url or
                "gitlab.com" in url or
                "bitbucket.org" in url or
                "dev.azure.com" in url or
                "git.sr.ht" in url
            ):
                return True
        return False

    async def clone_repository(
        self, repo_url: Union[str, AnyUrl], timeout: int = 180
    ) -> str:
        """Clone a git repository to a temporary directory."""
        repo_url_str = str(repo_url)  # Convert HttpUrl to string immediately

        if not self.is_valid_url(repo_url_str):
            if os.path.isdir(repo_url_str):
                self.status_log.append(f"Using local directory: {repo_url_str}")
                logger.info(f"Using local directory: {repo_url_str}")
                return os.path.abspath(repo_url_str)
            else:
                self.status_log.append(f"Invalid repository URL or path: {repo_url_str}")
                logger.error(f"Invalid repository URL or path: {repo_url_str}")
                raise ValueError(f"Invalid repository URL or path: {repo_url_str}")

        # Use repo_url_str for all path operations
        base_name = os.path.basename(repo_url_str.rstrip("/"))
        repo_name_sanitized = os.path.splitext(base_name)[0]
        safe_repo_name = "".join(c if c.isalnum() or c in ('_', '-') else '' for c in repo_name_sanitized)
        if not safe_repo_name:
            safe_repo_name = "repository"

        temp_dir_name = f"graphix_{safe_repo_name}_{os.urandom(4).hex()}"
        temp_dir = os.path.join(tempfile.gettempdir(), temp_dir_name)

        try:
            self.status_log.append(
                f"Cloning repository {repo_url_str} to {temp_dir} (timeout: {timeout}s)"
            )
            logger.info(
                f"Cloning repository {repo_url_str} to {temp_dir} (timeout: {timeout}s)"
            )
            os.makedirs(os.path.dirname(temp_dir), exist_ok=True)

            import subprocess
            cmd = [
                "git",
                "clone",
                "--depth",
                "1",
                repo_url_str,  # Use string form for command
                temp_dir,
            ]
            loop = asyncio.get_running_loop()
            try:
                # Run the blocking subprocess call in a separate thread
                process = await loop.run_in_executor(
                    None,  # Use the default ThreadPoolExecutor
                    lambda: subprocess.run(
                        cmd,
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        check=True, # Raise CalledProcessError for non-zero exit codes
                        timeout=timeout # Apply timeout here
                    )
                )
                if process.returncode != 0:
                    raise Exception(
                        f"Git clone failed: {process.stderr.decode().strip()}"
                    )
            except subprocess.CalledProcessError as e:
                raise Exception(f"Git clone failed: {e.stderr.decode().strip()}")
            except subprocess.TimeoutExpired:
                raise Exception(f"Git clone timed out after {timeout} seconds.")
            except Exception as e:
                raise Exception(f"Error in clone operation: {str(e)}")
            if not os.path.exists(os.path.join(temp_dir, ".git")):
                raise Exception("Repository was not cloned successfully")
            return temp_dir
        except Exception as e:
            logger.error(f"Error in clone operation: {str(e)}")
            raise

    async def analyze_repository(
        self,
        repo_path: Union[str, AnyUrl], 
        timeout: int = 600,
        clone: bool = True, 
        perform_cleanup: bool = True,
        max_files_to_analyze: Optional[int] = None
    ) -> Dict:
        """Analyzes a software repository to generate a callgraph."""
        start_time = time.time()
        self.status_log.append("Starting repository analysis.")
        repo_path_input_str = str(repo_path) # Convert original input for logging/initial checks

        current_repo_physical_path = None

        if clone:
            self.status_log.append(f"Cloning repository from {repo_path_input_str}")
            logger.info(f"Cloning repository from {repo_path_input_str}")
            clone_timeout = timeout // 3
            try:
                # clone_repository now expects Union[str, AnyUrl] and handles str conversion internally
                cloned_path = await self.clone_repository(repo_path, timeout=clone_timeout)
                current_repo_physical_path = os.path.abspath(cloned_path)
                self.tmp_dir = current_repo_physical_path 
                self.cleanup_needed = True 
                logger.info(f"Successfully cloned repository to {current_repo_physical_path}")
                self.status_log.append(f"Repository cloned to {current_repo_physical_path}")
            except Exception as e:
                logger.error(f"Failed to clone repository: {e}")
                self.status_log.append(f"Failed to clone repository: {e}")
                raise
        elif os.path.isdir(repo_path_input_str):
            current_repo_physical_path = os.path.abspath(repo_path_input_str)
            self.tmp_dir = None 
            self.cleanup_needed = False 
            logger.info(f"Using local repository path: {current_repo_physical_path}")
            self.status_log.append(f"Using local repository path: {current_repo_physical_path}")
        else:
            msg = f"Invalid repository path or URL: {repo_path_input_str}"
            logger.error(msg)
            self.status_log.append(msg)
            raise ValueError(msg)
        
        self.repo_path = current_repo_physical_path # This is the path to be used for analysis

        self.status_log.append(f"Starting repository analysis in: {self.repo_path}")
        logger.info(f"Starting repository analysis in: {self.repo_path}")

        if not self.repo_path or not os.path.isdir(self.repo_path):
            logger.error(f"Invalid repository path: {self.repo_path}")
            raise ValueError(f"Invalid repository path: {self.repo_path}")

        repo_root = self.repo_path
        while (
            not os.path.exists(os.path.join(repo_root, ".git"))
            and os.path.dirname(repo_root) != repo_root
        ):
            repo_root = os.path.dirname(repo_root)
        logger.info(f"Using repository root: {repo_root}")
        self.repo_path = repo_root
        self.repository_id = os.path.basename(repo_root)
        
        # Log repository analysis start
        log_message = f"Starting repository analysis for {self.repository_id}"
        logger.info(log_message)
        self.status_log.append(log_message)
        
        # Check if we have existing callgraph data that we can reuse
        existing_callgraph = await self.codebase_data_service.get_callgraph(self.repository_id)
        if existing_callgraph:
            logger.info(f"Found existing callgraph data for {self.repository_id}")
            
            # Convert nodes and links to the format expected by API consumers
            result = {
                "nodes": [node.dict() for node in existing_callgraph.nodes],
                "links": [link.dict() for link in existing_callgraph.links],
                "metadata": existing_callgraph.metadata.dict()
            }
            
            return result
        py_files = []
        total_files_found = 0
        
        for root, dirs, files in os.walk(self.repo_path):
            # Skip virtual environment directories
            if "venv" in dirs:
                dirs.remove("venv")
            if ".venv" in dirs:
                dirs.remove(".venv")
            if ".git" in dirs:
                dirs.remove(".git")

            total_files_found += len(files)
            
            for file in files:
                if file.endswith(".py"):
                    py_files.append(os.path.join(root, file))
                    
        log_message = f"Found {len(py_files)} Python files out of {total_files_found} total files"
        logger.info(log_message)
        self.status_log.append(log_message)
        if not py_files:
            logger.warning(f"No Python files found in {repo_root}")
            return {"nodes": [], "links": []}
        logger.info(
            f"Found {len(py_files)} Python files, analyzing up to {max_files_to_analyze or len(py_files)}..."
        )
        processed_files = 0
        for file_path in py_files:
            if time.time() - start_time > timeout:
                logger.warning(f"Analysis timed out after {timeout} seconds")
                raise asyncio.TimeoutError(
                    f"Analysis timed out after {timeout} seconds"
                )
            try:
                await asyncio.sleep(0.1)
                self.analyze_file(file_path)
                processed_files += 1
                logger.info(
                    f"Analyzed {file_path} ({processed_files}/{min(len(py_files), max_files_to_analyze or len(py_files))})"
                )
            except Exception as e:
                logger.error(
                    f"Error analyzing {file_path}: {str(e)}\n{traceback.format_exc()}"
                )
        if not self.functions:
            logger.warning("No functions found in any Python files")
            return {"nodes": [], "links": []}
        logger.info(
            f"Analyzed {processed_files} Python files, generating callgraph..."
        )
        await self.generate_callgraph()
        self._detect_framework()
        
        # Calculate analysis time
        analysis_time = time.time() - start_time
        
        # Prepare metadata
        metadata = {
            "framework_analyzed_as": self.detected_framework_name,
            "files_analyzed": len(py_files),
            "total_files_found": total_files_found,
            "analysis_time_seconds": round(analysis_time, 2),
            "timeout_seconds": timeout,
            "status": "completed",
            "status_log": self.status_log
        }
        
        # Calculate metrics
        if self.complexity_scores:
            complexity_values = list(self.complexity_scores.values())
            avg_complexity = sum(complexity_values) / len(complexity_values) if complexity_values else 0
            most_complex_function = None
            max_complexity = 0
            
            for func_name, complexity in self.complexity_scores.items():
                if complexity > max_complexity:
                    max_complexity = complexity
                    most_complex_function = func_name
                    
            self.metrics = {
                "avg_complexity": round(avg_complexity, 2),
                "max_complexity": round(max_complexity, 2)
            }
            
            if most_complex_function:
                for node in self.nodes:
                    if node.get("id") == most_complex_function:
                        self.metrics["most_complex_function"] = node
                        break
                        
            metadata["metrics"] = self.metrics

        # Prepare result for API response
        result = {
            "nodes": self.nodes,
            "links": self.links,
            "metadata": metadata
        }
        
        # Store callgraph data in the database
        try:
            callgraph_data = CallgraphDataCreate(
                repository_id=self.repository_id,
                nodes=self.nodes,
                links=self.links,
                metadata=metadata
            )
            
            self.callgraph_id = await self.codebase_data_service.store_callgraph(callgraph_data)
            logger.info(f"Stored callgraph data with ID: {self.callgraph_id}")
            
            # Add callgraph ID to result metadata
            result["metadata"]["callgraph_id"] = self.callgraph_id
        except Exception as e:
            logger.error(f"Failed to store callgraph data: {str(e)}")
            result["metadata"]["store_error"] = str(e)

        if perform_cleanup and clone:
            await self.cleanup()

        return result

    def analyze_file(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {str(e)}")
            return
        if not content.strip():
            logger.debug(f"Skipping empty file: {file_path}")
            return
        if not self.repo_path:
            logger.warning(f"repo_path not set when analyzing {file_path}")
            return
        try:
            rel_path = os.path.relpath(file_path, self.repo_path)
            module_name = rel_path.replace(".py", "").replace(os.sep, ".")
            if os.path.basename(file_path) == "__init__.py":
                module_name = module_name.rstrip(".__init__")
        except ValueError as e:
            logger.error(f"Error calculating module path for {file_path}: {str(e)}")
            return
        try:
            tree = ast.parse(content, filename=file_path)
            for node in ast.walk(tree):
                for child in ast.iter_child_nodes(node):
                    child.parent = node
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {str(e)}")
            return
        self.imports[module_name] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.name
                    asname = alias.asname or name
                    self.imports[module_name].append(name)
                    self._add_import_alias(module_name, asname, name)
            elif isinstance(node, ast.ImportFrom):
                if node.module is None:
                    continue
                for alias in node.names:
                    name = alias.name
                    asname = alias.asname or name
                    full_name = f"{node.module}.{name}"
                    self.imports[module_name].append(full_name)
                    self._add_import_alias(module_name, asname, full_name)
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                class_name = f"{module_name}.{node.name}"
                # MODIFIED: Extract source code for the class
                class_source_code = ast.get_source_segment(content, node)
                self.classes[class_name] = {
                    "methods": [],
                    "file": file_path,
                    "type": "class",
                    "module": module_name,
                    "base_classes": [
                        (
                            base.id
                            if isinstance(base, ast.Name)
                            else self._get_attr_name(base)
                        )
                        for base in node.bases
                        if hasattr(base, "id") or isinstance(base, ast.Attribute)
                    ],
                    # NEW: Store the source code snippet
                    "source_code": class_source_code,
                }
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = f"{class_name}.{item.name}"
                        try:
                            complexity = self._calculate_complexity(item)
                            docstring = ast.get_docstring(item) or ""
                            # MODIFIED: Extract source code for the method
                            method_source_code = ast.get_source_segment(content, item)
                            self.functions[method_name] = {
                                "node": item,
                                "file": file_path,
                                "complexity": complexity,
                                "type": "method",
                                "class": class_name,
                                "module": module_name,
                                "docstring": docstring,
                                "lineno": item.lineno,
                                "code_snippet": ast.get_source_segment(content, item) or "",
                                # NEW: Store the source code snippet
                                "source_code": method_source_code,
                            }
                            self.classes[class_name]["methods"].append(method_name)
                        except Exception as e:
                            logger.warning(
                                f"Error processing method {method_name}: {str(e)}"
                            )
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                parents = self._get_all_parents(node)
                if not any(isinstance(p, ast.ClassDef) for p in parents):
                    func_name = f"{module_name}.{node.name}"
                    try:
                        complexity = self._calculate_complexity(node)
                        docstring = ast.get_docstring(node) or ""
                        # MODIFIED: Extract source code for the function
                        function_source_code = ast.get_source_segment(content, node)
                        self.functions[func_name] = {
                            "node": node,
                            "file": file_path,
                            "complexity": complexity,
                            "type": "function",
                            "module": module_name,
                            "docstring": docstring,
                            "lineno": node.lineno,
                            "code_snippet": ast.get_source_segment(content, node) or "",
                            # NEW: Store the source code snippet
                            "source_code": function_source_code,
                        }
                    except Exception as e:
                        logger.warning(
                            f"Error processing function {func_name}: {str(e)}"
                        )

    def _add_import_alias(self, module_name: str, alias: str, full_name: str) -> None:
        if not hasattr(self, "import_aliases"):
            self.import_aliases = {}
        if module_name not in self.import_aliases:
            self.import_aliases[module_name] = {}
        self.import_aliases[module_name][alias] = full_name

    def _get_attr_name(self, node: ast.AST) -> str:
        if isinstance(node, ast.Attribute):
            return f"{self._get_attr_name(node.value)}.{node.attr}"
        elif isinstance(node, ast.Name):
            return node.id
        return ""

    def _get_all_parents(self, node: ast.AST) -> List[ast.AST]:
        parents = []
        current = node
        while hasattr(current, "parent"):
            parent = current.parent
            parents.append(parent)
            current = parent
        return parents

    def _get_parents(self, node: ast.AST) -> List[ast.AST]:
        parents = []
        current = node
        while hasattr(current, "parent"):
            parents.append(current.parent)
            current = current.parent
        return parents

    async def generate_callgraph(self) -> Dict[str, List]:
        logger.info(
            f"Generating callgraph from {len(self.functions)} functions and {len(self.classes)} classes"
        )
        self.detected_framework_name = self._detect_framework()
        logger.info(
            f"Framework detected: {self.detected_framework_name.capitalize() if self.detected_framework_name else 'Generic Python'}"
        )
        is_django = self.detected_framework_name == "django"
        
        # Add class nodes to the callgraph
        for class_name, class_info in self.classes.items():
            group = self._determine_group(class_name)
            raw_docstring = class_info.get("docstring", "Class documentation unavailable.")
            
            self.nodes.append(
                {
                    "id": class_name,
                    "group": group,
                    "type": "class",
                    "complexity": 0,  # Classes don't have complexity score
                    "file": class_info["file"],
                    "class": "",  # This is a class itself
                    "metadata": {
                        "raw_docstring": raw_docstring,
                        "source_code": class_info.get("source_code", ""),
                    },
                    "code_snippet": class_info.get("code_snippet", ""),
                    "lineno": class_info.get("lineno", 0)
                }
            )
        
        # Add function nodes to the callgraph
        for func_name, func_info in self.functions.items():
            group = self._determine_group(func_name)
            # LLM-based enrichment for purpose and suggestion is removed from here.
            # This information will be generated by LLMDocGeneratorService later.
            # Store raw docstring directly.
            raw_docstring = func_info.get("docstring", "Function documentation unavailable.")

            self.nodes.append(
                {
                    "id": func_name,
                    "group": group,
                    "type": func_info["type"],
                    "complexity": func_info["complexity"],
                    "file": func_info["file"],
                    "class": func_info.get("class", ""),
                    "metadata": {
                        "raw_docstring": raw_docstring,
                        # NEW: Include source code in metadata
                        "source_code": func_info.get("source_code", ""),
                    },
                    # Add other statically available info to metadata if needed
                    "code_snippet": func_info.get("code_snippet", ""),
                    "lineno": func_info.get("lineno", 0)
                }
            )
        already_linked = set()
        view_functions = set()
        if is_django:
            for func_name, func_info in self.functions.items():
                if self._is_django_view(func_name, func_info):
                    view_functions.add(func_name)
            logger.info(f"Found {len(view_functions)} Django view functions")
            
        # Add links between classes and their methods
        for func_name, func_info in self.functions.items():
            if func_info.get("type") == "method" and func_info.get("class"):
                class_name = func_info.get("class")
                if class_name in self.classes:
                    link_key = f"{class_name}->{func_name}"
                    if link_key not in already_linked:
                        self.links.append({
                            "source": class_name,
                            "target": func_name,
                            "value": 1,
                            "type": "contains",
                        })
                        already_linked.add(link_key)
        for func_name, func_info in self.functions.items():
            calls = self._find_function_calls(func_info["node"])
            if is_django:
                django_calls = self._find_django_specific_calls(
                    func_info["node"], func_name
                )
                calls.update(django_calls)
            module_name = func_info.get("module", "")
            func_file = func_info.get("file", "")
            for called_func in calls:
                link_key = f"{func_name}->{called_func}"
                if func_name == called_func or link_key in already_linked:
                    continue
                if called_func in self.functions:
                    self.links.append(
                        {
                            "source": func_name,
                            "target": called_func,
                            "value": 1,
                            "type": "call",
                        }
                    )
                    already_linked.add(link_key)
                    continue
                elif "." in called_func:
                    try:
                        class_name, method_name = called_func.rsplit(".", 1)
                        if class_name in self.classes:
                            for class_method in self.classes[class_name]["methods"]:
                                if class_method.endswith(f".{method_name}"):
                                    self.links.append(
                                        {
                                            "source": func_name,
                                            "target": class_method,
                                            "value": 1,
                                            "type": "call",
                                        }
                                    )
                                    already_linked.add(link_key)
                                    break
                    except Exception as e:
                        logger.debug(f"Error processing call '{called_func}': {str(e)}")
                elif is_django and func_name in view_functions:
                    for potential_func in self.functions:
                        if (
                            potential_func != func_name
                            and called_func in potential_func
                        ):
                            self.links.append(
                                {
                                    "source": func_name,
                                    "target": potential_func,
                                    "value": 1,
                                    "type": "django_call",
                                }
                            )
                            already_linked.add(link_key)
                            break
        if is_django and view_functions:
            self._add_django_url_pattern_links(view_functions, already_linked)
        avg_complexity = (
            sum(node["complexity"] for node in self.nodes) / len(self.nodes)
            if self.nodes
            else 0
        )
        most_complex = None
        if self.nodes:
            most_complex_node = max(self.nodes, key=lambda x: x["complexity"])
            most_complex = {
                "id": most_complex_node["id"],
                "complexity": most_complex_node["complexity"],
                "file": most_complex_node["file"],
            }
        return {
            "nodes": self.nodes,
            "links": self.links,
            "classes": list(self.classes.keys()),
            "imports": self.imports,
            "metadata": {
                "total_nodes": len(self.nodes),
                "total_links": len(self.links),
                "avg_complexity": avg_complexity,
                "functionCount": len(self.nodes),
                "dependencyCount": len(self.links),
                "mostComplexFunction": most_complex,
            },
        }
        return result

    def _calculate_complexity(self, node: ast.AST) -> int:
        complexity = 1
        for subnode in ast.walk(node):
            if isinstance(subnode, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(subnode, ast.BoolOp):
                complexity += len(subnode.values) - 1
            elif isinstance(subnode, ast.Try):
                complexity += len(subnode.handlers)
            elif isinstance(subnode, (ast.With, ast.AsyncWith)):
                complexity += 1
        return complexity

    def _find_function_calls(self, node: ast.AST) -> Set[str]:
        calls = set()
        module_info = self._get_module_context(node)
        current_module = module_info.get("module", "")
        local_vars = {}
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Assign):
                for target in subnode.targets:
                    if isinstance(target, ast.Name):
                        var_name = target.id
                        if isinstance(subnode.value, ast.Call) and isinstance(
                            subnode.value.func, ast.Name
                        ):
                            class_name = subnode.value.func.id
                            if (
                                hasattr(self, "import_aliases")
                                and current_module in self.import_aliases
                            ):
                                if class_name in self.import_aliases[current_module]:
                                    class_name = self.import_aliases[current_module][
                                        class_name
                                    ]
                            local_vars[var_name] = {
                                "type": "class",
                                "class": class_name,
                            }
                        elif isinstance(subnode.value, ast.Attribute):
                            module_path = self._get_attr_name(subnode.value)
                            local_vars[var_name] = {
                                "type": "module",
                                "path": module_path,
                            }
                        elif isinstance(subnode.value, ast.Name):
                            other_var = subnode.value.id
                            local_vars[var_name] = {
                                "type": "reference",
                                "ref": other_var,
                            }
                        elif isinstance(subnode.value, ast.List):
                            local_vars[var_name] = {"type": "list"}
                        elif isinstance(subnode.value, ast.Dict):
                            local_vars[var_name] = {"type": "dict"}
            elif isinstance(subnode, ast.Import):
                for alias in subnode.names:
                    name = alias.name
                    asname = alias.asname or name
                    local_vars[asname] = {"type": "import", "module": name}
            elif isinstance(subnode, ast.ImportFrom):
                if subnode.module:
                    module = subnode.module
                    for alias in subnode.names:
                        name = alias.name
                        asname = alias.asname or name
                        full_name = f"{module}.{name}"
                        local_vars[asname] = {
                            "type": "import",
                            "module": module,
                            "name": name,
                            "full": full_name,
                        }
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                if isinstance(subnode.func, ast.Name):
                    func_name = subnode.func.id
                    if (
                        func_name in local_vars
                        and local_vars[func_name].get("type") == "class"
                    ):
                        continue
                    resolved_names = self._resolve_function_name(
                        func_name, current_module
                    )
                    for resolved in resolved_names:
                        calls.add(resolved)
                    calls.add(func_name)
                elif isinstance(subnode.func, ast.Attribute):
                    method_name = subnode.func.attr
                    if isinstance(subnode.func.value, ast.Name):
                        obj_name = subnode.func.value.id
                        if obj_name == "self" and module_info.get("class"):
                            class_name = module_info.get("class")
                            calls.add(f"{class_name}.{method_name}")
                        elif obj_name in local_vars:
                            var_info = local_vars[obj_name]
                            if var_info.get("type") == "class":
                                class_name = var_info.get("class")
                                calls.add(f"{class_name}.{method_name}")
                            elif var_info.get("type") == "module":
                                module_path = var_info.get("path")
                                calls.add(f"{module_path}.{method_name}")
                            elif var_info.get("type") == "import":
                                if "full" in var_info:
                                    calls.add(f"{var_info['full']}.{method_name}")
                                else:
                                    calls.add(f"{var_info['module']}.{method_name}")
                        calls.add(f"{obj_name}.{method_name}")
                    elif isinstance(subnode.func.value, ast.Attribute):
                        attr_path = self._get_attr_path(subnode.func)
                        if attr_path:
                            calls.add(attr_path)
                            parts = attr_path.split(".")
                            if (
                                len(parts) >= 2
                                and parts[0] in local_vars
                                and local_vars[parts[0]].get("type") == "import"
                            ):
                                module = local_vars[parts[0]].get("module")
                                calls.add(f"{module}.{'.'.join(parts[1:])}")
                    elif isinstance(subnode.func.value, ast.Call):
                        inner_func = subnode.func.value.func
                        if isinstance(inner_func, ast.Name):
                            calls.add(f"{inner_func.id}.{method_name}")
                        elif isinstance(inner_func, ast.Attribute):
                            inner_path = self._get_attr_path(inner_func)
                            if inner_path:
                                calls.add(f"{inner_path}.{method_name}")
        resolved_calls = set()
        for call in calls:
            resolved = self._resolve_call(call, current_module)
            if resolved:
                resolved_calls.add(resolved)
            resolved_calls.add(call)
        return resolved_calls

    def _get_attr_path(self, node: ast.Attribute) -> str:
        path = []
        current = node
        while isinstance(current, ast.Attribute):
            path.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            path.insert(0, current.id)
            return ".".join(path)
        return None

    def _detect_framework(self) -> str:
        django_indicators = [
            "django",
            "settings.py",
            "urls.py",
            "wsgi.py",
            "models.py",
            "views.py",
            "from django",
            "import django",
        ]
        for class_name in self.classes.keys():
            if any(
                indicator in class_name.lower()
                for indicator in [
                    "modeladmin",
                    "listview",
                    "detailview",
                    "createview",
                    "updateview",
                    "deleteview",
                ]
            ):
                return "django"
        for func_info in self.functions.values():
            file_path = func_info.get("file", "")
            if any(indicator in file_path for indicator in django_indicators):
                return "django"
        for imports_list in self.imports.values():
            for import_name in imports_list:
                if import_name.startswith("django") or "django" in import_name:
                    return "django"
        return "python"

    def _is_django_view(self, func_name: str, func_info: dict) -> bool:
        if func_info.get("type") == "method":
            class_name = func_info.get("class", "")
            if any(
                base in class_name.lower()
                for base in [
                    "view",
                    "listview",
                    "detailview",
                    "createview",
                    "updateview",
                    "deleteview",
                    "formview",
                ]
            ):
                return True
            method_name = func_name.split(".")[-1]
            if method_name in ["get", "post", "put", "delete", "dispatch"]:
                return True
        else:
            if not func_info.get("node"):
                return False
            try:
                node = func_info["node"]
                args = node.args.args if hasattr(node, "args") else []
                if args and args[0].arg == "request":
                    return True
                file_path = func_info.get("file", "")
                if "views.py" in file_path and not func_name.startswith("_"):
                    return True
            except Exception as e:
                logger.debug(
                    f"Error checking if {func_name} is a Django view: {str(e)}"
                )
        return False

    def _find_django_specific_calls(self, node: ast.AST, func_name: str) -> Set[str]:
        django_calls = set()
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                if isinstance(subnode.func, ast.Name) and subnode.func.id == "render":
                    django_calls.add("render_template")
                elif isinstance(subnode.func, ast.Name) and subnode.func.id in [
                    "get_object_or_404",
                    "get_list_or_404",
                ]:
                    if subnode.args:
                        if isinstance(subnode.args[0], ast.Name):
                            model_name = subnode.args[0].id
                            for class_name in self.classes.keys():
                                if class_name.endswith(f".{model_name}"):
                                    django_calls.add(f"{class_name}.objects.get")
                                    django_calls.add(f"{class_name}.objects.filter")
                                    break
                elif isinstance(subnode.func, ast.Attribute) and isinstance(
                    subnode.func.value, ast.Attribute
                ):
                    if subnode.func.attr in [
                        "get",
                        "filter",
                        "all",
                        "create",
                        "update",
                    ]:
                        if (
                            hasattr(subnode.func.value, "attr")
                            and subnode.func.value.attr == "objects"
                        ):
                            if isinstance(subnode.func.value.value, ast.Name):
                                model_name = subnode.func.value.value.id
                                for class_name in self.classes.keys():
                                    if class_name.endswith(f".{model_name}"):
                                        django_calls.add(
                                            f"{class_name}.objects.{subnode.func.attr}"
                                        )
                                        break
        return django_calls

    def _add_django_url_pattern_links(
        self, view_functions: Set[str], already_linked: Set[str]
    ) -> None:
        for func_name in self.functions.keys():
            func_info = self.functions[func_name]
            file_path = func_info.get("file", "")
            if "urls.py" in file_path:
                node = func_info.get("node")
                if not node:
                    continue
                for view_func in view_functions:
                    view_name = view_func.split(".")[-1]
                    for subnode in ast.walk(node):
                        if isinstance(subnode, ast.Name) and subnode.id == view_name:
                            link_key = f"{func_name}->{view_func}"
                            if link_key not in already_linked:
                                self.links.append(
                                    {
                                        "source": func_name,
                                        "target": view_func,
                                        "value": 1,
                                        "type": "url_pattern",
                                    }
                                )
                                already_linked.add(link_key)
                        elif isinstance(subnode, ast.Str) and view_name in subnode.s:
                            link_key = f"{func_name}->{view_func}"
                            if link_key not in already_linked:
                                self.links.append(
                                    {
                                        "source": func_name,
                                        "target": view_func,
                                        "value": 1,
                                        "type": "url_pattern",
                                    }
                                )
                                already_linked.add(link_key)

    def _resolve_function_name(self, func_name: str, module_name: str) -> List[str]:
        resolved = []
        for full_name in self.functions.keys():
            if full_name.endswith(f".{func_name}"):
                resolved.append(full_name)
        if hasattr(self, "import_aliases") and module_name in self.import_aliases:
            aliases = self.import_aliases[module_name]
            if func_name in aliases:
                resolved.append(aliases[func_name])
        if module_name:
            resolved.append(f"{module_name}.{func_name}")
        return resolved

    def _resolve_call(self, call: str, module_name: str) -> str:
        if call in self.functions:
            return call
        if "." not in call and module_name:
            full_name = f"{module_name}.{call}"
            if full_name in self.functions:
                return full_name
        if "." in call:
            obj, method = call.split(".", 1)
            if obj == "self" and module_name:
                for func_name in self.functions:
                    if func_name.endswith(f".{method}") and module_name in func_name:
                        return func_name
        return None

    def _get_module_context(self, node: ast.AST) -> Dict[str, str]:
        context = {}
        func_name = None
        for name, info in self.functions.items():
            if info.get("node") == node:
                func_name = name
                context["module"] = info.get("module", "")
                if "class" in info:
                    context["class"] = info["class"]
                break
        if not func_name:
            parents = self._get_all_parents(node)
            for parent in parents:
                if isinstance(parent, ast.ClassDef):
                    context["class"] = parent.name
                elif isinstance(parent, ast.Module) and hasattr(parent, "name"):
                    context["module"] = parent.name
        return context

    def _get_module_name(self, node: ast.AST) -> str:
        if hasattr(node, "parent") and isinstance(node.parent, ast.ClassDef):
            class_node = node.parent
            if hasattr(class_node, "parent") and isinstance(
                class_node.parent, ast.Module
            ):
                for func_name, func_info in self.functions.items():
                    if func_info.get("node") == node:
                        parts = func_name.split(".")
                        if len(parts) > 1:
                            return ".".join(parts[:-2])
        for func_name, func_info in self.functions.items():
            if func_info.get("node") == node:
                parts = func_name.split(".")
                if len(parts) > 1:
                    return ".".join(parts[:-1])
        return None
        return calls

    def _determine_group(self, func_name: str) -> int:
        if "." in func_name:
            parts = func_name.split(".")
            if len(parts) > 2:
                return hash(parts[0] + "." + parts[1]) % 10
            return hash(parts[0]) % 10
        return 0

    async def cleanup(self):
        if self.tmp_dir and os.path.exists(self.tmp_dir):
            logger.info(f"Attempting to cleanup temporary directory: {self.tmp_dir}")
            # Retry mechanism for cleanup, especially for Windows file locking issues
            for attempt in range(3):
                try:
                    # Ensure all handles to .git folder are released
                    # This can be tricky, sometimes just a small delay helps
                    if os.path.exists(os.path.join(self.tmp_dir, '.git')):
                        # Attempt to clear read-only flags on .git files if they exist
                        for root, dirs, files in os.walk(os.path.join(self.tmp_dir, '.git')):
                            for name in files:
                                try:
                                    filepath = os.path.join(root, name)
                                    os.chmod(filepath, 0o777) # stat.S_IWRITE | stat.S_IREAD | stat.S_IEXEC
                                except Exception as e_chmod:
                                    logger.debug(f"Failed to chmod {filepath}: {e_chmod}")
                            for name in dirs:
                                try:
                                    dirpath = os.path.join(root, name)
                                    os.chmod(dirpath, 0o777)
                                except Exception as e_chmod:
                                    logger.debug(f"Failed to chmod {dirpath}: {e_chmod}")

                    shutil.rmtree(self.tmp_dir)
                    logger.info(f"Successfully cleaned up temporary directory: {self.tmp_dir}")
                    self.tmp_dir = None # Reset tmp_dir after successful cleanup
                    return
                except PermissionError as e_perm:
                    logger.warning(f"Cleanup attempt {attempt + 1} failed with PermissionError: {e_perm}")
                    if attempt < 2:
                        await asyncio.sleep(2)  # Wait for 2 seconds before retrying
                    else:
                        logger.error(f"Failed to cleanup temporary directory {self.tmp_dir} after multiple attempts due to PermissionError: {e_perm}")
                        # Optionally, log which file is causing the issue if possible from the error
                        if hasattr(e_perm, 'filename') and e_perm.filename:
                            logger.error(f"Access denied on file: {e_perm.filename}")
                        # Even if cleanup fails, we might not want to raise an exception if ignore_errors was the previous behavior
                        # For now, we log the error and continue, similar to ignore_errors=True
                        break # Exit loop after final attempt
                except Exception as e:
                    logger.error(f"An unexpected error occurred during cleanup attempt {attempt + 1} for {self.tmp_dir}: {e}")
                    if attempt < 2:
                        await asyncio.sleep(1)
                    else:
                        # Log and continue, similar to ignore_errors=True behavior
                        break # Exit loop after final attempt
            # If self.tmp_dir still exists, log that cleanup ultimately failed.
            if self.tmp_dir and os.path.exists(self.tmp_dir):
                logger.error(f"Cleanup of {self.tmp_dir} ultimately failed. Some files might remain.")
        elif self.tmp_dir:
            logger.info(f"Temporary directory {self.tmp_dir} not found, no cleanup needed or already cleaned.")
        else:
            logger.info("No temporary directory was set (self.tmp_dir is None), no cleanup performed by this instance.")
\n\n# ==============================\n# Filename: services\callgraph_enrichment_service.py\n# ==============================\n\ndef enrich_django(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "views." in node["id"]:
            node["framework"] = "django"
            node["type"] = "view"
            if node["id"].endswith("View"):
                node["tags"] = ["class-based-view"]
            elif "api_" in node["id"]:
                node["tags"] = ["api-view"]
    return callgraph

def enrich_flask(callgraph: dict) -> dict:
    for node in callgraph["nodes"]:
        if "routes." in node["id"] or "blueprints." in node["id"]:
            node["framework"] = "flask"
            node["type"] = "route"
            if "get_" in node["id"]:
                node["tags"] = ["http-get"]
            elif "post_" in node["id"]:
                node["tags"] = ["http-post"]
    return callgraph\n\n# ==============================\n# Filename: services\codebase_data_service.py\n# ==============================\n\nimport logging
from typing import Dict, List, Optional, Any
from datetime import datetime

from app.models.callgraph import CallgraphData, CallgraphDataDB, CallgraphDataCreate
from app.services.database import get_database
from bson.objectid import ObjectId

logger = logging.getLogger(__name__)

class CodebaseDataService:
    """Service for accessing and managing codebase data."""
    
    def __init__(self, database=None):
        self.db = database
        self.collection = "callgraph_data"
        
    async def initialize(self):
        """Initialize the service with database connection."""
        if self.db is None:
            self.db = await get_database()
            
    async def store_callgraph(self, callgraph_data: CallgraphDataCreate) -> str:
        """
        Store callgraph data in the database.
        
        Args:
            callgraph_data: The callgraph data to store
            
        Returns:
            The ID of the stored callgraph data
        """
        await self.initialize()
        
        # Check if a callgraph for this repository already exists
        existing = await self.db[self.collection].find_one({"repository_id": callgraph_data.repository_id})
        
        now = datetime.utcnow()
        
        if existing:
            # Update existing record
            callgraph_dict = callgraph_data.dict()
            callgraph_dict["updated_at"] = now
            
            await self.db[self.collection].update_one(
                {"_id": existing["_id"]},
                {"$set": callgraph_dict}
            )
            
            return str(existing["_id"])
        else:
            # Create new record
            callgraph_dict = callgraph_data.dict()
            callgraph_dict["created_at"] = now
            callgraph_dict["updated_at"] = now
            
            result = await self.db[self.collection].insert_one(callgraph_dict)
            
            return str(result.inserted_id)
            
    async def get_callgraph(self, repository_id: str) -> Optional[CallgraphDataDB]:
        """
        Retrieve callgraph data for a repository.
        
        Args:
            repository_id: The ID of the repository
            
        Returns:
            The callgraph data or None if not found
        """
        await self.initialize()
        
        data = await self.db[self.collection].find_one({"repository_id": repository_id})
        
        if data:
            data["id"] = str(data.pop("_id"))
            return CallgraphDataDB(**data)
        
        return None
        
    async def get_callgraph_by_id(self, callgraph_id: str) -> Optional[CallgraphDataDB]:
        """
        Retrieve callgraph data by its ID.
        
        Args:
            callgraph_id: The ID of the callgraph data
            
        Returns:
            The callgraph data or None if not found
        """
        await self.initialize()
        
        try:
            data = await self.db[self.collection].find_one({"_id": ObjectId(callgraph_id)})
            
            if data:
                data["id"] = str(data.pop("_id"))
                return CallgraphDataDB(**data)
        except Exception as e:
            logger.error(f"Error retrieving callgraph by ID: {e}")
            
        return None
        
    async def get_code_elements(self, repository_id: str) -> List[Dict[str, Any]]:
        """
        Extract code elements from callgraph nodes.
        
        Args:
            repository_id: The ID of the repository
            
        Returns:
            List of code elements with their metadata
        """
        callgraph = await self.get_callgraph(repository_id)
        
        if not callgraph:
            return []
            
        elements = []
        for node in callgraph.nodes:
            element = node.dict()
            # Add any transformations or additional data here
            elements.append(element)
            
        return elements
        
    async def get_relationships(self, repository_id: str) -> List[Dict[str, Any]]:
        """
        Extract relationships from callgraph links.
        
        Args:
            repository_id: The ID of the repository
            
        Returns:
            List of relationships with their metadata
        """
        callgraph = await self.get_callgraph(repository_id)
        
        if not callgraph:
            return []
            
        relationships = []
        for link in callgraph.links:
            relationship = link.dict()
            # Add any transformations or additional data here
            relationships.append(relationship)
            
        return relationships
        
    async def get_element_by_id(self, repository_id: str, element_id: str) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific code element by its ID.
        
        Args:
            repository_id: The ID of the repository
            element_id: The ID of the code element
            
        Returns:
            The code element or None if not found
        """
        callgraph = await self.get_callgraph(repository_id)
        
        if not callgraph:
            return None
            
        for node in callgraph.nodes:
            if node.id == element_id:
                return node.dict()
                
        return None
        
    async def get_related_elements(self, repository_id: str, element_id: str) -> Dict[str, List[Dict[str, Any]]]:
        """
        Get elements related to a specific code element.
        
        Args:
            repository_id: The ID of the repository
            element_id: The ID of the code element
            
        Returns:
            Dictionary with 'callers' and 'callees' lists
        """
        callgraph = await self.get_callgraph(repository_id)
        
        if not callgraph:
            return {"callers": [], "callees": []}
            
        # Find links where the element is the source (outgoing calls)
        callees_links = [link for link in callgraph.links if link.source == element_id]
        
        # Find links where the element is the target (incoming calls)
        callers_links = [link for link in callgraph.links if link.target == element_id]
        
        # Get the actual node data for callees
        callees = []
        for link in callees_links:
            for node in callgraph.nodes:
                if node.id == link.target:
                    callee = node.dict()
                    callee["relationship"] = link.dict()
                    callees.append(callee)
                    break
                    
        # Get the actual node data for callers
        callers = []
        for link in callers_links:
            for node in callgraph.nodes:
                if node.id == link.source:
                    caller = node.dict()
                    caller["relationship"] = link.dict()
                    callers.append(caller)
                    break
                    
        return {
            "callers": callers,
            "callees": callees
        }
        
    async def delete_callgraph(self, repository_id: str) -> bool:
        """
        Delete callgraph data for a repository.
        
        Args:
            repository_id: The ID of the repository
            
        Returns:
            True if successfully deleted, False otherwise
        """
        await self.initialize()
        
        result = await self.db[self.collection].delete_one({"repository_id": repository_id})
        
        return result.deleted_count > 0
\n\n# ==============================\n# Filename: services\context_flow_analysis.py\n# ==============================\n\nimport ast
import os
import logging
from typing import Dict, Set, List, Tuple, Optional, Any, Union
import networkx as nx
from collections import defaultdict
from .abstract_interpretation import AbstractInterpreter, KCFACallGraphBuilder


class ContextualCallPath:
    def __init__(
        self,
        source: str,
        target: str,
        source_context: Tuple[str, ...] = None,
        target_context: Tuple[str, ...] = None,
    ):
        self.source = source
        self.target = target
        self.source_context = source_context or tuple()
        self.target_context = target_context or tuple()

    def __eq__(self, other):
        if not isinstance(other, ContextualCallPath):
            return False
        return (
            self.source == other.source
            and self.target == other.target
            and self.source_context == other.source_context
            and self.target_context == other.target_context
        )

    def __hash__(self):
        return hash(
            (self.source, self.target, self.source_context, self.target_context)
        )

    def __str__(self):
        source_ctx = f"[{':'.join(self.source_context)}]" if self.source_context else ""
        target_ctx = f"[{':'.join(self.target_context)}]" if self.target_context else ""
        return f"{self.source}{source_ctx} -> {self.target}{target_ctx}"

    def __repr__(self):
        return self.__str__()


class ContextFlowAnalyzer:
    def __init__(self, k: int = 2, max_depth: int = 8):
        self.k = k
        self.max_depth = max_depth
        self.callgraph_builder = KCFACallGraphBuilder(k, max_depth)
        self.context_paths = set()
        self.infeasible_paths = set()
        self.value_flow = {}
        self.polymorphic_calls = defaultdict(set)

    def analyze_files(self, file_paths: List[str], file_contents: List[str]) -> Dict:
        results = {}
        for path, content in zip(file_paths, file_contents):
            file_result = self.callgraph_builder.analyze_file(path, content)
            if "error" not in file_result:
                results[path] = file_result
                for caller, callees in file_result["context_callgraph"].items():
                    caller_parts = caller.split(":")
                    caller_context = tuple(caller_parts[:-1])
                    caller_function = caller_parts[-1]
                    for callee in callees:
                        callee_parts = callee.split(":")
                        callee_context = tuple(callee_parts[:-1])
                        callee_function = callee_parts[-1]
                        path = ContextualCallPath(
                            caller_function,
                            callee_function,
                            caller_context,
                            callee_context,
                        )
                        self.context_paths.add(path)
        self._identify_infeasible_paths()
        self._analyze_value_flow()
        self._detect_polymorphic_calls()
        return {
            "context_paths": self.context_paths,
            "infeasible_paths": self.infeasible_paths,
            "polymorphic_calls": self.polymorphic_calls,
            "value_flow": self.value_flow,
        }

    def _identify_infeasible_paths(self) -> None:
        graph = nx.DiGraph()
        for path in self.context_paths:
            source_key = f"{':'.join(path.source_context)}:{path.source}"
            target_key = f"{':'.join(path.target_context)}:{path.target}"
            graph.add_edge(source_key, target_key)
        entry_points = [
            node
            for node in graph.nodes()
            if graph.in_degree(node) == 0 or node.count(":") == 0
        ]
        reachable = set()
        for entry in entry_points:
            reachable.update(nx.descendants(graph, entry))
            reachable.add(entry)
        for path in self.context_paths:
            source_key = f"{':'.join(path.source_context)}:{path.source}"
            target_key = f"{':'.join(path.target_context)}:{path.target}"
            if source_key not in reachable or target_key not in reachable:
                self.infeasible_paths.add(path)

    def _analyze_value_flow(self) -> None:
        pass

    def _detect_polymorphic_calls(self) -> None:
        call_sites = defaultdict(set)
        for path in self.context_paths:
            if path not in self.infeasible_paths:
                source_with_ctx = (path.source, path.source_context)
                call_sites[source_with_ctx].add(path.target)
        for source, targets in call_sites.items():
            if len(targets) > 1:
                function, context = source
                self.polymorphic_calls[function].update(targets)

    def to_enhanced_callgraph(self) -> Dict:
        nodes = []
        links = []
        node_ids = set()
        for path in self.context_paths:
            if path.source not in node_ids:
                nodes.append(
                    {
                        "id": path.source,
                        "name": path.source.split(".")[-1],
                        "type": "function",
                        "group": 1,
                        "complexity": 1,
                        "metadata": {
                            "contexts": [":".join(path.source_context)],
                            "polymorphic": path.source in self.polymorphic_calls,
                        },
                    }
                )
                node_ids.add(path.source)
            if path.target not in node_ids:
                nodes.append(
                    {
                        "id": path.target,
                        "name": path.target.split(".")[-1],
                        "type": "function",
                        "group": 1,
                        "complexity": 1,
                        "metadata": {
                            "contexts": [":".join(path.target_context)],
                            "polymorphic": path.target in self.polymorphic_calls,
                        },
                    }
                )
                node_ids.add(path.target)
        basic_links = defaultdict(int)
        context_counts = defaultdict(int)
        for path in self.context_paths:
            if path not in self.infeasible_paths:
                key = (path.source, path.target)
                basic_links[key] += 1
                context_counts[key] += 1
        for (source, target), count in basic_links.items():
            links.append(
                {
                    "source": source,
                    "target": target,
                    "value": count,
                    "type": "call",
                    "context_count": context_counts[(source, target)],
                }
            )
        return {
            "nodes": nodes,
            "links": links,
            "metadata": {
                "context_sensitive": True,
                "k": self.k,
                "infeasible_paths_count": len(self.infeasible_paths),
                "polymorphic_calls_count": sum(
                    len(targets) for targets in self.polymorphic_calls.values()
                ),
            },
        }


class TypeInferenceEngine:
    def __init__(self, analyzer: ContextFlowAnalyzer):
        self.analyzer = analyzer
        self.inferred_types = {}

    def infer_types(self) -> Dict:
        return self.inferred_types

    def _add_visualization_attributes(self, callgraph: Dict) -> None:
        types = self.infer_types()
        for node in callgraph["nodes"]:
            node_id = node["id"]
            if node_id in types:
                if "metadata" not in node:
                    node["metadata"] = {}
                node["metadata"]["inferred_types"] = types[node_id]

    def enhance_callgraph(self, callgraph: Dict) -> Dict:
        types = self.infer_types()
        for node in callgraph["nodes"]:
            node_id = node["id"]
            if node_id in types:
                if "metadata" not in node:
                    node["metadata"] = {}
                node["metadata"]["inferred_types"] = types[node_id]
        return callgraph
\n\n# ==============================\n# Filename: services\control_flow.py\n# ==============================\n\nimport ast
from typing import Dict, List, Set, Optional, Tuple, Any, Union
import logging

logger = logging.getLogger(__name__)


class CFGBlock:
    def __init__(self, id: int):
        self.id = id
        self.statements: List[ast.AST] = []
        self.predecessors: Set["CFGBlock"] = set()
        self.successors: Set["CFGBlock"] = set()
        self.in_vars: Set[str] = set()
        self.out_vars: Set[str] = set()
        self.entry_point = False
        self.exit_point = False
        self.condition: Optional[ast.AST] = None

    def add_statement(self, statement: ast.AST) -> None:
        self.statements.append(statement)

    def add_successor(
        self, block: "CFGBlock", condition: Optional[ast.AST] = None
    ) -> None:
        self.successors.add(block)
        block.predecessors.add(self)
        if condition:
            block.condition = condition

    def __repr__(self) -> str:
        return (
            f"CFGBlock(id={self.id}, statements={len(self.statements)}, "
            f"predecessors={len(self.predecessors)}, successors={len(self.successors)})"
        )


class ControlFlowGraph:
    def __init__(self):
        self.blocks: List[CFGBlock] = []
        self.entry_block: Optional[CFGBlock] = None
        self.exit_block: Optional[CFGBlock] = None
        self.current_block: Optional[CFGBlock] = None
        self._block_counter = 0

    def create_block(self) -> CFGBlock:
        block = CFGBlock(self._block_counter)
        self._block_counter += 1
        self.blocks.append(block)
        return block

    def set_entry_block(self, block: CFGBlock) -> None:
        self.entry_block = block
        block.entry_point = True
        self.current_block = block

    def set_exit_block(self, block: CFGBlock) -> None:
        self.exit_block = block
        block.exit_point = True

    def add_statement(self, statement: ast.AST) -> None:
        if not self.current_block:
            self.current_block = self.create_block()
            if not self.entry_block:
                self.set_entry_block(self.current_block)
        self.current_block.add_statement(statement)

    def connect_blocks(
        self, source: CFGBlock, target: CFGBlock, condition: Optional[ast.AST] = None
    ) -> None:
        source.add_successor(target, condition)

    def __repr__(self) -> str:
        return f"ControlFlowGraph(blocks={len(self.blocks)})"


class CFGBuilder:
    def __init__(self):
        self.cfg = ControlFlowGraph()
        self.break_stack: List[List[CFGBlock]] = []
        self.continue_stack: List[List[CFGBlock]] = []
        self.current_loop_entry: List[CFGBlock] = []

    def build(self, node: Union[ast.AST, List[ast.AST]]) -> ControlFlowGraph:
        self.cfg.set_entry_block(self.cfg.create_block())
        exit_block = self.cfg.create_block()
        self.cfg.set_exit_block(exit_block)
        if isinstance(node, list):
            self._process_body(node)
        else:
            self._process_node(node)
        if self.cfg.current_block and self.cfg.current_block != exit_block:
            self.cfg.connect_blocks(self.cfg.current_block, exit_block)
        return self.cfg

    def _process_body(self, body: List[ast.AST]) -> None:
        for statement in body:
            self._process_node(statement)

    def _process_node(self, node: ast.AST) -> None:
        if isinstance(node, ast.If):
            self._process_if(node)
        elif isinstance(node, ast.For) or isinstance(node, ast.AsyncFor):
            self._process_for(node)
        elif isinstance(node, ast.While):
            self._process_while(node)
        elif isinstance(node, ast.Try):
            self._process_try(node)
        elif isinstance(node, ast.Break):
            self._process_break()
        elif isinstance(node, ast.Continue):
            self._process_continue()
        elif isinstance(node, ast.Return):
            self._process_return(node)
        elif isinstance(node, ast.Raise):
            self._process_raise(node)
        elif isinstance(node, ast.With) or isinstance(node, ast.AsyncWith):
            self._process_with(node)
        else:
            self.cfg.add_statement(node)

    def _process_if(self, node: ast.If) -> None:
        before_if = self.cfg.current_block
        true_block = self.cfg.create_block()
        false_block = self.cfg.create_block()
        after_if = self.cfg.create_block()
        self.cfg.connect_blocks(before_if, true_block, node.test)
        if hasattr(ast, "UnaryOp"):
            not_test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        else:
            not_test = ast.Not(node.test)
        self.cfg.connect_blocks(before_if, false_block, not_test)
        self.cfg.current_block = true_block
        self._process_body(node.body)
        true_end = self.cfg.current_block
        self.cfg.current_block = false_block
        if node.orelse:
            self._process_body(node.orelse)
        false_end = self.cfg.current_block
        if true_end and true_end != after_if:
            self.cfg.connect_blocks(true_end, after_if)
        if false_end and false_end != after_if:
            self.cfg.connect_blocks(false_end, after_if)
        self.cfg.current_block = after_if

    def _process_for(self, node: Union[ast.For, ast.AsyncFor]) -> None:
        loop_header = self.cfg.create_block()
        loop_body = self.cfg.create_block()
        after_loop = self.cfg.create_block()
        self.cfg.connect_blocks(self.cfg.current_block, loop_header)
        loop_header.add_statement(node)
        self.cfg.connect_blocks(loop_header, loop_body, node.iter)
        self.cfg.connect_blocks(loop_header, after_loop)
        self.break_stack.append([after_loop])
        self.continue_stack.append([loop_header])
        self.current_loop_entry.append(loop_header)
        self.cfg.current_block = loop_body
        self._process_body(node.body)
        if node.orelse:
            else_block = self.cfg.create_block()
            self.cfg.connect_blocks(self.cfg.current_block, else_block)
            self.cfg.current_block = else_block
            self._process_body(node.orelse)
            self.cfg.connect_blocks(self.cfg.current_block, after_loop)
        else:
            self.cfg.connect_blocks(self.cfg.current_block, loop_header)
        self.break_stack.pop()
        self.continue_stack.pop()
        self.current_loop_entry.pop()
        self.cfg.current_block = after_loop

    def _process_while(self, node: ast.While) -> None:
        loop_cond = self.cfg.create_block()
        loop_body = self.cfg.create_block()
        after_loop = self.cfg.create_block()
        self.cfg.connect_blocks(self.cfg.current_block, loop_cond)
        loop_cond.add_statement(node)
        self.cfg.connect_blocks(loop_cond, loop_body, node.test)
        if hasattr(ast, "UnaryOp"):
            not_test = ast.UnaryOp(op=ast.Not(), operand=node.test)
        else:
            not_test = ast.Not(node.test)
        self.cfg.connect_blocks(loop_cond, after_loop, not_test)
        self.break_stack.append([after_loop])
        self.continue_stack.append([loop_cond])
        self.current_loop_entry.append(loop_cond)
        self.cfg.current_block = loop_body
        self._process_body(node.body)
        if node.orelse:
            else_block = self.cfg.create_block()
            self.cfg.connect_blocks(self.cfg.current_block, else_block)
            self.cfg.current_block = else_block
            self._process_body(node.orelse)
            self.cfg.connect_blocks(self.cfg.current_block, after_loop)
        else:
            self.cfg.connect_blocks(self.cfg.current_block, loop_cond)
        self.break_stack.pop()
        self.continue_stack.pop()
        self.current_loop_entry.pop()
        self.cfg.current_block = after_loop

    def _process_try(self, node: ast.Try) -> None:
        try_block = self.cfg.create_block()
        handler_blocks = [self.cfg.create_block() for _ in node.handlers]
        else_block = self.cfg.create_block() if node.orelse else None
        finally_block = self.cfg.create_block() if node.finalbody else None
        after_try = self.cfg.create_block()
        self.cfg.connect_blocks(self.cfg.current_block, try_block)
        self.cfg.current_block = try_block
        self._process_body(node.body)
        if node.orelse:
            self.cfg.connect_blocks(self.cfg.current_block, else_block)
        for i, handler in enumerate(node.handlers):
            exc_type = handler.type
            handler_block = handler_blocks[i]
            self.cfg.connect_blocks(try_block, handler_block, exc_type)
            self.cfg.current_block = handler_block
            self._process_body(handler.body)
            if finally_block:
                self.cfg.connect_blocks(self.cfg.current_block, finally_block)
            else:
                self.cfg.connect_blocks(self.cfg.current_block, after_try)
        if else_block:
            self.cfg.current_block = else_block
            self._process_body(node.orelse)
            if finally_block:
                self.cfg.connect_blocks(self.cfg.current_block, finally_block)
            else:
                self.cfg.connect_blocks(self.cfg.current_block, after_try)
        if finally_block:
            self.cfg.current_block = finally_block
            self._process_body(node.finalbody)
            self.cfg.connect_blocks(self.cfg.current_block, after_try)
        self.cfg.current_block = after_try

    def _process_break(self) -> None:
        if not self.break_stack:
            logger.warning("Break statement outside of a loop")
            return
        self.cfg.add_statement(ast.Break())
        for target in self.break_stack[-1]:
            self.cfg.connect_blocks(self.cfg.current_block, target)
        self.cfg.current_block = self.cfg.create_block()

    def _process_continue(self) -> None:
        if not self.continue_stack:
            logger.warning("Continue statement outside of a loop")
            return
        self.cfg.add_statement(ast.Continue())
        for target in self.continue_stack[-1]:
            self.cfg.connect_blocks(self.cfg.current_block, target)
        self.cfg.current_block = self.cfg.create_block()

    def _process_return(self, node: ast.Return) -> None:
        self.cfg.add_statement(node)
        self.cfg.connect_blocks(self.cfg.current_block, self.cfg.exit_block)
        self.cfg.current_block = self.cfg.create_block()

    def _process_raise(self, node: ast.Raise) -> None:
        self.cfg.add_statement(node)
        self.cfg.current_block = self.cfg.create_block()

    def _process_with(self, node: Union[ast.With, ast.AsyncWith]) -> None:
        self.cfg.add_statement(node)
        self._process_body(node.body)


class FlowSensitiveAnalyzer:
    def __init__(self):
        self.cfg_builder = CFGBuilder()

    def analyze_function(
        self, node: Union[ast.FunctionDef, ast.AsyncFunctionDef]
    ) -> ControlFlowGraph:
        cfg = self.cfg_builder.build(node.body)
        self._analyze_data_flow(cfg)
        return cfg

    def _analyze_data_flow(self, cfg: ControlFlowGraph) -> None:
        for block in cfg.blocks:
            block.in_vars = set()
            block.out_vars = set()
        changed = True
        while changed:
            changed = False
            for block in cfg.blocks:
                if block.entry_point:
                    continue
                old_in = block.in_vars.copy()
                block.in_vars = set()
                for pred in block.predecessors:
                    block.in_vars.update(pred.out_vars)
                if old_in != block.in_vars:
                    changed = True
                old_out = block.out_vars.copy()
                block.out_vars = self._process_block_variables(
                    block, block.in_vars.copy()
                )
                if old_out != block.out_vars:
                    changed = True

    def _process_block_variables(self, block: CFGBlock, in_vars: Set[str]) -> Set[str]:
        out_vars = in_vars.copy()
        for stmt in block.statements:
            if isinstance(stmt, ast.Assign):
                for target in stmt.targets:
                    if isinstance(target, ast.Name):
                        out_vars.add(target.id)
                    elif isinstance(target, (ast.Tuple, ast.List)) and hasattr(
                        target, "elts"
                    ):
                        for elt in target.elts:
                            if isinstance(elt, ast.Name):
                                out_vars.add(elt.id)
            elif isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
                out_vars.add(stmt.target.id)
            elif isinstance(stmt, (ast.With, ast.AsyncWith)):
                for item in stmt.items:
                    if item.optional_vars and isinstance(item.optional_vars, ast.Name):
                        out_vars.add(item.optional_vars.id)
            elif isinstance(stmt, (ast.For, ast.AsyncFor)) and isinstance(
                stmt.target, ast.Name
            ):
                out_vars.add(stmt.target.id)
            elif isinstance(
                stmt, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            ):
                out_vars.add(stmt.name)
        return out_vars
\n\n# ==============================\n# Filename: services\database.py\n# ==============================\n\nimport logging
import motor.motor_asyncio
import os
from ..models.base import settings

logger = logging.getLogger(__name__)

# MongoDB client instance (initialized lazily)
_client = None
_db = None

# Check if MongoDB URI is provided in environment or config
def get_mongodb_uri():
    # First try environment variable
    mongo_uri = os.environ.get("MONGODB_URI")
    if mongo_uri:
        return mongo_uri
        
    # Try settings
    mongo_uri = getattr(settings, "MONGODB_URI", None)
    if mongo_uri:
        return mongo_uri
        
    # Fallback: use localhost with the app name as db
    return "mongodb://localhost:27017/graphix"

async def get_database():
    """
    Get a MongoDB database instance for storing callgraph data.
    
    This is a singleton factory that initializes the MongoDB connection
    on first call and returns the database instance on subsequent calls.
    
    Returns:
        Motor AsyncIOMotorDatabase instance
    """
    global _client, _db
    
    if _db is None:
        mongo_uri = get_mongodb_uri()
        db_name = os.environ.get("MONGODB_DB_NAME", "graphix")
        
        # Extract database name from URI if present in the URI itself
        if "/" in mongo_uri.split("://")[-1] and not mongo_uri.endswith("/"):
            uri_parts = mongo_uri.split("/")
            if len(uri_parts) > 3:  # protocol://host:port/dbname
                db_name = uri_parts[-1].split("?")[0]  # Remove query parameters if any
                mongo_uri = "/".join(uri_parts[:-1])  # Remove dbname from URI
        
        try:
            logger.info(f"Connecting to MongoDB for callgraph data storage")
            _client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
            _db = _client[db_name]
            
            # Verify connection
            await _db.command("ping")
            logger.info(f"Connected to MongoDB database: {db_name}")
            
            # Create necessary indexes for callgraph data if they don't exist
            await _db["callgraph_data"].create_index("repository_id", unique=True)
        except Exception as e:
            logger.error(f"Failed to connect to MongoDB: {str(e)}")
            logger.error("Using in-memory fallback for callgraph data. This is not suitable for production!")
            
            # Create an in-memory database for development/testing
            # This is a proper async-compatible mock
            class AsyncMockCollection:
                def __init__(self, name):
                    self.name = name
                    self.data = {}
                
                async def find_one(self, query):
                    # Simple implementation that checks repository_id
                    repo_id = query.get("repository_id")
                    return self.data.get(repo_id)
                
                async def insert_one(self, document):
                    # Store by repository_id
                    class MockResult:
                        def __init__(self, id_value):
                            self.inserted_id = id_value
                    
                    doc_id = str(len(self.data) + 1)  # Simple ID generation
                    repo_id = document.get("repository_id")
                    if repo_id:
                        document["_id"] = doc_id
                        self.data[repo_id] = document
                    return MockResult(doc_id)
                
                async def update_one(self, query, update):
                    # Simple implementation that updates by repository_id
                    class MockResult:
                        def __init__(self, count):
                            self.modified_count = count
                    
                    repo_id = query.get("repository_id")
                    if repo_id in self.data:
                        # Apply updates
                        if "$set" in update:
                            for key, value in update["$set"].items():
                                self.data[repo_id][key] = value
                        return MockResult(1)
                    return MockResult(0)
                
                async def delete_one(self, query):
                    # Simple implementation that deletes by repository_id
                    class MockResult:
                        def __init__(self, count):
                            self.deleted_count = count
                    
                    repo_id = query.get("repository_id")
                    if repo_id in self.data:
                        del self.data[repo_id]
                        return MockResult(1)
                    return MockResult(0)
                
                async def create_index(self, field_name, unique=False):
                    # Mock index creation
                    return field_name
            
            class AsyncMockDatabase:
                def __init__(self):
                    self.collections = {}
                
                def __getitem__(self, collection_name):
                    if collection_name not in self.collections:
                        self.collections[collection_name] = AsyncMockCollection(collection_name)
                    return self.collections[collection_name]
                
                async def command(self, command_name):
                    # Mock ping command
                    if command_name == "ping":
                        return {"ok": 1}
                    return {"ok": 0}
            
            _db = AsyncMockDatabase()
            logger.warning("Using in-memory mock database - data will not persist!")
    
    return _db
\n\n# ==============================\n# Filename: services\definition_manager.py\n# ==============================\n\nimport ast
from typing import Dict, List, Optional, Set, Any, Tuple
import os


class Definition:
    def __init__(self, name: str, qualified_name: str, node: ast.AST, file_path: str):
        self.name = name
        self.qualified_name = qualified_name
        self.node = node
        self.file_path = file_path
        self.references: List[Tuple[ast.AST, str]] = []
        self.lineno = getattr(node, "lineno", 0)
        self.end_lineno = getattr(node, "end_lineno", 0)

    def add_reference(self, node: ast.AST, file_path: str) -> None:
        self.references.append((node, file_path))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.qualified_name}>"


class FunctionDefinition(Definition):
    def __init__(
        self, name: str, qualified_name: str, node: ast.FunctionDef, file_path: str
    ):
        super().__init__(name, qualified_name, node, file_path)
        self.is_method = False
        self.class_name = None
        self.parameters = []
        self.return_type = None
        self.docstring = ast.get_docstring(node)
        self.calls: List[Tuple[str, ast.Call]] = []
        self.complexity = 1
        self.is_async = isinstance(node, ast.AsyncFunctionDef)
        if hasattr(node, "args"):
            self._extract_parameters(node.args)
        if "." in qualified_name:
            parent_name = qualified_name.rsplit(".", 1)[0]
            if parent_name:
                self.is_method = True
                self.class_name = parent_name

    def _extract_parameters(self, args: ast.arguments) -> None:
        if hasattr(args, "args"):
            for arg in args.args:
                param_name = getattr(arg, "arg", None)
                if param_name:
                    self.parameters.append(param_name)
        if hasattr(args, "vararg") and args.vararg:
            vararg_name = getattr(args.vararg, "arg", args.vararg)
            if vararg_name:
                self.parameters.append(f"*{vararg_name}")
        if hasattr(args, "kwonlyargs"):
            for kwarg in args.kwonlyargs:
                param_name = getattr(kwarg, "arg", None)
                if param_name:
                    self.parameters.append(param_name)
        if hasattr(args, "kwarg") and args.kwarg:
            kwarg_name = getattr(args.kwarg, "arg", args.kwarg)
            if kwarg_name:
                self.parameters.append(f"**{kwarg_name}")

    def add_call(self, target_qualified_name: str, call_node: ast.Call) -> None:
        self.calls.append((target_qualified_name, call_node))

    def calculate_complexity(self) -> int:
        complexity = 1
        for node in ast.walk(self.node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.Try):
                complexity += len(node.handlers)
        self.complexity = complexity
        return complexity


class ClassDefinition(Definition):
    def __init__(
        self, name: str, qualified_name: str, node: ast.ClassDef, file_path: str
    ):
        super().__init__(name, qualified_name, node, file_path)
        self.methods: Dict[str, FunctionDefinition] = {}
        self.attributes: Dict[str, Any] = {}
        self.base_classes: List[str] = []
        self.docstring = ast.get_docstring(node)
        for base in node.bases:
            if isinstance(base, ast.Name):
                self.base_classes.append(base.id)
            elif isinstance(base, ast.Attribute):
                self.base_classes.append(self._get_attribute_name(base))

    def _get_attribute_name(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        elif isinstance(node.value, ast.Attribute):
            return f"{self._get_attribute_name(node.value)}.{node.attr}"
        return node.attr

    def add_method(self, method: FunctionDefinition) -> None:
        if method.name not in self.methods:
            self.methods[method.name] = method
            method.is_method = True
            method.class_name = self.qualified_name

    def add_attribute(self, name: str, value: Any) -> None:
        self.attributes[name] = value


class DefinitionManager:
    def __init__(self):
        self.functions: Dict[str, FunctionDefinition] = {}
        self.classes: Dict[str, ClassDefinition] = {}
        self.modules: Dict[str, str] = {}
        self.qualified_names: Dict[str, str] = {}

    def add_function(
        self, node: ast.FunctionDef, module_name: str, file_path: str
    ) -> FunctionDefinition:
        name = node.name
        qualified_name = f"{module_name}.{name}" if module_name else name
        func_def = FunctionDefinition(name, qualified_name, node, file_path)
        self.functions[qualified_name] = func_def
        if name not in self.qualified_names:
            self.qualified_names[name] = set()
        self.qualified_names[name].add(qualified_name)
        return func_def

    def add_class(
        self, node: ast.ClassDef, module_name: str, file_path: str
    ) -> ClassDefinition:
        name = node.name
        qualified_name = f"{module_name}.{name}" if module_name else name
        class_def = ClassDefinition(name, qualified_name, node, file_path)
        self.classes[qualified_name] = class_def
        if name not in self.qualified_names:
            self.qualified_names[name] = set()
        self.qualified_names[name].add(qualified_name)
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_name = item.name
                method_qualified_name = f"{qualified_name}.{method_name}"
                method_def = FunctionDefinition(
                    method_name, method_qualified_name, item, file_path
                )
                method_def.is_method = True
                method_def.class_name = qualified_name
                self.functions[method_qualified_name] = method_def
                class_def.add_method(method_def)
                if method_name not in self.qualified_names:
                    self.qualified_names[method_name] = set()
                self.qualified_names[method_name].add(method_qualified_name)
        return class_def

    def add_module(self, module_name: str, file_path: str) -> None:
        self.modules[module_name] = file_path

    def get_function(self, qualified_name: str) -> Optional[FunctionDefinition]:
        return self.functions.get(qualified_name)

    def get_class(self, qualified_name: str) -> Optional[ClassDefinition]:
        return self.classes.get(qualified_name)

    def get_module_path(self, module_name: str) -> Optional[str]:
        return self.modules.get(module_name)

    def resolve_name(self, name: str, module_context: str = None) -> List[str]:
        qualified_names = []
        if name in self.qualified_names:
            qualified_names.extend(self.qualified_names[name])
        if module_context:
            module_qualified = f"{module_context}.{name}"
            if module_qualified in self.functions or module_qualified in self.classes:
                qualified_names.append(module_qualified)
            for func_name in self.functions:
                if func_name.endswith(f".{name}"):
                    qualified_names.append(func_name)
            for class_name in self.classes:
                if class_name.endswith(f".{name}"):
                    qualified_names.append(class_name)
        return qualified_names

    def resolve_call(self, node: ast.Call, module_context: str = None) -> List[str]:
        targets = []
        if isinstance(node.func, ast.Name):
            name = node.func.id
            targets.extend(self.resolve_name(name, module_context))
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                obj_name = node.func.value.id
                method_name = node.func.attr
                if obj_name == "self" and module_context:
                    if "." in module_context:
                        class_context = module_context.rsplit(".", 1)[0]
                        qualified_method = f"{class_context}.{method_name}"
                        if qualified_method in self.functions:
                            targets.append(qualified_method)
                obj_targets = self.resolve_name(obj_name, module_context)
                for obj_target in obj_targets:
                    if obj_target in self.classes:
                        class_def = self.classes[obj_target]
                        qualified_method = f"{obj_target}.{method_name}"
                        if qualified_method in self.functions:
                            targets.append(qualified_method)
            elif isinstance(node.func.value, ast.Attribute):
                attr_name = self._get_attribute_name(node.func)
                if attr_name:
                    if attr_name in self.functions:
                        targets.append(attr_name)
                    parts = attr_name.split(".")
                    for i in range(1, len(parts)):
                        prefix = ".".join(parts[:i])
                        suffix = ".".join(parts[i:])
                        prefix_targets = self.resolve_name(prefix, module_context)
                        for prefix_target in prefix_targets:
                            qualified_name = f"{prefix_target}.{suffix}"
                            if qualified_name in self.functions:
                                targets.append(qualified_name)
        return targets

    def _get_attribute_name(self, node: ast.Attribute) -> str:
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.insert(0, current.id)
            return ".".join(parts)
        return None

    def analyze_file(self, file_path: str, tree: Optional[ast.AST] = None) -> None:
        if tree is None:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")
                return
            try:
                tree = ast.parse(content, filename=file_path)
            except SyntaxError as e:
                print(f"Syntax error in {file_path}: {e}")
                return
        for node_walker in ast.walk(tree):
            for child in ast.iter_child_nodes(node_walker):
                child.parent = node_walker
        module_name = os.path.splitext(os.path.basename(file_path))[0]
        self.add_module(module_name, file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(
                node, ast.AsyncFunctionDef
            ):
                if isinstance(node.parent, ast.Module):
                    self.add_function(node, module_name, file_path)
            elif isinstance(node, ast.ClassDef):
                if isinstance(node.parent, ast.Module):
                    self.add_class(node, module_name, file_path)
        for func_name, func_def in self.functions.items():
            self._analyze_function_calls(func_def, module_name)

    def _analyze_function_calls(
        self, func_def: FunctionDefinition, module_context: str
    ) -> None:
        for node in ast.walk(func_def.node):
            if isinstance(node, ast.Call):
                targets = self.resolve_call(node, module_context)
                for target in targets:
                    func_def.add_call(target, node)
        func_def.calculate_complexity()
\n\n# ==============================\n# Filename: services\documentation_service.py\n# ==============================\n\nimport os# Attempt to import the LLMDocGeneratorService, but don't fail if it's not there yet
try:
    from .llm_doc_generator_service import LLMDocGeneratorService
except ImportError:
    LLMDocGeneratorService = None 
    # This allows the service to run without LLM features if the generator isn't implemented

import os # Added os import, will be used later

import ast
import logging
import os
import sys
from typing import Dict, List, Set, Optional, Tuple, Any, Union

# Print Python path to diagnose import issues
print("\n\n*** PYTHON PATH in documentation_service.py ***")
for path in sys.path:
    print(f"  {path}")
print("\n")

try:
    from .llm_doc_generator_service import LLMDocGeneratorService
except ImportError:
    LLMDocGeneratorService = None # Allows service to run if LLM part is not yet implemented
import asyncio
from datetime import datetime

from .callgraph import CallgraphGenerator
from .enhanced_callgraph import EnhancedCallgraphGenerator
from .research_callgraph import ResearchCallgraphGenerator
from .dynamic_callgraph_builder import DynamicCallGraphBuilder
from .codebase_data_service import CodebaseDataService
from ..models.documentation import (
    ModuleDocumentation,
    ClassDocumentation,
    FunctionDocumentation
)

logger = logging.getLogger(__name__)

class DocumentationService:
    """
    Service for generating comprehensive documentation from code analysis.
    This service leverages the existing call graph analysis infrastructure
    to extract docstrings, function signatures, and other relevant documentation.
    """
    
    def __init__(self, framework_hint: str = "generic", repository_id: Optional[str] = None):
        """
        Initialize the DocumentationService.
        
        Args:
            framework_hint: Optional hint about the framework used in the codebase
        """
        self.framework_hint = framework_hint
        self.callgraph_generator = ResearchCallgraphGenerator(framework=framework_hint)
        self.codebase_data_service = CodebaseDataService()
        self.repo_path = None
        self.repository_id = repository_id # Store the passed repository_id
        self.documentation = {}
        self.docstrings = {}
        self.function_signatures = {}
        self.class_hierarchies = {}
        self.modules = {}
        
    async def analyze_repository(
        self,
        repo_path: str,
        timeout: int = 600,
        clone: bool = False,
        perform_cleanup: bool = True,
        repository_id: Optional[str] = None,
    ) -> Dict:
        """
        DEPRECATED: This method should not be called directly. 
        Use generate_from_callgraph instead.
        """
        logger.warning("analyze_repository in DocumentationService is deprecated. Performing a full new analysis.")
        
        # This path is now a fallback and should ideally be removed later.
        from ..utils.repository import normalize_repository_id
        self.repository_id = repository_id or normalize_repository_id(repo_path)
        
        # We have to re-instantiate a generator here for this fallback path to work.
        # This highlights the architectural issue.
        generator = ResearchCallgraphGenerator(framework=self.framework_hint)
        callgraph_result = await generator.analyze_repository(
            repo_path=repo_path,
            timeout=timeout,
            clone=clone,
            perform_cleanup=perform_cleanup,
        )
        
        return await self.generate_from_callgraph(callgraph_result)
    
    async def generate_from_callgraph(self, callgraph_result: Dict, perform_cleanup: bool = True) -> Dict:
        """
        Generate documentation directly from callgraph data without redoing analysis.
        
        Args:
            repo_path: Optional path to the repository for accessing file contents
            callgraph_result: Callgraph data with nodes and links
            clone: Whether to clone the repository if repo_path is a URL
            perform_cleanup: Whether to clean up temporary files after processing
            
        Returns:
            Dictionary with documentation data
        """
        # Initialize dictionaries for storing documentation
        doc_result = {
                "modules": [],
                "classes": [],
                "functions": [],
                "metadata": callgraph_result.get("metadata", {})
            }
        self.modules = {}
        self.classes = {}
        self.functions = {}
        
        # Repository path is no longer used directly in this method.
        # Source code is expected to be in callgraph_result node metadata.
        self.repo_path = None # Explicitly set to None as it's not used for file reading here.
        
        try:
            # Extract documentation from callgraph
            logger.info("Extracting documentation from callgraph data")
            await self._extract_documentation_from_callgraph(callgraph_result)
            
            # Prepare the documentation result structure
           
            
            # Convert module dictionaries to ModuleDocumentation objects
            for module_name, module_info in self.modules.items():
                module_doc = ModuleDocumentation(
                    name=module_info.get("name", module_name),
                    qualified_name=module_name,
                    docstring=module_info.get("docstring", ""),
                    file_path=module_info.get("file", ""),
                    element_type="module",
                    classes=module_info.get("classes", []),
                    functions=module_info.get("functions", [])
                )
                doc_result["modules"].append(module_doc.dict())
            
            # Convert class dictionaries to ClassDocumentation objects
            for class_name, class_info in self.classes.items():
                # Convert methods to FunctionDocumentation objects if they're not already
                methods = []
                for method in class_info.get("methods", []):
                    if isinstance(method, dict):
                        methods.append(FunctionDocumentation(
                            name=method.get("name", ""),
                            qualified_name=method.get("qualified_name", ""),
                            docstring=method.get("docstring", ""),
                            file_path=method.get("file", ""),
                            element_type="method",
                            signature=method.get("signature", ""),
                            args=method.get("parameters", []),
                            return_type=method.get("returns", None),
                            is_async=False
                        ))
                
                class_doc = ClassDocumentation(
                    name=class_info.get("name", class_name.split(".")[-1]),
                    qualified_name=class_name,
                    docstring=class_info.get("docstring", ""),
                    file_path=class_info.get("file", ""),
                    element_type="class",
                    methods=methods,
                    bases=class_info.get("bases", [])
                )
                doc_result["classes"].append(class_doc.dict())
            
            # Convert function dictionaries to FunctionDocumentation objects
            for func_name, func_info in self.functions.items():
                # Skip methods as they're added to their classes
                if func_info.get("is_method", False):
                    continue
                    
                func_doc = FunctionDocumentation(
                    name=func_name.split(".")[-1],
                    qualified_name=func_name,
                    docstring=func_info.get("docstring", ""),
                    file_path=func_info.get("file", ""),
                    element_type="function",
                    signature=func_info.get("signature", ""),
                    args=func_info.get("parameters", []),
                    return_type=func_info.get("returns", ""),
                    is_async=False,
                    dependencies=func_info.get("dependencies", [])
                )
                doc_result["functions"].append(func_doc.dict())
            
            return doc_result
        finally:
            # Cleanup of temporary directories (if any were created by callgraph generator)
            # is now handled by the callgraph generator itself or the calling router.
            pass
                
            for class_name, class_info in self.classes.items():
                # Convert methods to FunctionDocumentation objects if they're not already
                methods = []
                for method in class_info.get("methods", []):
                    if isinstance(method, dict):
                        methods.append(FunctionDocumentation(
                            name=method.get("name", ""),
                            qualified_name=method.get("qualified_name", ""),
                            docstring=method.get("docstring", ""),
                            file_path=method.get("file", ""),
                            element_type="method",
                            signature=method.get("signature", ""),
                            args=method.get("parameters", []),
                            return_type=method.get("returns", None),
                            is_async=False
                        ))
                
                class_doc = ClassDocumentation(
                    name=class_info.get("name", class_name.split(".")[-1]),
                    qualified_name=class_name,
                    docstring=class_info.get("docstring", ""),
                    file_path=class_info.get("file", ""),
                    element_type="class",
                    methods=methods,
                    bases=class_info.get("bases", [])
                )
                doc_result["classes"].append(class_doc.dict())
                
            for func_name, func_info in self.functions.items():
                # Skip methods as they're added to their classes
                if func_info.get("is_method", False):
                    continue
                    
                func_doc = FunctionDocumentation(
                    name=func_name.split(".")[-1],
                    qualified_name=func_name,
                    docstring=func_info.get("docstring", ""),
                    file_path=func_info.get("file", ""),
                    element_type="function",
                    signature=func_info.get("signature", ""),
                    args=func_info.get("parameters", []),
                    return_type=func_info.get("returns", ""),
                    is_async=False,
                    dependencies=func_info.get("dependencies", [])
                )
                doc_result["functions"].append(func_doc.dict())
                
            return doc_result

    
    async def _extract_documentation(self) -> None:
        """
        Extract docstrings, signatures, and other documentation elements from all Python files in the codebase.
        """
        if not self.repo_path or not os.path.isdir(self.repo_path):
            logger.error("Repository path is not valid for documentation extraction")
            return
        
        python_files = []
        for root, _, files in os.walk(self.repo_path):
            for file in files:
                if file.endswith(".py"):
                    python_files.append(os.path.join(root, file))
        
        logger.info(f"Extracting documentation from {len(python_files)} Python files")
        for file_path in python_files:
            try:
                await self._extract_file_documentation(file_path)
            except Exception as e:
                logger.error(f"Error extracting documentation from {file_path}: {str(e)}")
                
    async def _get_connected_elements_for_llm(self, node_id: str, nodes: List[Dict], links: List[Dict], max_context_elements: int = 5) -> List[Dict[str, Any]]: 
        """
        Gathers context for a given node from the callgraph, including directly connected elements.
        This context is intended to be passed to an LLM for documentation generation.
        """
        connections = [] # Use a simple list
        context = {"node_id": node_id, "connections": []}
        connected_node_ids = set()

        # Find direct connections (callers and callees)
        for link in links:
            if link.get("source") == node_id:
                connected_node_ids.add(link.get("target"))
            elif link.get("target") == node_id:
                connected_node_ids.add(link.get("source"))
        # Get details for connected nodes
        for n_id in list(connected_node_ids)[:max_context_elements]: # Limit context size
            for n_data in nodes:
                if n_data.get("id") == n_id:
                    context["connections"].append({
                        "id": n_data.get("id"),
                        "type": n_data.get("type"),
                        "file": n_data.get("file", "N/A"),
                        "signature": n_data.get("signature", "N/A"),
                        "docstring_preview": (n_data.get("docstring", "")[:100] + "...") if n_data.get("docstring") else "No docstring"
                    })
                    break
            return connections

    async def generate_documentation_for_callgraph(self, callgraph_id: str) -> Optional[Dict[str, Any]]:
        """
        Generate documentation for an entire callgraph by its ID using batch processing.
        
        Args:
            callgraph_id: The ID of the callgraph to generate documentation for
            
        Returns:
            Updated callgraph with generated documentation, or None if callgraph not found
        """
        logger.info(f"Generating documentation for callgraph: {callgraph_id}")
        
        # Get the callgraph
        callgraph = await self.callgraph_service.get_callgraph(callgraph_id)
        if not callgraph:
            logger.error(f"Callgraph not found: {callgraph_id}")
            return None
            
        # Collect all nodes that need documentation (don't have docstrings)
        nodes_needing_docs = []
        for node_id, node_data in callgraph.get('nodes', {}).items():
            if not node_data.get('docstring') and node_data.get('type') in ['function', 'class', 'method', 'module']:
                nodes_needing_docs.append(node_data)
                
        logger.info(f"Found {len(nodes_needing_docs)} nodes needing documentation in callgraph {callgraph_id}")
        
        if not nodes_needing_docs:
            logger.info(f"No nodes need documentation in callgraph {callgraph_id}")
            return callgraph
        
        # Initialize LLM doc generator if not already done
        if not hasattr(self, 'llm_doc_generator') or self.llm_doc_generator is None:
            try:
                self.llm_doc_generator = LLMDocGeneratorService()
                logger.info("Initialized LLMDocGeneratorService for documentation generation")
            except Exception as e:
                logger.error(f"Failed to initialize LLMDocGeneratorService: {e}")
                return callgraph
        
        # Process nodes in batches for efficiency and rate limit management
        updated_nodes = {}
        
        # Use the batch processor from LLMDocGeneratorService if it exists
        if hasattr(self.llm_doc_generator, 'batch_processor'):
            # Prepare the processing function
            async def process_node(node):
                node_id = node.get('id')
                context_elements = self._get_context_for_node(node, callgraph)
                return await self._generate_documentation_for_node(node, context_elements)
            
            # Process in batches
            logger.info(f"Processing {len(nodes_needing_docs)} nodes in batches")
            batch_results = await self.llm_doc_generator.batch_processor.process_batch(
                nodes_needing_docs, process_node
            )
            
            # Process results
            for node, docs in batch_results:
                if docs:
                    node_id = node.get('id')
                    updated_node = node.copy()  # Create a copy to avoid modifying the original
                    updated_node.update(docs)
                    updated_nodes[node_id] = updated_node
                    logger.info(f"Generated documentation for node: {node_id}")
                else:
                    logger.warning(f"Failed to generate documentation for node: {node.get('id')}")
        else:
            # Fallback to processing one by one if batch processor not available
            logger.warning("Batch processor not available, processing nodes one by one")
            for node in nodes_needing_docs:
                node_id = node.get('id')
                
                # Get context elements for this node
                context_elements = self._get_context_for_node(node, callgraph)
                
                # Generate documentation
                docs = await self._generate_documentation_for_node(node, context_elements)
                if docs:
                    # Update the node with the generated documentation
                    updated_node = node.copy()  # Create a copy to avoid modifying the original
                    updated_node.update(docs)
                    updated_nodes[node_id] = updated_node
                    logger.info(f"Generated documentation for node: {node_id}")
                else:
                    logger.warning(f"Failed to generate documentation for node: {node_id}")
        
        # Update the callgraph with the generated documentation
        for node_id, updated_node in updated_nodes.items():
            callgraph['nodes'][node_id] = updated_node
            
        logger.info(f"Updated {len(updated_nodes)} nodes with documentation in callgraph {callgraph_id}")
        
        return callgraph
    
    async def _get_context_for_node(self, node: Dict[str, Any], callgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Get context elements for a node to help with documentation generation.
        Includes related nodes based on callgraph relationships.
        
        Args:
            node: The node to get context for
            callgraph: The callgraph containing the node
            
        Returns:
            List of related nodes that provide context
        """
        node_id = node.get('id')
        context_elements = []
        
        # Get links from the callgraph
        links = callgraph.get('links', [])
        nodes = callgraph.get('nodes', {})
        
        # Find direct relationships (calls, called by, etc.)
        related_links = [link for link in links if link.get('source') == node_id or link.get('target') == node_id]
        
        # Add related nodes to context
        for link in related_links:
            related_id = link.get('source') if link.get('target') == node_id else link.get('target')
            if related_id in nodes and related_id != node_id:
                relation_type = link.get('type', 'unknown')
                context_elements.append({
                    'node': nodes[related_id],
                    'relation': relation_type,
                    'direction': 'incoming' if link.get('target') == node_id else 'outgoing'
                })
        
        # Limit to the most relevant context elements (e.g., max 5)
        return context_elements[:5]
    
    async def _generate_documentation_for_node(self, node: Dict[str, Any], context_elements: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        """Generate documentation for a single node using the LLM."""
        # Ensure node has repository_id for proper MongoDB storage
        if 'repository_id' not in node and self.repository_id:
            node['repository_id'] = self.repository_id
            logger.info(f"DocumentationService: Added repository_id {self.repository_id} to node {node.get('id')}")
        elif 'repository_id' not in node and not self.repository_id:
            logger.warning(f"DocumentationService: Cannot add repository_id to node {node.get('id')} - repository_id is not set in DocumentationService")
        else:
            logger.debug(f"DocumentationService: Node {node.get('id')} already has repository_id {node.get('repository_id')}")
        
        # Generate documentation using LLM
        try:
            logger.info(f"DocumentationService: Calling LLMDocGeneratorService for node {node.get('id')} with repository_id {node.get('repository_id')}")
            documentation = await self.llm_doc_generator.generate_documentation_for_node(node, context_elements)
            if documentation:
                logger.info(f"DocumentationService: Successfully generated documentation for node {node.get('id')}")
                return documentation
            else:
                logger.warning(f"DocumentationService: Failed to generate documentation for node {node.get('id')}")
                return None
        except Exception as e:
            logger.error(f"DocumentationService: Error generating documentation for node {node.get('id')}: {e}", exc_info=True)
            return None
    

    async def _extract_documentation_from_callgraph(self, callgraph_result: Dict) -> None:
        """
        Extracts documentation by parsing source code from callgraph nodes and
        uses an LLM to generate docstrings for elements that lack them.

        Args:
            callgraph_result: Callgraph data with nodes and links.
        """
        logger.info("Extracting documentation from callgraph nodes and generating missing docstrings with LLM.")
        nodes = callgraph_result.get("nodes", [])
        links = callgraph_result.get("links", [])


        repository_id = self.repository_id
        if not repository_id:
            # As a fallback, try to get it from the callgraph metadata itself
            repository_id = callgraph_result.get("metadata", {}).get("repository_id")
        
        if not repository_id:
            logger.error("Could not determine repository_id. LLM-generated docs will not be cached in the database.")
            # --- FIX: Initialize LLMDocGeneratorService here ---
        llm_doc_generator = None
        if LLMDocGeneratorService:
            try:
                llm_doc_generator = LLMDocGeneratorService()
                logger.info("LLMDocGeneratorService initialized for docstring generation.")
            except Exception as e:
                logger.error(f"Failed to initialize LLMDocGeneratorService: {e}. LLM generation will be skipped.")
        else:
            logger.warning("LLMDocGeneratorService not available. Docstrings will not be generated by LLM.")

        for node in nodes:
            node_id = node.get("id")
            if not node_id:
                continue

            source_code = node.get("metadata", {}).get("source_code")
            file_path = node.get("metadata", {}).get("file_path", "unknown_file.py")
            node_type = node.get("type", "").lower()

            docstring = ""
            # Try to extract existing docstring first
            if source_code:
                try:
                    tree = ast.parse(source_code, filename=file_path)
                    if tree.body:
                        docstring = ast.get_docstring(tree.body[0]) or ""
                except (SyntaxError, IndexError) as e:
                    logger.warning(f"Could not parse source for {node_id} to get existing docstring: {e}")
            
            # --- FIX: Call LLM if docstring is missing ---
            # If the docstring is empty AND the node is a function/class/method AND the LLM service is available...
            if not docstring and node_type in ['function', 'method', 'class', 'module'] and llm_doc_generator:
                logger.info(f"Node '{node_id}' is missing a docstring. Attempting to generate one with LLM.")
                
                # Prepare context for the LLM
                context_elements = await self._get_connected_elements_for_llm(node_id, nodes, links)
                
                if repository_id and 'repository_id' not in node:
                    node['repository_id'] = repository_id
                # The LLM generator needs the node data and context
                generated_docs = await llm_doc_generator.generate_documentation_for_node(node, context_elements)
                
                if generated_docs and generated_docs.get('docstring'):
                    docstring = generated_docs['docstring']
                    logger.info(f"Successfully generated docstring for '{node_id}' with LLM.")
                else:
                    logger.warning(f"LLM failed to generate a docstring for '{node_id}'.")
            
            # Now, build the documentation structure with the (potentially LLM-generated) docstring
            node_parts = node_id.split('.')
            if node_type == 'module':
                module_name = node_id
            else:
                module_name = ".".join(node_parts[:-1]) if '.' in node_id else "unknown_module"

            if module_name not in self.modules:
                self.modules[module_name] = {
                    "name": module_name.split('.')[-1], "qualified_name": module_name, "file": file_path,
                    "docstring": "", "classes": [], "functions": []
                }

            if node_type == "module":
                self.modules[module_name]["docstring"] = docstring

            elif node_type == "class":
                class_qname = node_id
                self.classes[class_qname] = {
                    "name": node_parts[-1], "qualified_name": class_qname, "module": module_name,
                    "file": file_path, "docstring": docstring,
                    "bases": [b for b in node.get("metadata", {}).get("bases", []) if b],
                    "methods": []
                }
                if module_name in self.modules and class_qname not in self.modules[module_name]["classes"]:
                    self.modules[module_name]["classes"].append(class_qname)

            elif node_type in ["function", "method"]:
                is_method = (node_type == "method")
                parent_class_qname = ".".join(node_parts[:-1]) if is_method else None
                func_qname = node_id
                func_data = {
                    "name": node_parts[-1], "qualified_name": func_qname, "module": module_name,
                    "file": file_path, "docstring": docstring, "is_method": is_method,
                    "class_name": parent_class_qname,
                    "signature": node.get("metadata", {}).get("signature", f"{node_parts[-1]}(...)"),
                    "complexity": node.get("complexity", 0)
                }
                self.functions[func_qname] = func_data
                
                if is_method and parent_class_qname and parent_class_qname in self.classes:
                    if not any(m["qualified_name"] == func_qname for m in self.classes[parent_class_qname]["methods"]):
                        self.classes[parent_class_qname]["methods"].append(func_data)
                elif not is_method and module_name in self.modules:
                    if func_qname not in self.modules[module_name]["functions"]:
                        self.modules[module_name]["functions"].append(func_qname)

        logger.info(f"Documentation extraction and generation complete. Found: {len(self.modules)} modules, {len(self.classes)} classes, {len(self.functions)} functions.")
    
    async def _extract_file_documentation(self, file_path: str, source_content: Optional[str] = None) -> None:
        """
        Extract documentation from a single Python file's content.
        
        Args:
            file_path: Path to the Python file (used for context, like module naming)
            source_content: Optional string content of the file. If None, reads from file_path.
        """
        try:
            content = source_content
            if content is None:
                if not self.repo_path and not os.path.isabs(file_path):
                    logger.error(f"_extract_file_documentation called without source_content and no valid repo_path or absolute file_path: {file_path}")
                    return
                actual_file_path = os.path.join(self.repo_path, file_path) if self.repo_path and not os.path.isabs(file_path) else file_path
                if not os.path.exists(actual_file_path):
                    logger.warning(f"File not found for documentation extraction: {actual_file_path}")
                    return
                with open(actual_file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            
            if content is None:
                logger.error(f"Could not obtain source content for {file_path}")
                return

            tree = ast.parse(content, filename=file_path)
            
            module_name_parts = []
            if self.repo_path and not os.path.isabs(file_path) and os.path.commonpath([self.repo_path, os.path.join(self.repo_path, file_path)]) == self.repo_path:
                 rel_path = file_path
            elif os.path.isabs(file_path) and self.repo_path and os.path.commonpath([self.repo_path, file_path]) == self.repo_path:
                 rel_path = os.path.relpath(file_path, self.repo_path)
            else:
                 rel_path = file_path.replace(os.path.dirname(file_path) + os.sep, '') if os.path.dirname(file_path) else file_path

            module_name = rel_path.replace(".py", "").replace(os.sep, ".")
            
            if module_name.endswith(".__init__"):
                module_name = module_name[:-len(".__init__")]
            elif os.path.basename(file_path) == "__init__.py":
                 module_name = os.path.dirname(module_name) if os.path.dirname(module_name) else module_name
                
            module_docstring = ast.get_docstring(tree)
            if module_docstring:
                if module_name not in self.modules:
                    self.modules[module_name] = {
                        "name": module_name,
                        "qualified_name": module_name,
                        "file": file_path, 
                        "docstring": "",
                        "classes": [],
                        "functions": []
                    }
                self.modules[module_name]["docstring"] = self._clean_docstring(module_docstring)
                
            self._process_ast_nodes(tree, module_name, file_path)
            
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path} (from source content): {str(e)}")
        except Exception as e:
            logger.error(f"Error analyzing {file_path} (from source content): {str(e)}")
            
            if os.path.basename(file_path) == "__init__.py":
                module_name = module_name.rstrip(".__init__")
                
            # Extract module docstring
            module_docstring = ast.get_docstring(tree)
            if module_docstring:
                self.docstrings[module_name] = self._clean_docstring(module_docstring)
                
            # Process all nodes in the file
            self._process_ast_nodes(tree, module_name, file_path)
            
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {str(e)}")
        except Exception as e:
            logger.error(f"Error analyzing {file_path}: {str(e)}")
    
    def _process_ast_nodes(self, tree: ast.AST, module_name: str, file_path: str) -> None:
        """
        Process AST nodes to extract documentation elements.
        
        Args:
            tree: AST tree to process
            module_name: Name of the module
            file_path: Path to the source file
        """
        # Track current class for nested definitions
        current_class = []
        
        for node in ast.walk(tree):
            # Process classes
            if isinstance(node, ast.ClassDef):
                class_name = node.name
                qualified_name = f"{module_name}.{class_name}"
                
                if not current_class:  # Top-level class
                    current_class.append(class_name)
                    
                    # Get class docstring
                    class_docstring = ast.get_docstring(node)
                    if class_docstring:
                        self.docstrings[qualified_name] = self._clean_docstring(class_docstring)
                    
                    # Extract class hierarchy
                    bases = []
                    for base in node.bases:
                        if isinstance(base, ast.Name):
                            bases.append(base.id)
                        elif isinstance(base, ast.Attribute):
                            bases.append(self._get_attribute_name(base))
                    
                    self.class_hierarchies[qualified_name] = {
                        "name": class_name,
                        "module": module_name,
                        "bases": bases,
                        "file_path": file_path,
                        "docstring": self.docstrings.get(qualified_name, ""),
                        "methods": [],
                        "attributes": []
                    }
                else:
                    # Nested class
                    parent_class = ".".join(current_class)
                    current_class.append(class_name)
                    nested_qualified_name = f"{module_name}.{parent_class}.{class_name}"
                    
                    # Get class docstring
                    class_docstring = ast.get_docstring(node)
                    if class_docstring:
                        self.docstrings[nested_qualified_name] = self._clean_docstring(class_docstring)
                        
            # Process functions/methods
            elif isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
                func_name = node.name
                
                if current_class:  # Method in a class
                    class_name = ".".join(current_class)
                    qualified_name = f"{module_name}.{class_name}.{func_name}"
                    
                    # Add to class methods
                    class_qualified_name = f"{module_name}.{current_class[0]}"
                    if class_qualified_name in self.class_hierarchies:
                        self.class_hierarchies[class_qualified_name]["methods"].append(func_name)
                else:  # Module-level function
                    qualified_name = f"{module_name}.{func_name}"
                
                # Get function docstring
                func_docstring = ast.get_docstring(node)
                if func_docstring:
                    self.docstrings[qualified_name] = self._clean_docstring(func_docstring)
                
                # Extract function signature
                args = []
                for arg in node.args.args:
                    arg_name = arg.arg
                    arg_type = ""
                    if arg.annotation:
                        if isinstance(arg.annotation, ast.Name):
                            arg_type = arg.annotation.id
                        elif isinstance(arg.annotation, ast.Attribute):
                            arg_type = self._get_attribute_name(arg.annotation)
                        elif isinstance(arg.annotation, ast.Subscript):
                            arg_type = self._get_subscript_name(arg.annotation)
                    args.append((arg_name, arg_type))
                
                # Get return annotation if available
                return_type = ""
                if node.returns:
                    if isinstance(node.returns, ast.Name):
                        return_type = node.returns.id
                    elif isinstance(node.returns, ast.Attribute):
                        return_type = self._get_attribute_name(node.returns)
                    elif isinstance(node.returns, ast.Subscript):
                        return_type = self._get_subscript_name(node.returns)
                
                self.function_signatures[qualified_name] = {
                    "name": func_name,
                    "module": module_name,
                    "class": current_class[0] if current_class else None,
                    "args": args,
                    "return_type": return_type,
                    "is_async": isinstance(node, ast.AsyncFunctionDef),
                    "file_path": file_path,
                    "docstring": self.docstrings.get(qualified_name, "")
                }
                
            # Keep track of class context for nested definitions
            if isinstance(node, ast.ClassDef) and len(current_class) > 0 and current_class[-1] == node.name:
                for child in ast.iter_child_nodes(node):
                    if isinstance(child, ast.ClassDef):
                        # We'll handle nested classes in the recursive walk
                        pass
                    
                # We're done with this class, pop it from the context
                current_class.pop()
                
    def _get_attribute_name(self, node: ast.Attribute) -> str:
        """Get the full name of an attribute node (e.g., typing.List)"""
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        parts.reverse()
        return ".".join(parts)
    
    def _get_subscript_name(self, node: ast.Subscript) -> str:
        """Get the name of a subscript (e.g., List[str])"""
        if isinstance(node.value, ast.Name):
            base = node.value.id
        elif isinstance(node.value, ast.Attribute):
            base = self._get_attribute_name(node.value)
        else:
            return "unknown"
            
        if isinstance(node.slice, ast.Index):
            # Python 3.8 and below
            if hasattr(node.slice, 'value'):
                if isinstance(node.slice.value, ast.Name):
                    param = node.slice.value.id
                elif isinstance(node.slice.value, ast.Attribute):
                    param = self._get_attribute_name(node.slice.value)
                else:
                    param = "any"
            else:
                param = "any"
        else:
            # Python 3.9+
            if isinstance(node.slice, ast.Name):
                param = node.slice.id
            elif isinstance(node.slice, ast.Attribute):
                param = self._get_attribute_name(node.slice)
            else:
                param = "any"
                
        return f"{base}[{param}]"
    
    def _clean_docstring(self, docstring: str) -> str:
        """Clean and normalize a docstring"""
        if not docstring:
            return ""
            
        # Remove leading/trailing whitespace
        docstring = docstring.strip()
        
        # Normalize line breaks
        lines = docstring.split("\n")
        cleaned_lines = []
        
        # Remove common indentation
        if len(lines) > 1:
            # Find minimum indentation of non-empty lines after the first line
            indents = [len(line) - len(line.lstrip()) for line in lines[1:] if line.strip()]
            if indents:
                min_indent = min(indents)
                # Remove the minimum indentation from each line
                cleaned_lines.append(lines[0])
                cleaned_lines.extend([line[min_indent:] if line.strip() else "" for line in lines[1:]])
            else:
                cleaned_lines = lines
        else:
            cleaned_lines = lines
            
        return "\n".join(cleaned_lines)
    
    def _generate_documentation(self, callgraph_result: Dict) -> Dict:
        """
        Generate structured documentation using extracted information and callgraph.
        
        Args:
            callgraph_result: Result from callgraph analysis
            
        Returns:
            Dict containing structured documentation
        """
        modules = {}
        classes = {}
        functions = {}
        
        # Organize by modules
        for name, signature in self.function_signatures.items():
            module_name = signature["module"]
            
            if module_name not in modules:
                modules[module_name] = {
                    "name": module_name,
                    "docstring": self.docstrings.get(module_name, ""),
                    "classes": [],
                    "functions": [],
                    "file_path": signature["file_path"]
                }
                
            if signature["class"] is None:
                # Module-level function
                functions[name] = {
                    "name": signature["name"],
                    "qualified_name": name,
                    "module": module_name,
                    "signature": self._format_signature(signature),
                    "docstring": signature["docstring"],
                    "is_async": signature["is_async"],
                    "file_path": signature["file_path"]
                }
                modules[module_name]["functions"].append(name)
        
        # Process classes
        for name, hierarchy in self.class_hierarchies.items():
            module_name = hierarchy["module"]
            
            if module_name not in modules:
                modules[module_name] = {
                    "name": module_name,
                    "docstring": self.docstrings.get(module_name, ""),
                    "classes": [],
                    "functions": [],
                    "file_path": hierarchy["file_path"]
                }
                
            classes[name] = {
                "name": hierarchy["name"],
                "qualified_name": name,
                "module": module_name,
                "bases": hierarchy["bases"],
                "docstring": hierarchy["docstring"],
                "methods": [],
                "file_path": hierarchy["file_path"]
            }
            
            modules[module_name]["classes"].append(name)
            
            # Add methods to class
            for method_name in hierarchy["methods"]:
                method_qualified_name = f"{name}.{method_name}"
                if method_qualified_name in self.function_signatures:
                    method_signature = self.function_signatures[method_qualified_name]
                    classes[name]["methods"].append({
                        "name": method_name,
                        "qualified_name": method_qualified_name,
                        "signature": self._format_signature(method_signature),
                        "docstring": method_signature["docstring"],
                        "is_async": method_signature["is_async"]
                    })
        
        # Enhance with callgraph relationships
        if "links" in callgraph_result:
            for link in callgraph_result["links"]:
                source = link.get("source")
                target = link.get("target")
                link_type = link.get("type", "call")
                
                if source in functions:
                    if "dependencies" not in functions[source]:
                        functions[source]["dependencies"] = []
                    functions[source]["dependencies"].append({
                        "target": target,
                        "type": link_type
                    })
                    
                # Check for method calls (may be in format Class.method)
                for class_name, class_info in classes.items():
                    class_methods = [m["qualified_name"] for m in class_info["methods"]]
                    if source in class_methods:
                        for i, method in enumerate(class_info["methods"]):
                            if method["qualified_name"] == source:
                                if "dependencies" not in method:
                                    classes[class_name]["methods"][i]["dependencies"] = []
                                classes[class_name]["methods"][i]["dependencies"].append({
                                    "target": target,
                                    "type": link_type
                                })
        
        # Generate final documentation structure
        documentation = {
            "modules": list(modules.values()),
            "classes": list(classes.values()),
            "functions": list(functions.values()),
            "metadata": callgraph_result.get("metadata", {})
        }
        
        # Add documentation-specific metadata
        documentation["metadata"]["documentation_generated"] = True
        documentation["metadata"]["docstrings_count"] = len(self.docstrings)
        documentation["metadata"]["functions_count"] = len(functions)
        documentation["metadata"]["classes_count"] = len(classes)
        documentation["metadata"]["modules_count"] = len(modules)
        
        return documentation
    
    def _format_signature(self, signature: Dict) -> str:
        """Format a function signature into a readable string"""
        func_name = signature["name"]
        is_async = signature["is_async"]
        args_str = []
        
        for arg_name, arg_type in signature["args"]:
            if arg_type:
                args_str.append(f"{arg_name}: {arg_type}")
            else:
                args_str.append(arg_name)
                
        return_type = signature.get("return_type", "")
        if return_type:
            return_annotation = f" -> {return_type}"
        else:
            return_annotation = ""
            
        async_prefix = "async " if is_async else ""
        return f"{async_prefix}def {func_name}({', '.join(args_str)}){return_annotation}"
    
    async def generate_docstrings_for_elements(self, elements: List[Dict], use_llm: bool = True) -> Dict:
        """
        Generate or enhance docstrings for code elements using LLM if requested.
        
        Args:
            elements: List of code elements (functions, classes, etc.)
            use_llm: Whether to use LLM to enhance or generate missing docstrings
            
        Returns:
            Dictionary mapping element names to generated/enhanced docstrings
        """
        result = {}
        
        for element in elements:
            element_name = element.get("qualified_name", element.get("name", ""))
            existing_docstring = element.get("docstring", "")
            
            if not existing_docstring and use_llm:
                # TODO: Implement LLM-based docstring generation
                # This will be implemented when we add the LLM service
                generated_docstring = await self._generate_docstring_with_llm(element)
                result[element_name] = generated_docstring
            else:
                result[element_name] = existing_docstring
                
        return result
    
    async def _generate_docstring_with_llm(self, element: Dict) -> str:
        """
        Generate a docstring for a code element using LLM.
        This is a placeholder for now - will be implemented when LLM service is added.
        
        Args:
            element: Code element to generate docstring for
            
        Returns:
            Generated docstring
        """
        # Placeholder - will be implemented when LLM service is added
        return "TODO: Generated docstring will be implemented with LLM integration"
    
    async def generate_markdown_documentation(self, doc_result: Dict) -> str:
        """
        Generate markdown documentation from documentation data.
        
        Args:
            doc_result: Documentation data from analyze_repository
            
        Returns:
            Markdown documentation as a string
        """
        if not doc_result:
            logger.warning("No documentation data available.")
            return ""
            
        modules = doc_result.get("modules", [])
        classes = doc_result.get("classes", [])
        functions = doc_result.get("functions", [])
        
        # Start with a header
        md = "# Repository Documentation\n\n"
        
        # Add repository information if available
        if self.repository_id:
            md += f"## Repository: {self.repository_id}\n\n"
        
        # Group by module
        modules_dict = {m.get("name"): m for m in modules if m.get("name")}
        
        # Add modules section
        if modules:
            md += "## Modules\n\n"
            for module_item in modules:
                module_name = module_item.get("name", "Unknown")
                md += f"### {module_name}\n\n"
                if module_item.get("docstring"):
                    md += f"{module_item['docstring']}\n\n"
                
                # Find classes in this module
                module_classes = [c for c in classes if c.get("module") == module_name]
                if module_classes:
                    md += "#### Classes\n\n"
                    for cls in module_classes:
                        md += f"##### {cls.get('name', 'Unknown')}\n\n"
                        if cls.get("docstring"):
                            md += f"{cls['docstring']}\n\n"
                        if cls.get("bases"):
                            md += f"**Inherits from:** {', '.join(cls['bases'])}\n\n"
                
                # Find functions in this module (not methods)
                module_funcs = [f for f in functions if f.get("module") == module_name and not f.get("is_method")]
                if module_funcs:
                    md += "#### Functions\n\n"
                    for func in module_funcs:
                        md += f"##### `{func.get('signature', func.get('name', 'Unknown'))}` \n\n"
                        if func.get("docstring"):
                            md += f"{func['docstring']}\n\n"
                        
        # Add standalone classes section
        standalone_classes = [c for c in classes if not c.get("module") or c.get("module") not in modules_dict]
        if standalone_classes:
            md += "## Standalone Classes\n\n"
            for cls in standalone_classes:
                md += f"### {cls.get('name', 'Unknown')}\n\n"
                if cls.get("file"):
                    md += f"**File:** {cls['file']}\n\n"
                if cls.get("docstring"):
                    md += f"{cls['docstring']}\n\n"
                if cls.get("bases"):
                    md += f"**Inherits from:** {', '.join(cls['bases'])}\n\n"
        
        # Add standalone functions section
        standalone_funcs = [f for f in functions if (not f.get("module") or f.get("module") not in modules_dict) and not f.get("is_method")]
        if standalone_funcs:
            md += "## Standalone Functions\n\n"
            for func in standalone_funcs:
                md += f"### `{func.get('signature', func.get('name', 'Unknown'))}`\n\n"
                if func.get("file"):
                    md += f"**File:** {func.get('file', 'Unknown')}\n\n"
                if func.get("docstring"):
                    md += f"{func['docstring']}\n\n"
        
        # Add metrics
        md += "## Metrics\n\n"
        md += f"- Total Modules: {len(modules)}\n"
        md += f"- Total Classes: {len(classes)}\n"
        md += f"- Total Functions: {len(functions)}\n"
        
        return md
    
    def _generate_class_markdown(self, class_info: Dict) -> str:
        """Generate markdown documentation for a class"""
        class_name = class_info["name"]
        qualified_name = class_info["qualified_name"]
        docstring = class_info["docstring"]
        bases = class_info["bases"]
        
        content = [
            f"# Class: {class_name}",
            "",
            f"**Qualified name**: `{qualified_name}`",
            "",
            docstring if docstring else "No class description available.",
            "",
            "## Inheritance",
            ""
        ]
        
        if bases:
            content.append(f"Inherits from: {', '.join(bases)}")
        else:
            content.append("No base classes.")
            
        content.extend([
            "",
            "## Methods",
            ""
        ])
        
        # List methods
        if class_info["methods"]:
            for method in class_info["methods"]:
                method_name = method["name"]
                method_summary = method["docstring"].split("\n")[0] if method["docstring"] else "No description available"
                content.append(f"### {method_name}")
                content.append("")
                content.append(f"**Signature**: `{method['signature']}`")
                content.append("")
                content.append(method["docstring"] if method["docstring"] else "No method description available.")
                content.append("")
                
                # Add dependencies if available
                if "dependencies" in method and method["dependencies"]:
                    content.append("**Calls:**")
                    for dep in method["dependencies"]:
                        content.append(f"- `{dep['target']}` ({dep['type']})")
                    content.append("")
        else:
            content.append("No methods in this class.")
            
        return "\n".join(content)
\n\n# ==============================\n# Filename: services\dynamic_call_analyzer.py\n# ==============================\n\nimport ast
import logging
from typing import Dict, List, Set, Optional, Tuple, Any, Union

logger = logging.getLogger(__name__)


class DynamicCallAnalyzer:
    def __init__(self, definition_manager=None):
        self.definition_manager = definition_manager
        self.dynamic_calls: List[Dict[str, Any]] = []

    def analyze_node(
        self, node: ast.AST, module_context: str = None
    ) -> List[Dict[str, Any]]:
        self.dynamic_calls = []
        self.module_context = module_context
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                self._analyze_call(subnode)
        return self.dynamic_calls

    def _analyze_call(self, node: ast.Call) -> None:
        if self._is_getattr_call(node):
            self._handle_getattr_call(node)
        elif self._is_dict_dispatch(node):
            self._handle_dict_dispatch(node)
        elif self._is_dynamic_import(node):
            self._handle_dynamic_import(node)
        elif self._is_apply_pattern(node):
            self._handle_apply_pattern(node)
        elif self._is_dependency_injection(node):
            self._handle_dependency_injection(node)

    def _is_getattr_call(self, node: ast.Call) -> bool:
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id == "getattr"
        ):
            return True
        if isinstance(node.func, ast.Name) and hasattr(node, "getattr_info"):
            return True
        return False

    def _handle_getattr_call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id == "getattr"
        ):
            if len(node.func.args) >= 2 and isinstance(node.func.args[1], ast.Str):
                obj_node = node.func.args[0]
                method_name = node.func.args[1].s
                obj_type = self._get_node_type(obj_node)
                self.dynamic_calls.append(
                    {
                        "type": "getattr",
                        "object_type": obj_type,
                        "method_name": method_name,
                        "node": node,
                        "possible_targets": self._resolve_getattr_targets(
                            obj_node, method_name
                        ),
                    }
                )

    def _is_dict_dispatch(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Subscript):
            return True
        return False

    def _handle_dict_dispatch(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Subscript):
            dict_name = self._get_node_name(node.func.value)
            key_repr = self._get_subscript_key_repr(node.func.slice)
            self.dynamic_calls.append(
                {
                    "type": "dict_dispatch",
                    "dict_name": dict_name,
                    "key": key_repr,
                    "node": node,
                    "possible_targets": self._resolve_dict_dispatch_targets(
                        node.func.value, node.func.slice
                    ),
                }
            )

    def _is_dynamic_import(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            return True
        if isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if node.func.value.id == "importlib" and node.func.attr == "import_module":
                return True
        return False

    def _handle_dynamic_import(self, node: ast.Call) -> None:
        module_name = None
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            if node.args and isinstance(node.args[0], ast.Str):
                module_name = node.args[0].s
        elif isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if node.func.value.id == "importlib" and node.func.attr == "import_module":
                if node.args and isinstance(node.args[0], ast.Str):
                    module_name = node.args[0].s
        if module_name:
            self.dynamic_calls.append(
                {
                    "type": "dynamic_import",
                    "module_name": module_name,
                    "node": node,
                    "possible_targets": [module_name],
                }
            )

    def _is_apply_pattern(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name) and node.func.id in (
            "map",
            "filter",
            "apply",
        ):
            return True
        return False

    def _handle_apply_pattern(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in ("map", "filter"):
            if node.args and isinstance(node.args[0], ast.Name):
                func_name = node.args[0].id
                self.dynamic_calls.append(
                    {
                        "type": "higher_order",
                        "function": node.func.id,
                        "argument_function": func_name,
                        "node": node,
                        "possible_targets": self._resolve_name(func_name),
                    }
                )

    def _is_dependency_injection(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id in (
                "container",
                "provider",
                "injector",
            ):
                if node.func.attr in ("get", "provide", "inject"):
                    return True
        return False

    def _handle_dependency_injection(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            container_name = node.func.value.id
            method_name = node.func.attr
            if node.args and isinstance(node.args[0], ast.Str):
                service_name = node.args[0].s
                self.dynamic_calls.append(
                    {
                        "type": "dependency_injection",
                        "container": container_name,
                        "method": method_name,
                        "service": service_name,
                        "node": node,
                        "possible_targets": [service_name],
                    }
                )

    def _get_node_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value_name = self._get_node_name(node.value)
            if value_name:
                return f"{value_name}.{node.attr}"
        return None

    def _get_node_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            if self.definition_manager:
                qualified_names = self.definition_manager.resolve_name(
                    node.id, self.module_context
                )
                if qualified_names:
                    for qname in qualified_names:
                        if qname in self.definition_manager.classes:
                            return qname
            return f"variable:{node.id}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return f"call_result:{node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                return f"call_result:{self._get_node_name(node.func)}"
        elif isinstance(node, ast.Str):
            return "str"
        elif isinstance(node, ast.Num):
            return "num"
        elif isinstance(node, ast.Dict):
            return "dict"
        elif isinstance(node, ast.List):
            return "list"
        return "unknown"

    def _get_subscript_key_repr(self, node: ast.AST) -> str:
        if isinstance(node, ast.Index):
            return self._get_subscript_key_repr(node.value)
        elif isinstance(node, ast.Str):
            return f"'{node.s}'"
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_node_name(node)}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return f"{node.func.id}(...)"
        return "unknown_key"

    def _resolve_name(self, name: str) -> List[str]:
        if self.definition_manager:
            return self.definition_manager.resolve_name(name, self.module_context)
        return [name]

    def _resolve_getattr_targets(
        self, obj_node: ast.AST, method_name: str
    ) -> List[str]:
        targets = []
        if isinstance(obj_node, ast.Name) and self.definition_manager:
            obj_name = obj_node.id
            qualified_names = self.definition_manager.resolve_name(
                obj_name, self.module_context
            )
            for qname in qualified_names:
                if qname in self.definition_manager.classes:
                    class_def = self.definition_manager.classes[qname]
                    method_qname = f"{qname}.{method_name}"
                    if method_qname in self.definition_manager.functions:
                        targets.append(method_qname)
                    else:
                        for base in class_def.base_classes:
                            base_method = f"{base}.{method_name}"
                            if base_method in self.definition_manager.functions:
                                targets.append(base_method)
        return targets

    def _resolve_dict_dispatch_targets(
        self, dict_node: ast.AST, key_node: ast.AST
    ) -> List[str]:
        targets = []
        if isinstance(key_node, ast.Index) and isinstance(key_node.value, ast.Str):
            key_str = key_node.value.s
            if isinstance(dict_node, ast.Name) and hasattr(dict_node, "parent_scope"):
                parent_scope = dict_node.parent_scope
                for node in ast.walk(parent_scope):
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == dict_node.id
                        for target in node.targets
                    ):
                        if isinstance(node.value, ast.Dict):
                            for i, k in enumerate(node.value.keys):
                                if (
                                    isinstance(k, ast.Str)
                                    and k.s == key_str
                                    and i < len(node.value.values)
                                ):
                                    value = node.value.values[i]
                                    if isinstance(value, ast.Name):
                                        targets.extend(self._resolve_name(value.id))
        return targets
\n\n# ==============================\n# Filename: services\dynamic_callgraph_builder.py\n# ==============================\n\nimport ast
import json
import os
from typing import Dict, List, Any, Set, Tuple
from .relationship_analysis import Relationship, RelationshipType
from .relationship_analysis.dynamic_analyzer import DynamicRelationshipAnalyzer
from .advanced_analysis.type_inference_engine import TypeInferenceEngine, PyType
from .advanced_analysis.context_sensitive_analyzer import ContextSensitiveAnalyzer


class DynamicCallGraphBuilder:
    def __init__(self, framework_hint: str, project_root_path: str = ""):
        self.framework_to_analyze_as = framework_hint
        self.project_root_path = project_root_path
        self.relationship_analyzer = DynamicRelationshipAnalyzer()
        self.type_engine = TypeInferenceEngine()
        self.context_analyzer = ContextSensitiveAnalyzer(k=2)
        self.current_file_graph: Dict[str, List[Dict[str, Any]]] = {
            "nodes": [],
            "links": [],
        }
        self.current_file_node_ids: Set[str] = set()

    def _add_node_to_current_file_graph(
        self, node_id: str, node_type: str, file_path: str = "", metadata: Dict = None
    ):
        if node_id not in self.current_file_node_ids:
            full_metadata = metadata or {}
            if file_path and "file_path" not in full_metadata:
                full_metadata["file_path"] = file_path
            if node_type == "module" and "category" not in full_metadata:
                full_metadata["category"] = "module"
                if file_path.endswith("__init__.py"):
                    full_metadata["category"] = "package_init"
            elif node_type == "class" and "category" not in full_metadata:
                full_metadata["category"] = "class_definition"
            elif node_type == "function" and "category" not in full_metadata:
                full_metadata["category"] = "function_definition"
            self.current_file_graph["nodes"].append(
                {"id": node_id, "type": node_type, "metadata": full_metadata}
            )
            self.current_file_node_ids.add(node_id)

    def _add_link_to_current_file_graph(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        metadata: Dict = None,
    ):
        metadata = metadata or {}
        file_path = metadata.get("file_path", "")
        if source_id not in self.current_file_node_ids:
            if self._is_external_entity(source_id):
                source_type = self._infer_node_type_from_id(source_id)
                self._add_placeholder_node(source_id, source_type, file_path)
            else:
                source_type = self._infer_node_type_from_id(source_id)
                self._add_node_to_current_file_graph(
                    source_id, source_type, file_path, {"category": "fallback_node"}
                )
        if target_id not in self.current_file_node_ids:
            if self._is_external_entity(target_id):
                target_type = self._infer_node_type_from_id(target_id)
                self._add_placeholder_node(target_id, target_type, file_path)
            else:
                target_type = self._infer_node_type_from_id(target_id)
                self._add_node_to_current_file_graph(
                    target_id, target_type, file_path, {"category": "fallback_node"}
                )
        link_data = {
            "source": source_id,
            "target": target_id,
            "type": rel_type.name,
            "metadata": metadata,
        }
        link_key_tuple = (
            source_id,
            target_id,
            rel_type.name,
            json.dumps(metadata, sort_keys=True),
        )
        self.current_file_graph["links"].append(link_data)

    def build_callgraph_for_file(
        self, ast_root: ast.AST, file_path: str = ""
    ) -> Dict[str, List[Dict[str, Any]]]:
        self.current_file_graph = {"nodes": [], "links": []}
        self.current_file_node_ids = set()
        initial_types = self.type_engine.infer_types(ast_root)
        module_name = self._get_module_name(file_path)
        self._add_node_to_current_file_graph(
            node_id=module_name, node_type="module", file_path=file_path
        )
        self._analyze_node(
            ast_root,
            context=[module_name] if module_name else [],
            current_types=initial_types.copy(),
            file_path=file_path,
        )
        return self.current_file_graph

    def get_analysis_metadata(self) -> Dict[str, Any]:
        """Returns metadata about the analysis performed by this builder instance."""
        return {
            "framework_analyzed_as": self.framework_to_analyze_as,
            "context_sensitivity_k": self.context_analyzer.k,
        }

    def _get_module_name(self, file_path: str) -> str:
        if not file_path:
            return "<unknown_module>"
        if not self.project_root_path:
            return os.path.splitext(os.path.basename(file_path))[0]
        try:
            relative_path = os.path.relpath(file_path, self.project_root_path)
            module_path = os.path.splitext(relative_path)[0]
            return module_path.replace(os.sep, ".")
        except ValueError:
            return os.path.splitext(os.path.basename(file_path))[0]

    def _qualify_name(self, name: str, context: List[str]) -> str:
        if not context or len(context) == 1:
            return f"{context[0] if context else self._get_module_name('')}.{name}"
        return ".".join(context + [name])

    def _analyze_node(
        self,
        node: ast.AST,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        node_type_name = type(node).__name__
        handler_name = f"_analyze_{node_type_name.lower()}"
        handler = getattr(self, handler_name, self._analyze_generic_node)
        handler(node, context, current_types, file_path)

    def _analyze_generic_node(
        self,
        node: ast.AST,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        for child_node in ast.iter_child_nodes(node):
            self._analyze_node(child_node, context, current_types, file_path)

    def _analyze_module(
        self,
        node: ast.Module,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        module_context = context[:1]
        for stmt in node.body:
            self._analyze_node(stmt, module_context, current_types, file_path)

    def _analyze_functiondef(
        self,
        node: ast.FunctionDef,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        func_name = node.name
        full_func_name = self._qualify_name(func_name, context)
        node_metadata = {
            "args": [arg.arg for arg in node.args.args],
            "lineno": node.lineno,
            "file_path": file_path,
        }
        self._add_node_to_current_file_graph(
            node_id=full_func_name, node_type="function", metadata=node_metadata
        )
        analysis_ctx = {
            "current_module": (
                context[0] if context else self._get_module_name(file_path)
            ),
            "current_class": (
                context[1]
                if len(context) > 1 and self._is_class_context_heuristic(context[1])
                else None
            ),
            "current_function": func_name,
            "file_path": file_path,
            "project_root": self.project_root_path,
        }
        relationships = self.relationship_analyzer.analyze(
            self.framework_to_analyze_as, node, analysis_ctx
        )
        for rel in relationships:
            self._add_link_to_current_file_graph(
                rel.source or full_func_name, rel.target, rel.type, rel.metadata
            )
        new_context = context + [func_name]
        for stmt in node.body:
            self._analyze_node(stmt, new_context, current_types, file_path)

    def _analyze_classdef(
        self,
        node: ast.ClassDef,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        class_name = node.name
        full_class_name = self._qualify_name(class_name, context)
        base_names = []
        for base in node.bases:
            base_name_str = ast.unparse(base)
            resolved_base_name = base_name_str
            inferred_type_for_base = current_types.get(base_name_str)
            if isinstance(inferred_type_for_base, str):
                resolved_base_name = inferred_type_for_base
            base_names.append(resolved_base_name)
        node_metadata = {
            "bases": base_names,
            "lineno": node.lineno,
            "file_path": file_path,
        }
        self._add_node_to_current_file_graph(
            node_id=full_class_name, node_type="class", metadata=node_metadata
        )
        for base_name_str in base_names:
            self._add_link_to_current_file_graph(
                full_class_name,
                base_name_str,
                RelationshipType.INHERITANCE,
                {"file_path": file_path},
            )
        analysis_ctx = {
            "current_module": (
                context[0] if context else self._get_module_name(file_path)
            ),
            "current_class": class_name,
            "file_path": file_path,
            "project_root": self.project_root_path,
        }
        relationships = self.relationship_analyzer.analyze(
            self.framework_to_analyze_as, node, analysis_ctx
        )
        for rel in relationships:
            self._add_link_to_current_file_graph(
                rel.source or full_class_name, rel.target, rel.type, rel.metadata
            )
        new_context = context + [class_name]
        for stmt in node.body:
            self._analyze_node(stmt, new_context, current_types, file_path)

    def _analyze_call(
        self,
        node: ast.Call,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ) -> None:
        caller_name = ".".join(context) if context else "__main__"
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            target_name = self._qualify_name(func_name, context[:-1] if context else [])
            if target_name == func_name and "__main__" not in target_name:
                module_name = self._get_module_name(file_path)
                if module_name:
                    alternative_target = f"{module_name}.{func_name}"
                    if self.type_engine and self.type_engine.is_known_global(
                        alternative_target
                    ):
                        target_name = alternative_target
            if func_name in [
                "render",
                "redirect",
                "get_object_or_404",
                "Q",
                "path",
                "include",
                "static",
                "reverse",
            ]:
                target_name = (
                    f"django.{func_name}" if func_name != "Q" else "django.db.models.Q"
                )
            if func_name in [
                "ForeignKey",
                "OneToOneField",
                "ManyToManyField",
                "CharField",
                "TextField",
                "DateTimeField",
                "ImageField",
                "FileField",
                "BooleanField",
            ]:
                target_name = f"django.db.models.{func_name}"
                if (
                    func_name in ["ForeignKey", "OneToOneField", "ManyToManyField"]
                    and node.args
                ):
                    if isinstance(node.args[0], ast.Name):
                        related_model = node.args[0].id
                        if len(context) >= 2 and self._is_class_context_heuristic(
                            context[-2].split(".")[-1]
                        ):
                            current_model = context[-2]
                            relationship_metadata = {"relationship_type": func_name}
                            self._add_link_to_current_file_graph(
                                current_model.split(".")[-1],
                                related_model,
                                RelationshipType.MODEL_ACCESS,
                                relationship_metadata,
                            )
        elif isinstance(node.func, ast.Attribute):
            value_node = node.func.value
            attr_name = node.func.attr
            if isinstance(value_node, ast.Name):
                var_name = value_node.id
                var_type = None
                if var_name in current_types:
                    var_type = current_types[var_name]
                if var_type:
                    if isinstance(var_type, str):
                        target_name = f"{var_type}.{attr_name}"
                    else:
                        if hasattr(var_type, "qualified_name"):
                            target_name = f"{var_type.qualified_name}.{attr_name}"
                        else:
                            target_name = f"<UnknownClass>.{attr_name}"
                else:
                    if var_name == "self" and len(context) >= 1:
                        if len(context) >= 2 and self._is_class_context_heuristic(
                            context[-2].split(".")[-1]
                        ):
                            class_name = context[-2]
                            target_name = f"{class_name}.{attr_name}"
                        else:
                            target_name = f"<UnknownClass>.{attr_name}"
                    else:
                        module_prefix = (
                            ".".join(context[0:-1])
                            if len(context) > 1
                            else self._get_module_name(file_path)
                        )
                        if self._is_class_context_heuristic(var_name):
                            potential_class_name = (
                                f"{module_prefix}.{var_name}"
                                if module_prefix
                                else var_name
                            )
                            target_name = f"{potential_class_name}.{attr_name}"
                        else:
                            target_name = f"{var_name}.{attr_name}"
                if var_name in ["models"] and attr_name in [
                    "Model",
                    "CharField",
                    "TextField",
                    "ForeignKey",
                    "OneToOneField",
                    "ManyToManyField",
                    "DateTimeField",
                    "ImageField",
                    "FileField",
                ]:
                    target_name = f"django.db.models.{attr_name}"
                if var_name in ["forms"] and attr_name in [
                    "ModelForm",
                    "Form",
                    "CharField",
                    "EmailField",
                ]:
                    target_name = f"django.forms.{attr_name}"
            else:
                target_name = f"<ComplexCall>.{attr_name}"
        else:
            target_name = "<DynamicCall>"
        call_analysis_context = {
            "current_module": (
                context[0] if context else self._get_module_name(file_path)
            ),
            "current_class": (
                context[1]
                if len(context) > 1 and self._is_class_context_heuristic(context[1])
                else None
            ),
            "current_function": (
                context[-1]
                if len(context) > 1
                and not self._is_class_context_heuristic(context[-1])
                else (
                    context[-2]
                    if len(context) > 2
                    and not self._is_class_context_heuristic(context[-2])
                    else None
                )
            ),
            "file_path": file_path,
            "caller_name": caller_name,
            "project_root": self.project_root_path,
        }
        relationships = self.relationship_analyzer.analyze(
            self.framework_to_analyze_as, node, call_analysis_context
        )
        for rel in relationships:
            self._add_link_to_current_file_graph(
                rel.source or caller_name, rel.target, rel.type, rel.metadata
            )
        call_metadata = {
            "resolution": "context_sensitive",
            "lineno": node.lineno,
            "file_path": file_path,
        }
        self._add_link_to_current_file_graph(
            caller_name, target_name, RelationshipType.FUNCTION_CALL, call_metadata
        )
        for arg_node in node.args:
            self._analyze_node(arg_node, context, current_types, file_path)
        for kwarg_node in node.keywords:
            self._analyze_node(kwarg_node.value, context, current_types, file_path)
        self._analyze_node(node.func, context, current_types, file_path)

    def _is_class_context_heuristic(self, name_part: str) -> bool:
        return name_part and name_part[0].isupper()

    def _is_external_entity(self, node_id: str) -> bool:
        """Determine if a node ID represents an external entity that needs a placeholder."""
        external_patterns = [
            "<UnknownClass>",
            "models.Model",
            "ImportError",
            "UserCreationForm",
            "forms.ModelForm",
            "AppConfig",
            "ListView",
            "DetailView",
            "CreateView",
            "UpdateView",
            "DeleteView",
            "LoginRequiredMixin",
            "UserPassesTestMixin",
        ]
        if any(pattern in node_id for pattern in external_patterns):
            return True
        if "." not in node_id and node_id[0].isupper():
            return True
        return False

    def _infer_node_type_from_id(self, node_id: str) -> str:
        """Infer the type of node based on its ID pattern."""
        node_type = "module"
        if "<UnknownClass>" in node_id:
            node_type = "class"
        elif "." in node_id and node_id.split(".")[-1][0].islower():
            node_type = "function"
        elif "." in node_id and node_id.split(".")[-1][0].isupper():
            node_type = "class"
        elif node_id[0].isupper() and "." not in node_id:
            node_type = "class"
        return node_type

    def _add_placeholder_node(self, node_id: str, node_type: str, file_path: str = ""):
        """Add a placeholder node for an external or unresolved entity."""
        metadata = {"category": "external_entity", "is_placeholder": True}
        if file_path:
            metadata["file_path"] = file_path
        if "<UnknownClass>" in node_id:
            metadata["category"] = "unresolved_class"
        elif node_id[0].isupper() and "." not in node_id:
            metadata["category"] = "external_class"
        if node_type == "function" and any(
            field in node_id
            for field in ["Field", "CharField", "TextField", "ForeignKey"]
        ):
            metadata["category"] = "model_field"
        self._add_node_to_current_file_graph(node_id, node_type, file_path, metadata)


if __name__ == "__main__":
    source_code = """
class Greeter:
    def __init__(self, name):
        self.name = name
    def greet(self):
        print(f"Hello, {self.name}!")
class Person:
    def __init__(self, greeter: Greeter):
        self.greeter = greeter
    def introduce(self):
        self.greeter.greet()
def main_func():
    g = Greeter("World")
    p = Person(g)
    p.introduce()
main_func()
"""
    ast_tree = ast.parse(source_code)
    builder = DynamicCallGraphBuilder(
        framework_hint="generic", project_root_path="/dummy/project"
    )
    file_graph_data = builder.build_callgraph_for_file(
        ast_tree, file_path="/dummy/project/example.py"
    )
    print("--- File Specific Graph ---")
    print(json.dumps(file_graph_data, indent=2))
    metadata = builder.get_analysis_metadata()
    print("\n--- Analysis Metadata ---")
    print(json.dumps(metadata, indent=2))
\n\n# ==============================\n# Filename: services\enhanced_callgraph.py\n# ==============================\n\nimport os
import ast
import logging
from typing import Dict, List, Set, Optional, Tuple, Any
import time
import asyncio
import traceback
from .callgraph import CallgraphGenerator
from .scope_manager import ScopeManager, Scope
from .definition_manager import DefinitionManager, FunctionDefinition, ClassDefinition

logger = logging.getLogger(__name__)


class EnhancedCallgraphGenerator(CallgraphGenerator):
    def __init__(self):
        super().__init__()
        self.scope_manager = ScopeManager()
        self.definition_manager = DefinitionManager()
        self.framework_type = None
        self.framework_specific_handlers = {
            "django": self._handle_django_framework,
            "flask": self._handle_flask_framework,
            "fastapi": self._handle_fastapi_framework,
        }

    async def analyze_repository(
        self, repo_path: str, timeout: int = 600, clone: bool = False, perform_cleanup: bool = True
    ) -> Dict:
        start_time = time.time()
        self.status = "Analyzing repository..."

        logger.info(f"[EnhancedCallgraphGenerator] analyze_repository called with: repo_path={repo_path}, clone={clone}")

        if clone:
            logger.info(f"[EnhancedCallgraphGenerator] Cloning repository: {repo_path}")
            self.tmp_dir = await self.clone_repository(str(repo_path), timeout=timeout)
            self.repo_path = self.tmp_dir
            self.cleanup_needed = True
            logger.info(f"[EnhancedCallgraphGenerator] After cloning: self.tmp_dir={self.tmp_dir}, self.repo_path={self.repo_path}")
        else:
            logger.info(f"[EnhancedCallgraphGenerator] Using existing path: {repo_path}")
            self.repo_path = repo_path
            self.tmp_dir = None
            self.cleanup_needed = False

        logger.info(f"[EnhancedCallgraphGenerator] Before os.path.exists check: self.repo_path={self.repo_path}")
        if not os.path.exists(self.repo_path):
            logger.error(f"[EnhancedCallgraphGenerator] FileNotFoundError: Repository path does not exist: {self.repo_path}")
            raise FileNotFoundError(f"Repository path does not exist: {self.repo_path}")

        # Skip the base analysis from CallgraphGenerator
        # Instead, we'll populate self.functions and self.classes directly
        # through _enhanced_analyze_file which also calls definition_manager.analyze_file
        self.functions = {}
        self.classes = {}
        self.imports = {}
        self.nodes = []
        self.links = []

        logger.info(f"Performing detailed analysis of files in {self.repo_path}...")
        for root, dirs, files in os.walk(self.repo_path):
            dirs[:] = [
                d
                for d in dirs
                if not d.startswith(('.', '_'))
                and d not in ('venv', 'env', 'node_modules', '__pycache__', '.git')
            ]
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    try:
                        self._enhanced_analyze_file(file_path)
                    except Exception as e:
                        logger.debug(f"Error in enhanced analysis of {file_path}: {str(e)}")

        self.framework_type = self._detect_framework()
        logger.info(f"Detected framework: {self.framework_type}")

        if self.framework_type in self.framework_specific_handlers:
            handler = self.framework_specific_handlers[self.framework_type]
            handler()

        enhanced_callgraph = self._build_enhanced_callgraph()

        if perform_cleanup and clone:
            await self.cleanup()

        logger.info(f"Enhanced analysis completed in {time.time() - start_time:.2f} seconds")
        return enhanced_callgraph

    def _enhanced_analyze_file(self, file_path: str) -> None:
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception as e:
            logger.error(f"Failed to read {file_path}: {str(e)}")
            return
        try:
            tree = ast.parse(content, filename=file_path)
            for node_walker in ast.walk(tree):
                for child in ast.iter_child_nodes(node_walker):
                    child.parent = node_walker
            rel_path = os.path.relpath(file_path, self.repo_path)
            module_name = rel_path.replace(".py", "").replace(os.sep, ".")
            if os.path.basename(file_path) == "__init__.py":
                module_name = module_name.rstrip(".__init__")
            self.scope_manager.analyze_scope(tree, module_name, "module")
            self.definition_manager.analyze_file(file_path, tree=tree)
        except SyntaxError as e:
            logger.warning(f"Syntax error in {file_path}: {str(e)}")
        except Exception as e:
            logger.error(
                f"Error analyzing {file_path}: {str(e)}\n{traceback.format_exc()}"
            )

    def _safe_read_file(self, file_path: str) -> str:
        if any(
            file_path.endswith(ext)
            for ext in [
                ".pyc",
                ".png",
                ".jpg",
                ".jpeg",
                ".gif",
                ".pdf",
                ".zip",
                ".gz",
                ".tar",
                ".exe",
                ".dll",
                ".so",
                ".bin",
                ".dat",
                ".db",
                ".sqlite",
                ".sqlite3",
                ".svg",
                ".ico",
                ".woff",
                ".ttf",
            ]
        ):
            return ""
        encodings = ["utf-8", "latin-1", "iso-8859-1", "cp1252"]
        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except (UnicodeDecodeError, PermissionError, IOError, OSError):
                continue
        try:
            with open(file_path, "rb") as f:
                content = f.read(1024)
                if b"\x00" not in content[:1000]:
                    return content.decode("latin-1", errors="replace")
        except (IOError, OSError):
            pass
        return ""

    def _detect_framework(self) -> str:
        framework_indicators = {"django": 0, "flask": 0, "fastapi": 0}
        for root, _, files in os.walk(self.repo_path):
            for file in files:
                try:
                    file_path = os.path.join(root, file)
                    file_content = self._safe_read_file(file_path)
                    if not file_content:
                        continue
                    if "settings.py" in file_path or "urls.py" in file_path:
                        framework_indicators["django"] += 1
                    if "app.py" in file_path and "run(" in file_content:
                        framework_indicators["flask"] += 1
                    if "fastapi" in file_path or "APIRouter" in file_content:
                        framework_indicators["fastapi"] += 1
                except Exception as e:
                    logger.debug(f"Skipping file {file_path} due to error: {str(e)}")
                    continue
        for module_imports in self.imports.values():
            for import_str in module_imports:
                if "django" in import_str:
                    framework_indicators["django"] += 1
                if "flask" in import_str:
                    framework_indicators["flask"] += 1
                if "fastapi" in import_str:
                    framework_indicators["fastapi"] += 1
        if max(framework_indicators.values()) > 0:
            return max(framework_indicators.items(), key=lambda x: x[1])[0]
        return "python"

    async def cleanup(self):
        if self.repo_path and os.path.exists(self.repo_path):
            logger.info(f"Cleaning up temporary repository at {self.repo_path}")
            try:
                import shutil
                shutil.rmtree(self.repo_path)
                self.repo_path = None
            except Exception as e:
                logger.error(f"Error cleaning up repository {self.repo_path}: {e}")

    def _handle_django_framework(self) -> None:
        logger.info("Applying Django-specific analysis...")
        django_views = set()
        for func_name, func_info in self.base_functions.items():
            if func_info.get("is_django_view", False):
                django_views.add(func_name)
                if func_name in self.functions:
                    self.functions[func_name]["is_django_view"] = True
            if "views.py" in func_info.get("file", ""):
                if not func_name.startswith("_"):
                    django_views.add(func_name)
                    if func_name in self.functions:
                        self.functions[func_name]["is_django_view"] = True
        django_models = set()
        for class_name, class_info in self.classes.items():
            if "models.py" in class_info.get("file", ""):
                django_models.add(class_name)
        logger.info(f"Found {len(django_views)} Django view functions")
        logger.info(f"Found {len(django_models)} Django model classes")
        self._analyze_url_patterns(django_views)
        self._connect_django_views_to_templates(django_views)
        self._connect_django_views_to_models(django_views, django_models)
        self._add_view_to_view_links(django_views)

    def _handle_flask_framework(self) -> None:
        logger.info("Applying Flask-specific analysis...")

    def _handle_fastapi_framework(self) -> None:
        logger.info("Applying FastAPI-specific analysis...")

    def _analyze_url_patterns(self, view_functions: Set[str]) -> None:
        url_files = []
        for root, dirs, files in os.walk(self.repo_path):
            for file in files:
                if file == "urls.py":
                    url_files.append(os.path.join(root, file))
        for urls_file in url_files:
            app_name = os.path.basename(os.path.dirname(urls_file))
            try:
                content = self._safe_read_file(urls_file)
                if not content:
                    continue
                url_node_id = f"urls:{app_name}"
                if not any(node.get("id") == url_node_id for node in self.nodes):
                    self.nodes.append(
                        {
                            "id": url_node_id,
                            "name": f"URLs ({app_name})",
                            "type": "url_config",
                            "file": urls_file,
                            "complexity": 1,
                        }
                    )
                for view_func in view_functions:
                    view_name = view_func.split(".")[-1]
                    if view_name in content:
                        self.links.append(
                            {
                                "source": url_node_id,
                                "target": view_func,
                                "value": 1,
                                "type": "url_route",
                            }
                        )
                        if "include" in content:
                            for other_url_file in url_files:
                                if other_url_file != urls_file:
                                    other_app = os.path.basename(
                                        os.path.dirname(other_url_file)
                                    )
                                    if other_app in content:
                                        self.links.append(
                                            {
                                                "source": url_node_id,
                                                "target": f"urls:{other_app}",
                                                "value": 1,
                                                "type": "url_include",
                                            }
                                        )
            except Exception as e:
                logger.debug(f"Error analyzing URL patterns in {urls_file}: {str(e)}")

    def _add_view_to_view_links(self, view_functions: Set[str]) -> None:
        for view_func in view_functions:
            try:
                if view_func not in self.functions:
                    continue
                func_info = self.functions[view_func]
                node = func_info.get("node")
                if not node:
                    continue
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Call) and isinstance(
                        subnode.func, ast.Name
                    ):
                        if subnode.func.id in ["redirect", "reverse"]:
                            for other_view in view_functions:
                                other_name = other_view.split(".")[-1]
                                for arg in subnode.args:
                                    if isinstance(arg, ast.Str) and other_name in arg.s:
                                        self.links.append(
                                            {
                                                "source": view_func,
                                                "target": other_view,
                                                "value": 1,
                                                "type": "redirect",
                                            }
                                        )
            except Exception as e:
                logger.debug(
                    f"Error analyzing view-to-view links for {view_func}: {str(e)}"
                )

    def _connect_django_views_to_urls(self, view_functions: Set[str]) -> None:
        self._analyze_url_patterns(view_functions)

    def _connect_django_views_to_templates(self, view_functions: Set[str]) -> None:
        for view_func in view_functions:
            if view_func not in self.functions:
                continue
            func_info = self.functions[view_func]
            func_node = func_info.get("node")
            if not func_node:
                continue
            for node in ast.walk(func_node):
                if (
                    isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == "render"
                ):
                    if len(node.args) >= 2 and isinstance(node.args[1], ast.Str):
                        template_name = node.args[1].s
                        app_name = "unknown"
                        template_purpose = "Unknown"
                        if "/" in template_name:
                            app_name = template_name.split("/")[0]
                        if "form" in template_name.lower():
                            template_purpose = "Form"
                        elif "list" in template_name.lower():
                            template_purpose = "List View"
                        elif "detail" in template_name.lower():
                            template_purpose = "Detail View"
                        elif any(
                            x in template_name.lower() for x in ["create", "add", "new"]
                        ):
                            template_purpose = "Creation Form"
                        elif any(
                            x in template_name.lower() for x in ["edit", "update"]
                        ):
                            template_purpose = "Edit Form"
                        elif "delete" in template_name.lower():
                            template_purpose = "Deletion Form"
                        elif (
                            "home" in template_name.lower()
                            or "index" in template_name.lower()
                        ):
                            template_purpose = "Homepage"
                        elif "login" in template_name.lower():
                            template_purpose = "Login Form"
                        elif (
                            "register" in template_name.lower()
                            or "signup" in template_name.lower()
                        ):
                            template_purpose = "Registration Form"
                        elif "profile" in template_name.lower():
                            template_purpose = "User Profile"
                        display_name = f"{app_name.title()}: {template_purpose}"
                        template_id = f"template:{template_name}"
                        if template_id not in self.nodes:
                            self.nodes.append(
                                {
                                    "id": template_id,
                                    "name": display_name,
                                    "group": 9,
                                    "type": "template",
                                    "complexity": 1,
                                    "file": template_name,
                                    "metadata": {
                                        "docstring": f"Template: {template_name}\n\nPurpose: {template_purpose}\nApplication: {app_name}",
                                        "refactoring": "",
                                    },
                                }
                            )
                        self.links.append(
                            {
                                "source": view_func,
                                "target": template_id,
                                "value": 1,
                                "type": "render",
                            }
                        )

    def _connect_django_views_to_models(
        self, view_functions: Set[str], model_classes: Set[str] = None
    ) -> None:
        if model_classes is None:
            model_classes = set()
            for class_name, class_info in self.classes.items():
                if "models.py" in class_info.get("file", ""):
                    model_classes.add(class_name)
                elif class_info.get("type") == "model":
                    model_classes.add(class_name)
                elif class_info.get("node"):
                    try:
                        node = class_info.get("node")
                        for base in getattr(node, "bases", []):
                            if hasattr(base, "attr") and hasattr(base, "value"):
                                if (
                                    hasattr(base.value, "id")
                                    and base.value.id == "models"
                                    and hasattr(base, "attr")
                                    and base.attr == "Model"
                                ):
                                    model_classes.add(class_name)
                                    self.classes[class_name]["type"] = "model"
                                    break
                    except Exception as e:
                        logging.debug(f"Error checking model inheritance: {e}")
        for model_class in model_classes:
            if model_class in self.classes:
                model_info = self.classes[model_class]
                file_path = model_info.get("file", "")
                node = model_info.get("node")
                app_name = "unknown"
                if file_path:
                    parts = file_path.split(os.sep)
                    for i, part in enumerate(parts):
                        if part == "models.py" and i > 0:
                            app_name = parts[i - 1]
                            break
                fields = []
                relations = []
                if node:
                    for item in node.body:
                        if isinstance(item, ast.Assign) and len(item.targets) == 1:
                            if isinstance(item.targets[0], ast.Name):
                                field_name = item.targets[0].id
                                field_type = ""
                                if isinstance(item.value, ast.Call):
                                    if hasattr(item.value.func, "attr"):
                                        field_type = item.value.func.attr
                                    elif hasattr(item.value.func, "id"):
                                        field_type = item.value.func.id
                                    if any(
                                        x in field_type.lower()
                                        for x in [
                                            "foreignkey",
                                            "onetoone",
                                            "manytomany",
                                        ]
                                    ):
                                        relations.append((field_name, field_type))
                                    else:
                                        fields.append((field_name, field_type))
                docstring = model_info.get("docstring", "")
                if not docstring:
                    docstring = f"Django Model: {model_class}"
                    if app_name != "unknown":
                        docstring += f"\nApplication: {app_name}"
                    if fields:
                        docstring += "\n\nFields:"
                        for field_name, field_type in fields:
                            docstring += f"\n - {field_name}: {field_type}"
                    if relations:
                        docstring += "\n\nRelationships:"
                        for field_name, field_type in relations:
                            docstring += f"\n - {field_name}: {field_type}"
                self.classes[model_class]["metadata"] = {
                    "docstring": docstring,
                    "refactoring": model_info.get("metadata", {}).get(
                        "refactoring", ""
                    ),
                    "app": app_name,
                    "fields": fields,
                    "relations": relations,
                }
                for i, node in enumerate(self.nodes):
                    if node.get("id") == model_class:
                        self.nodes[i]["type"] = "model"
                        self.nodes[i]["group"] = 5
                        self.nodes[i][
                            "name"
                        ] = f"{app_name.title()}: {model_class.split('.')[-1]}"
                        self.nodes[i]["metadata"] = self.classes[model_class][
                            "metadata"
                        ]
                        break
        self._add_model_relationships(model_classes, view_functions)

    def _add_model_relationships(
        self, model_classes: Set[str], view_functions: Set[str] = None
    ) -> None:
        model_name_map = {}
        view_functions = view_functions or set()
        for model_class in model_classes:
            short_name = model_class.split(".")[-1]
            model_name_map[short_name] = model_class
        for model_class in model_classes:
            if model_class not in self.classes:
                continue
            model_info = self.classes[model_class]
            node = model_info.get("node")
            if not node:
                continue
            for item in node.body:
                if isinstance(item, ast.Assign) and len(item.targets) == 1:
                    if not isinstance(item.targets[0], ast.Name):
                        continue
                    field_name = item.targets[0].id
                    if not isinstance(item.value, ast.Call):
                        continue
                    field_type = ""
                    if hasattr(item.value.func, "attr"):
                        field_type = item.value.func.attr
                    elif hasattr(item.value.func, "id"):
                        field_type = item.value.func.id
                    is_relation = any(
                        x in field_type.lower()
                        for x in ["foreignkey", "onetoone", "manytomany"]
                    )
                    if not is_relation:
                        continue
                    target_model = None
                    for arg in item.value.args:
                        if isinstance(arg, ast.Name):
                            target_model_name = arg.id
                            if target_model_name in model_name_map:
                                target_model = model_name_map[target_model_name]
                            break
                        elif isinstance(arg, ast.Str):
                            target_model_name = (
                                arg.s.split(".")[-1] if "." in arg.s else arg.s
                            )
                            if target_model_name in model_name_map:
                                target_model = model_name_map[target_model_name]
                            break
                    if target_model and target_model != model_class:
                        relationship_type = field_type.lower().replace("field", "")
                        self.links.append(
                            {
                                "source": model_class,
                                "target": target_model,
                                "value": 1,
                                "type": "model_relation",
                                "label": relationship_type,
                            }
                        )
                        logging.debug(
                            f"Added model relationship: {model_class} -> {target_model} ({field_name}: {field_type})"
                        )
        for view_func in view_functions:
            try:
                if view_func not in self.functions:
                    continue
                view_info = self.functions[view_func]
                node = view_info.get("node")
                file_path = view_info.get("file", "")
                if not node:
                    continue
                source_code = ""
                try:
                    source_code = ast.unparse(node)
                except:
                    with open(file_path, "r") as f:
                        source_code = f.read()
                for model_class in model_classes:
                    model_name = model_class.split(".")[-1]
                    if model_name in source_code:
                        for pattern in [
                            f"{model_name}.objects",
                            f"get({model_name}",
                            f"filter({model_name}",
                        ]:
                            if pattern in source_code:
                                self.links.append(
                                    {
                                        "source": view_func,
                                        "target": model_class,
                                        "value": 1,
                                        "type": "model_access",
                                    }
                                )
                                break
                model_accesses = set()
                for subnode in ast.walk(node):
                    if isinstance(subnode, ast.Attribute) and isinstance(
                        subnode.value, ast.Name
                    ):
                        obj_name = subnode.value.id
                        for model_class in model_classes:
                            model_name = model_class.split(".")[-1]
                            if obj_name == model_name and subnode.attr == "objects":
                                model_accesses.add(model_class)
                    elif isinstance(subnode, ast.Call) and isinstance(
                        subnode.func, ast.Name
                    ):
                        if subnode.func.id.endswith("Form"):
                            for kw in subnode.keywords:
                                if kw.arg == "model" and isinstance(kw.value, ast.Name):
                                    model_name = kw.value.id
                                    for model_class in model_classes:
                                        if (
                                            model_class.endswith("." + model_name)
                                            or model_class == model_name
                                        ):
                                            model_accesses.add(model_class)
                for model_class in model_accesses:
                    self.links.append(
                        {
                            "source": view_func,
                            "target": model_class,
                            "value": 1,
                            "type": "model_access",
                        }
                    )
            except Exception as e:
                logger.debug(f"Error connecting view {view_func} to models: {str(e)}")

    def _build_enhanced_callgraph(self) -> Dict[str, List]:
        for func_name, func_def in self.definition_manager.functions.items():
            short_name = func_name.split(".")[-1]
            matching_func = None
            for existing_func in self.functions.keys():
                if (
                    existing_func.endswith("." + short_name)
                    or existing_func == short_name
                ):
                    matching_func = existing_func
                    break
            if not matching_func:
                continue
            for target_name, call_node in func_def.calls:
                target_short_name = target_name.split(".")[-1]
                matching_target = None
                for existing_func in self.functions.keys():
                    if (
                        existing_func.endswith("." + target_short_name)
                        or existing_func == target_short_name
                    ):
                        matching_target = existing_func
                        break
                if not matching_target:
                    continue
                link_exists = False
                for link in self.links:
                    if (
                        link.get("source") == matching_func
                        and link.get("target") == matching_target
                    ):
                        link_exists = True
                        break
                if not link_exists:
                    self.links.append(
                        {
                            "source": matching_func,
                            "target": matching_target,
                            "value": 1,
                            "type": "call",
                        }
                    )
        node_ids = {node.get("id") for node in self.nodes}
        new_nodes = []
        for link in self.links:
            for endpoint in ["source", "target"]:
                node_id = link.get(endpoint)
                if node_id and node_id not in node_ids:
                    new_nodes.append(
                        {
                            "id": node_id,
                            "name": node_id.split(".")[-1],
                            "type": (
                                "function"
                                if ":" not in node_id
                                else node_id.split(":")[0]
                            ),
                            "complexity": 1,
                        }
                    )
                    node_ids.add(node_id)
        self.nodes.extend(new_nodes)
        callgraph = {"nodes": self.nodes, "links": self.links}
        avg_complexity = (
            sum(node.get("complexity", 1) for node in self.nodes) / len(self.nodes)
            if self.nodes
            else 0
        )
        most_complex = None
        if self.nodes:
            most_complex_node = max(self.nodes, key=lambda x: x["complexity"])
            most_complex = {
                "id": most_complex_node["id"],
                "complexity": most_complex_node["complexity"],
                "file": most_complex_node["file"],
            }
        result = {
            "nodes": self.nodes,
            "links": self.links,
            "classes": list(self.classes.keys()),
            "imports": self.imports,
            "metadata": {
                "total_nodes": len(self.nodes),
                "total_links": len(self.links),
                "avg_complexity": avg_complexity,
                "functionCount": len(self.nodes),
                "dependencyCount": len(self.links),
                "mostComplexFunction": most_complex,
                "framework": self.framework_type,
            },
        }
        logger.info(
            f"Enhanced callgraph generated with {len(self.nodes)} nodes and {len(self.links)} links"
        )
        return result
\n\n# ==============================\n# Filename: services\llm\__init__.py\n# ==============================\n\n"""
LLM integration services for GraphiX.
Provides high-level interfaces for leveraging LLMs in the application.
"""
\n\n# ==============================\n# Filename: services\llm\chat_service.py\n# ==============================\n\nimport os
import logging
import json
import uuid
from typing import Dict, List, Set, Optional, Any, Union
import asyncio
from datetime import datetime

from .llm_manager import LLMManager, Message
from .context_builder import ContextBuilder
from ...models.base import settings

logger = logging.getLogger(__name__)

class ChatSession:
    """
    Represents a single chat session about a codebase.
    
    Maintains conversation history, context, and metadata for a chat session.
    """
    
    def __init__(self, 
                 session_id: Optional[str] = None,
                 repository_id: Optional[str] = None,
                 callgraph_data: Optional[Dict] = None):
        """
        Initialize a new chat session.
        
        Args:
            session_id: Optional session ID (generated if not provided)
            repository_id: ID of the repository being discussed
            callgraph_data: Optional callgraph data for contextual information
        """
        self.session_id = session_id or str(uuid.uuid4())
        self.repository_id = repository_id
        self.callgraph_data = callgraph_data
        self.messages = []
        self.context_history = []
        self.created_at = datetime.now()
        self.last_active = datetime.now()
        
    def add_message(self, role: str, content: str) -> None:
        """
        Add a message to the conversation history.
        
        Args:
            role: Role of the message sender ('user', 'assistant', 'system')
            content: Content of the message
        """
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })
        self.last_active = datetime.now()
        
    def add_context(self, context: Dict) -> None:
        """
        Add context information to the session history.
        
        Args:
            context: Context information used for a response
        """
        self.context_history.append({
            "context": context,
            "timestamp": datetime.now().isoformat()
        })
        
    def get_messages(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get the conversation history.
        
        Args:
            limit: Optional limit on number of messages to return
            
        Returns:
            List of messages, most recent last
        """
        if limit is not None:
            return self.messages[-limit:]
        return self.messages
    
    def get_formatted_messages(self, limit: Optional[int] = None) -> List[Message]:
        """
        Get the conversation history formatted for LLM API.
        
        Args:
            limit: Optional limit on number of messages to return
            
        Returns:
            List of Message objects for LLM API
        """
        messages = self.get_messages(limit)
        return [Message(role=msg["role"], content=msg["content"]) for msg in messages]
    
    def to_dict(self) -> Dict:
        """
        Convert the session to a dictionary representation.
        
        Returns:
            Dictionary representation of the session
        """
        return {
            "session_id": self.session_id,
            "repository_id": self.repository_id,
            "messages_count": len(self.messages),
            "created_at": self.created_at.isoformat(),
            "last_active": self.last_active.isoformat()
        }

class ChatService:
    """
    Service for managing codebase chat functionality.
    
    This service orchestrates conversations about codebases, leveraging
    the context builder and LLM services to provide intelligent responses.
    """
    
    def __init__(self):
        """Initialize the chat service with required dependencies"""
        self.llm_manager = LLMManager()
        self.context_builder = ContextBuilder()
        self.sessions = {}
        self.system_prompt_template = """
You are an expert code assistant analyzing a codebase. You can understand code structure, relationships between components, and provide insightful answers about the codebase.

Use the following context about the codebase to inform your responses:

{context}

Remember to:
1. Focus on what's in the provided code and context
2. If you're uncertain about aspects not in the context, acknowledge the limitations
3. When discussing code structure, consider the relationships between components
4. Provide concrete examples from the code when relevant
5. Be precise and technical while remaining helpful and clear
"""
    
    async def create_session(self, 
                           repository_id: Optional[str] = None,
                           callgraph_data: Optional[Dict] = None) -> ChatSession:
        """
        Create a new chat session.
        
        Args:
            repository_id: ID of the repository being discussed
            callgraph_data: Optional callgraph data for contextual information
            
        Returns:
            New ChatSession object
        """
        session = ChatSession(
            repository_id=repository_id,
            callgraph_data=callgraph_data
        )
        
        self.sessions[session.session_id] = session
        
        # Add initial system message if we have callgraph data
        if callgraph_data and "metadata" in callgraph_data:
            framework = callgraph_data["metadata"].get(
                "framework_analyzed_as", 
                callgraph_data["metadata"].get("framework", "unknown")
            )
            
            system_message = (
                f"This is a {framework} codebase with {len(callgraph_data.get('nodes', []))} "
                f"functions and classes and {len(callgraph_data.get('links', []))} dependencies. "
                f"Ask me any questions about the code structure, functionality, or components."
            )
            
            session.add_message("system", system_message)
            
        return session
    
    def get_session(self, session_id: str) -> Optional[ChatSession]:
        """
        Get a chat session by ID.
        
        Args:
            session_id: ID of the session to retrieve
            
        Returns:
            ChatSession object or None if not found
        """
        return self.sessions.get(session_id)
    
    def list_sessions(self, repository_id: Optional[str] = None) -> List[Dict]:
        """
        List all chat sessions, optionally filtered by repository.
        
        Args:
            repository_id: Optional repository ID to filter by
            
        Returns:
            List of session dictionaries
        """
        if repository_id:
            return [
                session.to_dict()
                for session in self.sessions.values()
                if session.repository_id == repository_id
            ]
            
        return [session.to_dict() for session in self.sessions.values()]
    
    async def process_message(self,
                             session_id: str,
                             message: str,
                             code_elements: Optional[List[Dict]] = None,
                             highlighted_code: Optional[str] = None,
                             active_node_ids: Optional[List[str]] = None) -> Dict:
        """
        Process a user message and generate a response.
        
        Args:
            session_id: ID of the chat session
            message: User message content
            code_elements: Optional list of code elements currently in focus
            highlighted_code: Optional highlighted code snippet for context
            active_node_ids: Optional list of node IDs currently active in the visualization
            
        Returns:
            Dictionary with response, metadata, and nodes to highlight
        """
        session = self.get_session(session_id)
        
        if not session:
            logger.error(f"Chat session {session_id} not found")
            return {
                "error": "Chat session not found",
                "session_id": session_id
            }
            
        # Add user message to session
        session.add_message("user", message)
        
        # Build context for this query
        context = await self.context_builder.build_context_for_query(
            query=message,
            repository_id=session.repository_id,
            callgraph_data=session.callgraph_data,
            code_elements=code_elements
        )
        
        # Add any highlighted code if provided
        if highlighted_code:
            highlighted_context = f"# Highlighted Code\n```python\n{highlighted_code}\n```"
            context["context"] = highlighted_context + "\n\n" + context["context"]
            
        # If there are active nodes in the visualization, add their IDs as context
        if active_node_ids and len(active_node_ids) > 0:
            active_nodes_info = "\n\nCurrently focused on: " + ", ".join(active_node_ids)
            context["context"] += active_nodes_info
            
        # Save context to session
        session.add_context(context)
        
        # Prepare system prompt with context
        system_prompt = self.system_prompt_template.format(context=context["context"])
        
        # Prepare messages for LLM
        messages = [
            Message(role="system", content=system_prompt)
        ]
        
        # Add conversation history (limit to last 10 messages)
        user_assistant_messages = [
            msg for msg in session.get_messages() 
            if msg["role"] in ["user", "assistant"]
        ][-10:]
        
        for msg in user_assistant_messages:
            messages.append(Message(role=msg["role"], content=msg["content"]))
            
        # Generate response from LLM
        response = await self.llm_manager.chat_completion(
            messages=messages,
            temperature=0.3  # Lower temperature for more consistent, factual responses
        )
        
        # Add assistant response to session
        session.add_message("assistant", response.text)
        
        # Extract node IDs to highlight in the visualization
        highlight_node_ids = []
        relationship_node_ids = []
        
        # Extract node IDs from context_used data
        if "context_used" in context:
            for element in context["context_used"]:
                if "id" in element and element["id"]:
                    # Add to highlight list if it's a directly mentioned element
                    if element.get("context_source") == "mentioned_element":
                        highlight_node_ids.append(element["id"])
                    # Add to relationship list if it's a related element
                    elif element.get("context_source") in ["relationship_caller", "relationship_callee"]:
                        relationship_node_ids.append(element["id"])
        
        return {
            "response": response.text,
            "session_id": session_id,
            "context_used": context["components"],
            "model": response.model,
            "usage": response.usage,
            "highlight_nodes": {
                "primary": highlight_node_ids,   # Nodes directly mentioned/queried
                "related": relationship_node_ids # Nodes related to the primary nodes
            },
            "code_context": context.get("context_used", []) # Full code elements used in context
        }
    
    async def delete_session(self, session_id: str) -> bool:
        """
        Delete a chat session.
        
        Args:
            session_id: ID of the session to delete
            
        Returns:
            True if session was deleted, False otherwise
        """
        if session_id in self.sessions:
            del self.sessions[session_id]
            return True
        return False
\n\n# ==============================\n# Filename: services\llm\context_builder.py\n# ==============================\n\nimport os
import logging
import re
import json
from typing import Dict, List, Set, Optional, Any, Union, Tuple
import asyncio
from datetime import datetime

from .embedding_service import EmbeddingService
from ...models.embeddings import CodebaseChunkingConfig
from ...services.codebase_data_service import CodebaseDataService

logger = logging.getLogger(__name__)

class ContextBuilder:
    """
    Service for building rich context for LLM queries based on code analysis.
    
    This service integrates with the call graph and vector search to provide
    relevant context for LLM conversations about the codebase.
    """
    
    def __init__(self):
        """Initialize the context builder with required dependencies"""
        self.embedding_service = EmbeddingService()
        self.codebase_data_service = CodebaseDataService()
        
    async def build_context_for_query(self,
                                     query: str,
                                     repository_id: Optional[str] = None,
                                     callgraph_data: Optional[Dict] = None,
                                     code_elements: Optional[List[Dict]] = None,
                                     max_context_length: int = 4000) -> Dict:
        """
        Build context for an LLM query based on code analysis and vector search.
        
        Args:
            query: The user's query about the codebase
            repository_id: ID of the repository being discussed
            callgraph_data: Optional callgraph data for contextual information
            code_elements: Optional list of code elements for additional context
            max_context_length: Maximum length of context to return
            
        Returns:
            Dictionary with formatted context and metadata
        """
        # Initialize context components
        context_components = []
        used_code_context = []
        
        # If callgraph_data is not provided but repository_id is, try to get it from the data service
        if not callgraph_data and repository_id:
            try:
                callgraph = await self.codebase_data_service.get_callgraph(repository_id)
                if callgraph:
                    logger.info(f"Retrieved callgraph data for repository {repository_id} from data service")
                    callgraph_data = {
                        "nodes": [node.dict() for node in callgraph.nodes],
                        "links": [link.dict() for link in callgraph.links],
                        "metadata": callgraph.metadata.dict()
                    }
            except Exception as e:
                logger.error(f"Error retrieving callgraph data: {str(e)}")
        
        # 1. First add repository-level context if available
        if repository_id and callgraph_data and "metadata" in callgraph_data:
            metadata = callgraph_data["metadata"]
            repo_context = self._build_repository_context(metadata)
            context_components.append(("repository_overview", repo_context))
            
        # 2. Add semantic search results based on the query
        semantic_results = await self.embedding_service.search_similar_code(
            query=query,
            repository_id=repository_id,
            n_results=5
        )
        
        if semantic_results:
            semantic_context = self._format_semantic_search_results(semantic_results)
            context_components.append(("semantic_search", semantic_context))
            # Track the code elements we've used for context
            for result in semantic_results:
                if "content" in result and "id" in result:
                    used_code_context.append({
                        "id": result["id"],
                        "name": result.get("title", result.get("id")),
                        "type": result.get("type", "code_snippet"),
                        "file": result.get("file", ""),
                        "content": result.get("content", ""),
                        "context_source": "semantic_search"
                    })
            
        # 3. Add relationship context from callgraph if available
        relationship_elements = []
        if callgraph_data and "nodes" in callgraph_data and "links" in callgraph_data:
            # Try to identify code elements mentioned in the query
            mentioned_elements = self._identify_mentioned_elements(
                query, callgraph_data["nodes"]
            )
            
            if mentioned_elements:
                relationship_context, elements = await self._extract_relationship_context(
                    mentioned_elements, callgraph_data, repository_id
                )
                context_components.append(("relationships", relationship_context))
                relationship_elements = elements
                
        # 4. Add any explicit code elements provided
        if code_elements:
            elements_context = self._format_code_elements(code_elements)
            context_components.append(("code_elements", elements_context))
            
        # Combine context components with priorities and respect max length
        combined_context = self._combine_context_components(
            context_components, max_context_length
        )
        
        # Merge all the code elements we've used for context
        used_context = used_code_context + relationship_elements
        
        # Add explicit code elements provided to the used context
        if code_elements:
            for element in code_elements:
                element_with_source = element.copy()
                element_with_source["context_source"] = "explicit_element"
                used_context.append(element_with_source)
        
        # Return the final context
        return {
            "context": combined_context,
            "components": [c[0] for c in context_components],
            "query": query,
            "repository_id": repository_id,
            "has_callgraph_data": callgraph_data is not None,
            "has_semantic_results": len(semantic_results) > 0,
            "context_length": len(combined_context),
            "context_used": used_context  # Include the code elements used in the context
        }
    
    def _build_repository_context(self, metadata: Dict) -> str:
        """
        Build context about the repository from metadata.
        
        Args:
            metadata: Repository metadata from callgraph analysis
            
        Returns:
            Formatted repository context
        """
        framework = metadata.get("framework_analyzed_as", metadata.get("framework", "unknown"))
        total_files = metadata.get("files_analyzed", 0)
        total_nodes = metadata.get("total_nodes", 0)
        total_links = metadata.get("total_links", 0)
        most_complex = metadata.get("mostComplexFunction", {})
        
        context = [
            "# Repository Overview",
            f"Framework: {framework}",
            f"Files analyzed: {total_files}",
            f"Functions/Classes: {total_nodes}",
            f"Dependencies: {total_links}"
        ]
        
        if most_complex and "id" in most_complex:
            context.append(f"Most complex function: {most_complex['id']} (complexity: {most_complex.get('complexity', 'N/A')})")
            
        return "\n".join(context)
    
    def _format_semantic_search_results(self, results: List[Dict]) -> str:
        """
        Format semantic search results into context.
        
        Args:
            results: List of semantic search results
            
        Returns:
            Formatted context from semantic search results
        """
        if not results:
            return ""
            
        context = ["# Relevant Code Sections"]
        
        for i, result in enumerate(results):
            element_type = result["element_type"]
            element_name = result["element_name"]
            qualified_name = result["qualified_name"] or element_name
            content = result["content"]
            
            # Add a header for each result
            context.append(f"\n## {element_type.capitalize()}: {qualified_name}")
            
            # Add file path if available
            if "file_path" in result and result["file_path"]:
                context.append(f"File: {result['file_path']}")
                
            # Add the content with proper formatting
            context.append("```python")
            context.append(content)
            context.append("```")
            
        return "\n".join(context)
    
    def _identify_mentioned_elements(self, query: str, nodes: List[Dict]) -> List[str]:
        """
        Identify code elements mentioned in the query.
        
        Args:
            query: The user's query
            nodes: List of nodes from callgraph
            
        Returns:
            List of mentioned element IDs
        """
        mentioned_elements = []
        
        # Extract all words from the query
        words = re.findall(r'\b\w+(?:\.\w+)*\b', query.lower())
        
        # Look for node names in the query
        for node in nodes:
            node_id = node.get("id", "").lower()
            node_name = node.get("name", "").lower()
            
            # Check for exact matches of name or id
            if node_name in words or node_id in words:
                mentioned_elements.append(node["id"])
                continue
                
            # Check for partial matches in qualified names
            if "." in node_id:
                parts = node_id.split(".")
                for part in parts:
                    if part in words and len(part) > 3:  # Avoid short common words
                        mentioned_elements.append(node["id"])
                        break
                        
        return mentioned_elements
    
    async def _extract_relationship_context(self, element_ids: List[str], callgraph: Dict, repository_id: Optional[str] = None) -> Tuple[str, List[Dict]]:
        """
        Extract relationship context for mentioned elements from callgraph.
        
        Args:
            element_ids: List of element IDs to get relationships for
            callgraph: Complete callgraph data
            repository_id: Optional repository ID for retrieving detailed relationship data
            
        Returns:
            Tuple of (formatted relationship context, list of code elements used)
        """
        if not element_ids or not callgraph:
            return "", []
            
        # Extract nodes and links from callgraph
        nodes = callgraph.get("nodes", [])
        links = callgraph.get("links", [])
        
        if not nodes or not links:
            return "", []
            
        # Build a map of node IDs to node data for quick lookup
        node_map = {node.get("id"): node for node in nodes if "id" in node}
        
        # Initialize context
        context = ["# Code Relationships"]
        used_elements = []
        
        # For each mentioned element, extract its relationships
        for element_id in element_ids:
            # Skip if the element is not found in the node map
            if element_id not in node_map:
                continue
                
            # Get element details
            element = node_map[element_id]
            element_name = element.get("name", element_id.split(".")[-1])
            element_type = element.get("type", "function")
            
            # Track this element
            used_elements.append({
                "id": element_id,
                "name": element_name,
                "type": element_type,
                "file": element.get("file", ""),
                "docstring": element.get("docstring", ""),
                "context_source": "mentioned_element"
            })
            
            # Try to get more detailed relationships from CodebaseDataService if repository_id is provided
            detailed_relationships = None
            if repository_id:
                try:
                    detailed_relationships = await self.codebase_data_service.get_related_elements(repository_id, element_id)
                except Exception as e:
                    logger.warning(f"Error getting detailed relationships for {element_id}: {str(e)}")
            
            # Add element header
            context.append(f"\n## {element_type.capitalize()}: {element_name}")
            
            # Add basic info
            if "file" in element:
                context.append(f"File: {element['file']}")
            if "docstring" in element and element["docstring"]:
                context.append(f"\nDocumentation: {element['docstring']}")
            
            # Use detailed relationships if available, otherwise use the callgraph links
            if detailed_relationships:
                # Process callers (incoming)
                callers = detailed_relationships.get("callers", [])
                if callers:
                    context.append("\nCalled by:")
                    for caller in callers:
                        caller_name = caller.get("name", caller.get("id", "").split(".")[-1])
                        link_type = caller.get("relationship", {}).get("type", "call")
                        context.append(f"- {caller_name} ({link_type})")
                        
                        # Track this element
                        used_elements.append({
                            "id": caller.get("id", ""),
                            "name": caller_name,
                            "type": caller.get("type", "function"),
                            "file": caller.get("file", ""),
                            "docstring": caller.get("docstring", ""),
                            "context_source": "relationship_caller"
                        })
                
                # Process callees (outgoing)
                callees = detailed_relationships.get("callees", [])
                if callees:
                    context.append("\nCalls:")
                    for callee in callees:
                        callee_name = callee.get("name", callee.get("id", "").split(".")[-1])
                        link_type = callee.get("relationship", {}).get("type", "call")
                        context.append(f"- {callee_name} ({link_type})")
                        
                        # Track this element
                        used_elements.append({
                            "id": callee.get("id", ""),
                            "name": callee_name,
                            "type": callee.get("type", "function"),
                            "file": callee.get("file", ""),
                            "docstring": callee.get("docstring", ""),
                            "context_source": "relationship_callee"
                        })
            else:
                # Fallback to using the callgraph links directly
                # Find incoming calls (who calls this element)
                incoming = []
                for link in links:
                    if link.get("target") == element_id:
                        source_id = link.get("source")
                        link_type = link.get("type", "call")
                        
                        if source_id in node_map:
                            source_name = node_map[source_id].get("name", source_id.split(".")[-1])
                            incoming.append((source_id, source_name, link_type))
                            
                # Find outgoing calls (what this element calls)
                outgoing = []
                for link in links:
                    if link.get("source") == element_id:
                        target_id = link.get("target")
                        link_type = link.get("type", "call")
                        
                        if target_id in node_map:
                            target_name = node_map[target_id].get("name", target_id.split(".")[-1])
                            outgoing.append((target_id, target_name, link_type))
                            
                # Add relationship information
                if incoming:
                    context.append("\nCalled by:")
                    for caller_id, caller_name, link_type in incoming:
                        context.append(f"- {caller_name} ({link_type})")
                        
                        # Track this element
                        if caller_id in node_map:
                            caller = node_map[caller_id]
                            used_elements.append({
                                "id": caller_id,
                                "name": caller_name,
                                "type": caller.get("type", "function"),
                                "file": caller.get("file", ""),
                                "docstring": caller.get("docstring", ""),
                                "context_source": "relationship_caller"
                            })
                        
                if outgoing:
                    context.append("\nCalls:")
                    for callee_id, callee_name, link_type in outgoing:
                        context.append(f"- {callee_name} ({link_type})")
                        
                        # Track this element
                        if callee_id in node_map:
                            callee = node_map[callee_id]
                            used_elements.append({
                                "id": callee_id,
                                "name": callee_name,
                                "type": callee.get("type", "function"),
                                "file": callee.get("file", ""),
                                "docstring": callee.get("docstring", ""),
                                "context_source": "relationship_callee"
                            })
        
        return "\n".join(context), used_elements
    
    def _format_code_elements(self, elements: List[Dict]) -> str:
        """
        Format code elements into context.
        
        Args:
            elements: List of code elements
            
        Returns:
            Formatted context from code elements
        """
        if not elements:
            return ""
            
        context = ["# Code Elements"]
        
        for element in elements:
            element_type = element.get("type", "unknown")
            element_name = element.get("name", "")
            
            # Add a header for each element
            context.append(f"\n## {element_type.capitalize()}: {element_name}")
            
            # Add signature if available
            if "signature" in element:
                context.append("```python")
                context.append(element["signature"])
                context.append("```")
                
            # Add docstring if available
            if "docstring" in element and element["docstring"]:
                context.append("\nDocumentation:")
                context.append(element["docstring"])
                
            # Add dependencies if available
            if "dependencies" in element and element["dependencies"]:
                context.append("\nDependencies:")
                for dep in element["dependencies"]:
                    target = dep.get("target", "")
                    dep_type = dep.get("type", "call")
                    context.append(f"- {target} ({dep_type})")
                    
        return "\n".join(context)
    
    def _combine_context_components(self, 
                                   components: List[Tuple[str, str]], 
                                   max_length: int) -> str:
        """
        Combine context components respecting maximum length.
        
        Args:
            components: List of (component_name, content) tuples
            max_length: Maximum length of combined context
            
        Returns:
            Combined context string
        """
        # Priority order for components
        priority_order = {
            "code_elements": 1,      # Explicitly provided elements are highest priority
            "semantic_search": 2,    # Semantic search results are next
            "relationships": 3,      # Relationship context is next
            "repository_overview": 4 # Repository overview is lowest priority
        }
        
        # Sort components by priority
        sorted_components = sorted(
            components, 
            key=lambda x: priority_order.get(x[0], 999)
        )
        
        # Combine components respecting max length
        combined = []
        current_length = 0
        
        for _, content in sorted_components:
            if current_length + len(content) + 2 <= max_length:  # +2 for newlines
                if combined:  # Add separator if not first component
                    combined.append("\n\n")
                    current_length += 2
                    
                combined.append(content)
                current_length += len(content)
            else:
                # If we can't fit the whole component, try to fit a truncated version
                remaining_space = max_length - current_length - 2  # -2 for newline and "..."
                if remaining_space > 100:  # Only truncate if we can add something meaningful
                    if combined:
                        combined.append("\n\n")
                        current_length += 2
                        
                    truncated = content[:remaining_space - 3] + "..."
                    combined.append(truncated)
                    current_length += len(truncated)
                    
                # Stop once we've reached the limit
                break
                
        return "".join(combined)
\n\n# ==============================\n# Filename: services\llm\embedding_service.py\n# ==============================\n\nimport os
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
\n\n# ==============================\n# Filename: services\llm\llm_manager.py\n# ==============================\n\nimport os
import logging
import asyncio
from typing import Dict, List, Any, Optional, Union, Type
import importlib

from ..llm_providers.base_provider import BaseLLMProvider, Message, LLMResponse
from ...models.base import settings

logger = logging.getLogger(__name__)

class LLMManager:
    """
    Manager for LLM providers.
    
    This service orchestrates access to different LLM providers and handles
    fallbacks, caching, and provider selection based on the task requirements.
    """
    
    def __init__(self):
        """Initialize the LLM manager"""
        self.providers = {}
        self.default_provider = None
        self._load_providers()
    
    def _load_providers(self) -> None:
        """Load all available LLM providers based on configuration"""
        # Define provider configurations
        provider_configs = {
            "openai": {
                "module": "app.services.llm_providers.openai_provider",
                "class": "OpenAIProvider",
                "api_key": settings.OPENAI_API_KEY,
                "default_model": settings.OPENAI_MODEL or "gpt-3.5-turbo"
            },
            "anthropic": {
                "module": "app.services.llm_providers.anthropic_provider",
                "class": "AnthropicProvider",
                "api_key": settings.ANTHROPIC_API_KEY,
                "default_model": settings.ANTHROPIC_MODEL or "claude-3-sonnet-20240229"
            },
            "gemini": {
                "module": "app.services.llm_providers.gemini_provider",
                "class": "GeminiProvider",
                "api_key": settings.GEMINI_API_KEY,
                "default_model": "gemini-2.0-flash-lite"
            }
        }
        
        # Initialize each provider if API key is available
        for provider_name, config in provider_configs.items():
            try:
                if not config.get("api_key"):
                    logger.info(f"No API key found for {provider_name}, skipping")
                    continue
                    
                # Dynamically import the provider module and class
                module = importlib.import_module(config["module"])
                provider_class = getattr(module, config["class"])
                
                # Initialize the provider
                provider_instance = provider_class(
                    api_key=config["api_key"],
                    model=config["default_model"]
                )
                
                self.providers[provider_name] = provider_instance
                logger.info(f"Loaded {provider_name} provider with model {config['default_model']}")
                
                # Set as default provider if none is set
                if self.default_provider is None:
                    self.default_provider = provider_name
                    
            except Exception as e:
                logger.error(f"Error loading {provider_name} provider: {str(e)}")
        
        # Set default provider based on configuration if available
        if settings.DEFAULT_LLM_PROVIDER and settings.DEFAULT_LLM_PROVIDER in self.providers:
            self.default_provider = settings.DEFAULT_LLM_PROVIDER
            
        logger.info(f"Default LLM provider: {self.default_provider}")
    
    @property
    def available_providers(self) -> List[str]:
        """Get list of available provider names"""
        return list(self.providers.keys())
    
    def get_provider(self, provider_name: Optional[str] = None) -> Optional[BaseLLMProvider]:
        """
        Get a specific provider by name, or the default provider.
        
        Args:
            provider_name: Name of the provider to get
            
        Returns:
            Provider instance or None if not available
        """
        if provider_name is not None and provider_name in self.providers:
            return self.providers[provider_name]
            
        if self.default_provider is not None:
            return self.providers[self.default_provider]
            
        return None
    
    async def generate_text(self,
                           prompt: str,
                           provider_name: Optional[str] = None,
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text using the specified provider.
        
        Args:
            prompt: The prompt to generate text from
            provider_name: Name of the provider to use (uses default if None)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        provider = self.get_provider(provider_name)
        
        if provider is None:
            logger.error(f"No LLM provider available for text generation")
            return LLMResponse(
                text="Error: No LLM provider available",
                model="none",
                metadata={"error": "No provider available"}
            )
            
        return await provider.generate_text(
            prompt=prompt,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
    
    async def chat_completion(self,
                             messages: List[Message],
                             provider_name: Optional[str] = None,
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation.
        
        Args:
            messages: List of messages in the conversation
            provider_name: Name of the provider to use (uses default if None)
            max_tokens: Maximum tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        provider = self.get_provider(provider_name)
        
        if provider is None:
            logger.error(f"No LLM provider available for chat completion")
            return LLMResponse(
                text="Error: No LLM provider available",
                model="none",
                metadata={"error": "No provider available"}
            )
            
        return await provider.chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
    
    async def get_embeddings(self,
                            text: Union[str, List[str]],
                            provider_name: Optional[str] = None) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text.
        
        Args:
            text: Text or list of texts to generate embeddings for
            provider_name: Name of the provider to use (uses default if None)
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        provider = self.get_provider(provider_name)
        
        if provider is None:
            logger.error(f"No LLM provider available for embeddings")
            # Return empty embedding with a reasonable dimensionality
            empty_embedding = [0.0] * 1536
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(text)
                
        return await provider.get_embeddings(text)
    
    async def health_check(self) -> Dict[str, bool]:
        """
        Check health of all providers.
        
        Returns:
            Dictionary mapping provider names to health status
        """
        health_status = {}
        
        for name, provider in self.providers.items():
            try:
                is_healthy = await provider.health_check()
                health_status[name] = is_healthy
            except Exception as e:
                logger.error(f"Error checking health of {name}: {str(e)}")
                health_status[name] = False
                
        return health_status
\n\n# ==============================\n# Filename: services\llm_doc_generator_service.py\n# ==============================\n\nimport logging
import os
import re
import time
import random
import asyncio
import ast
import inspect
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, Tuple, Callable, Union, get_type_hints
from functools import lru_cache

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted, ServiceUnavailable
from app.models.base import settings
from app.services.database import get_database
from ..utils.ast_generator import ASTGenerator

logger = logging.getLogger(__name__)

# THIS PRINT STATEMENT WILL BE EXECUTED WHEN THE MODULE IS LOADED
print("\n\n*** MODULE LOAD: llm_doc_generator_service.py is being loaded ***\n\n")


class ResponseCache:
    """A simple cache for LLM responses to avoid redundant API calls."""
    
    def __init__(self, max_size: int = 100):
        """Initialize the cache with a maximum size."""
        self.cache = {}
        self.max_size = max_size
        self.access_times = {}
        
    def get(self, key: str) -> Optional[Dict[str, str]]:
        """Get a cached response if it exists."""
        if key in self.cache:
            self.access_times[key] = datetime.now()
            logger.debug(f"Cache hit for key: {key[:20]}...")
            return self.cache[key]
        logger.debug(f"Cache miss for key: {key[:20]}...")
        return None
    
    def set(self, key: str, value: Dict[str, str]) -> None:
        """Set a cached response."""
        # If cache is full, remove least recently used item
        if len(self.cache) >= self.max_size:
            oldest_key = min(self.access_times.items(), key=lambda x: x[1])[0]
            del self.cache[oldest_key]
            del self.access_times[oldest_key]
            
        self.cache[key] = value
        self.access_times[key] = datetime.now()
        logger.debug(f"Cached response for key: {key[:20]}...")
        
    def clear(self) -> None:
        """Clear the cache."""
        self.cache.clear()
        self.access_times.clear()
        logger.info("Response cache cleared")


class RateLimiter:
    """Handles rate limiting with exponential backoff for API calls."""
    
    def __init__(self, max_retries: int = 5, base_delay: float = 2.0, jitter: float = 0.5):
        """Initialize the rate limiter."""
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.jitter = jitter
        
    async def execute_with_backoff(self, func: Callable, *args, **kwargs) -> Any:
        """Execute a function with exponential backoff on rate limit errors."""
        retries = 0
        last_exception = None
        
        while retries <= self.max_retries:
            try:
                # Execute the function
                return await func(*args, **kwargs) if asyncio.iscoroutinefunction(func) else func(*args, **kwargs)
            except (ResourceExhausted, ServiceUnavailable) as e:
                last_exception = e
                retries += 1
                
                if retries > self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) exceeded for API call")
                    break
                    
                # Calculate backoff delay with jitter
                delay = self.base_delay * (2 ** (retries - 1))
                jitter_amount = random.uniform(-self.jitter, self.jitter) * delay
                delay = max(0.1, delay + jitter_amount)  # Ensure delay is at least 0.1s
                
                logger.warning(f"Rate limit exceeded. Retrying in {delay:.2f}s (retry {retries}/{self.max_retries})")
                await asyncio.sleep(delay)
        
        # If we've exhausted retries, raise the last exception
        if last_exception:
            raise last_exception
        
        return None


class BatchProcessor:
    """Processes documentation requests in batches to manage API rate limits."""
    
    def __init__(self, batch_size: int = 5, delay_between_batches: float = 1.0):
        """Initialize the batch processor."""
        self.batch_size = batch_size
        self.delay_between_batches = delay_between_batches
        
    async def process_batch(self, items: List[Any], process_func: Callable, *args, **kwargs) -> List[Tuple[Any, Any]]:
        """Process items in batches, with delay between batches to avoid rate limits."""
        results = []
        batches = [items[i:i + self.batch_size] for i in range(0, len(items), self.batch_size)]
        
        logger.info(f"Processing {len(items)} items in {len(batches)} batches of size {self.batch_size}")
        
        for batch_index, batch in enumerate(batches):
            batch_results = []
            logger.info(f"Processing batch {batch_index + 1}/{len(batches)} with {len(batch)} items")
            
            # Process all items in this batch concurrently
            tasks = []
            for item in batch:
                task = asyncio.create_task(process_func(item, *args, **kwargs))
                tasks.append((item, task))
            
            # Wait for all tasks in this batch to complete
            for item, task in tasks:
                try:
                    result = await task
                    batch_results.append((item, result))
                except Exception as e:
                    logger.error(f"Error processing item: {e}")
                    batch_results.append((item, None))
            
            results.extend(batch_results)
            
            # Delay before processing the next batch (unless it's the last batch)
            if batch_index < len(batches) - 1:
                logger.debug(f"Delaying {self.delay_between_batches}s before next batch")
                await asyncio.sleep(self.delay_between_batches)
        
        return results


class LLMDocGeneratorService:
    """
    Service to generate documentation for code elements using Google Gemini.
    This service takes information about a code node (e.g., function, class)
    and its context from the callgraph, then prompts Gemini to generate
    a docstring and/or signature.
    """

    def __init__(self, llm_provider_config: Optional[Dict] = None):
        """
        Initialize the LLMDocGeneratorService with Google Gemini.

        Args:
            llm_provider_config: Optional configuration. If provided and contains 'gemini_api_key',
                                it will be used. Otherwise, attempts to use GEMINI_API_KEY env var.
        """
        self.model = None
        gemini_api_key = None
        self.db = None  # MongoDB database connection, initialized when needed

        # Initialize helper components
        self.cache = ResponseCache(max_size=200)  # Cache up to 200 responses
        self.rate_limiter = RateLimiter(max_retries=3, base_delay=2.0, jitter=0.5)
        self.batch_processor = BatchProcessor(batch_size=5, delay_between_batches=2.0)
        self.ast_generator = ASTGenerator()
        
        # Load configuration options
        self.config = {
            'model_name': 'gemini-2.0-flash-lite',
            'temperature': 0.2,  # Lower temperature for more deterministic outputs
            'max_output_tokens': 1024,  # Reasonable limit for documentation
            'cache_enabled': True,  # Enable caching by default
            'use_ast_data': True,  # Use AST data when available
        }
        
        # Override config from provided configuration if any
        if llm_provider_config and isinstance(llm_provider_config, dict):
            self.config.update({k: v for k, v in llm_provider_config.items() 
                               if k in self.config})

        # Get API key from config or settings
        if llm_provider_config and llm_provider_config.get('gemini_api_key'):
            gemini_api_key = llm_provider_config['gemini_api_key']
            logger.info("Using Gemini API key from llm_provider_config.")
        else:
            gemini_api_key = settings.GEMINI_API_KEY
            logger.info("Using Gemini API key from Pydantic settings (loaded from .env).")
            
        if not gemini_api_key:
            logger.error("No Gemini API key found. Cannot initialize LLMDocGeneratorService.")
            return # Cannot proceed without API key

        try:
            # Initialize the Gemini model client
            genai.configure(api_key=gemini_api_key)
            self.model = genai.GenerativeModel(
                self.config['model_name'],
                generation_config={
                    'temperature': self.config['temperature'],
                    'max_output_tokens': self.config['max_output_tokens'],
                }
            )
            logger.info(f"LLMDocGeneratorService initialized successfully with Gemini model: {self.model.model_name}")
        except Exception as e:
            logger.error(f"Failed to initialize Gemini client: {e}")
            self.model = None # Ensure model is None if initialization fails


    async def generate_documentation_for_node(self, node_data: Dict[str, Any], context_elements: List[Dict[str, Any]]) -> Optional[Dict[str, str]]:
        # !!!!! THIS IS A CRITICAL DIAGNOSTIC PRINT STATEMENT !!!!!
        print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node ENTERED for node: {node_data.get('id')} ---")
        # !!!!! END OF CRITICAL DIAGNOSTIC PRINT STATEMENT !!!!!

        """
        Generates documentation (docstring and signature) for a given code node
        using the configured LLM. Implements caching, rate limiting, and error handling.

        First checks MongoDB for existing documentation, then falls back to in-memory cache,
        and finally generates new documentation using the LLM if needed.

        Args:
            node_data: Dictionary containing details of the node to document.
            context_elements: List of dictionaries representing related code elements for context.

        Returns:
            A dictionary with 'docstring' and 'signature' if successful, else None.
        """
        if not self.model:
            logger.warning("LLM model not initialized in LLMDocGeneratorService. Cannot generate documentation.")
            print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node EXITING because self.model is None ---") # DEBUG PRINT
            return None

        # Create a cache key based on node data and context elements
        node_id = node_data.get('id', '')
        repository_id = node_data.get('repository_id', '')
        cache_key = self._generate_cache_key(node_data, context_elements)
        
        # Initialize database connection if needed
        try:
            await self._initialize_db()
        except Exception as e:
            logger.error(f"LLMDocGeneratorService: Failed to initialize database: {e}")
            # Continue with in-memory cache only
        
        # Check MongoDB first if database is initialized and we have repository_id and node_id
        if self.db is not None and repository_id and node_id:
            try:
                doc = await self.db['node_documentation'].find_one({
                    'node_id': node_id,
                    'repository_id': repository_id
                })
                
                if doc and 'documentation' in doc:
                    logger.info(f"LLMDocGeneratorService: Using documentation from MongoDB for node: {node_id}")
                    print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node RETURNING MongoDB result ---") # DEBUG PRINT
                    return doc['documentation']
            except Exception as e:
                logger.error(f"LLMDocGeneratorService: Error retrieving documentation from MongoDB: {e}")
                # Continue with in-memory cache

        # Check in-memory cache if enabled
        if self.config.get('cache_enabled', True):
            cached_result = self.cache.get(cache_key)
            if cached_result:
                logger.info(f"LLMDocGeneratorService: Using cached documentation for node: {node_id}")
                print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node RETURNING cached result ---") # DEBUG PRINT
                return cached_result

        try:
            logger.info(f"LLMDocGeneratorService: Attempting to generate documentation for node: {node_id}")
            
            # Add AST data if available and enabled
            if self.config.get('use_ast_data', True):
                node_data = await self._enrich_with_ast_data(node_data)
            
            # Build the prompt with all available information
            prompt = self._build_prompt(node_data, context_elements)
            logger.info(f"LLMDocGeneratorService: Generated prompt for LLM (node: {node_id}, first 500 chars of prompt):\n{prompt[:500]}...")

            # Execute API call with rate limiting and backoff
            logger.info(f"LLMDocGeneratorService: Sending request to Gemini for node: {node_id}")
            
            async def _generate_content():
                return self.model.generate_content(prompt)
            
            llm_response = await self.rate_limiter.execute_with_backoff(_generate_content)
            
            # Extract and log the response text
            response_text_to_log = getattr(llm_response, 'text', str(llm_response)) 
            logger.info(f"LLMDocGeneratorService: Raw LLM response for node {node_id}:\n{response_text_to_log}")
            
            # Parse the response
            parsed_docs = self._parse_llm_response(response_text_to_log) 
            
            if not parsed_docs:
                logger.warning(f"LLMDocGeneratorService: Could not parse LLM response for node {node_id}. Raw response was logged above. Check parsing logic and LLM output format.")
            else:
                logger.info(f"LLMDocGeneratorService: Successfully parsed LLM response for node {node_id}")
                
                # Cache successful result if caching is enabled
                if self.config.get('cache_enabled', True):
                    self.cache.set(cache_key, parsed_docs)
                    logger.debug(f"LLMDocGeneratorService: Cached documentation for node: {node_id}")
                
                # Store in MongoDB if database is initialized and we have repository_id and node_id
                if self.db is not None and repository_id and node_id:
                    try:
                        # Check if the node_documentation collection exists
                        collections = await self.db.list_collection_names()
                        if 'node_documentation' not in collections:
                            logger.warning(f"LLMDocGeneratorService: node_documentation collection does not exist. Creating it now.")
                        
                        # Log the attempt to store documentation
                        logger.info(f"LLMDocGeneratorService: Attempting to store documentation in MongoDB for node: {node_id}, repository: {repository_id}")
                        
                        result = await self.db['node_documentation'].update_one(
                            {
                                'node_id': node_id,
                                'repository_id': repository_id
                            },
                            {
                                '$set': {
                                    'node_id': node_id,
                                    'repository_id': repository_id,
                                    'documentation': parsed_docs,
                                    'generated_at': datetime.now()
                                }
                            },
                            upsert=True
                        )
                        
                        # Log detailed information about the result
                        if result.matched_count > 0:
                            logger.info(f"LLMDocGeneratorService: Updated existing documentation in MongoDB for node: {node_id}")
                        elif result.upserted_id is not None:
                            logger.info(f"LLMDocGeneratorService: Inserted new documentation in MongoDB for node: {node_id}, upserted_id: {result.upserted_id}")
                        else:
                            logger.warning(f"LLMDocGeneratorService: MongoDB update_one operation did not match or insert any documents for node: {node_id}")
                    except Exception as e:
                        logger.error(f"LLMDocGeneratorService: Error storing documentation in MongoDB: {e}", exc_info=True)
                        # Continue without MongoDB storage
                else:
                    if self.db is None:
                        logger.warning(f"LLMDocGeneratorService: Cannot store documentation in MongoDB for node {node_id} - database connection not initialized")
                    elif not repository_id:
                        logger.warning(f"LLMDocGeneratorService: Cannot store documentation in MongoDB for node {node_id} - missing repository_id")
                    elif not node_id:
                        logger.warning("LLMDocGeneratorService: Cannot store documentation in MongoDB - missing node_id")

                # Also store to a local JSON file as requested
                try:
                    output_file = 'generated_docs.json'
                    # Read existing data if file exists, otherwise start with an empty list
                    existing_data = []
                    if os.path.exists(output_file):
                        with open(output_file, 'r') as f:
                            try:
                                existing_data = json.load(f)
                            except json.JSONDecodeError:
                                existing_data = [] # Handle empty or invalid JSON

                    # Append new data
                    existing_data.append({
                        'node_id': node_id,
                        'repository_id': repository_id,
                        'documentation': parsed_docs,
                        'generated_at': datetime.now().isoformat()
                    })

                    # Write back the entire list
                    with open(output_file, 'w') as f:
                        json.dump(existing_data, f, indent=4)
                    logger.info(f"LLMDocGeneratorService: Stored documentation for node {node_id} in {output_file}")
                except Exception as json_e:
                    logger.error(f"LLMDocGeneratorService: Error storing documentation to JSON file: {json_e}", exc_info=True)
            print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node RETURNING parsed_docs: {parsed_docs is not None} ---") # DEBUG PRINT
            return parsed_docs
                
        except ResourceExhausted as e:
            # Handle rate limit errors specifically
            logger.error(f"LLMDocGeneratorService: Rate limit exceeded for Gemini API call for node {node_id}: {e}")
            print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node ERRORED (rate limit): {e} ---") # DEBUG PRINT
            return None
            
        except Exception as e:
            logger.error(f"LLMDocGeneratorService: Error during Gemini API call or critical error in parsing for node {node_id}: {e}", exc_info=True)
            print(f"--- DEBUG: LLMDocGeneratorService.generate_documentation_for_node ERRORED: {e} ---") # DEBUG PRINT
            return None
            
    async def _initialize_db(self):
        """Initialize the MongoDB database connection if not already initialized."""
        if self.db is None:
            try:
                self.db = await get_database()
                logger.info("LLMDocGeneratorService: MongoDB database connection initialized")
                
                # Check if node_documentation collection exists
                collections = await self.db.list_collection_names()
                if 'node_documentation' not in collections:
                    logger.warning("LLMDocGeneratorService: node_documentation collection does not exist. It will be created automatically.")
                
                # Ensure the node_documentation collection exists with proper indexes
                try:
                    await self.db['node_documentation'].create_index(
                        [('node_id', 1), ('repository_id', 1)],
                        unique=True
                    )
                    logger.info("LLMDocGeneratorService: Created index on node_documentation collection")
                except Exception as e:
                    # This is expected if the index already exists
                    if "IndexKeySpecsConflict" in str(e):
                        logger.warning("LLMDocGeneratorService: IndexKeySpecsConflict detected. Attempting to drop and recreate index.")
                        try:
                            await self.db['node_documentation'].drop_index('node_id_1_repository_id_1') # Assuming this is the default name
                            logger.info("LLMDocGeneratorService: Successfully dropped conflicting index.")
                            await self.db['node_documentation'].create_index(
                                [('node_id', 1), ('repository_id', 1)],
                                unique=True
                            )
                            logger.info("LLMDocGeneratorService: Successfully recreated unique index on node_documentation collection.")
                        except Exception as drop_e:
                            logger.error(f"LLMDocGeneratorService: Failed to drop or recreate index: {drop_e}")
                    else:
                        logger.error(f"LLMDocGeneratorService: Failed to create index on node_documentation collection: {e}")
            except Exception as e:
                logger.error(f"LLMDocGeneratorService: Failed to initialize MongoDB connection: {e}", exc_info=True)
                self.db = None
    
    def _generate_cache_key(self, node_data: Dict[str, Any], context_elements: List[Dict[str, Any]]) -> str:
        """Generate a unique cache key for the documentation request."""
        node_id = node_data.get('id', '')
        node_type = node_data.get('type', '')
        
        # Include basic identifiers in the cache key
        key_parts = [f"node:{node_id}", f"type:{node_type}"]
        
        # Add context element IDs in a deterministic order
        if context_elements:
            context_ids = sorted([element.get('id', '') for element in context_elements])
            context_key = f"context:{','.join(context_ids)}"
            key_parts.append(context_key)
        
        return "|".join(key_parts)
        
    async def _enrich_with_ast_data(self, node_data: Dict[str, Any]) -> Dict[str, Any]:
        """Enrich node data with AST information if available.
        
        Parses the source file using the ast module and extracts detailed type hints,
        parameter information, docstrings, and other metadata to enhance the context
        available for LLM-based documentation generation.
        
        Args:
            node_data: Dictionary containing the node data to enrich
            
        Returns:
            Enriched data dictionary with additional AST-derived information
        """
        # Clone the node data to avoid modifying the original
        enriched_data = {**node_data}
        
        # Check if we have a file path and it's accessible
        file_path = node_data.get('file', '')
        if not file_path or not os.path.isfile(file_path):
            logger.debug(f"AST enrichment skipped: File not accessible for node {node_data.get('id')}")
            return enriched_data
        
        # Get node identifier and type
        node_id = node_data.get('id', '')
        node_type = node_data.get('type', '').lower()
        
        if not node_id or not node_type:
            logger.debug(f"AST enrichment skipped: Missing node ID or type for {file_path}")
            return enriched_data
        
        try:
            # Read the source file content
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()

            # Parse the file content using ASTGenerator
            # Determine language for ASTGenerator (assuming python for now based on context)
            # TODO: Enhance language detection if other file types are processed.
            language_for_ast = 'python' 
            source_code_bytes = source_code.encode('utf-8')
            tree_sitter_ast = self.ast_generator.parse_file_content(source_code_bytes, language=language_for_ast)

            if not tree_sitter_ast:
                logger.warning(f"AST enrichment skipped: Failed to parse file {file_path} with ASTGenerator for node {node_data.get('id')}")
                return enriched_data
            
            logger.info(f"Successfully parsed file {file_path} with ASTGenerator for node {node_data.get('id')}")

            # Use ASTGenerator to find the specific node and get its source code
            # The 'node_id' from callgraph might be like 'file.py.ClassName.method_name' or 'file.py.function_name'
            # We need to adapt this for find_node_and_get_source which expects 'ClassName.methodName' or 'function_name'
            
            # Determine the identifier and type for ASTGenerator based on callgraph node_id and node_type
            cg_node_id = node_data.get('id', '') # e.g., services.callgraph.CallgraphGenerator.analyze_repository
            cg_node_type = node_data.get('type', '').lower() # e.g., 'method', 'function', 'class'
            
            # Prepare identifier for find_node_and_get_source
            # It expects 'function_name', 'ClassName', or 'ClassName.method_name'
            # The callgraph 'id' is often fully qualified, e.g., module.submodule.Class.method
            # We need the simple name or Class.method part.
            id_parts = cg_node_id.split('.')
            ast_node_identifier = ''
            
            if cg_node_type == 'method' and len(id_parts) >= 2:
                # Assuming the last two parts are ClassName.methodName
                ast_node_identifier = f"{id_parts[-2]}.{id_parts[-1]}"
            elif (cg_node_type == 'function' or cg_node_type == 'class') and len(id_parts) >= 1:
                # Assuming the last part is the function/class name
                ast_node_identifier = id_parts[-1]
            else:
                logger.warning(f"Could not determine a simple AST node identifier from callgraph ID '{cg_node_id}' and type '{cg_node_type}'. Skipping Tree-sitter source extraction.")

            if ast_node_identifier and tree_sitter_ast:
                try:
                    # Read file content as bytes for Tree-sitter
                    with open(file_path, 'rb') as fb:
                        source_code_bytes = fb.read()

                    extracted_source = self.ast_generator.find_node_and_get_source(
                        ast_root_node=tree_sitter_ast, 
                        node_identifier=ast_node_identifier, 
                        target_node_type=cg_node_type, # Use callgraph's node type
                        source_code_bytes=source_code_bytes
                    )
                    if extracted_source:
                        enriched_data['ast_extracted_source'] = extracted_source
                        logger.info(f"Successfully extracted source for '{ast_node_identifier}' from {file_path} using Tree-sitter.")
                    else:
                        logger.warning(f"Could not extract source for '{ast_node_identifier}' from {file_path} using Tree-sitter. Method returned None.")
                except Exception as e_find_source:
                    logger.error(f"Error calling find_node_and_get_source for '{ast_node_identifier}' in {file_path}: {e_find_source}", exc_info=True)
            elif not tree_sitter_ast:
                logger.warning(f"Skipping Tree-sitter source extraction for {cg_node_id} as tree_sitter_ast is None.")
            elif not ast_node_identifier:
                 logger.warning(f"Skipping Tree-sitter source extraction for {cg_node_id} as ast_node_identifier could not be determined.")
            
            # For now, we are not modifying the existing AST extraction logic which uses Python's 'ast' module.
            # The plan is to eventually replace it or augment it with Tree-sitter.
            # The following lines preserve the original 'ast' module based enrichment for now.
            
            py_ast_tree = ast.parse(source_code, filename=file_path)
            target_py_ast_node = self._find_ast_node(py_ast_tree, node_id, node_type)

            if not target_py_ast_node:
                logger.debug(f"Python AST enrichment skipped: Could not find node {node_id} in {file_path} using 'ast' module")
                # We still return enriched_data because Tree-sitter parsing might have been successful
                # and we might add Tree-sitter specific data later.
            else:
                if node_type == 'function' or node_type == 'method':
                    func_details = self._extract_function_details(target_py_ast_node, source_code)
                    enriched_data.update(func_details)
                elif node_type == 'class':
                    class_details = self._extract_class_details(target_py_ast_node, source_code, py_ast_tree)
                    enriched_data.update(class_details)
                elif node_type == 'module':
                    module_details = self._extract_module_details(py_ast_tree, source_code)
                    enriched_data.update(module_details)
                logger.info(f"Successfully enriched node {node_id} with Python 'ast' module data")

            return enriched_data
            
        except Exception as e:
            logger.warning(f"Error enriching node data with AST for {node_data.get('id')} in file {file_path}: {e}", exc_info=True)
            return enriched_data
            
    def _find_ast_node(self, tree: ast.AST, node_id: str, node_type: str) -> Optional[ast.AST]:
        """Find the target AST node based on node ID and type.
        
        Args:
            tree: AST tree of the module
            node_id: ID of the node to find (e.g., 'module.Class.method')
            node_type: Type of the node ('function', 'method', 'class', 'module')
            
        Returns:
            The AST node if found, None otherwise
        """
        # For module nodes, return the tree itself
        if node_type == 'module':
            return tree
        
        # Extract the node name (last part of the ID)
        name_parts = node_id.split('.')
        target_name = name_parts[-1]
        
        # For functions, methods, and classes, search through the AST
        class NodeFinder(ast.NodeVisitor):
            def __init__(self, target_name: str, node_type: str):
                self.target_name = target_name
                self.node_type = node_type
                self.found_node = None
                self.current_class = None
            
            def visit_ClassDef(self, node):
                old_class = self.current_class
                self.current_class = node.name
                
                # Check if this is the target class
                if self.node_type == 'class' and node.name == self.target_name:
                    self.found_node = node
                    return
                
                # Visit children to find methods
                self.generic_visit(node)
                self.current_class = old_class
            
            def visit_FunctionDef(self, node):
                # Check if this is a method in the right class
                if self.node_type == 'method':
                    class_name = name_parts[-2] if len(name_parts) > 1 else None
                    if node.name == self.target_name and self.current_class == class_name:
                        self.found_node = node
                        return
                
                # Check if this is a function
                elif self.node_type == 'function' and node.name == self.target_name and not self.current_class:
                    self.found_node = node
                    return
                
                self.generic_visit(node)
        
        # Run the visitor on the AST
        finder = NodeFinder(target_name, node_type)
        finder.visit(tree)
        
        return finder.found_node
    
    def _extract_function_details(self, node: ast.FunctionDef, source_code: str) -> Dict[str, Any]:
        """Extract detailed information from a function or method AST node.
        
        Args:
            node: Function definition AST node
            source_code: Source code string for retrieving code snippets
            
        Returns:
            Dictionary with extracted function details
        """
        result = {}
        
        # Get function signature and return type annotation
        signature = {
            'name': node.name,
            'parameters': [],
            'return_type': None
        }
        
        # Extract return type annotation if present
        if node.returns:
            signature['return_type'] = self._format_annotation(node.returns)
        
        # Extract parameter information
        for arg in node.args.args:
            param = {
                'name': arg.arg,
                'type': self._format_annotation(arg.annotation) if hasattr(arg, 'annotation') and arg.annotation else None,
                'default': None
            }
            signature['parameters'].append(param)
        
        # Extract default values for parameters
        defaults = node.args.defaults
        if defaults:
            # Apply defaults to the appropriate parameters (from the end)
            offset = len(signature['parameters']) - len(defaults)
            for i, default in enumerate(defaults):
                if i + offset >= 0:
                    signature['parameters'][i + offset]['default'] = self._format_ast_value(default)
        
        # Handle *args and **kwargs
        if node.args.vararg:
            signature['parameters'].append({
                'name': f"*{node.args.vararg.arg}",
                'type': self._format_annotation(node.args.vararg.annotation) if hasattr(node.args.vararg, 'annotation') and node.args.vararg.annotation else None,
                'default': None
            })
        
        if node.args.kwarg:
            signature['parameters'].append({
                'name': f"**{node.args.kwarg.arg}",
                'type': self._format_annotation(node.args.kwarg.annotation) if hasattr(node.args.kwarg, 'annotation') and node.args.kwarg.annotation else None,
                'default': None
            })
        
        # Extract decorators
        decorators = []
        for decorator in node.decorator_list:
            decorators.append(self._format_decorator(decorator))
        
        # Extract function docstring
        docstring = ast.get_docstring(node) or ''
        
        # Get function source code
        try:
            func_source_lines = source_code.splitlines()[node.lineno-1:node.end_lineno]
            func_source = '\n'.join(func_source_lines)
        except (AttributeError, IndexError):
            func_source = ''
        
        # Compile the result
        result['ast_signature'] = signature
        result['ast_decorators'] = decorators
        result['ast_docstring'] = docstring
        result['ast_source_snippet'] = func_source[:1000] if func_source else ''  # Limit to 1000 chars
        result['ast_is_async'] = isinstance(node, ast.AsyncFunctionDef)
        
        return result
    
    def _extract_class_details(self, node: ast.ClassDef, source_code: str, tree: ast.AST) -> Dict[str, Any]:
        """Extract detailed information from a class AST node.
        
        Args:
            node: Class definition AST node
            source_code: Source code string for retrieving code snippets
            tree: Full AST tree for analyzing class hierarchy
            
        Returns:
            Dictionary with extracted class details
        """
        result = {}
        
        # Extract base classes
        bases = []
        for base in node.bases:
            base_name = self._format_annotation(base)
            if base_name:
                bases.append(base_name)
        
        # Extract docstring
        docstring = ast.get_docstring(node) or ''
        
        # Extract class source code
        try:
            class_source_lines = source_code.splitlines()[node.lineno-1:node.end_lineno]
            class_source = '\n'.join(class_source_lines)
        except (AttributeError, IndexError):
            class_source = ''
        
        # Extract class methods and attributes
        methods = []
        class_vars = []
        
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods.append(item.name)
            elif isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                # Class variable with type annotation
                var_name = item.target.id
                var_type = self._format_annotation(item.annotation) if item.annotation else None
                class_vars.append({'name': var_name, 'type': var_type})
            elif isinstance(item, ast.Assign):
                # Class variable without type annotation
                for target in item.targets:
                    if isinstance(target, ast.Name):
                        class_vars.append({'name': target.id, 'type': None})
        
        # Compile the result
        result['ast_bases'] = bases
        result['ast_docstring'] = docstring
        result['ast_source_snippet'] = class_source[:1000] if class_source else ''  # Limit to 1000 chars
        result['ast_methods'] = methods
        result['ast_class_vars'] = class_vars
        
        return result
    
    def _extract_module_details(self, tree: ast.AST, source_code: str) -> Dict[str, Any]:
        """Extract detailed information from a module AST.
        
        Args:
            tree: Module AST
            source_code: Source code string
            
        Returns:
            Dictionary with extracted module details
        """
        result = {}
        
        # Extract module docstring
        docstring = ast.get_docstring(tree) or ''
        
        # Extract imports
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for name in node.names:
                    imports.append({'module': name.name, 'alias': name.asname})
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ''
                for name in node.names:
                    imports.append({'module': f"{module}.{name.name}", 'alias': name.asname})
        
        # Extract top-level definitions
        top_level_classes = []
        top_level_functions = []
        top_level_vars = []
        
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                top_level_classes.append(node.name)
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                top_level_functions.append(node.name)
            elif isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        top_level_vars.append(target.id)
        
        # Compile the result
        result['ast_docstring'] = docstring
        result['ast_imports'] = imports
        result['ast_top_level_classes'] = top_level_classes
        result['ast_top_level_functions'] = top_level_functions
        result['ast_top_level_vars'] = top_level_vars
        
        return result
    
    def _format_annotation(self, annotation) -> Optional[str]:
        """Format a type annotation AST node into a string representation.
        
        Args:
            annotation: AST node representing a type annotation
            
        Returns:
            String representation of the type annotation, or None if not available
        """
        if annotation is None:
            return None
        
        try:
            if isinstance(annotation, ast.Name):
                return annotation.id
            elif isinstance(annotation, ast.Attribute):
                return self._format_attribute(annotation)
            elif isinstance(annotation, ast.Subscript):
                # Handle subscripted types (e.g., List[str])
                value = self._format_annotation(annotation.value)
                if not value:
                    return None
                
                if isinstance(annotation.slice, ast.Index):
                    # Python 3.8 and earlier
                    slice_value = self._format_annotation(annotation.slice.value)
                elif isinstance(annotation.slice, ast.Slice):
                    slice_value = "slice"
                else:
                    # Python 3.9+
                    slice_value = self._format_annotation(annotation.slice)
                
                return f"{value}[{slice_value}]"
            elif isinstance(annotation, ast.Tuple):
                # Handle tuple types (e.g., Tuple[int, str])
                elements = []
                for elt in annotation.elts:
                    elt_str = self._format_annotation(elt)
                    if elt_str:
                        elements.append(elt_str)
                return f"Tuple[{', '.join(elements)}]"
            elif isinstance(annotation, ast.Constant):
                # Handle literal values
                return repr(annotation.value)
            elif isinstance(annotation, ast.BinOp):
                # Handle binary operations (e.g., Union types with |)
                left = self._format_annotation(annotation.left)
                right = self._format_annotation(annotation.right)
                if isinstance(annotation.op, ast.BitOr):
                    return f"{left} | {right}"
                return f"Union[{left}, {right}]"
            elif isinstance(annotation, ast.Constant):
                return str(annotation.value)
            elif hasattr(ast, 'Constant') and isinstance(annotation, ast.Constant):
                # Python 3.8+
                return str(annotation.value)
            elif hasattr(ast, 'NameConstant') and isinstance(annotation, ast.NameConstant):
                # Python 3.7 and earlier
                return str(annotation.value)
            else:
                # Try using ast.unparse for Python 3.9+
                if hasattr(ast, 'unparse'):
                    return ast.unparse(annotation)
                return "Any"  # Fallback for complex/unknown annotations
        except Exception as e:
            logger.debug(f"Error formatting annotation: {e}")
            return "Any"  # Fallback for any errors
    
    def _format_attribute(self, node: ast.Attribute) -> str:
        """Format an attribute node (e.g., typing.List).
        
        Args:
            node: Attribute AST node
            
        Returns:
            String representation of the attribute
        """
        if isinstance(node.value, ast.Attribute):
            parent = self._format_attribute(node.value)
            return f"{parent}.{node.attr}"
        elif isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        else:
            return node.attr
    
    def _format_decorator(self, node: ast.AST) -> str:
        """Format a decorator AST node into a string representation.
        
        Args:
            node: Decorator AST node
            
        Returns:
            String representation of the decorator
        """
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return self._format_attribute(node)
        elif isinstance(node, ast.Call):
            func_name = self._format_annotation(node.func)
            args = []
            for arg in node.args:
                arg_str = self._format_ast_value(arg)
                if arg_str:
                    args.append(arg_str)
            
            kwargs = []
            for keyword in node.keywords:
                value_str = self._format_ast_value(keyword.value)
                if value_str:
                    kwargs.append(f"{keyword.arg}={value_str}")
            
            all_args = args + kwargs
            return f"{func_name}({', '.join(all_args)})"
        else:
            # Try using ast.unparse for Python 3.9+
            if hasattr(ast, 'unparse'):
                return ast.unparse(node)
            return "unknown_decorator"  # Fallback
    
    def _format_ast_value(self, node: ast.AST) -> str:
        """Format an AST value node into a string representation.
        
        Args:
            node: AST node representing a value
            
        Returns:
            String representation of the value
        """
        if node is None:
            return "None"
        
        if isinstance(node, ast.Constant):
            return repr(node.value)
        elif hasattr(ast, 'Constant') and isinstance(node, ast.Constant):
            # Python 3.8+
            return repr(node.value)
        elif hasattr(ast, 'Num') and isinstance(node, ast.Num):
            # Python 3.7 and earlier
            return str(node.n)
        elif hasattr(ast, 'Str') and isinstance(node, ast.Str):
            # Python 3.7 and earlier
            return repr(node.s)
        elif hasattr(ast, 'NameConstant') and isinstance(node, ast.NameConstant):
            # Python 3.7 and earlier
            return str(node.value)
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.List):
            elements = [self._format_ast_value(elt) for elt in node.elts]
            return f"[{', '.join(elements)}]"
        elif isinstance(node, ast.Tuple):
            elements = [self._format_ast_value(elt) for elt in node.elts]
            return f"({', '.join(elements)})"
        elif isinstance(node, ast.Dict):
            pairs = []
            for k, v in zip(node.keys, node.values):
                key = self._format_ast_value(k) if k is not None else "None"
                value = self._format_ast_value(v)
                pairs.append(f"{key}: {value}")
            return f"{{{', '.join(pairs)}}}"
        elif isinstance(node, ast.Call):
            func_name = self._format_annotation(node.func)
            return f"{func_name}(...)"
        else:
            # Try using ast.unparse for Python 3.9+
            if hasattr(ast, 'unparse'):
                return ast.unparse(node)
            return "..."  # Fallback for complex expressions

    def _parse_llm_response(self, response_text: str) -> Optional[Dict[str, str]]:
        # !!!!! THIS IS A CRITICAL DIAGNOSTIC PRINT STATEMENT !!!!!
        print(f"--- DEBUG: LLMDocGeneratorService._parse_llm_response ENTERED with text length: {len(response_text)} ---")
        # !!!!! END OF CRITICAL DIAGNOSTIC PRINT STATEMENT !!!!!

        """
        Parse LLM response to extract docstring and signature.
        Handles multiple response formats including structured JSON, markdown blocks, and plain text.

        Args:
            response_text: Raw text response from the LLM.

        Returns:
            Dict with 'docstring' and 'signature' keys, or None if parsing failed.
        """
        if not response_text:
            logger.warning("LLMDocGeneratorService._parse_llm_response: Received empty response")
            return None
            
        try:
            # Log the raw response for debugging
            logger.debug(f"LLMDocGeneratorService._parse_llm_response: Attempting to parse: {response_text[:200]}...")

            # Strategy 1: Try to parse as JSON
            json_result = self._try_parse_json(response_text)
            if json_result:
                logger.info("LLMDocGeneratorService: Successfully parsed response as JSON")
                return json_result

            # Strategy 2: Try to extract using regex patterns for code blocks
            code_block_result = self._try_parse_code_blocks(response_text)
            if code_block_result:
                logger.info("LLMDocGeneratorService: Successfully parsed response using code block extraction")
                return code_block_result

            # Strategy 3: Look for explicitly section markers
            section_result = self._try_parse_sections(response_text)
            if section_result:
                logger.info("LLMDocGeneratorService: Successfully parsed response using section markers")
                return section_result

            # Strategy 4: Fallback to basic regex patterns
            fallback_result = self._try_fallback_parsing(response_text)
            if fallback_result:
                logger.info("LLMDocGeneratorService: Successfully parsed response using fallback method")
                return fallback_result

            # If all strategies failed, log and return None
            logger.warning("LLMDocGeneratorService: All parsing strategies failed")
            return None
                
        except Exception as e:
            logger.error(f"LLMDocGeneratorService._parse_llm_response: Error parsing LLM response: {e}", exc_info=True)
            return None
    
    def _try_parse_json(self, text: str) -> Optional[Dict[str, str]]:
        """Attempt to parse the response as JSON."""
        # Look for JSON blocks in the response
        json_matches = re.findall(r'```(?:json)?\s*({.+?})\s*```', text, re.DOTALL)
        if not json_matches:
            # Try without code blocks
            json_matches = re.findall(r'({\s*"docstring":.+?"signature":.+?})', text, re.DOTALL)
            if not json_matches:
                return None
        
        for json_str in json_matches:
            try:
                # Use the json module imported at the top level
                data = json.loads(json_str)
                # Check if the JSON has the expected fields
                if 'docstring' in data or 'signature' in data:
                    return {
                        'docstring': data.get('docstring', ''),
                        'signature': data.get('signature', '')
                    }
            except json.JSONDecodeError:
                continue
        
        return None
    
    def _try_parse_code_blocks(self, text: str) -> Optional[Dict[str, str]]:
        """Extract docstring and signature from code blocks."""
        # Look for Python code blocks
        code_block_matches = re.findall(r'```(?:python)?\s*(.+?)\s*```', text, re.DOTALL)
        
        if not code_block_matches:
            return None
            
        for code_block in code_block_matches:
            docstring_match = re.search(r'"""(.+?)"""', code_block, re.DOTALL)
            signature_match = re.search(r'def\s+([^\n]+):', code_block)
            
            docstring = docstring_match.group(1).strip() if docstring_match else ""
            signature = signature_match.group(1).strip() if signature_match else ""
            
            if docstring or signature:
                return {
                    'docstring': docstring,
                    'signature': signature
                }
        
        return None
    
    def _try_parse_sections(self, text: str) -> Optional[Dict[str, str]]:
        """Extract content from explicitly marked sections."""
        # Look for sections like 'Docstring:' and 'Signature:'
        docstring_section = re.search(r'(?:Docstring|Documentation|Doc):\s*(.+?)(?=(?:Signature|Function signature|Method signature|Parameters|Return|$))', text, re.DOTALL)
        signature_section = re.search(r'(?:Signature|Function signature|Method signature):\s*(.+?)(?=(?:Docstring|Documentation|Doc|Parameters|Return|$))', text, re.DOTALL)
        
        docstring = docstring_section.group(1).strip() if docstring_section else ""
        signature = signature_section.group(1).strip() if signature_section else ""
        
        # Clean up markdown formatting
        docstring = re.sub(r'```.*?```', '', docstring, flags=re.DOTALL).strip()
        signature = re.sub(r'```.*?```', '', signature, flags=re.DOTALL).strip()
        
        if docstring or signature:
            return {
                'docstring': docstring,
                'signature': signature
            }
        
        return None
    
    def _try_fallback_parsing(self, text: str) -> Optional[Dict[str, str]]:
        """Last resort parsing using basic patterns."""
        # Try to extract the docstring and signature using regex
        docstring_match = re.search(r'"""(.+?)"""', text, re.DOTALL)
        docstring = docstring_match.group(1).strip() if docstring_match else ""

        signature_match = re.search(r'def\s+([^\n]+):', text)
        signature = signature_match.group(1).strip() if signature_match else ""
        
        # If we still don't have a signature, try to find anything that looks like a function/method signature
        if not signature:
            alt_sig_match = re.search(r'([a-zA-Z_][a-zA-Z0-9_]*\s*\(.*?\)(?:\s*->\s*[^:\n]+)?)', text)
            signature = alt_sig_match.group(1).strip() if alt_sig_match else ""
        
        # If we still don't have a docstring, look for anything that might be a description
        if not docstring:
            desc_match = re.search(r'(?:Description|Summary|Overview|Purpose):\s*(.+?)(?=\n\n|$)', text, re.DOTALL)
            docstring = desc_match.group(1).strip() if desc_match else ""
        
        if docstring or signature:
            return {
                'docstring': docstring,
                'signature': signature
            }
        
        print(f"--- DEBUG: LLMDocGeneratorService._parse_llm_response RETURNING None ---") # DEBUG PRINT
        return None

    def _build_prompt(self, node_data: Dict[str, Any], context_elements: List[Dict[str, Any]]) -> str:
        """
        Builds a prompt for LLM to generate documentation for a code element.
        Incorporates AST-extracted type information and code structure to enhance context.

        Args:
            node_data: Dictionary containing details of the node to document
            context_elements: List of dictionaries representing related code elements for context

        Returns:
            A formatted prompt string to send to the LLM
        """
        node_id = node_data.get('id', 'Unknown')
        node_type = node_data.get('type', 'Unknown').lower()
        
        # Start with a clear system prompt
        prompt = [
            "You are an expert software documentation writer specializing in Python.",
            "Generate concise, accurate documentation for the following code element.",
            "Focus on providing a clear description of its purpose, parameters, return values, and any exceptions raised.",
            "Use the surrounding context, relationships, and extracted type information to create precise documentation.",
            "\n"
        ]
        
        # Add information about the specific code element
        prompt.append(f"## CODE ELEMENT INFORMATION\n")
        prompt.append(f"Identifier: {node_id}")
        prompt.append(f"Type: {node_type}")
        
        if 'file' in node_data:
            prompt.append(f"File: {node_data.get('file')}")
            
        if 'current_signature' in node_data and node_data['current_signature']:
            prompt.append(f"Current signature: {node_data['current_signature']}")
            
        if 'current_docstring' in node_data and node_data['current_docstring']:
            prompt.append(f"Current docstring: \n```\n{node_data['current_docstring']}\n```")
            
        if 'complexity' in node_data:
            prompt.append(f"Complexity: {node_data.get('complexity')}")
        
        # Add AST-derived information if available
        ast_data_added = False
        
        # Include detailed function/method signature information
        if 'ast_signature' in node_data:
            ast_data_added = True
            signature_info = node_data['ast_signature']
            prompt.append(f"\n## AST-DERIVED TYPE INFORMATION\n")
            
            # Function/method name and return type
            return_type = signature_info.get('return_type', 'Unknown')
            prompt.append(f"Function name: {signature_info.get('name', 'Unknown')}")
            prompt.append(f"Return type: {return_type}")
            
            # Parameters with types and default values
            if 'parameters' in signature_info and signature_info['parameters']:
                prompt.append(f"\nParameters:")
                for param in signature_info['parameters']:
                    param_str = f"- {param.get('name', 'Unknown')}"
                    if param.get('type'):
                        param_str += f" (type: {param.get('type')})"
                    if param.get('default'):
                        param_str += f" = {param.get('default')}"
                    prompt.append(param_str)
            
            # Decorators
            if 'ast_decorators' in node_data and node_data['ast_decorators']:
                prompt.append(f"\nDecorators:")
                for decorator in node_data['ast_decorators']:
                    prompt.append(f"- @{decorator}")
            
            # Is async function
            if 'ast_is_async' in node_data:
                prompt.append(f"\nAsync function: {'Yes' if node_data['ast_is_async'] else 'No'}")
        
        # Include class information
        elif 'ast_bases' in node_data:
            ast_data_added = True
            prompt.append(f"\n## AST-DERIVED CLASS INFORMATION\n")
            
            # Base classes
            if node_data['ast_bases']:
                prompt.append(f"Base classes: {', '.join(node_data['ast_bases'])}")
            else:
                prompt.append("No base classes (inherits directly from object)")
            
            # Methods
            if 'ast_methods' in node_data and node_data['ast_methods']:
                prompt.append(f"\nClass methods:")
                for method in node_data['ast_methods']:
                    prompt.append(f"- {method}()")
            
            # Class variables
            if 'ast_class_vars' in node_data and node_data['ast_class_vars']:
                prompt.append(f"\nClass variables:")
                for var in node_data['ast_class_vars']:
                    var_str = f"- {var.get('name', 'Unknown')}"
                    if var.get('type'):
                        var_str += f" (type: {var.get('type')})"
                    prompt.append(var_str)
        
        # Include module information
        elif 'ast_imports' in node_data:
            ast_data_added = True
            prompt.append(f"\n## AST-DERIVED MODULE INFORMATION\n")
            
            # Top-level classes
            if 'ast_top_level_classes' in node_data and node_data['ast_top_level_classes']:
                prompt.append(f"Classes defined in this module:")
                for cls in node_data['ast_top_level_classes']:
                    prompt.append(f"- {cls}")
            
            # Top-level functions
            if 'ast_top_level_functions' in node_data and node_data['ast_top_level_functions']:
                prompt.append(f"\nFunctions defined in this module:")
                for func in node_data['ast_top_level_functions']:
                    prompt.append(f"- {func}()")
            
            # Imports
            if node_data['ast_imports']:
                prompt.append(f"\nImports:")
                imports_sample = node_data['ast_imports'][:10]  # Limit to first 10 imports
                for imp in imports_sample:
                    import_str = f"- {imp.get('module', 'Unknown')}"
                    if imp.get('alias'):
                        import_str += f" as {imp.get('alias')}"
                    prompt.append(import_str)
                if len(node_data['ast_imports']) > 10:
                    prompt.append(f"  ... and {len(node_data['ast_imports']) - 10} more imports")
        
        # Source code snippet if available
        if 'ast_source_snippet' in node_data and node_data['ast_source_snippet']:
            prompt.append(f"\n## SOURCE CODE SNIPPET\n```python\n{node_data['ast_source_snippet']}\n```")
            ast_data_added = True
        
        # Original AST-derived docstring if available
        if 'ast_docstring' in node_data and node_data['ast_docstring'] and node_data['ast_docstring'] != node_data.get('current_docstring', ''):
            prompt.append(f"\n## EXISTING AST-DERIVED DOCSTRING\n```\n{node_data['ast_docstring']}\n```")
            ast_data_added = True
        
        # Add relationship context if available
        if context_elements:
            prompt.append(f"\n## RELATIONSHIP CONTEXT\n")
            for i, element in enumerate(context_elements, 1):
                element_id = element.get('id', 'Unknown')
                element_type = element.get('type', 'Unknown').lower()
                relation = element.get('relation', 'related to')  # How is it related
                
                prompt.append(f"Related element {i}: {element_id} ({element_type}) - {relation}")
                if 'docstring' in element and element['docstring']:
                    shortened_docstring = element['docstring'].split('\n')[0] if '\n' in element['docstring'] else element['docstring']
                    prompt.append(f"  Description: {shortened_docstring[:100]}")
        
        # Output formatting instructions
        prompt.append(f"\n## OUTPUT FORMAT\n")
        prompt.append("Please generate a concise one-line summary, a detailed docstring, a corrected or inferred signature, and a refactoring suggestion. Provide the output in the following JSON format:")
        prompt.append("""```json
{
  "summary": "A concise one-line summary of the code element's purpose.",
  "docstring": "A detailed, well-formatted docstring for the code element. Include sections for Args, Returns, and Raises where appropriate.",
  "signature": "The corrected or inferred signature of the code element (e.g., function_name(param1: type1, param2: type2) -> return_type).",
  "suggestion": "One key suggestion for refactoring or improving the code element."
}
```""")
        
        # Different instructions based on node type
        if node_type == 'function' or node_type == 'method':
            prompt.append("Focus on accurately describing parameters, return values, and potential exceptions.")
            prompt.append("Ensure parameter types in the signature match the AST-derived type information.")
        elif node_type == 'class':
            prompt.append("Focus on the class's purpose, important attributes, and usage examples.")
            prompt.append("Mention inheritance and key methods that users should be aware of.")
        elif node_type == 'module':
            prompt.append("Focus on the module's overall purpose and the key components it contains.")
            prompt.append("Highlight the most important classes and functions for a new user of this module.")
        
    
        # Different instructions based on node type
        if node_type == 'function' or node_type == 'method':
            prompt.append("Focus on accurately describing parameters, return values, and potential exceptions.")
            prompt.append("Ensure parameter types in the signature match the AST-derived type information.")
        elif node_type == 'class':
            prompt.append("Focus on the class's purpose, important attributes, and usage examples.")
            prompt.append("Mention inheritance and key methods that users should be aware of.")
        elif node_type == 'module':
            prompt.append("Focus on the module's overall purpose and the key components it contains.")
            prompt.append("Highlight the most important classes and functions for a new user of this module.")
        
        # If no AST data was found, mention it
        if not ast_data_added and node_type != 'module':
            prompt.append("\nNote: No detailed type information could be extracted from the AST. Please generate documentation based on the available context.")
            
        return "\n".join(prompt)

# Example usage (for testing purposes, if run directly)
if __name__ == '__main__':
    import asyncio
    # This is a dummy setup for testing the service structure.
    # You'd need a proper LLM client and configuration for real use.
    
    # Configure logging for standalone testing
    # logging.basicConfig(level=logging.DEBUG,
    #                     format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

    test_node = {
        'id': 'module_a.ClassB.method_c',
        'type': 'method',
        'file': 'module_a/file_b.py',
        'current_docstring': '',
        'current_signature': 'method_c(self, param1: int) -> str',
        'name_parts': ['module_a', 'ClassB', 'method_c']
    }
    test_context = [
        {
            'id': 'module_a.another_func',
            'type': 'function',
            'file': 'module_a/file_a.py',
            'signature': 'another_func(arg: str)',
            'docstring_preview': 'This function does something else...'
        }
    ]

    async def main():
        # Initialize service (without real LLM config for this test)
        llm_service = LLMDocGeneratorService(llm_provider_config=None)
        
        # Test prompt building
        prompt = llm_service._build_prompt(test_node, test_context)
        logger.info(f"--- Generated Prompt ---\n{prompt}\n------------------------")

        # Test LLM generation (will be simulated)
        generated_docs = await llm_service.generate_documentation_for_node(test_node, test_context)
        if generated_docs:
            logger.info(f"--- Generated Documentation (Simulated) ---")
            logger.info(f"Docstring: {generated_docs.get('docstring')}")
            logger.info(f"Signature: {generated_docs.get('signature')}")
            logger.info(f"-----------------------------------------")
        else:
            logger.error("Documentation generation failed.")

    asyncio.run(main())
\n\n# ==============================\n# Filename: services\llm_providers\__init__.py\n# ==============================\n\n"""
LLM Provider services for GraphiX.
Provides abstracted access to various LLM providers for code understanding and chat capabilities.
"""
\n\n# ==============================\n# Filename: services\llm_providers\anthropic_provider.py\n# ==============================\n\nimport os
import logging
import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Union

import httpx

from .base_provider import BaseLLMProvider, Message, LLMResponse

logger = logging.getLogger(__name__)

class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic LLM provider implementation.
    
    Supports text generation and chat completion using Anthropic's Claude models.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "claude-3-sonnet-20240229"):
        """
        Initialize the Anthropic provider.
        
        Args:
            api_key: Anthropic API key
            model: Default model to use
        """
        super().__init__(api_key=api_key, model=model)
        self.api_base = "https://api.anthropic.com/v1"
        self.min_call_interval = 1.0  # seconds between API calls
        
        # Use environment variable if no API key provided
        if not self.api_key:
            self.api_key = os.environ.get("ANTHROPIC_API_KEY")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return [
            "claude-3-opus-20240229",
            "claude-3-sonnet-20240229",
            "claude-3-haiku-20240307"
        ]
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        model_limits = {
            "claude-3-opus-20240229": 200000,
            "claude-3-sonnet-20240229": 200000,
            "claude-3-haiku-20240307": 200000
        }
        return model_limits.get(self.model, 100000)
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.api_key is not None
    
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt using Anthropic's API.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Anthropic API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format as a chat message for Anthropic API
        messages = [{"role": "user", "content": prompt}]
        
        # Call chat completion for consistency
        return await self.chat_completion(
            messages=[Message(role="user", content=prompt)],
            max_tokens=max_tokens,
            temperature=temperature,
            **kwargs
        )
    
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation using Anthropic's API.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Anthropic API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format messages for Anthropic API
        formatted_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        # Prepare API request
        url = f"{self.api_base}/messages"
        headers = {
            "Content-Type": "application/json",
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01"
        }
        
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or min(4000, self.max_tokens // 4),
            "system": kwargs.get("system", "You are a helpful assistant for coding tasks.")
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ["model", "system"]:  # Skip ones we've already processed
                payload[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                text = result["content"][0]["text"]
                
                # Anthropic doesn't provide finish_reason and usage in the same format as OpenAI
                # Extract what we can
                usage = {}
                if "usage" in result:
                    usage = result["usage"]
                
                return LLMResponse(
                    text=text,
                    model=payload["model"],
                    usage=usage,
                    finish_reason=result.get("stop_reason", None),
                    metadata={"response": result}
                )
                
        except Exception as e:
            logger.error(f"Error with Anthropic chat completion: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=payload["model"],
                metadata={"error": str(e)}
            )
    
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text.
        
        Note: Anthropic doesn't provide a public embeddings API.
        This is a placeholder that returns empty embeddings.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Empty embeddings as list of floats or list of list of floats
        """
        logger.warning("Anthropic does not provide a public embeddings API. Returning empty embeddings.")
        
        # Return empty embedding with a reasonable dimensionality
        empty_embedding = [0.0] * 1024
        
        if isinstance(text, str):
            return empty_embedding
        else:
            return [empty_embedding] * len(text)
\n\n# ==============================\n# Filename: services\llm_providers\base_provider.py\n# ==============================\n\nimport abc
import logging
import time
import asyncio
from typing import Dict, List, Any, Optional, Union
from pydantic import BaseModel

logger = logging.getLogger(__name__)

class Message(BaseModel):
    """Message model for LLM conversation"""
    role: str  # 'system', 'user', 'assistant'
    content: str
    
class LLMResponse(BaseModel):
    """Response model for LLM providers"""
    text: str
    model: str
    usage: Dict[str, int] = {}
    finish_reason: Optional[str] = None
    metadata: Dict[str, Any] = {}

class BaseLLMProvider(abc.ABC):
    """
    Abstract base class for LLM providers.
    
    All LLM providers must implement this interface to ensure
    consistent access across different backend implementations.
    """
    
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        """
        Initialize the LLM provider.
        
        Args:
            api_key: API key for the provider
            model: Default model to use for generation
        """
        self.api_key = api_key
        self.model = model
        self.last_call_time = 0
        self.min_call_interval = 1.0  # seconds between API calls
    
    @property
    def provider_name(self) -> str:
        """Get the name of the provider"""
        return self.__class__.__name__.replace("Provider", "")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return []
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        return 4096
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.api_key is not None
    
    async def _rate_limit(self) -> None:
        """Apply rate limiting to avoid hitting API limits"""
        current_time = time.time()
        elapsed = current_time - self.last_call_time
        
        if elapsed < self.min_call_interval:
            wait_time = self.min_call_interval - elapsed
            logger.debug(f"Rate limiting: waiting {wait_time:.2f} seconds")
            await asyncio.sleep(wait_time)
            
        self.last_call_time = time.time()
    
    @abc.abstractmethod
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        pass
    
    @abc.abstractmethod
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional provider-specific parameters
            
        Returns:
            LLMResponse object with generated text
        """
        pass
    
    @abc.abstractmethod
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        pass
    
    async def health_check(self) -> bool:
        """
        Check if the provider is healthy and responding.
        
        Returns:
            True if healthy, False otherwise
        """
        try:
            # Try a simple completion with minimal tokens
            response = await self.generate_text(
                prompt="Hello",
                max_tokens=5,
                temperature=0.0
            )
            return response is not None and hasattr(response, 'text')
        except Exception as e:
            logger.error(f"Health check failed for {self.provider_name}: {str(e)}")
            return False
\n\n# ==============================\n# Filename: services\llm_providers\gemini_provider.py\n# ==============================\n\nimport os
import logging
import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Union

try:
    import google.generativeai as genai
    GENAI_AVAILABLE = True
except ImportError:
    GENAI_AVAILABLE = False

from .base_provider import BaseLLMProvider, Message, LLMResponse

logger = logging.getLogger(__name__)

class GeminiProvider(BaseLLMProvider):
    """
    Gemini LLM provider implementation.
    
    Supports text generation, chat completion, and basic embeddings using Google's Gemini models.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "gemini-2.0-flash-lite"):
        """
        Initialize the Gemini provider.
        
        Args:
            api_key: Gemini API key
            model: Default model to use
        """
        super().__init__(api_key=api_key, model=model)
        self.available = GENAI_AVAILABLE
        self.min_call_interval = 1.0  # seconds between API calls
        
        # Use environment variable if no API key provided
        if not self.api_key:
            self.api_key = os.environ.get("GEMINI_API_KEY")
            
        # Initialize the Gemini client
        if self.available and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.client = genai.GenerativeModel(self.model)
                logger.info(f"Initialized Gemini provider with model {self.model}")
            except Exception as e:
                logger.error(f"Error initializing Gemini provider: {str(e)}")
                self.available = False
        else:
            if not self.available:
                logger.warning("Gemini SDK not available. Install it with 'pip install google-generativeai'")
            elif not self.api_key:
                logger.warning("No Gemini API key provided")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return [
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.0-pro",
            "gemini-1.0-pro-vision"
        ]
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        model_limits = {
            "gemini-1.5-pro": 1000000,  # 1M tokens
            "gemini-1.5-flash": 1000000,
            "gemini-1.0-pro": 32000,
            "gemini-1.0-pro-vision": 32000
        }
        return model_limits.get(self.model, 32000)
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.available and self.api_key is not None
    
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt using Gemini's API.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Gemini API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        if not self.is_available:
            logger.error("Gemini provider is not available")
            return LLMResponse(
                text="Error: Gemini provider is not available",
                model=self.model,
                metadata={"error": "Provider not available"}
            )
            
        try:
            # Configure generation parameters
            generation_config = {
                "temperature": temperature,
                "top_p": kwargs.get("top_p", 0.95),
                "top_k": kwargs.get("top_k", 40),
            }
            
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens
                
            # Generate text
            response = await asyncio.to_thread(
                self.client.generate_content,
                prompt,
                generation_config=generation_config
            )
            
            # Extract text from response
            if hasattr(response, 'text'):
                text = response.text
            else:
                # Try to get text from parts if available
                text = ""
                for part in getattr(response, 'parts', []):
                    if hasattr(part, 'text'):
                        text += part.text
                        
            # Get usage information if available
            usage = {}
            if hasattr(response, 'usage'):
                usage = response.usage
                
            return LLMResponse(
                text=text,
                model=self.model,
                usage=usage,
                metadata={"response": str(response)}
            )
                
        except Exception as e:
            logger.error(f"Error generating text with Gemini: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=self.model,
                metadata={"error": str(e)}
            )
    
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation using Gemini's API.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the Gemini API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        if not self.is_available:
            logger.error("Gemini provider is not available")
            return LLMResponse(
                text="Error: Gemini provider is not available",
                model=self.model,
                metadata={"error": "Provider not available"}
            )
        
        logger.info(f"Processing chat completion with Gemini model: {self.model}")
        logger.info(f"Received {len(messages)} messages")
            
        try:
            # For simplicity and reliability, convert the conversation to a single prompt
            prompt = ""
            for msg in messages:
                role_prefix = ""
                if msg.role == "system":
                    role_prefix = "SYSTEM: "
                elif msg.role == "user":
                    role_prefix = "USER: "
                elif msg.role == "assistant":
                    role_prefix = "ASSISTANT: "
                    
                prompt += f"{role_prefix}{msg.content}\n\n"
                
            # Add a final assistant prefix to prompt the model to respond
            prompt += "ASSISTANT: "
            
            logger.info(f"Simplified prompt approach for Gemini: {prompt[:100]}...")
            
            # Generate content with the simplified approach
            generation_config = {
                "temperature": temperature,
                "top_p": kwargs.get("top_p", 0.95),
                "top_k": kwargs.get("top_k", 40),
            }
            
            if max_tokens:
                generation_config["max_output_tokens"] = max_tokens
            
            # Use the simpler generate_content approach instead of chat
            response = await asyncio.to_thread(
                self.client.generate_content,
                prompt,
                generation_config=generation_config
            )
            
            # Debug response
            logger.info(f"Gemini response type: {type(response)}")
            
            # Extract text from response
            if hasattr(response, 'text'):
                text = response.text
                logger.info(f"Found response.text: {text[:100]}...")
            else:
                # Try to get text from parts if available
                text = ""
                logger.info(f"No direct text attribute, checking parts")
                for part in getattr(response, 'parts', []):
                    if hasattr(part, 'text'):
                        text += part.text
                        
                # If still empty, try candidates
                if not text and hasattr(response, 'candidates'):
                    logger.info("Checking candidates")
                    for candidate in response.candidates:
                        if hasattr(candidate, 'content') and hasattr(candidate.content, 'parts'):
                            for part in candidate.content.parts:
                                if hasattr(part, 'text'):
                                    text += part.text
                
            # Debug the extracted text
            if text:
                logger.info(f"Successfully extracted text: {text[:100]}...")
            else:
                logger.error("Failed to extract any text from the Gemini response")
                logger.error(f"Raw response: {str(response)}")
            
            # Get usage information if available
            usage = {}
            if hasattr(response, 'usage'):
                usage = response.usage
                
            return LLMResponse(
                text=text or "I apologize, but I couldn't generate a response. Please try again.",
                model=self.model,
                usage=usage,
                metadata={"response": str(response)}
            )
                
        except Exception as e:
            logger.error(f"Error with Gemini chat completion: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=self.model,
                metadata={"error": str(e)}
            )
    
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text using Gemini's embedding model.
        Note: This is a basic implementation as Gemini's embedding capabilities are evolving.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        # Apply rate limiting
        await self._rate_limit()
        
        if not self.is_available:
            logger.error("Gemini provider is not available for embeddings")
            # Return empty embedding with a reasonable dimensionality
            empty_embedding = [0.0] * 768
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(text)
                
        try:
            # Format input
            if isinstance(text, str):
                input_texts = [text]
            else:
                input_texts = text
                
            # Get embeddings
            embeddings = []
            for input_text in input_texts:
                # Use embedding model if available, otherwise use a workaround
                try:
                    embedding_model = genai.get_model("embedding-001")
                    embedding = await asyncio.to_thread(
                        embedding_model.embed_content,
                        input_text
                    )
                    
                    # Extract the values
                    if hasattr(embedding, 'embedding'):
                        embeddings.append(embedding.embedding)
                    else:
                        # Fallback to a reasonable dimensionality
                        logger.warning("Could not extract embedding values from Gemini response")
                        embeddings.append([0.0] * 768)
                except Exception as e:
                    logger.error(f"Error getting embedding from Gemini: {str(e)}")
                    embeddings.append([0.0] * 768)
                    
            # Return single embedding or list based on input
            if isinstance(text, str):
                return embeddings[0]
            else:
                return embeddings
                
        except Exception as e:
            logger.error(f"Error generating embeddings with Gemini: {str(e)}")
            # Return empty embedding with a reasonable dimensionality
            empty_embedding = [0.0] * 768
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(input_texts)
\n\n# ==============================\n# Filename: services\llm_providers\openai_provider.py\n# ==============================\n\nimport os
import logging
import json
import time
import asyncio
from typing import Dict, List, Any, Optional, Union, Tuple
import httpx

from .base_provider import BaseLLMProvider, Message, LLMResponse

logger = logging.getLogger(__name__)

class OpenAIProvider(BaseLLMProvider):
    """
    OpenAI LLM provider implementation.
    
    Supports text generation, chat completion, and embeddings using OpenAI's API.
    """
    
    def __init__(self, 
                 api_key: Optional[str] = None, 
                 model: str = "gpt-3.5-turbo",
                 embedding_model: str = "text-embedding-3-small"):
        """
        Initialize the OpenAI provider.
        
        Args:
            api_key: OpenAI API key
            model: Default model to use for text generation and chat
            embedding_model: Model to use for embeddings
        """
        super().__init__(api_key=api_key, model=model)
        self.embedding_model = embedding_model
        self.api_base = "https://api.openai.com/v1"
        self.min_call_interval = 1.0  # seconds between API calls
        
        # Use environment variable if no API key provided
        if not self.api_key:
            self.api_key = os.environ.get("OPENAI_API_KEY")
    
    @property
    def available_models(self) -> List[str]:
        """Get the list of available models for this provider"""
        return [
            "gpt-4-turbo",
            "gpt-4",
            "gpt-3.5-turbo",
            "gpt-3.5-turbo-16k"
        ]
    
    @property
    def max_tokens(self) -> int:
        """Get the maximum number of tokens supported by the default model"""
        model_limits = {
            "gpt-4-turbo": 128000,
            "gpt-4": 8192,
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-16k": 16384
        }
        return model_limits.get(self.model, 4096)
    
    @property
    def is_available(self) -> bool:
        """Check if the provider is available and properly configured"""
        return self.api_key is not None
    
    async def generate_text(self, 
                           prompt: str, 
                           max_tokens: Optional[int] = None,
                           temperature: float = 0.7,
                           **kwargs) -> LLMResponse:
        """
        Generate text based on a prompt using OpenAI's API.
        
        Args:
            prompt: The prompt to generate text from
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the OpenAI API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format as a chat message for consistency
        messages = [{"role": "user", "content": prompt}]
        
        # Prepare API request
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens or min(1024, self.max_tokens // 2)
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ["model"]:  # Skip ones we've already processed
                payload[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                text = result["choices"][0]["message"]["content"]
                finish_reason = result["choices"][0]["finish_reason"]
                usage = result.get("usage", {})
                
                return LLMResponse(
                    text=text,
                    model=payload["model"],
                    usage=usage,
                    finish_reason=finish_reason,
                    metadata={"response": result}
                )
                
        except Exception as e:
            logger.error(f"Error generating text with OpenAI: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=payload["model"],
                metadata={"error": str(e)}
            )
    
    async def chat_completion(self,
                             messages: List[Message],
                             max_tokens: Optional[int] = None,
                             temperature: float = 0.7,
                             **kwargs) -> LLMResponse:
        """
        Generate a response based on a conversation using OpenAI's API.
        
        Args:
            messages: List of messages in the conversation
            max_tokens: Maximum number of tokens to generate
            temperature: Sampling temperature
            **kwargs: Additional parameters to pass to the OpenAI API
            
        Returns:
            LLMResponse object with generated text
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Format messages for OpenAI API
        formatted_messages = [{"role": msg.role, "content": msg.content} for msg in messages]
        
        # Prepare API request
        url = f"{self.api_base}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        payload = {
            "model": kwargs.get("model", self.model),
            "messages": formatted_messages,
            "temperature": temperature,
            "max_tokens": max_tokens or min(1024, self.max_tokens // 2)
        }
        
        # Add any additional parameters
        for key, value in kwargs.items():
            if key not in ["model"]:  # Skip ones we've already processed
                payload[key] = value
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                text = result["choices"][0]["message"]["content"]
                finish_reason = result["choices"][0]["finish_reason"]
                usage = result.get("usage", {})
                
                return LLMResponse(
                    text=text,
                    model=payload["model"],
                    usage=usage,
                    finish_reason=finish_reason,
                    metadata={"response": result}
                )
                
        except Exception as e:
            logger.error(f"Error with OpenAI chat completion: {str(e)}")
            # Return empty response with error info
            return LLMResponse(
                text="",
                model=payload["model"],
                metadata={"error": str(e)}
            )
    
    async def get_embeddings(self, text: Union[str, List[str]]) -> Union[List[float], List[List[float]]]:
        """
        Generate embeddings for the given text using OpenAI's embeddings API.
        
        Args:
            text: Text or list of texts to generate embeddings for
            
        Returns:
            Embeddings as list of floats or list of list of floats
        """
        # Apply rate limiting
        await self._rate_limit()
        
        # Prepare API request
        url = f"{self.api_base}/embeddings"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        # Format input
        if isinstance(text, str):
            input_texts = [text]
        else:
            input_texts = text
        
        payload = {
            "model": self.embedding_model,
            "input": input_texts
        }
        
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                result = response.json()
                
                embeddings = [item["embedding"] for item in result["data"]]
                
                # Return single embedding or list based on input
                if isinstance(text, str):
                    return embeddings[0]
                else:
                    return embeddings
                
        except Exception as e:
            logger.error(f"Error generating embeddings with OpenAI: {str(e)}")
            # Return empty embedding with appropriate dimensionality
            # OpenAI's text-embedding-3-small has 1536 dimensions
            empty_embedding = [0.0] * 1536
            
            if isinstance(text, str):
                return empty_embedding
            else:
                return [empty_embedding] * len(input_texts)
\n\n# ==============================\n# Filename: services\relationship_analysis\__init__.py\n# ==============================\n\nfrom enum import Enum, auto
from dataclasses import dataclass
from typing import Dict, List, Set, Optional, Type, Any


class RelationshipType(Enum):
    FUNCTION_CALL = auto()
    TEMPLATE_RENDER = auto()
    MODEL_ACCESS = auto()
    URL_ROUTE = auto()
    INHERITANCE = auto()
    IMPLEMENTS = auto()
    DEPENDENCY_INJECTION = auto()
    EVENT_HANDLER = auto()
    ASYNC_AWAIT = auto()
    GENERIC = auto()


@dataclass
class Relationship:
    source: str
    target: str
    type: RelationshipType
    metadata: Dict = None
    confidence: float = 1.0
    context: List[str] = None
\n\n# ==============================\n# Filename: services\relationship_analysis\dynamic_analyzer.py\n# ==============================\n\nimport ast
from typing import Dict, List, Optional
from . import Relationship, RelationshipType


class DynamicRelationshipAnalyzer:
    def __init__(self):
        self.relationship_handlers = {
            "django": self._analyze_django_relationships,
            "flask": self._analyze_flask_relationships,
            "fastapi": self._analyze_fastapi_relationships,
        }

    def analyze(
        self, framework: str, ast_node: ast.AST, context: Dict
    ) -> List[Relationship]:
        handler = self.relationship_handlers.get(framework)
        if handler:
            return handler(ast_node, context)
        return self._analyze_generic_relationships(ast_node, context)

    def _analyze_django_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and hasattr(node.func.value, "id")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "models"
                and node.func.attr in ["ForeignKey", "OneToOneField", "ManyToManyField"]
            ):
                target_model = (
                    node.args[0].id
                    if node.args and isinstance(node.args[0], ast.Name)
                    else "unknown"
                )
                relationships.append(
                    Relationship(
                        source=context.get("current_class", ""),
                        target=target_model,
                        type=RelationshipType.MODEL_ACCESS,
                        metadata={"relationship_type": node.func.attr},
                    )
                )
        return relationships

    def _analyze_flask_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Attribute
                ):
                    if decorator.func.attr == "route":
                        route_path = (
                            decorator.args[0].s
                            if decorator.args
                            and isinstance(decorator.args[0], ast.Constant)
                            else "unknown_route"
                        )
                        relationships.append(
                            Relationship(
                                source=context.get("module_name", "flask_app"),
                                target=node.name,
                                type=RelationshipType.URL_ROUTE,
                                metadata={"path": route_path, "framework": "flask"},
                            )
                        )
        return relationships

    def _analyze_fastapi_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Attribute
                ):
                    if decorator.func.attr in [
                        "get",
                        "post",
                        "put",
                        "delete",
                        "patch",
                        "head",
                        "options",
                        "trace",
                    ]:
                        route_path = (
                            decorator.args[0].s
                            if decorator.args
                            and isinstance(decorator.args[0], ast.Constant)
                            else "unknown_route"
                        )
                        relationships.append(
                            Relationship(
                                source=context.get("module_name", "fastapi_app"),
                                target=node.name,
                                type=RelationshipType.URL_ROUTE,
                                metadata={
                                    "path": route_path,
                                    "method": decorator.func.attr.upper(),
                                    "framework": "fastapi",
                                },
                            )
                        )
        return relationships

    def _analyze_generic_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                path_parts = []
                curr_attr = node.func
                while isinstance(curr_attr, ast.Attribute):
                    path_parts.append(curr_attr.attr)
                    curr_attr = curr_attr.value
                if isinstance(curr_attr, ast.Name):
                    path_parts.append(curr_attr.id)
                    func_name = ".".join(reversed(path_parts))
                else:
                    func_name = path_parts[0] if path_parts else "complex_call_target"
            if func_name:
                source_name = context.get(
                    "current_function",
                    context.get(
                        "current_class", context.get("module_name", "unknown_source")
                    ),
                )
                relationships.append(
                    Relationship(
                        source=source_name,
                        target=func_name,
                        type=RelationshipType.FUNCTION_CALL,
                    )
                )
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    parts = []
                    curr = base
                    while isinstance(curr, ast.Attribute):
                        parts.append(curr.attr)
                        curr = curr.value
                    if isinstance(curr, ast.Name):
                        parts.append(curr.id)
                    base_name = ".".join(reversed(parts))
                if base_name:
                    relationships.append(
                        Relationship(
                            source=class_name,
                            target=base_name,
                            type=RelationshipType.INHERITANCE,
                        )
                    )
        return relationships
\n\n# ==============================\n# Filename: services\research_callgraph.py\n# ==============================\n\nimport os
import ast
import logging
from typing import Dict, List, Set, Optional, Tuple, Any
import time
import shutil
from .enhanced_callgraph import EnhancedCallgraphGenerator
from .dynamic_callgraph_builder import DynamicCallGraphBuilder
import tempfile
from .callgraph import rate_limited # Added import

logger = logging.getLogger(__name__)


class ResearchCallgraphGenerator(EnhancedCallgraphGenerator):
    def __init__(self, framework: str = "generic", max_depth: int = 8):
        super().__init__()
        self.max_depth = max_depth
        self.dynamic_builder: Optional[DynamicCallGraphBuilder] = None
        self.initial_framework_hint = framework

    @rate_limited(max_per_minute=20)
    async def _generate_llm_content_with_rate_limit(self, func_name: str, func_info: dict) -> str:
        # code_snippet = func_info.get("code_snippet", "No code snippet available.")
        # # file_path = func_info.get("file", "N/A") # Already in func_name usually
        
        # prompt_parts = [
        #     f"Analyze the Python function `{func_name}`.",
        #     f"Code snippet:\n```python\n{code_snippet}\n```",
        #     "Provide a concise summary of its purpose and one key suggestion for improvement or refactoring if applicable. If no specific suggestion, state 'No specific refactoring suggestion.'.",
        #     "Format the response as: Purpose: [Your summary]. Suggestion: [Your suggestion]."
        # ]

        # if not self.model:
        #     logger.warning(f"LLM model not available for {func_name}. Skipping LLM content generation.")
        #     return "LLM model not available. Purpose: Unknown. Suggestion: None."
        
        # try:
        #     logger.debug(f"Generating LLM content for {func_name} with prompt parts: {prompt_parts}")
        #     response = await self.model.generate_content_async(prompt_parts)
            
        #     generated_text = ""
        #     if response and hasattr(response, 'text') and response.text:
        #         generated_text = response.text
        #     elif response and hasattr(response, 'parts') and response.parts:
        #         generated_text = "".join(part.text for part in response.parts if hasattr(part, 'text'))

        #     if not generated_text:
        #         logger.warning(f"LLM generated empty content for {func_name}")
        #         generated_text = "LLM generated empty content. Purpose: Unknown. Suggestion: None."
        #     else:
        #         logger.debug(f"LLM response for {func_name}: {generated_text}")
        #     return generated_text
        # except Exception as e:
        #     logger.error(f"Error during LLM content generation for {func_name}: {e}")
        #     logger.error(traceback.format_exc())
        #     return f"Error generating LLM content. Purpose: Error. Suggestion: Error ({str(e)})."
        return "Purpose: Not generated. Suggestion: Not generated."

    async def analyze_repository(
        self,
        repo_path: str,
        timeout: int = 600,
        clone: bool = False,
        perform_cleanup: bool = True,
    ) -> Dict:
        start_time = time.time()
        try:
            # Determine if cloning is needed based on whether repo_path is a URL
            should_clone = clone or self.is_valid_url(repo_path)
            await super().analyze_repository(
                repo_path, timeout, should_clone, perform_cleanup=False
            )
            local_repo_path = self.repo_path
            if not local_repo_path or not os.path.isdir(local_repo_path):
                logging.error(
                    f"Repository path '{local_repo_path}' is not a valid directory after attempting to prepare it. Original path: {repo_path}"
                )
                return {
                    "nodes": [],
                    "links": [],
                    "metadata": {
                        "error": "Invalid repository path after setup",
                        "status": "error",
                    },
                }
            logging.info(
                f"ResearchCallgraphGenerator proceeding with analysis on local path: {local_repo_path}"
            )

            # Populate base_functions and other attributes from superclass analysis
            # This is crucial for framework-specific handlers that rely on these attributes
            self.base_functions = self.functions.copy()
            self.base_classes = self.classes.copy()
            self.base_imports = self.imports.copy()

            self.dynamic_builder = DynamicCallGraphBuilder(
                framework_hint=self.initial_framework_hint,
                project_root_path=local_repo_path,
            )
            python_files = []
            for root, _, files_in_dir in os.walk(local_repo_path):
                for file_item in files_in_dir:
                    if file_item.endswith(".py"):
                        path_parts = os.path.normpath(root).split(os.sep)
                        if any(
                            part
                            in [
                                ".git",
                                ".hg",
                                ".svn",
                                "node_modules",
                                "__pycache__",
                                "migrations",
                            ]
                            or part.endswith((".egg-info", ".dist-info", ".cache"))
                            or (
                                "site-packages" in path_parts
                                or "dist-packages" in path_parts
                            )
                            or (
                                part in ["venv", "env"]
                                and local_repo_path
                                == os.path.dirname(os.path.join(root, part))
                            )
                            for part in path_parts
                        ):
                            continue
                        python_files.append(os.path.join(root, file_item))
            if not python_files:
                logging.warning(
                    f"No Python files found for analysis in {local_repo_path}. Check repository structure and filters."
                )
                return {
                    "nodes": [],
                    "links": [],
                    "metadata": {
                        "status": "completed_no_files",
                        "files_analyzed": 0,
                        "total_files_found": 0,
                    },
                }
            aggregated_graph: Dict[str, Any] = {
                "nodes": [],
                "links": [],
                "metadata": {},
            }
            added_node_ids: Set[str] = set()
            added_link_keys: Set[Tuple[str, str, str]] = set()
            idx = 0
            elapsed_time = 0.0
            for idx, file_path_item in enumerate(python_files):
                elapsed_time = time.time() - start_time
                if elapsed_time > timeout:
                    logging.warning(
                        f"Timeout reached processing files. Processed {idx}/{len(python_files)}."
                    )
                    break
                content = self._safe_read_file(file_path_item)
                if not content:
                    logging.warning(f"Could not read or empty file: {file_path_item}")
                    continue
                try:
                    ast_tree = ast.parse(content, filename=file_path_item)
                    file_specific_graph = self.dynamic_builder.build_callgraph_for_file(
                        ast_tree, file_path=file_path_item
                    )
                    for node in file_specific_graph.get("nodes", []):
                        node_id = node["id"]
                        if node_id not in added_node_ids:
                            aggregated_graph["nodes"].append(node)
                            added_node_ids.add(node_id)
                        else:
                            for existing_node in aggregated_graph["nodes"]:
                                if existing_node["id"] == node_id:
                                    if existing_node.get("metadata", {}).get(
                                        "is_placeholder", False
                                    ) and not node.get("metadata", {}).get(
                                        "is_placeholder", False
                                    ):
                                        existing_node["metadata"] = node.get(
                                            "metadata", {}
                                        )
                                    if "file_path" in node.get("metadata", {}) and node[
                                        "metadata"
                                    ]["file_path"] != existing_node.get(
                                        "metadata", {}
                                    ).get(
                                        "file_path", ""
                                    ):
                                        if (
                                            "file_occurrences"
                                            not in existing_node["metadata"]
                                        ):
                                            existing_node["metadata"][
                                                "file_occurrences"
                                            ] = [
                                                existing_node["metadata"].get(
                                                    "file_path", ""
                                                )
                                            ]
                                        existing_node["metadata"][
                                            "file_occurrences"
                                        ].append(node["metadata"].get("file_path", ""))
                                    break
                    for link in file_specific_graph.get("links", []):
                        source_id = str(link["source"])
                        target_id = str(link["target"])
                        link_type = str(link["type"])
                        link_key = (source_id, target_id, link_type)
                        if (
                            source_id not in added_node_ids
                            or target_id not in added_node_ids
                        ):
                            logging.warning(
                                f"Skipping link with missing node: {source_id} -> {target_id} [{link_type}]"
                            )
                            continue
                        if link_key not in added_link_keys:
                            aggregated_graph["links"].append(link)
                            added_link_keys.add(link_key)
                except SyntaxError as e:
                    logging.error(f"Syntax error parsing {file_path_item}: {e}")
                except Exception as e:
                    logging.error(
                        f"Error analyzing {file_path_item} with DynamicCallGraphBuilder: {e}",
                        exc_info=True,
                    )
            else:
                idx += 1
            if hasattr(self.dynamic_builder, "finalize_graph"):
                self.dynamic_builder.finalize_graph(aggregated_graph)
            analysis_duration = time.time() - start_time
            builder_metadata = {}
            if hasattr(self.dynamic_builder, "get_analysis_metadata"):
                builder_metadata = self.dynamic_builder.get_analysis_metadata()
            else:
                builder_metadata["framework_analyzed_as"] = (
                    self.dynamic_builder.framework_detector.get_detected_framework()
                    or self.initial_framework_hint
                )
            final_metadata = {
                "research_grade_analysis_completed": True,
                "files_analyzed": idx,
                "total_files_found": len(python_files),
                "analysis_time_seconds": round(analysis_duration, 2),
                "timeout_seconds": timeout,
                **builder_metadata,
            }
            if elapsed_time > timeout:
                final_metadata["status"] = "timed_out"
            else:
                final_metadata["status"] = "completed"
            aggregated_graph["metadata"] = final_metadata
            if hasattr(self, 'status_log') and self.status_log:
                 final_metadata.setdefault("status_log_from_backend", []).extend(self.status_log)
            logging.info(f"[ResearchCallgraphGenerator] TRY BLOCK END: self.repo_path = {getattr(self, 'repo_path', None)}, perform_cleanup = {perform_cleanup}")
            return aggregated_graph

        finally:
            current_repo_path = getattr(self, 'repo_path', None)
            logging.info(
                f"[ResearchCallgraphGenerator] FINALLY BLOCK START: "
                f"self.repo_path = {current_repo_path}, "
                f"perform_cleanup = {perform_cleanup}"
            )

            if perform_cleanup and current_repo_path and os.path.exists(current_repo_path) and \
               current_repo_path.startswith(tempfile.gettempdir()): 
                logging.info(f"ResearchCallgraphGenerator: Cleaning up temporary directory: {current_repo_path}")
                try:
                    shutil.rmtree(current_repo_path)
                    self.repo_path = None 
                except Exception as e:
                    logging.error(f"Error during cleanup of {current_repo_path}: {e}")
            elif perform_cleanup:
                logging.warning(
                    f"ResearchCallgraphGenerator: perform_cleanup is True, but self.repo_path ('{current_repo_path}') "
                    f"is not a valid temp directory to clean or does not exist."
                )

            if hasattr(self.dynamic_builder, 'cleanup'):
                self.dynamic_builder.cleanup()

    async def _enhance_with_research_results(self, basic_result: Dict) -> Dict:
        logging.info(
            "_enhance_with_research_results is effectively handled by DynamicCallGraphBuilder during analyze_repository."
        )
        return basic_result

    def _add_visualization_attributes(self, callgraph: Dict) -> None:
        """
        This method is largely deprecated.
        DynamicCallGraphBuilder should enrich nodes/links with semantic metadata.
        The frontend's DynamicAttributeProvider uses this metadata for styling.
        Kept for minimal backward compatibility or specific overrides if absolutely necessary.
        """
        logging.debug(
            "_add_visualization_attributes called, but most styling should be frontend-driven."
        )
        pass

    def _calculate_type_confidence(self, type_info: Dict) -> float:
        logging.debug(
            "Attempting to calculate type confidence; TypeInferenceEngine should ideally provide this."
        )
        if not type_info:
            return 0.0
\n\n# ==============================\n# Filename: services\scope_manager.py\n# ==============================\n\nimport ast
from typing import Dict, Optional, List, Any, Set


class Scope:
    def __init__(
        self,
        parent: Optional["Scope"] = None,
        name: str = "unknown",
        scope_type: str = "module",
    ):
        self.parent = parent
        self.name = name
        self.scope_type = scope_type
        self.children: List[Scope] = []
        self.variables: Dict[str, "Variable"] = {}
        self.defined_functions: Dict[str, "FunctionDefinition"] = {}
        self.defined_classes: Dict[str, "ClassDefinition"] = {}

    def add_variable(
        self, name: str, value_type: str = None, definition_node: ast.AST = None
    ) -> "Variable":
        var = Variable(name, value_type, definition_node, self)
        self.variables[name] = var
        return var

    def get_variable(self, name: str) -> Optional["Variable"]:
        return self.variables.get(name)

    def __repr__(self) -> str:
        return f"<Scope {self.scope_type}:{self.name}>"


class Variable:
    def __init__(
        self,
        name: str,
        value_type: str = None,
        definition_node: ast.AST = None,
        scope: Scope = None,
    ):
        self.name = name
        self.possible_types: Set[str] = {value_type} if value_type else set()
        self.definitions: List[ast.AST] = [definition_node] if definition_node else []
        self.scope = scope
        self.references: List[ast.AST] = []

    def add_type(self, value_type: str) -> None:
        if value_type:
            self.possible_types.add(value_type)

    def add_definition(self, node: ast.AST) -> None:
        if node and node not in self.definitions:
            self.definitions.append(node)

    def add_reference(self, node: ast.AST) -> None:
        if node and node not in self.references:
            self.references.append(node)

    def __repr__(self) -> str:
        types_str = ", ".join(self.possible_types) if self.possible_types else "unknown"
        return f"<Variable {self.name}: {types_str}>"


class ScopeManager:
    def __init__(self):
        self.global_scope = Scope(None, "global", "module")
        self.current_scope = self.global_scope

    def enter_scope(self, name: str, scope_type: str) -> Scope:
        new_scope = Scope(self.current_scope, name, scope_type)
        self.current_scope.children.append(new_scope)
        self.current_scope = new_scope
        return new_scope

    def exit_scope(self) -> Optional[Scope]:
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent
            return self.current_scope
        return None

    def lookup_variable(self, name: str) -> Optional[Variable]:
        scope = self.current_scope
        while scope:
            if name in scope.variables:
                return scope.variables[name]
            scope = scope.parent
        return None

    def add_variable(
        self, name: str, value_type: str = None, definition_node: ast.AST = None
    ) -> Variable:
        return self.current_scope.add_variable(name, value_type, definition_node)

    def process_assignment(self, node: ast.Assign) -> None:
        value_type = self._infer_type_of_node(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                var = self.lookup_variable(var_name)
                if var:
                    var.add_type(value_type)
                    var.add_definition(node)
                else:
                    self.add_variable(var_name, value_type, node)
            elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                self._process_unpacking_assignment(target, node.value, node)

    def _process_unpacking_assignment(
        self, target: ast.AST, value: ast.AST, node: ast.Assign
    ) -> None:
        if not hasattr(target, "elts"):
            return
        for i, elt in enumerate(target.elts):
            if isinstance(elt, ast.Name):
                var_name = elt.id
                value_type = None
                if isinstance(value, (ast.Tuple, ast.List)) and i < len(value.elts):
                    value_type = self._infer_type_of_node(value.elts[i])
                var = self.lookup_variable(var_name)
                if var:
                    var.add_type(value_type)
                    var.add_definition(node)
                else:
                    self.add_variable(var_name, value_type, node)

    def _infer_type_of_node(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Num):
            if isinstance(node.n, int):
                return "int"
            elif isinstance(node.n, float):
                return "float"
            return "num"
        elif isinstance(node, ast.Str):
            return "str"
        elif isinstance(node, ast.List):
            return "list"
        elif isinstance(node, ast.Dict):
            return "dict"
        elif isinstance(node, ast.Set):
            return "set"
        elif isinstance(node, ast.Tuple):
            return "tuple"
        elif isinstance(node, ast.NameConstant):
            if node.value is None:
                return "None"
            elif isinstance(node.value, bool):
                return "bool"
        elif isinstance(node, ast.Name):
            var = self.lookup_variable(node.id)
            if var and var.possible_types:
                return next(iter(var.possible_types))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                builtins_return_types = {
                    "int": "int",
                    "float": "float",
                    "str": "str",
                    "list": "list",
                    "dict": "dict",
                    "set": "set",
                    "tuple": "tuple",
                }
                if node.func.id in builtins_return_types:
                    return builtins_return_types[node.func.id]
        return None

    def analyze_scope(
        self, node: ast.AST, scope_name: str = "module", scope_type: str = "module"
    ) -> None:
        self.enter_scope(scope_name, scope_type)
        if isinstance(node, ast.Module):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    self.process_assignment(item)
                elif isinstance(item, ast.FunctionDef):
                    self.analyze_scope(item, item.name, "function")
                elif isinstance(item, ast.ClassDef):
                    self.analyze_scope(item, item.name, "class")
        elif isinstance(node, ast.FunctionDef) or isinstance(
            node, ast.AsyncFunctionDef
        ):
            for arg in node.args.args:
                arg_name = arg.arg if hasattr(arg, "arg") else arg.id
                self.add_variable(arg_name, None, arg)
            for item in node.body:
                if isinstance(item, ast.Assign):
                    self.process_assignment(item)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    self.process_assignment(item)
                elif isinstance(item, ast.FunctionDef):
                    self.analyze_scope(item, item.name, "method")
        self.exit_scope()
\n\n# ==============================\n# Filename: services\vector_store\__init__.py\n# ==============================\n\n"""
Vector store services for GraphiX.
Provides embeddings storage and retrieval capabilities for codebase analysis.
"""
\n\n# ==============================\n# Filename: services\vector_store\chroma_store.py\n# ==============================\n\nimport os
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
\n\n# ==============================\n# Filename: settings.py\n# ==============================\n\nimport os
from typing import Optional
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./sql_app.db")
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "your_github_client_id")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "your_github_client_secret")
    VECTOR_STORE_DIR: str = os.getenv("VECTOR_STORE_DIR", "./vector_data")
    OPENAI_API_KEY: Optional[str] = os.getenv("OPENAI_API_KEY", None)
    ANTHROPIC_API_KEY: Optional[str] = os.getenv("ANTHROPIC_API_KEY", None)
    GEMINI_API_KEY: Optional[str] = os.getenv("GEMINI_API_KEY", None)
    DEFAULT_LLM_PROVIDER: str = os.getenv("DEFAULT_LLM_PROVIDER", "openai")
    
    # MongoDB Settings
    MONGO_URI: str = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    MONGO_DB_NAME: str = os.getenv("MONGO_DB_NAME", "graphix_db")

    class Config:
        env_file = ".env"

settings = Settings()\n\n# ==============================\n# Filename: utils\__init__.py\n# ==============================\n\n# Utils package initialization\n\n# ==============================\n# Filename: utils\ast_generator.py\n# ==============================\n\n# c:\GraphiX\backend\app\utils\ast_generator.py
import os
import logging
from typing import Dict, Any, Optional

from tree_sitter import Language, Parser
# We are bypassing tree_sitter_languages.get_language due to the TypeError

logger = logging.getLogger(__name__)

# --- Start of Tree-sitter Python grammar loading ---
PYTHON_LANGUAGE: Optional[Language] = None

try:
    # Import the pre-compiled tree-sitter-python language package
    import tree_sitter_python as tspython
    PYTHON_LANGUAGE = Language(tspython.language())
    logger.info("Successfully loaded Tree-sitter Python grammar using pre-compiled package.")
except ImportError:
    logger.error(
        "'tree-sitter-python' package not found. Please install it: pip install tree-sitter-python. "
        "Tree-sitter based Python AST parsing will be unavailable."
    )
    PYTHON_LANGUAGE = None
except Exception as e:
    logger.error(
        f"Failed to load Tree-sitter Python grammar from pre-compiled package: {e}. "
        "Tree-sitter based Python AST parsing will be unavailable."
    )
    PYTHON_LANGUAGE = None # Ensure it's None on failure
# --- End of Tree-sitter Python grammar loading ---


class ASTGenerator:
    def __init__(self):
        self.python_parser: Optional[Parser] = None
        if PYTHON_LANGUAGE:
            self.python_parser = Parser(PYTHON_LANGUAGE) # Pass language to constructor
            logger.info("Python parser initialized successfully with Tree-sitter.")
        else:
            logger.error(
                "Python parser (Tree-sitter) not initialized due to grammar loading/building failure. "
                "LLM documentation features requiring detailed AST parsing might be affected."
            )

        # Placeholder for other language parsers if needed in the future
        # self.javascript_parser: Optional[Parser] = None
        # ... setup for other languages ...

    def get_language_parser(self, language: str) -> Optional[Parser]:
        """Returns the Tree-sitter parser for the specified language."""
        language_lower = language.lower()
        if language_lower == 'python':
            if not self.python_parser:
                logger.warning("Python parser requested but not available (Tree-sitter).")
            return self.python_parser
        # Example for JavaScript:
        # elif language_lower == 'javascript':
        #     return self.javascript_parser
        
        logger.warning(f"No Tree-sitter parser available or configured for language: {language}")
        return None

    def parse_file_content(self, file_content_bytes: bytes, language: str) -> Optional[Any]: # Tree-sitter AST node is Any
        """
        Parses the given file content bytes using the appropriate Tree-sitter parser.
        Returns the Tree-sitter AST root node, or None if parsing fails or parser is unavailable.
        """
        parser = self.get_language_parser(language)
        if not parser:
            logger.error(f"Cannot parse content: No Tree-sitter parser available for language '{language}'.")
            return None
        
        try:
            tree = parser.parse(file_content_bytes)
            return tree.root_node
        except Exception as e:
            logger.error(f"Error parsing content with Tree-sitter for language '{language}': {e}")
            return None

    def parse_file(self, file_path: str, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Reads a file and parses its content using Tree-sitter.
        Determines language from file extension if not provided.
        Returns a dictionary with 'ast' (Tree-sitter root node), 'content' (str), and 'error' (str/None).
        """
        lang_to_use = language
        if not lang_to_use:
            _, ext = os.path.splitext(file_path)
            if ext == '.py':
                lang_to_use = 'python'
            # elif ext == '.js': lang_to_use = 'javascript' # Example for JS
            else:
                msg = f"Could not determine language for file {file_path} from extension '{ext}'."
                logger.warning(msg)
                return {"ast": None, "content": "", "error": msg}
        
        logger.debug(f"Parsing file {file_path} with language {lang_to_use} using Tree-sitter.")

        try:
            with open(file_path, 'rb') as f:
                file_content_bytes = f.read()
        except Exception as e:
            logger.error(f"Error reading file {file_path}: {e}")
            return {"ast": None, "content": "", "error": str(e)}

        try:
            file_content_str = file_content_bytes.decode('utf-8')
        except UnicodeDecodeError:
            logger.warning(f"Could not decode file {file_path} as UTF-8. Using replacement characters.")
            file_content_str = file_content_bytes.decode('utf-8', errors='replace')
            
        parser = self.get_language_parser(lang_to_use)
        if not parser:
            err_msg = f"No Tree-sitter parser for '{lang_to_use}' for {file_path}."
            logger.error(err_msg)
            return {"ast": None, "content": file_content_str, "error": err_msg}

        try:
            tree = parser.parse(file_content_bytes)
            logger.debug(f"Successfully parsed {file_path} with Tree-sitter.")
            return {"ast": tree.root_node, "content": file_content_str, "error": None}
        except Exception as e:
            err_msg = f"Error during Tree-sitter parsing of {file_path}: {e}"
            logger.error(err_msg)
            return {"ast": None, "content": file_content_str, "error": err_msg}

    def _execute_ts_query(self, node_to_search_in, query_string: str):
        """Helper to execute a Tree-sitter query, assuming Python language."""
        if not PYTHON_LANGUAGE:
            logger.error("Tree-sitter Python language not loaded. Cannot execute query.")
            return []
        try:
            query = PYTHON_LANGUAGE.query(query_string)
            captures = query.captures(node_to_search_in)
            return captures
        except Exception as e:
            logger.error(f"Error executing Tree-sitter query: {e}")
            return []

    def find_node_and_get_source(
        self,
        ast_root_node,
        node_identifier: str,
        target_node_type: str,
        source_code_bytes: bytes
    ) -> Optional[str]:
        """
        Finds a specific node (function, class, or method) in the Tree-sitter AST 
        and returns its source code.

        Args:
            ast_root_node: The root node of the Tree-sitter AST for the file.
            node_identifier: The name of the node to find. 
                             For functions/classes: "name". 
                             For methods: "ClassName.methodName".
            target_node_type: Type of the node ("function", "class", "method").
            source_code_bytes: The byte content of the source file.

        Returns:
            The source code of the found node as a string, or None if not found.
        """
        if not self.python_parser:
            logger.error("Python parser not available (Tree-sitter). Cannot find node.")
            return None
        if not ast_root_node:
            logger.error("AST root node is None. Cannot find node.")
            return None

        parts = node_identifier.split('.')
        found_node = None

        if target_node_type == "function":
            if len(parts) != 1:
                logger.error(f"Invalid identifier '{node_identifier}' for type 'function'. Expected single name.")
                return None
            name_to_find = parts[0]
            query_string = """
            (function_definition
              name: (identifier) @name) @definition
            """
            captures = self._execute_ts_query(ast_root_node, query_string)
            for captured_node, name_in_query in captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == name_to_find:
                        found_node = captured_node
                        break
        
        elif target_node_type == "class":
            if len(parts) != 1:
                logger.error(f"Invalid identifier '{node_identifier}' for type 'class'. Expected single name.")
                return None
            name_to_find = parts[0]
            query_string = """
            (class_definition
              name: (identifier) @name) @definition
            """
            captures = self._execute_ts_query(ast_root_node, query_string)
            for captured_node, name_in_query in captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == name_to_find:
                        found_node = captured_node
                        break

        elif target_node_type == "method":
            if len(parts) != 2:
                logger.error(f"Invalid identifier '{node_identifier}' for type 'method'. Expected 'ClassName.methodName'.")
                return None
            class_name_to_find, method_name_to_find = parts[0], parts[1]

            class_query_string = """
            (class_definition
              name: (identifier) @name) @definition
            """
            class_captures = self._execute_ts_query(ast_root_node, class_query_string)
            class_node_found = None
            for captured_node, name_in_query in class_captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == class_name_to_find:
                        class_node_found = captured_node
                        break
            
            if not class_node_found:
                logger.debug(f"Method search: Class '{class_name_to_find}' not found in AST for identifier '{node_identifier}'.")
                return None
            
            method_query_string = """
            (function_definition
              name: (identifier) @name) @definition
            """
            method_captures = self._execute_ts_query(class_node_found, method_query_string)
            for captured_node, name_in_query in method_captures:
                if name_in_query == 'definition':
                    name_node = captured_node.child_by_field_name("name")
                    if name_node and name_node.text.decode('utf-8', errors='ignore') == method_name_to_find:
                        found_node = captured_node
                        break
        else:
            logger.error(f"Unsupported target_node_type: '{target_node_type}' for identifier '{node_identifier}'.")
            return None

        if found_node:
            start = found_node.start_byte
            end = found_node.end_byte
            return source_code_bytes[start:end].decode('utf-8', errors='ignore')
        else:
            logger.debug(f"Node '{node_identifier}' of type '{target_node_type}' not found in AST.")
            return None


# Example usage (optional, for testing this module directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Use DEBUG for more detailed output during test
    logger.info("Testing ASTGenerator standalone...")
    
    # This test part assumes tree-sitter-python source is in vendor/tree-sitter-python
    # For the test to fully pass, you need the actual grammar files there.
    # If they are missing, it will log an error but the script won't crash.
    
    ast_gen = ASTGenerator()
    if ast_gen.python_parser:
        logger.info("ASTGenerator initialized with Python parser.")
        
        dummy_py_file = os.path.join(os.path.dirname(__file__), 'dummy_test.py')
        with open(dummy_py_file, 'w') as f:
            f.write("def hello():\n  print('world')\n\nclass MyClass:\n  pass\n")
        
        logger.info(f"Attempting to parse: {dummy_py_file}")
        parse_result = ast_gen.parse_file(dummy_py_file)

        if parse_result["ast"]:
            logger.info(f"Successfully parsed dummy_test.py. AST root type: {parse_result['ast'].type}")
            # To see the structure: print(parse_result["ast"].sexp())
        else:
            logger.error(f"Failed to parse dummy_test.py: {parse_result['error']}")
        
        try:
            os.remove(dummy_py_file)
            logger.info(f"Cleaned up {dummy_py_file}")
        except OSError as e:
            logger.error(f"Error cleaning up {dummy_py_file}: {e}")
            
    else:
        logger.error("ASTGenerator could not initialize Python parser. Standalone test failed.")

    # Note: The compiled grammar (e.g., python_grammar.dll) will remain after this test.
    # This is generally fine. You only need to delete it if you want to force a rebuild.\n\n# ==============================\n# Filename: utils\repository.py\n# ==============================\n\nimport os
import re
from urllib.parse import urlparse

def normalize_repository_id(repo_url_or_path: str) -> str:
    """
    Normalize a repository URL or path to a consistent repository ID format.
    
    Args:
        repo_url_or_path: A repository URL (e.g., https://github.com/user/repo) or local path
        
    Returns:
        A normalized repository ID (e.g., 'user-repo' or just 'repo')
    """
    # Handle empty or None input
    if not repo_url_or_path:
        return ""
    
    # Convert to string if not already
    repo_url_or_path = str(repo_url_or_path)
    
    # Check if it's a local path
    if os.path.exists(repo_url_or_path):
        # Extract the last directory name as the repository ID
        repo_id = os.path.basename(os.path.normpath(repo_url_or_path))
    else:
        # Assume it's a URL
        parsed_url = urlparse(repo_url_or_path)
        
        # Extract path without leading/trailing slashes
        path = parsed_url.path.strip('/')
        
        if path:
            # Get the last part of the path (the repository name)
            repo_id = path.split('/')[-1]
        else:
            # If there's no path, use the netloc (domain) as fallback
            repo_id = parsed_url.netloc.split('.')[0] if parsed_url.netloc else repo_url_or_path
    
    # Remove .git extension if present
    repo_id = repo_id.replace('.git', '')
    
    # Remove any query parameters or fragments that might be in the ID
    repo_id = repo_id.split('?')[0].split('#')[0]
    
    # Replace special characters with underscores
    repo_id = re.sub(r'[^\w\-]', '_', repo_id)
    
    # Convert to lowercase for case-insensitive matching
    repo_id = repo_id.lower()
    
    return repo_id\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\bindings\python\tests\test_binding.py\n# ==============================\n\nfrom unittest import TestCase

import tree_sitter, tree_sitter_python


class TestLanguage(TestCase):
    def test_can_load_grammar(self):
        try:
            tree_sitter.Language(tree_sitter_python.language())
        except Exception:
            self.fail("Error loading Python grammar")
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\bindings\python\tree_sitter_python\__init__.py\n# ==============================\n\n"""Python grammar for tree-sitter"""

from importlib.resources import files as _files

from ._binding import language


def _get_query(name, file):
    query = _files(f"{__package__}.queries") / file
    globals()[name] = query.read_text()
    return globals()[name]


def __getattr__(name):
    if name == "HIGHLIGHTS_QUERY":
        return _get_query("HIGHLIGHTS_QUERY", "highlights.scm")
    if name == "TAGS_QUERY":
        return _get_query("TAGS_QUERY", "tags.scm")

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "language",
    "HIGHLIGHTS_QUERY",
    "TAGS_QUERY",
]


def __dir__():
    return sorted(__all__ + [
        "__all__", "__builtins__", "__cached__", "__doc__", "__file__",
        "__loader__", "__name__", "__package__", "__path__", "__spec__",
    ])
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\compound-statement-without-trailing-newline.py\n# ==============================\n\nclass Foo:
  def bar():
    print "hi"\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\crlf-line-endings.py\n# ==============================\n\nprint a

if b:    
    if c:
        d
    e
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\mixed-spaces-tabs.py\n# ==============================\n\ndef main():
	print "hello"
	# 1 tab = 8 spaces in Python 2
        return
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\multiple-newlines.py\n# ==============================\n\ndef hi():



    print "hi"


def bye():
    print "bye"
















\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\python2-grammar-crlf.py\n# ==============================\n\n# Python test set -- part 1, grammar.
# This just tests whether the parser accepts them all.

# NOTE: When you run this test as a script from the command line, you
# get warnings about certain hex/oct constants.  Since those are
# issued by the parser, you can't suppress them by adding a
# filterwarnings() call to this module.  Therefore, to shut up the
# regression test, the filterwarnings() call has been added to
# regrtest.py.

from test.test_support import run_unittest, check_syntax_error
import unittest
import sys
# testing import *
from sys import *

class TokenTests(unittest.TestCase):

    def testBackslash(self):
        # Backslash means line continuation:
        x = 1 \
        + 1
        self.assertEquals(x, 2, 'backslash for line continuation')

        # Backslash does not means continuation in comments :\
        x = 0
        self.assertEquals(x, 0, 'backslash ending comment')

    def testPlainIntegers(self):
        self.assertEquals(0xff, 255)
        self.assertEquals(0377, 255)
        self.assertEquals(2147483647, 017777777777)
        # "0x" is not a valid literal
        self.assertRaises(SyntaxError, eval, "0x")
        from sys import maxint
        if maxint == 2147483647:
            self.assertEquals(-2147483647-1, -020000000000)
            # XXX -2147483648
            self.assert_(037777777777 > 0)
            self.assert_(0xffffffff > 0)
            for s in '2147483648', '040000000000', '0x100000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        elif maxint == 9223372036854775807:
            self.assertEquals(-9223372036854775807-1, -01000000000000000000000)
            self.assert_(01777777777777777777777 > 0)
            self.assert_(0xffffffffffffffff > 0)
            for s in '9223372036854775808', '02000000000000000000000','0x10000000000000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        else:
            self.fail('Weird maxint value %r' % maxint)

    def testLongIntegers(self):
        x = 0L
        x = 0l
        x = 0xffffffffffffffffL
        x = 0xffffffffffffffffl
        x = 077777777777777777L
        x = 077777777777777777l
        x = 123456789012345678901234567890L
        x = 123456789012345678901234567890l

    def testFloats(self):
        x = 3.14
        x = 314.
        x = 0.314
        # XXX x = 000.314
        x = .314
        x = 3e14
        x = 3E14
        x = 3e-14
        x = 3e+14
        x = 3.e14
        x = .3e14
        x = 3.1e4

class GrammarTests(unittest.TestCase):

    # single_input: NEWLINE | simple_stmt | compound_stmt NEWLINE
    # XXX can't test in a script -- this rule is only used when interactive

    # file_input: (NEWLINE | stmt)* ENDMARKER
    # Being tested as this very moment this very module

    # expr_input: testlist NEWLINE
    # XXX Hard to test -- used only in calls to input()

    def testEvalInput(self):
        # testlist ENDMARKER
        x = eval('1, 0 or 1')

    def testFuncdef(self):
        ### 'def' NAME parameters ':' suite
        ### parameters: '(' [varargslist] ')'
        ### varargslist: (fpdef ['=' test] ',')* ('*' NAME [',' ('**'|'*' '*') NAME]
        ###            | ('**'|'*' '*') NAME)
        ###            | fpdef ['=' test] (',' fpdef ['=' test])* [',']
        ### fpdef: NAME | '(' fplist ')'
        ### fplist: fpdef (',' fpdef)* [',']
        ### arglist: (argument ',')* (argument | *' test [',' '**' test] | '**' test)
        ### argument: [test '='] test   # Really [keyword '='] test
        def f1(): pass
        f1()
        f1(*())
        f1(*(), **{})
        def f2(one_argument): pass
        def f3(two, arguments): pass
        def f4(two, (compound, (argument, list))): pass
        def f5((compound, first), two): pass
        self.assertEquals(f2.func_code.co_varnames, ('one_argument',))
        self.assertEquals(f3.func_code.co_varnames, ('two', 'arguments'))
        if sys.platform.startswith('java'):
            self.assertEquals(f4.func_code.co_varnames,
                   ('two', '(compound, (argument, list))', 'compound', 'argument',
                                'list',))
            self.assertEquals(f5.func_code.co_varnames,
                   ('(compound, first)', 'two', 'compound', 'first'))
        else:
            self.assertEquals(f4.func_code.co_varnames,
                  ('two', '.1', 'compound', 'argument',  'list'))
            self.assertEquals(f5.func_code.co_varnames,
                  ('.0', 'two', 'compound', 'first'))
        def a1(one_arg,): pass
        def a2(two, args,): pass
        def v0(*rest): pass
        def v1(a, *rest): pass
        def v2(a, b, *rest): pass
        def v3(a, (b, c), *rest): return a, b, c, rest

        f1()
        f2(1)
        f2(1,)
        f3(1, 2)
        f3(1, 2,)
        f4(1, (2, (3, 4)))
        v0()
        v0(1)
        v0(1,)
        v0(1,2)
        v0(1,2,3,4,5,6,7,8,9,0)
        v1(1)
        v1(1,)
        v1(1,2)
        v1(1,2,3)
        v1(1,2,3,4,5,6,7,8,9,0)
        v2(1,2)
        v2(1,2,3)
        v2(1,2,3,4)
        v2(1,2,3,4,5,6,7,8,9,0)
        v3(1,(2,3))
        v3(1,(2,3),4)
        v3(1,(2,3),4,5,6,7,8,9,0)

        # ceval unpacks the formal arguments into the first argcount names;
        # thus, the names nested inside tuples must appear after these names.
        if sys.platform.startswith('java'):
            self.assertEquals(v3.func_code.co_varnames, ('a', '(b, c)', 'rest', 'b', 'c'))
        else:
            self.assertEquals(v3.func_code.co_varnames, ('a', '.1', 'rest', 'b', 'c'))
        self.assertEquals(v3(1, (2, 3), 4), (1, 2, 3, (4,)))
        def d01(a=1): pass
        d01()
        d01(1)
        d01(*(1,))
        d01(**{'a':2})
        def d11(a, b=1): pass
        d11(1)
        d11(1, 2)
        d11(1, **{'b':2})
        def d21(a, b, c=1): pass
        d21(1, 2)
        d21(1, 2, 3)
        d21(*(1, 2, 3))
        d21(1, *(2, 3))
        d21(1, 2, *(3,))
        d21(1, 2, **{'c':3})
        def d02(a=1, b=2): pass
        d02()
        d02(1)
        d02(1, 2)
        d02(*(1, 2))
        d02(1, *(2,))
        d02(1, **{'b':2})
        d02(**{'a': 1, 'b': 2})
        def d12(a, b=1, c=2): pass
        d12(1)
        d12(1, 2)
        d12(1, 2, 3)
        def d22(a, b, c=1, d=2): pass
        d22(1, 2)
        d22(1, 2, 3)
        d22(1, 2, 3, 4)
        def d01v(a=1, *rest): pass
        d01v()
        d01v(1)
        d01v(1, 2)
        d01v(*(1, 2, 3, 4))
        d01v(*(1,))
        d01v(**{'a':2})
        def d11v(a, b=1, *rest): pass
        d11v(1)
        d11v(1, 2)
        d11v(1, 2, 3)
        def d21v(a, b, c=1, *rest): pass
        d21v(1, 2)
        d21v(1, 2, 3)
        d21v(1, 2, 3, 4)
        d21v(*(1, 2, 3, 4))
        d21v(1, 2, **{'c': 3})
        def d02v(a=1, b=2, *rest): pass
        d02v()
        d02v(1)
        d02v(1, 2)
        d02v(1, 2, 3)
        d02v(1, *(2, 3, 4))
        d02v(**{'a': 1, 'b': 2})
        def d12v(a, b=1, c=2, *rest): pass
        d12v(1)
        d12v(1, 2)
        d12v(1, 2, 3)
        d12v(1, 2, 3, 4)
        d12v(*(1, 2, 3, 4))
        d12v(1, 2, *(3, 4, 5))
        d12v(1, *(2,), **{'c': 3})
        def d22v(a, b, c=1, d=2, *rest): pass
        d22v(1, 2)
        d22v(1, 2, 3)
        d22v(1, 2, 3, 4)
        d22v(1, 2, 3, 4, 5)
        d22v(*(1, 2, 3, 4))
        d22v(1, 2, *(3, 4, 5))
        d22v(1, *(2, 3), **{'d': 4})
        def d31v((x)): pass
        d31v(1)
        def d32v((x,)): pass
        d32v((1,))

        # keyword arguments after *arglist
        def f(*args, **kwargs):
            return args, kwargs
        self.assertEquals(f(1, x=2, *[3, 4], y=5), ((1, 3, 4),
                                                    {'x':2, 'y':5}))
        self.assertRaises(SyntaxError, eval, "f(1, *(2,3), 4)")
        self.assertRaises(SyntaxError, eval, "f(1, x=2, *(3,4), x=5)")

        # Check ast errors in *args and *kwargs
        check_syntax_error(self, "f(*g(1=2))")
        check_syntax_error(self, "f(**g(1=2))")

    def testLambdef(self):
        ### lambdef: 'lambda' [varargslist] ':' test
        l1 = lambda : 0
        self.assertEquals(l1(), 0)
        l2 = lambda : a[d] # XXX just testing the expression
        l3 = lambda : [2 < x for x in [-1, 3, 0L]]
        self.assertEquals(l3(), [0, 1, 0])
        l4 = lambda x = lambda y = lambda z=1 : z : y() : x()
        self.assertEquals(l4(), 1)
        l5 = lambda x, y, z=2: x + y + z
        self.assertEquals(l5(1, 2), 5)
        self.assertEquals(l5(1, 2, 3), 6)
        check_syntax_error(self, "lambda x: x = 2")
        check_syntax_error(self, "lambda (None,): None")

    ### stmt: simple_stmt | compound_stmt
    # Tested below

    def testSimpleStmt(self):
        ### simple_stmt: small_stmt (';' small_stmt)* [';']
        x = 1; pass; del x
        def foo():
            # verify statements that end with semi-colons
            x = 1; pass; del x;
        foo()

    ### small_stmt: expr_stmt | print_stmt  | pass_stmt | del_stmt | flow_stmt | import_stmt | global_stmt | access_stmt | exec_stmt
    # Tested below

    def testExprStmt(self):
        # (exprlist '=')* exprlist
        1
        1, 2, 3
        x = 1
        x = 1, 2, 3
        x = y = z = 1, 2, 3
        x, y, z = 1, 2, 3
        abc = a, b, c = x, y, z = xyz = 1, 2, (3, 4)

        check_syntax_error(self, "x + 1 = 1")
        check_syntax_error(self, "a + 1 = b + 2")

    def testPrintStmt(self):
        # 'print' (test ',')* [test]
        import StringIO

        # Can't test printing to real stdout without comparing output
        # which is not available in unittest.
        save_stdout = sys.stdout
        sys.stdout = StringIO.StringIO()

        print 1, 2, 3
        print 1, 2, 3,
        print
        print 0 or 1, 0 or 1,
        print 0 or 1

        # 'print' '>>' test ','
        print >> sys.stdout, 1, 2, 3
        print >> sys.stdout, 1, 2, 3,
        print >> sys.stdout
        print >> sys.stdout, 0 or 1, 0 or 1,
        print >> sys.stdout, 0 or 1

        # test printing to an instance
        class Gulp:
            def write(self, msg): pass

        gulp = Gulp()
        print >> gulp, 1, 2, 3
        print >> gulp, 1, 2, 3,
        print >> gulp
        print >> gulp, 0 or 1, 0 or 1,
        print >> gulp, 0 or 1

        # test print >> None
        def driver():
            oldstdout = sys.stdout
            sys.stdout = Gulp()
            try:
                tellme(Gulp())
                tellme()
            finally:
                sys.stdout = oldstdout

        # we should see this once
        def tellme(file=sys.stdout):
            print >> file, 'hello world'

        driver()

        # we should not see this at all
        def tellme(file=None):
            print >> file, 'goodbye universe'

        driver()

        self.assertEqual(sys.stdout.getvalue(), '''\
1 2 3
1 2 3
1 1 1
1 2 3
1 2 3
1 1 1
hello world
''')
        sys.stdout = save_stdout

        # syntax errors
        check_syntax_error(self, 'print ,')
        check_syntax_error(self, 'print >> x,')

    def testDelStmt(self):
        # 'del' exprlist
        abc = [1,2,3]
        x, y, z = abc
        xyz = x, y, z

        del abc
        del x, y, (z, xyz)

    def testPassStmt(self):
        # 'pass'
        pass

    # flow_stmt: break_stmt | continue_stmt | return_stmt | raise_stmt
    # Tested below

    def testBreakStmt(self):
        # 'break'
        while 1: break

    def testContinueStmt(self):
        # 'continue'
        i = 1
        while i: i = 0; continue

        msg = ""
        while not msg:
            msg = "ok"
            try:
                continue
                msg = "continue failed to continue inside try"
            except:
                msg = "continue inside try called except block"
        if msg != "ok":
            self.fail(msg)

        msg = ""
        while not msg:
            msg = "finally block not called"
            try:
                continue
            finally:
                msg = "ok"
        if msg != "ok":
            self.fail(msg)

    def test_break_continue_loop(self):
        # This test warrants an explanation. It is a test specifically for SF bugs
        # #463359 and #462937. The bug is that a 'break' statement executed or
        # exception raised inside a try/except inside a loop, *after* a continue
        # statement has been executed in that loop, will cause the wrong number of
        # arguments to be popped off the stack and the instruction pointer reset to
        # a very small number (usually 0.) Because of this, the following test
        # *must* written as a function, and the tracking vars *must* be function
        # arguments with default values. Otherwise, the test will loop and loop.

        def test_inner(extra_burning_oil = 1, count=0):
            big_hippo = 2
            while big_hippo:
                count += 1
                try:
                    if extra_burning_oil and big_hippo == 1:
                        extra_burning_oil -= 1
                        break
                    big_hippo -= 1
                    continue
                except:
                    raise
            if count > 2 or big_hippo <> 1:
                self.fail("continue then break in try/except in loop broken!")
        test_inner()

    def testReturn(self):
        # 'return' [testlist]
        def g1(): return
        def g2(): return 1
        g1()
        x = g2()
        check_syntax_error(self, "class foo:return 1")

    def testYield(self):
        check_syntax_error(self, "class foo:yield 1")

    def testRaise(self):
        # 'raise' test [',' test]
        try: raise RuntimeError, 'just testing'
        except RuntimeError: pass
        try: raise KeyboardInterrupt
        except KeyboardInterrupt: pass

    def testImport(self):
        # 'import' dotted_as_names
        import sys
        import time, sys
        # 'from' dotted_name 'import' ('*' | '(' import_as_names ')' | import_as_names)
        from time import time
        from time import (time)
        # not testable inside a function, but already done at top of the module
        # from sys import *
        from sys import path, argv
        from sys import (path, argv)
        from sys import (path, argv,)

    def testGlobal(self):
        # 'global' NAME (',' NAME)*
        global a
        global a, b
        global one, two, three, four, five, six, seven, eight, nine, ten

    def testExec(self):
        # 'exec' expr ['in' expr [',' expr]]
        z = None
        del z
        exec 'z=1+1\n'
        if z != 2: self.fail('exec \'z=1+1\'\\n')
        del z
        exec 'z=1+1'
        if z != 2: self.fail('exec \'z=1+1\'')
        z = None
        del z
        import types
        if hasattr(types, "UnicodeType"):
            exec r"""if 1:
            exec u'z=1+1\n'
            if z != 2: self.fail('exec u\'z=1+1\'\\n')
            del z
            exec u'z=1+1'
            if z != 2: self.fail('exec u\'z=1+1\'')"""
        g = {}
        exec 'z = 1' in g
        if g.has_key('__builtins__'): del g['__builtins__']
        if g != {'z': 1}: self.fail('exec \'z = 1\' in g')
        g = {}
        l = {}

        import warnings
        warnings.filterwarnings("ignore", "global statement", module="<string>")
        exec 'global a; a = 1; b = 2' in g, l
        if g.has_key('__builtins__'): del g['__builtins__']
        if l.has_key('__builtins__'): del l['__builtins__']
        if (g, l) != ({'a':1}, {'b':2}):
            self.fail('exec ... in g (%s), l (%s)' %(g,l))

    def testAssert(self):
        # assert_stmt: 'assert' test [',' test]
        assert 1
        assert 1, 1
        assert lambda x:x
        assert 1, lambda x:x+1
        try:
            assert 0, "msg"
        except AssertionError, e:
            self.assertEquals(e.args[0], "msg")
        else:
            if __debug__:
                self.fail("AssertionError not raised by assert 0")

    ### compound_stmt: if_stmt | while_stmt | for_stmt | try_stmt | funcdef | classdef
    # Tested below

    def testIf(self):
        # 'if' test ':' suite ('elif' test ':' suite)* ['else' ':' suite]
        if 1: pass
        if 1: pass
        else: pass
        if 0: pass
        elif 0: pass
        if 0: pass
        elif 0: pass
        elif 0: pass
        elif 0: pass
        else: pass

    def testWhile(self):
        # 'while' test ':' suite ['else' ':' suite]
        while 0: pass
        while 0: pass
        else: pass

        # Issue1920: "while 0" is optimized away,
        # ensure that the "else" clause is still present.
        x = 0
        while 0:
            x = 1
        else:
            x = 2
        self.assertEquals(x, 2)

    def testFor(self):
        # 'for' exprlist 'in' exprlist ':' suite ['else' ':' suite]
        for i in 1, 2, 3: pass
        for i, j, k in (): pass
        else: pass
        class Squares:
            def __init__(self, max):
                self.max = max
                self.sofar = []
            def __len__(self): return len(self.sofar)
            def __getitem__(self, i):
                if not 0 <= i < self.max: raise IndexError
                n = len(self.sofar)
                while n <= i:
                    self.sofar.append(n*n)
                    n = n+1
                return self.sofar[i]
        n = 0
        for x in Squares(10): n = n+x
        if n != 285:
            self.fail('for over growing sequence')

        result = []
        for x, in [(1,), (2,), (3,)]:
            result.append(x)
        self.assertEqual(result, [1, 2, 3])

    def testTry(self):
        ### try_stmt: 'try' ':' suite (except_clause ':' suite)+ ['else' ':' suite]
        ###         | 'try' ':' suite 'finally' ':' suite
        ### except_clause: 'except' [expr [('as' | ',') expr]]
        try:
            1/0
        except ZeroDivisionError:
            pass
        else:
            pass
        try: 1/0
        except EOFError: pass
        except TypeError as msg: pass
        except RuntimeError, msg: pass
        except: pass
        else: pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError): pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError), msg: pass
        try: pass
        finally: pass

    def testSuite(self):
        # simple_stmt | NEWLINE INDENT NEWLINE* (stmt NEWLINE*)+ DEDENT
        if 1: pass
        if 1:
            pass
        if 1:
            #
            #
            #
            pass
            pass
            #
            pass
            #

    def testTest(self):
        ### and_test ('or' and_test)*
        ### and_test: not_test ('and' not_test)*
        ### not_test: 'not' not_test | comparison
        if not 1: pass
        if 1 and 1: pass
        if 1 or 1: pass
        if not not not 1: pass
        if not 1 and 1 and 1: pass
        if 1 and 1 or 1 and 1 and 1 or not 1 and 1: pass

    def testComparison(self):
        ### comparison: expr (comp_op expr)*
        ### comp_op: '<'|'>'|'=='|'>='|'<='|'<>'|'!='|'in'|'not' 'in'|'is'|'is' 'not'
        if 1: pass
        x = (1 == 1)
        if 1 == 1: pass
        if 1 != 1: pass
        if 1 <> 1: pass
        if 1 < 1: pass
        if 1 > 1: pass
        if 1 <= 1: pass
        if 1 >= 1: pass
        if 1 is 1: pass
        if 1 is not 1: pass
        if 1 in (): pass
        if 1 not in (): pass
        if 1 < 1 > 1 == 1 >= 1 <= 1 <> 1 != 1 in 1 not in 1 is 1 is not 1: pass

    def testBinaryMaskOps(self):
        x = 1 & 1
        x = 1 ^ 1
        x = 1 | 1

    def testShiftOps(self):
        x = 1 << 1
        x = 1 >> 1
        x = 1 << 1 >> 1

    def testAdditiveOps(self):
        x = 1
        x = 1 + 1
        x = 1 - 1 - 1
        x = 1 - 1 + 1 - 1 + 1

    def testMultiplicativeOps(self):
        x = 1 * 1
        x = 1 / 1
        x = 1 % 1
        x = 1 / 1 * 1 % 1

    def testUnaryOps(self):
        x = +1
        x = -1
        x = ~1
        x = ~1 ^ 1 & 1 | 1 & 1 ^ -1
        x = -1*1/1 + 1*1 - ---1*1

    def testSelectors(self):
        ### trailer: '(' [testlist] ')' | '[' subscript ']' | '.' NAME
        ### subscript: expr | [expr] ':' [expr]

        import sys, time
        c = sys.path[0]
        x = time.time()
        x = sys.modules['time'].time()
        a = '01234'
        c = a[0]
        c = a[-1]
        s = a[0:5]
        s = a[:5]
        s = a[0:]
        s = a[:]
        s = a[-5:]
        s = a[:-1]
        s = a[-4:-3]
        # A rough test of SF bug 1333982.  http://python.org/sf/1333982
        # The testing here is fairly incomplete.
        # Test cases should include: commas with 1 and 2 colons
        d = {}
        d[1] = 1
        d[1,] = 2
        d[1,2] = 3
        d[1,2,3] = 4
        L = list(d)
        L.sort()
        self.assertEquals(str(L), '[1, (1,), (1, 2), (1, 2, 3)]')

    def testAtoms(self):
        ### atom: '(' [testlist] ')' | '[' [testlist] ']' | '{' [dictmaker] '}' | '`' testlist '`' | NAME | NUMBER | STRING
        ### dictmaker: test ':' test (',' test ':' test)* [',']

        x = (1)
        x = (1 or 2 or 3)
        x = (1 or 2 or 3, 2, 3)

        x = []
        x = [1]
        x = [1 or 2 or 3]
        x = [1 or 2 or 3, 2, 3]
        x = []

        x = {}
        x = {'one': 1}
        x = {'one': 1,}
        x = {'one' or 'two': 1 or 2}
        x = {'one': 1, 'two': 2}
        x = {'one': 1, 'two': 2,}
        x = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}

        x = `x`
        x = `1 or 2 or 3`
        self.assertEqual(`1,2`, '(1, 2)')

        x = x
        x = 'x'
        x = 123

    ### exprlist: expr (',' expr)* [',']
    ### testlist: test (',' test)* [',']
    # These have been exercised enough above

    def testClassdef(self):
        # 'class' NAME ['(' [testlist] ')'] ':' suite
        class B: pass
        class B2(): pass
        class C1(B): pass
        class C2(B): pass
        class D(C1, C2, B): pass
        class C:
            def meth1(self): pass
            def meth2(self, arg): pass
            def meth3(self, a1, a2): pass
        # decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        # decorators: decorator+
        # decorated: decorators (classdef | funcdef)
        def class_decorator(x):
            x.decorated = True
            return x
        @class_decorator
        class G:
            pass
        self.assertEqual(G.decorated, True)

    def testListcomps(self):
        # list comprehension tests
        nums = [1, 2, 3, 4, 5]
        strs = ["Apple", "Banana", "Coconut"]
        spcs = ["  Apple", " Banana ", "Coco  nut  "]

        self.assertEqual([s.strip() for s in spcs], ['Apple', 'Banana', 'Coco  nut'])
        self.assertEqual([3 * x for x in nums], [3, 6, 9, 12, 15])
        self.assertEqual([x for x in nums if x > 2], [3, 4, 5])
        self.assertEqual([(i, s) for i in nums for s in strs],
                         [(1, 'Apple'), (1, 'Banana'), (1, 'Coconut'),
                          (2, 'Apple'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Apple'), (3, 'Banana'), (3, 'Coconut'),
                          (4, 'Apple'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Apple'), (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(i, s) for i in nums for s in [f for f in strs if "n" in f]],
                         [(1, 'Banana'), (1, 'Coconut'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Banana'), (3, 'Coconut'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(lambda a:[a**i for i in range(a+1)])(j) for j in range(5)],
                         [[1], [1, 1], [1, 2, 4], [1, 3, 9, 27], [1, 4, 16, 64, 256]])

        def test_in_func(l):
            return [None < x < 3 for x in l if x > 2]

        self.assertEqual(test_in_func(nums), [False, False, False])

        def test_nested_front():
            self.assertEqual([[y for y in [x, x + 1]] for x in [1,3,5]],
                             [[1, 2], [3, 4], [5, 6]])

        test_nested_front()

        check_syntax_error(self, "[i, s for i in nums for s in strs]")
        check_syntax_error(self, "[x if y]")

        suppliers = [
          (1, "Boeing"),
          (2, "Ford"),
          (3, "Macdonalds")
        ]

        parts = [
          (10, "Airliner"),
          (20, "Engine"),
          (30, "Cheeseburger")
        ]

        suppart = [
          (1, 10), (1, 20), (2, 20), (3, 30)
        ]

        x = [
          (sname, pname)
            for (sno, sname) in suppliers
              for (pno, pname) in parts
                for (sp_sno, sp_pno) in suppart
                  if sno == sp_sno and pno == sp_pno
        ]

        self.assertEqual(x, [('Boeing', 'Airliner'), ('Boeing', 'Engine'), ('Ford', 'Engine'),
                             ('Macdonalds', 'Cheeseburger')])

    def testGenexps(self):
        # generator expression tests
        g = ([x for x in range(10)] for x in range(1))
        self.assertEqual(g.next(), [x for x in range(10)])
        try:
            g.next()
            self.fail('should produce StopIteration exception')
        except StopIteration:
            pass

        a = 1
        try:
            g = (a for d in a)
            g.next()
            self.fail('should produce TypeError')
        except TypeError:
            pass

        self.assertEqual(list((x, y) for x in 'abcd' for y in 'abcd'), [(x, y) for x in 'abcd' for y in 'abcd'])
        self.assertEqual(list((x, y) for x in 'ab' for y in 'xy'), [(x, y) for x in 'ab' for y in 'xy'])

        a = [x for x in range(10)]
        b = (x for x in (y for y in a))
        self.assertEqual(sum(b), sum([x for x in range(10)]))

        self.assertEqual(sum(x**2 for x in range(10)), sum([x**2 for x in range(10)]))
        self.assertEqual(sum(x*x for x in range(10) if x%2), sum([x*x for x in range(10) if x%2]))
        self.assertEqual(sum(x for x in (y for y in range(10))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10)))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in [y for y in (z for z in range(10))]), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True)) if True), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True) if False) if True), 0)
        check_syntax_error(self, "foo(x for x in range(10), 100)")
        check_syntax_error(self, "foo(100, x for x in range(10))")

    def testComprehensionSpecials(self):
        # test for outmost iterable precomputation
        x = 10; g = (i for i in range(x)); x = 5
        self.assertEqual(len(list(g)), 10)

        # This should hold, since we're only precomputing outmost iterable.
        x = 10; t = False; g = ((i,j) for i in range(x) if t for j in range(x))
        x = 5; t = True;
        self.assertEqual([(i,j) for i in range(10) for j in range(5)], list(g))

        # Grammar allows multiple adjacent 'if's in listcomps and genexps,
        # even though it's silly. Make sure it works (ifelse broke this.)
        self.assertEqual([ x for x in range(10) if x % 2 if x % 3 ], [1, 5, 7])
        self.assertEqual(list(x for x in range(10) if x % 2 if x % 3), [1, 5, 7])

        # verify unpacking single element tuples in listcomp/genexp.
        self.assertEqual([x for x, in [(4,), (5,), (6,)]], [4, 5, 6])
        self.assertEqual(list(x for x, in [(7,), (8,), (9,)]), [7, 8, 9])

    def test_with_statement(self):
        class manager(object):
            def __enter__(self):
                return (1, 2)
            def __exit__(self, *args):
                pass

        with manager():
            pass
        with manager() as x:
            pass
        with manager() as (x, y):
            pass
        with manager(), manager():
            pass
        with manager() as x, manager() as y:
            pass
        with manager() as x, manager():
            pass

    def testIfElseExpr(self):
        # Test ifelse expressions in various cases
        def _checkeval(msg, ret):
            "helper to check that evaluation of expressions is done correctly"
            print x
            return ret

        self.assertEqual([ x() for x in lambda: True, lambda: False if x() ], [True])
        self.assertEqual([ x() for x in (lambda: True, lambda: False) if x() ], [True])
        self.assertEqual([ x(False) for x in (lambda x: False if x else True, lambda x: True if x else False) if x(False) ], [True])
        self.assertEqual((5 if 1 else _checkeval("check 1", 0)), 5)
        self.assertEqual((_checkeval("check 2", 0) if 0 else 5), 5)
        self.assertEqual((5 and 6 if 0 else 1), 1)
        self.assertEqual(((5 and 6) if 0 else 1), 1)
        self.assertEqual((5 and (6 if 1 else 1)), 6)
        self.assertEqual((0 or _checkeval("check 3", 2) if 0 else 3), 3)
        self.assertEqual((1 or _checkeval("check 4", 2) if 1 else _checkeval("check 5", 3)), 1)
        self.assertEqual((0 or 5 if 1 else _checkeval("check 6", 3)), 5)
        self.assertEqual((not 5 if 1 else 1), False)
        self.assertEqual((not 5 if 0 else 1), 1)
        self.assertEqual((6 + 1 if 1 else 2), 7)
        self.assertEqual((6 - 1 if 1 else 2), 5)
        self.assertEqual((6 * 2 if 1 else 4), 12)
        self.assertEqual((6 / 2 if 1 else 3), 3)
        self.assertEqual((6 < 4 if 0 else 2), 2)

    def testStringLiterals(self):
        x = ''; y = ""; self.assert_(len(x) == 0 and x == y)
        x = '\''; y = "'"; self.assert_(len(x) == 1 and x == y and ord(x) == 39)
        x = '"'; y = "\""; self.assert_(len(x) == 1 and x == y and ord(x) == 34)
        x = "doesn't \"shrink\" does it"
        y = 'doesn\'t "shrink" does it'
        self.assert_(len(x) == 24 and x == y)
        x = "does \"shrink\" doesn't it"
        y = 'does "shrink" doesn\'t it'
        self.assert_(len(x) == 24 and x == y)
        x = """
The "quick"
brown fox
jumps over
the 'lazy' dog.
"""
        y = '\nThe "quick"\nbrown fox\njumps over\nthe \'lazy\' dog.\n'
        self.assertEquals(x, y)
        y = '''
The "quick"
brown fox
jumps over
the 'lazy' dog.
'''
        self.assertEquals(x, y)
        y = "\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the 'lazy' dog.\n\
"
        self.assertEquals(x, y)
        y = '\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the \'lazy\' dog.\n\
'
        self.assertEquals(x, y)



def test_main():
    run_unittest(TokenTests, GrammarTests)

if __name__ == '__main__':
    test_main()
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\python2-grammar.py\n# ==============================\n\n# Python test set -- part 1, grammar.
# This just tests whether the parser accepts them all.

# NOTE: When you run this test as a script from the command line, you
# get warnings about certain hex/oct constants.  Since those are
# issued by the parser, you can't suppress them by adding a
# filterwarnings() call to this module.  Therefore, to shut up the
# regression test, the filterwarnings() call has been added to
# regrtest.py.

from test.test_support import run_unittest, check_syntax_error
import unittest
import sys
# testing import *
from sys import *

class TokenTests(unittest.TestCase):

    def testBackslash(self):
        # Backslash means line continuation:
        x = 1 \
        + 1
        self.assertEquals(x, 2, 'backslash for line continuation')

        # Backslash does not means continuation in comments :\
        x = 0
        self.assertEquals(x, 0, 'backslash ending comment')

    def testPlainIntegers(self):
        self.assertEquals(0xff, 255)
        self.assertEquals(0377, 255)
        self.assertEquals(2147483647, 017777777777)
        # "0x" is not a valid literal
        self.assertRaises(SyntaxError, eval, "0x")
        from sys import maxint
        if maxint == 2147483647:
            self.assertEquals(-2147483647-1, -020000000000)
            # XXX -2147483648
            self.assert_(037777777777 > 0)
            self.assert_(0xffffffff > 0)
            for s in '2147483648', '040000000000', '0x100000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        elif maxint == 9223372036854775807:
            self.assertEquals(-9223372036854775807-1, -01000000000000000000000)
            self.assert_(01777777777777777777777 > 0)
            self.assert_(0xffffffffffffffff > 0)
            for s in '9223372036854775808', '02000000000000000000000', \
                     '0x10000000000000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        else:
            self.fail('Weird maxint value %r' % maxint)

    def testLongIntegers(self):
        x = 0L
        x = 0l
        x = 0xffffffffffffffffL
        x = 0xffffffffffffffffl
        x = 077777777777777777L
        x = 077777777777777777l
        x = 123456789012345678901234567890L
        x = 123456789012345678901234567890l

    def testFloats(self):
        x = 3.14
        x = 314.
        x = 0.314
        # XXX x = 000.314
        x = .314
        x = 3e14
        x = 3E14
        x = 3e-14
        x = 3e+14
        x = 3.e14
        x = .3e14
        x = 3.1e4

class GrammarTests(unittest.TestCase):

    # single_input: NEWLINE | simple_stmt | compound_stmt NEWLINE
    # XXX can't test in a script -- this rule is only used when interactive

    # file_input: (NEWLINE | stmt)* ENDMARKER
    # Being tested as this very moment this very module

    # expr_input: testlist NEWLINE
    # XXX Hard to test -- used only in calls to input()

    def testEvalInput(self):
        # testlist ENDMARKER
        x = eval('1, 0 or 1')

    def testFuncdef(self):
        ### 'def' NAME parameters ':' suite
        ### parameters: '(' [varargslist] ')'
        ### varargslist: (fpdef ['=' test] ',')* ('*' NAME [',' ('**'|'*' '*') NAME]
        ###            | ('**'|'*' '*') NAME)
        ###            | fpdef ['=' test] (',' fpdef ['=' test])* [',']
        ### fpdef: NAME | '(' fplist ')'
        ### fplist: fpdef (',' fpdef)* [',']
        ### arglist: (argument ',')* (argument | *' test [',' '**' test] | '**' test)
        ### argument: [test '='] test   # Really [keyword '='] test
        def f1(): pass
        f1()
        f1(*())
        f1(*(), **{})
        def f2(one_argument): pass
        def f3(two, arguments): pass
        def f4(two, (compound, (argument, list))): pass
        def f5((compound, first), two): pass
        self.assertEquals(f2.func_code.co_varnames, ('one_argument',))
        self.assertEquals(f3.func_code.co_varnames, ('two', 'arguments'))
        if sys.platform.startswith('java'):
            self.assertEquals(f4.func_code.co_varnames,
                   ('two', '(compound, (argument, list))', 'compound', 'argument',
                                'list',))
            self.assertEquals(f5.func_code.co_varnames,
                   ('(compound, first)', 'two', 'compound', 'first'))
        else:
            self.assertEquals(f4.func_code.co_varnames,
                  ('two', '.1', 'compound', 'argument',  'list'))
            self.assertEquals(f5.func_code.co_varnames,
                  ('.0', 'two', 'compound', 'first'))
        def a1(one_arg,): pass
        def a2(two, args,): pass
        def v0(*rest): pass
        def v1(a, *rest): pass
        def v2(a, b, *rest): pass
        def v3(a, (b, c), *rest): return a, b, c, rest

        f1()
        f2(1)
        f2(1,)
        f3(1, 2)
        f3(1, 2,)
        f4(1, (2, (3, 4)))
        v0()
        v0(1)
        v0(1,)
        v0(1,2)
        v0(1,2,3,4,5,6,7,8,9,0)
        v1(1)
        v1(1,)
        v1(1,2)
        v1(1,2,3)
        v1(1,2,3,4,5,6,7,8,9,0)
        v2(1,2)
        v2(1,2,3)
        v2(1,2,3,4)
        v2(1,2,3,4,5,6,7,8,9,0)
        v3(1,(2,3))
        v3(1,(2,3),4)
        v3(1,(2,3),4,5,6,7,8,9,0)

        # ceval unpacks the formal arguments into the first argcount names;
        # thus, the names nested inside tuples must appear after these names.
        if sys.platform.startswith('java'):
            self.assertEquals(v3.func_code.co_varnames, ('a', '(b, c)', 'rest', 'b', 'c'))
        else:
            self.assertEquals(v3.func_code.co_varnames, ('a', '.1', 'rest', 'b', 'c'))
        self.assertEquals(v3(1, (2, 3), 4), (1, 2, 3, (4,)))
        def d01(a=1): pass
        d01()
        d01(1)
        d01(*(1,))
        d01(**{'a':2})
        def d11(a, b=1): pass
        d11(1)
        d11(1, 2)
        d11(1, **{'b':2})
        def d21(a, b, c=1): pass
        d21(1, 2)
        d21(1, 2, 3)
        d21(*(1, 2, 3))
        d21(1, *(2, 3))
        d21(1, 2, *(3,))
        d21(1, 2, **{'c':3})
        def d02(a=1, b=2): pass
        d02()
        d02(1)
        d02(1, 2)
        d02(*(1, 2))
        d02(1, *(2,))
        d02(1, **{'b':2})
        d02(**{'a': 1, 'b': 2})
        def d12(a, b=1, c=2): pass
        d12(1)
        d12(1, 2)
        d12(1, 2, 3)
        def d22(a, b, c=1, d=2): pass
        d22(1, 2)
        d22(1, 2, 3)
        d22(1, 2, 3, 4)
        def d01v(a=1, *rest): pass
        d01v()
        d01v(1)
        d01v(1, 2)
        d01v(*(1, 2, 3, 4))
        d01v(*(1,))
        d01v(**{'a':2})
        def d11v(a, b=1, *rest): pass
        d11v(1)
        d11v(1, 2)
        d11v(1, 2, 3)
        def d21v(a, b, c=1, *rest): pass
        d21v(1, 2)
        d21v(1, 2, 3)
        d21v(1, 2, 3, 4)
        d21v(*(1, 2, 3, 4))
        d21v(1, 2, **{'c': 3})
        def d02v(a=1, b=2, *rest): pass
        d02v()
        d02v(1)
        d02v(1, 2)
        d02v(1, 2, 3)
        d02v(1, *(2, 3, 4))
        d02v(**{'a': 1, 'b': 2})
        def d12v(a, b=1, c=2, *rest): pass
        d12v(1)
        d12v(1, 2)
        d12v(1, 2, 3)
        d12v(1, 2, 3, 4)
        d12v(*(1, 2, 3, 4))
        d12v(1, 2, *(3, 4, 5))
        d12v(1, *(2,), **{'c': 3})
        def d22v(a, b, c=1, d=2, *rest): pass
        d22v(1, 2)
        d22v(1, 2, 3)
        d22v(1, 2, 3, 4)
        d22v(1, 2, 3, 4, 5)
        d22v(*(1, 2, 3, 4))
        d22v(1, 2, *(3, 4, 5))
        d22v(1, *(2, 3), **{'d': 4})
        def d31v((x)): pass
        d31v(1)
        def d32v((x,)): pass
        d32v((1,))

        # keyword arguments after *arglist
        def f(*args, **kwargs):
            return args, kwargs
        self.assertEquals(f(1, x=2, *[3, 4], y=5), ((1, 3, 4),
                                                    {'x':2, 'y':5}))
        self.assertRaises(SyntaxError, eval, "f(1, *(2,3), 4)")
        self.assertRaises(SyntaxError, eval, "f(1, x=2, *(3,4), x=5)")

        # Check ast errors in *args and *kwargs
        check_syntax_error(self, "f(*g(1=2))")
        check_syntax_error(self, "f(**g(1=2))")

    def testLambdef(self):
        ### lambdef: 'lambda' [varargslist] ':' test
        l1 = lambda : 0
        self.assertEquals(l1(), 0)
        l2 = lambda : a[d] # XXX just testing the expression
        l3 = lambda : [2 < x for x in [-1, 3, 0L]]
        self.assertEquals(l3(), [0, 1, 0])
        l4 = lambda x = lambda y = lambda z=1 : z : y() : x()
        self.assertEquals(l4(), 1)
        l5 = lambda x, y, z=2: x + y + z
        self.assertEquals(l5(1, 2), 5)
        self.assertEquals(l5(1, 2, 3), 6)
        check_syntax_error(self, "lambda x: x = 2")
        check_syntax_error(self, "lambda (None,): None")

    ### stmt: simple_stmt | compound_stmt
    # Tested below

    def testSimpleStmt(self):
        ### simple_stmt: small_stmt (';' small_stmt)* [';']
        x = 1; pass; del x
        def foo():
            # verify statements that end with semi-colons
            x = 1; pass; del x;
        foo()

    ### small_stmt: expr_stmt | print_stmt  | pass_stmt | del_stmt | flow_stmt | import_stmt | global_stmt | access_stmt | exec_stmt
    # Tested below

    def testExprStmt(self):
        # (exprlist '=')* exprlist
        1
        1, 2, 3
        x = 1
        x = 1, 2, 3
        x = y = z = 1, 2, 3
        x, y, z = 1, 2, 3
        abc = a, b, c = x, y, z = xyz = 1, 2, (3, 4)

        check_syntax_error(self, "x + 1 = 1")
        check_syntax_error(self, "a + 1 = b + 2")

    def testPrintStmt(self):
        # 'print' (test ',')* [test]
        import StringIO

        # Can't test printing to real stdout without comparing output
        # which is not available in unittest.
        save_stdout = sys.stdout
        sys.stdout = StringIO.StringIO()

        print 1, 2, 3
        print 1, 2, 3,
        print
        print 0 or 1, 0 or 1,
        print 0 or 1

        # 'print' '>>' test ','
        print >> sys.stdout, 1, 2, 3
        print >> sys.stdout, 1, 2, 3,
        print >> sys.stdout
        print >> sys.stdout, 0 or 1, 0 or 1,
        print >> sys.stdout, 0 or 1

        # test printing to an instance
        class Gulp:
            def write(self, msg): pass

        gulp = Gulp()
        print >> gulp, 1, 2, 3
        print >> gulp, 1, 2, 3,
        print >> gulp
        print >> gulp, 0 or 1, 0 or 1,
        print >> gulp, 0 or 1

        # test print >> None
        def driver():
            oldstdout = sys.stdout
            sys.stdout = Gulp()
            try:
                tellme(Gulp())
                tellme()
            finally:
                sys.stdout = oldstdout

        # we should see this once
        def tellme(file=sys.stdout):
            print >> file, 'hello world'

        driver()

        # we should not see this at all
        def tellme(file=None):
            print >> file, 'goodbye universe'

        driver()

        self.assertEqual(sys.stdout.getvalue(), '''\
1 2 3
1 2 3
1 1 1
1 2 3
1 2 3
1 1 1
hello world
''')
        sys.stdout = save_stdout

        # syntax errors
        check_syntax_error(self, 'print ,')
        check_syntax_error(self, 'print >> x,')

    def testDelStmt(self):
        # 'del' exprlist
        abc = [1,2,3]
        x, y, z = abc
        xyz = x, y, z

        del abc
        del x, y, (z, xyz)

    def testPassStmt(self):
        # 'pass'
        pass

    # flow_stmt: break_stmt | continue_stmt | return_stmt | raise_stmt
    # Tested below

    def testBreakStmt(self):
        # 'break'
        while 1: break

    def testContinueStmt(self):
        # 'continue'
        i = 1
        while i: i = 0; continue

        msg = ""
        while not msg:
            msg = "ok"
            try:
                continue
                msg = "continue failed to continue inside try"
            except:
                msg = "continue inside try called except block"
        if msg != "ok":
            self.fail(msg)

        msg = ""
        while not msg:
            msg = "finally block not called"
            try:
                continue
            finally:
                msg = "ok"
        if msg != "ok":
            self.fail(msg)

    def test_break_continue_loop(self):
        # This test warrants an explanation. It is a test specifically for SF bugs
        # #463359 and #462937. The bug is that a 'break' statement executed or
        # exception raised inside a try/except inside a loop, *after* a continue
        # statement has been executed in that loop, will cause the wrong number of
        # arguments to be popped off the stack and the instruction pointer reset to
        # a very small number (usually 0.) Because of this, the following test
        # *must* written as a function, and the tracking vars *must* be function
        # arguments with default values. Otherwise, the test will loop and loop.

        def test_inner(extra_burning_oil = 1, count=0):
            big_hippo = 2
            while big_hippo:
                count += 1
                try:
                    if extra_burning_oil and big_hippo == 1:
                        extra_burning_oil -= 1
                        break
                    big_hippo -= 1
                    continue
                except:
                    raise
            if count > 2 or big_hippo <> 1:
                self.fail("continue then break in try/except in loop broken!")
        test_inner()

    def testReturn(self):
        # 'return' [testlist]
        def g1(): return
        def g2(): return 1
        g1()
        x = g2()
        check_syntax_error(self, "class foo:return 1")

    def testYield(self):
        check_syntax_error(self, "class foo:yield 1")

    def testRaise(self):
        # 'raise' test [',' test]
        try: raise RuntimeError, 'just testing'
        except RuntimeError: pass
        try: raise KeyboardInterrupt
        except KeyboardInterrupt: pass

    def testImport(self):
        # 'import' dotted_as_names
        import sys
        import time, sys
        # 'from' dotted_name 'import' ('*' | '(' import_as_names ')' | import_as_names)
        from time import time
        from time import (time)
        # not testable inside a function, but already done at top of the module
        # from sys import *
        from sys import path, argv
        from sys import (path, argv)
        from sys import (path, argv,)

    def testGlobal(self):
        # 'global' NAME (',' NAME)*
        global a
        global a, b
        global one, two, three, four, five, six, seven, eight, nine, ten

    def testExec(self):
        # 'exec' expr ['in' expr [',' expr]]
        z = None
        del z
        exec 'z=1+1\n'
        if z != 2: self.fail('exec \'z=1+1\'\\n')
        del z
        exec 'z=1+1'
        if z != 2: self.fail('exec \'z=1+1\'')
        z = None
        del z
        import types
        if hasattr(types, "UnicodeType"):
            exec r"""if 1:
            exec u'z=1+1\n'
            if z != 2: self.fail('exec u\'z=1+1\'\\n')
            del z
            exec u'z=1+1'
            if z != 2: self.fail('exec u\'z=1+1\'')"""
        g = {}
        exec 'z = 1' in g
        if g.has_key('__builtins__'): del g['__builtins__']
        if g != {'z': 1}: self.fail('exec \'z = 1\' in g')
        g = {}
        l = {}

        import warnings
        warnings.filterwarnings("ignore", "global statement", module="<string>")
        exec 'global a; a = 1; b = 2' in g, l
        if g.has_key('__builtins__'): del g['__builtins__']
        if l.has_key('__builtins__'): del l['__builtins__']
        if (g, l) != ({'a':1}, {'b':2}):
            self.fail('exec ... in g (%s), l (%s)' %(g,l))

    def testAssert(self):
        # assert_stmt: 'assert' test [',' test]
        assert 1
        assert 1, 1
        assert lambda x:x
        assert 1, lambda x:x+1
        try:
            assert 0, "msg"
        except AssertionError, e:
            self.assertEquals(e.args[0], "msg")
        else:
            if __debug__:
                self.fail("AssertionError not raised by assert 0")

    ### compound_stmt: if_stmt | while_stmt | for_stmt | try_stmt | funcdef | classdef
    # Tested below

    def testIf(self):
        # 'if' test ':' suite ('elif' test ':' suite)* ['else' ':' suite]
        if 1: pass
        if 1: pass
        else: pass
        if 0: pass
        elif 0: pass
        if 0: pass
        elif 0: pass
        elif 0: pass
        elif 0: pass
        else: pass

    def testWhile(self):
        # 'while' test ':' suite ['else' ':' suite]
        while 0: pass
        while 0: pass
        else: pass

        # Issue1920: "while 0" is optimized away,
        # ensure that the "else" clause is still present.
        x = 0
        while 0:
            x = 1
        else:
            x = 2
        self.assertEquals(x, 2)

    def testFor(self):
        # 'for' exprlist 'in' exprlist ':' suite ['else' ':' suite]
        for i in 1, 2, 3: pass
        for i, j, k in (): pass
        else: pass
        class Squares:
            def __init__(self, max):
                self.max = max
                self.sofar = []
            def __len__(self): return len(self.sofar)
            def __getitem__(self, i):
                if not 0 <= i < self.max: raise IndexError
                n = len(self.sofar)
                while n <= i:
                    self.sofar.append(n*n)
                    n = n+1
                return self.sofar[i]
        n = 0
        for x in Squares(10): n = n+x
        if n != 285:
            self.fail('for over growing sequence')

        result = []
        for x, in [(1,), (2,), (3,)]:
            result.append(x)
        self.assertEqual(result, [1, 2, 3])

    def testTry(self):
        ### try_stmt: 'try' ':' suite (except_clause ':' suite)+ ['else' ':' suite]
        ###         | 'try' ':' suite 'finally' ':' suite
        ### except_clause: 'except' [expr [('as' | ',') expr]]
        try:
            1/0
        except ZeroDivisionError:
            pass
        else:
            pass
        try: 1/0
        except EOFError: pass
        except TypeError as msg: pass
        except RuntimeError, msg: pass
        except: pass
        else: pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError): pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError), msg: pass
        try: pass
        finally: pass

    def testSuite(self):
        # simple_stmt | NEWLINE INDENT NEWLINE* (stmt NEWLINE*)+ DEDENT
        if 1: pass
        if 1:
            pass
        if 1:
            #
            #
            #
            pass
            pass
            #
            pass
            #

    def testTest(self):
        ### and_test ('or' and_test)*
        ### and_test: not_test ('and' not_test)*
        ### not_test: 'not' not_test | comparison
        if not 1: pass
        if 1 and 1: pass
        if 1 or 1: pass
        if not not not 1: pass
        if not 1 and 1 and 1: pass
        if 1 and 1 or 1 and 1 and 1 or not 1 and 1: pass

    def testComparison(self):
        ### comparison: expr (comp_op expr)*
        ### comp_op: '<'|'>'|'=='|'>='|'<='|'<>'|'!='|'in'|'not' 'in'|'is'|'is' 'not'
        if 1: pass
        x = (1 == 1)
        if 1 == 1: pass
        if 1 != 1: pass
        if 1 <> 1: pass
        if 1 < 1: pass
        if 1 > 1: pass
        if 1 <= 1: pass
        if 1 >= 1: pass
        if 1 is 1: pass
        if 1 is not 1: pass
        if 1 in (): pass
        if 1 not in (): pass
        if 1 < 1 > 1 == 1 >= 1 <= 1 <> 1 != 1 in 1 not in 1 is 1 is not 1: pass

    def testBinaryMaskOps(self):
        x = 1 & 1
        x = 1 ^ 1
        x = 1 | 1

    def testShiftOps(self):
        x = 1 << 1
        x = 1 >> 1
        x = 1 << 1 >> 1

    def testAdditiveOps(self):
        x = 1
        x = 1 + 1
        x = 1 - 1 - 1
        x = 1 - 1 + 1 - 1 + 1

    def testMultiplicativeOps(self):
        x = 1 * 1
        x = 1 / 1
        x = 1 % 1
        x = 1 / 1 * 1 % 1

    def testUnaryOps(self):
        x = +1
        x = -1
        x = ~1
        x = ~1 ^ 1 & 1 | 1 & 1 ^ -1
        x = -1*1/1 + 1*1 - ---1*1

    def testSelectors(self):
        ### trailer: '(' [testlist] ')' | '[' subscript ']' | '.' NAME
        ### subscript: expr | [expr] ':' [expr]

        import sys, time
        c = sys.path[0]
        x = time.time()
        x = sys.modules['time'].time()
        a = '01234'
        c = a[0]
        c = a[-1]
        s = a[0:5]
        s = a[:5]
        s = a[0:]
        s = a[:]
        s = a[-5:]
        s = a[:-1]
        s = a[-4:-3]
        # A rough test of SF bug 1333982.  http://python.org/sf/1333982
        # The testing here is fairly incomplete.
        # Test cases should include: commas with 1 and 2 colons
        d = {}
        d[1] = 1
        d[1,] = 2
        d[1,2] = 3
        d[1,2,3] = 4
        L = list(d)
        L.sort()
        self.assertEquals(str(L), '[1, (1,), (1, 2), (1, 2, 3)]')

    def testAtoms(self):
        ### atom: '(' [testlist] ')' | '[' [testlist] ']' | '{' [dictmaker] '}' | '`' testlist '`' | NAME | NUMBER | STRING
        ### dictmaker: test ':' test (',' test ':' test)* [',']

        x = (1)
        x = (1 or 2 or 3)
        x = (1 or 2 or 3, 2, 3)

        x = []
        x = [1]
        x = [1 or 2 or 3]
        x = [1 or 2 or 3, 2, 3]
        x = []

        x = {}
        x = {'one': 1}
        x = {'one': 1,}
        x = {'one' or 'two': 1 or 2}
        x = {'one': 1, 'two': 2}
        x = {'one': 1, 'two': 2,}
        x = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}

        x = `x`
        x = `1 or 2 or 3`
        self.assertEqual(`1,2`, '(1, 2)')

        x = x
        x = 'x'
        x = 123

    ### exprlist: expr (',' expr)* [',']
    ### testlist: test (',' test)* [',']
    # These have been exercised enough above

    def testClassdef(self):
        # 'class' NAME ['(' [testlist] ')'] ':' suite
        class B: pass
        class B2(): pass
        class C1(B): pass
        class C2(B): pass
        class D(C1, C2, B): pass
        class C:
            def meth1(self): pass
            def meth2(self, arg): pass
            def meth3(self, a1, a2): pass
        # decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        # decorators: decorator+
        # decorated: decorators (classdef | funcdef)
        def class_decorator(x):
            x.decorated = True
            return x
        @class_decorator
        class G:
            pass
        self.assertEqual(G.decorated, True)

    def testListcomps(self):
        # list comprehension tests
        nums = [1, 2, 3, 4, 5]
        strs = ["Apple", "Banana", "Coconut"]
        spcs = ["  Apple", " Banana ", "Coco  nut  "]

        self.assertEqual([s.strip() for s in spcs], ['Apple', 'Banana', 'Coco  nut'])
        self.assertEqual([3 * x for x in nums], [3, 6, 9, 12, 15])
        self.assertEqual([x for x in nums if x > 2], [3, 4, 5])
        self.assertEqual([(i, s) for i in nums for s in strs],
                         [(1, 'Apple'), (1, 'Banana'), (1, 'Coconut'),
                          (2, 'Apple'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Apple'), (3, 'Banana'), (3, 'Coconut'),
                          (4, 'Apple'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Apple'), (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(i, s) for i in nums for s in [f for f in strs if "n" in f]],
                         [(1, 'Banana'), (1, 'Coconut'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Banana'), (3, 'Coconut'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(lambda a:[a**i for i in range(a+1)])(j) for j in range(5)],
                         [[1], [1, 1], [1, 2, 4], [1, 3, 9, 27], [1, 4, 16, 64, 256]])

        def test_in_func(l):
            return [None < x < 3 for x in l if x > 2]

        self.assertEqual(test_in_func(nums), [False, False, False])

        def test_nested_front():
            self.assertEqual([[y for y in [x, x + 1]] for x in [1,3,5]],
                             [[1, 2], [3, 4], [5, 6]])

        test_nested_front()

        check_syntax_error(self, "[i, s for i in nums for s in strs]")
        check_syntax_error(self, "[x if y]")

        suppliers = [
          (1, "Boeing"),
          (2, "Ford"),
          (3, "Macdonalds")
        ]

        parts = [
          (10, "Airliner"),
          (20, "Engine"),
          (30, "Cheeseburger")
        ]

        suppart = [
          (1, 10), (1, 20), (2, 20), (3, 30)
        ]

        x = [
          (sname, pname)
            for (sno, sname) in suppliers
              for (pno, pname) in parts
                for (sp_sno, sp_pno) in suppart
                  if sno == sp_sno and pno == sp_pno
        ]

        self.assertEqual(x, [('Boeing', 'Airliner'), ('Boeing', 'Engine'), ('Ford', 'Engine'),
                             ('Macdonalds', 'Cheeseburger')])

    def testGenexps(self):
        # generator expression tests
        g = ([x for x in range(10)] for x in range(1))
        self.assertEqual(g.next(), [x for x in range(10)])
        try:
            g.next()
            self.fail('should produce StopIteration exception')
        except StopIteration:
            pass

        a = 1
        try:
            g = (a for d in a)
            g.next()
            self.fail('should produce TypeError')
        except TypeError:
            pass

        self.assertEqual(list((x, y) for x in 'abcd' for y in 'abcd'), [(x, y) for x in 'abcd' for y in 'abcd'])
        self.assertEqual(list((x, y) for x in 'ab' for y in 'xy'), [(x, y) for x in 'ab' for y in 'xy'])

        a = [x for x in range(10)]
        b = (x for x in (y for y in a))
        self.assertEqual(sum(b), sum([x for x in range(10)]))

        self.assertEqual(sum(x**2 for x in range(10)), sum([x**2 for x in range(10)]))
        self.assertEqual(sum(x*x for x in range(10) if x%2), sum([x*x for x in range(10) if x%2]))
        self.assertEqual(sum(x for x in (y for y in range(10))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10)))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in [y for y in (z for z in range(10))]), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True)) if True), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True) if False) if True), 0)
        check_syntax_error(self, "foo(x for x in range(10), 100)")
        check_syntax_error(self, "foo(100, x for x in range(10))")

    def testComprehensionSpecials(self):
        # test for outmost iterable precomputation
        x = 10; g = (i for i in range(x)); x = 5
        self.assertEqual(len(list(g)), 10)

        # This should hold, since we're only precomputing outmost iterable.
        x = 10; t = False; g = ((i,j) for i in range(x) if t for j in range(x))
        x = 5; t = True;
        self.assertEqual([(i,j) for i in range(10) for j in range(5)], list(g))

        # Grammar allows multiple adjacent 'if's in listcomps and genexps,
        # even though it's silly. Make sure it works (ifelse broke this.)
        self.assertEqual([ x for x in range(10) if x % 2 if x % 3 ], [1, 5, 7])
        self.assertEqual(list(x for x in range(10) if x % 2 if x % 3), [1, 5, 7])

        # verify unpacking single element tuples in listcomp/genexp.
        self.assertEqual([x for x, in [(4,), (5,), (6,)]], [4, 5, 6])
        self.assertEqual(list(x for x, in [(7,), (8,), (9,)]), [7, 8, 9])

    def test_with_statement(self):
        class manager(object):
            def __enter__(self):
                return (1, 2)
            def __exit__(self, *args):
                pass

        with manager():
            pass
        with manager() as x:
            pass
        with manager() as (x, y):
            pass
        with manager(), manager():
            pass
        with manager() as x, manager() as y:
            pass
        with manager() as x, manager():
            pass

    def testIfElseExpr(self):
        # Test ifelse expressions in various cases
        def _checkeval(msg, ret):
            "helper to check that evaluation of expressions is done correctly"
            print x
            return ret

        self.assertEqual([ x() for x in lambda: True, lambda: False if x() ], [True])
        self.assertEqual([ x() for x in (lambda: True, lambda: False) if x() ], [True])
        self.assertEqual([ x(False) for x in (lambda x: False if x else True, lambda x: True if x else False) if x(False) ], [True])
        self.assertEqual((5 if 1 else _checkeval("check 1", 0)), 5)
        self.assertEqual((_checkeval("check 2", 0) if 0 else 5), 5)
        self.assertEqual((5 and 6 if 0 else 1), 1)
        self.assertEqual(((5 and 6) if 0 else 1), 1)
        self.assertEqual((5 and (6 if 1 else 1)), 6)
        self.assertEqual((0 or _checkeval("check 3", 2) if 0 else 3), 3)
        self.assertEqual((1 or _checkeval("check 4", 2) if 1 else _checkeval("check 5", 3)), 1)
        self.assertEqual((0 or 5 if 1 else _checkeval("check 6", 3)), 5)
        self.assertEqual((not 5 if 1 else 1), False)
        self.assertEqual((not 5 if 0 else 1), 1)
        self.assertEqual((6 + 1 if 1 else 2), 7)
        self.assertEqual((6 - 1 if 1 else 2), 5)
        self.assertEqual((6 * 2 if 1 else 4), 12)
        self.assertEqual((6 / 2 if 1 else 3), 3)
        self.assertEqual((6 < 4 if 0 else 2), 2)

    def testStringLiterals(self):
        x = ''; y = ""; self.assert_(len(x) == 0 and x == y)
        x = '\''; y = "'"; self.assert_(len(x) == 1 and x == y and ord(x) == 39)
        x = '"'; y = "\""; self.assert_(len(x) == 1 and x == y and ord(x) == 34)
        x = "doesn't \"shrink\" does it"
        y = 'doesn\'t "shrink" does it'
        self.assert_(len(x) == 24 and x == y)
        x = "does \"shrink\" doesn't it"
        y = 'does "shrink" doesn\'t it'
        self.assert_(len(x) == 24 and x == y)
        x = """
The "quick"
brown fox
jumps over
the 'lazy' dog.
"""
        y = '\nThe "quick"\nbrown fox\njumps over\nthe \'lazy\' dog.\n'
        self.assertEquals(x, y)
        y = '''
The "quick"
brown fox
jumps over
the 'lazy' dog.
'''
        self.assertEquals(x, y)
        y = "\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the 'lazy' dog.\n\
"
        self.assertEquals(x, y)
        y = '\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the \'lazy\' dog.\n\
'
        self.assertEquals(x, y)



def test_main():
    run_unittest(TokenTests, GrammarTests)

if __name__ == '__main__':
    test_main()

\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\python3-grammar-crlf.py\n# ==============================\n\n# Python test set -- part 1, grammar.
# This just tests whether the parser accepts them all.

# NOTE: When you run this test as a script from the command line, you
# get warnings about certain hex/oct constants.  Since those are
# issued by the parser, you can't suppress them by adding a
# filterwarnings() call to this module.  Therefore, to shut up the
# regression test, the filterwarnings() call has been added to
# regrtest.py.

from test.support import run_unittest, check_syntax_error
import unittest
import sys
# testing import *
from sys import *

class TokenTests(unittest.TestCase):

    def testBackslash(self):
        # Backslash means line continuation:
        x = 1 \
        + 1
        self.assertEquals(x, 2, 'backslash for line continuation')

        # Backslash does not means continuation in comments :\
        x = 0
        self.assertEquals(x, 0, 'backslash ending comment')

    def testPlainIntegers(self):
        self.assertEquals(type(000), type(0))
        self.assertEquals(0xff, 255)
        self.assertEquals(0o377, 255)
        self.assertEquals(2147483647, 0o17777777777)
        self.assertEquals(0b1001, 9)
        # "0x" is not a valid literal
        self.assertRaises(SyntaxError, eval, "0x")
        from sys import maxsize
        if maxsize == 2147483647:
            self.assertEquals(-2147483647-1, -0o20000000000)
            # XXX -2147483648
            self.assert_(0o37777777777 > 0)
            self.assert_(0xffffffff > 0)
            self.assert_(0b1111111111111111111111111111111 > 0)
            for s in ('2147483648', '0o40000000000', '0x100000000',
                      '0b10000000000000000000000000000000'):
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        elif maxsize == 9223372036854775807:
            self.assertEquals(-9223372036854775807-1, -0o1000000000000000000000)
            self.assert_(0o1777777777777777777777 > 0)
            self.assert_(0xffffffffffffffff > 0)
            self.assert_(0b11111111111111111111111111111111111111111111111111111111111111 > 0)
            for s in '9223372036854775808', '0o2000000000000000000000', \
                     '0x10000000000000000', \
                     '0b100000000000000000000000000000000000000000000000000000000000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        else:
            self.fail('Weird maxsize value %r' % maxsize)

    def testLongIntegers(self):
        x = 0
        x = 0xffffffffffffffff
        x = 0Xffffffffffffffff
        x = 0o77777777777777777
        x = 0O77777777777777777
        x = 123456789012345678901234567890
        x = 0b100000000000000000000000000000000000000000000000000000000000000000000
        x = 0B111111111111111111111111111111111111111111111111111111111111111111111

    def testUnderscoresInNumbers(self):
        # Integers
        x = 1_0
        x = 123_456_7_89
        x = 0xabc_123_4_5
        x = 0X_abc_123
        x = 0B11_01
        x = 0b_11_01
        x = 0o45_67
        x = 0O_45_67

        # Floats
        x = 3_1.4
        x = 03_1.4
        x = 3_1.
        x = .3_1
        x = 3.1_4
        x = 0_3.1_4
        x = 3e1_4
        x = 3_1e+4_1
        x = 3_1E-4_1

    def testFloats(self):
        x = 3.14
        x = 314.
        x = 0.314
        # XXX x = 000.314
        x = .314
        x = 3e14
        x = 3E14
        x = 3e-14
        x = 3e+14
        x = 3.e14
        x = .3e14
        x = 3.1e4

    def testEllipsis(self):
        x = ...
        self.assert_(x is Ellipsis)
        self.assertRaises(SyntaxError, eval, ".. .")

class GrammarTests(unittest.TestCase):

    # single_input: NEWLINE | simple_stmt | compound_stmt NEWLINE
    # XXX can't test in a script -- this rule is only used when interactive

    # file_input: (NEWLINE | stmt)* ENDMARKER
    # Being tested as this very moment this very module

    # expr_input: testlist NEWLINE
    # XXX Hard to test -- used only in calls to input()

    def testEvalInput(self):
        # testlist ENDMARKER
        x = eval('1, 0 or 1')

    def testFuncdef(self):
        ### [decorators] 'def' NAME parameters ['->' test] ':' suite
        ### decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        ### decorators: decorator+
        ### parameters: '(' [typedargslist] ')'
        ### typedargslist: ((tfpdef ['=' test] ',')*
        ###                ('*' [tfpdef] (',' tfpdef ['=' test])* [',' '**' tfpdef] | '**' tfpdef)
        ###                | tfpdef ['=' test] (',' tfpdef ['=' test])* [','])
        ### tfpdef: NAME [':' test]
        ### varargslist: ((vfpdef ['=' test] ',')*
        ###              ('*' [vfpdef] (',' vfpdef ['=' test])*  [',' '**' vfpdef] | '**' vfpdef)
        ###              | vfpdef ['=' test] (',' vfpdef ['=' test])* [','])
        ### vfpdef: NAME
        def f1(): pass
        f1()
        f1(*())
        f1(*(), **{})
        def f2(one_argument): pass
        def f3(two, arguments): pass
        self.assertEquals(f2.__code__.co_varnames, ('one_argument',))
        self.assertEquals(f3.__code__.co_varnames, ('two', 'arguments'))
        def a1(one_arg,): pass
        def a2(two, args,): pass
        def v0(*rest): pass
        def v1(a, *rest): pass
        def v2(a, b, *rest): pass

        f1()
        f2(1)
        f2(1,)
        f3(1, 2)
        f3(1, 2,)
        v0()
        v0(1)
        v0(1,)
        v0(1,2)
        v0(1,2,3,4,5,6,7,8,9,0)
        v1(1)
        v1(1,)
        v1(1,2)
        v1(1,2,3)
        v1(1,2,3,4,5,6,7,8,9,0)
        v2(1,2)
        v2(1,2,3)
        v2(1,2,3,4)
        v2(1,2,3,4,5,6,7,8,9,0)

        def d01(a=1): pass
        d01()
        d01(1)
        d01(*(1,))
        d01(**{'a':2})
        def d11(a, b=1): pass
        d11(1)
        d11(1, 2)
        d11(1, **{'b':2})
        def d21(a, b, c=1): pass
        d21(1, 2)
        d21(1, 2, 3)
        d21(*(1, 2, 3))
        d21(1, *(2, 3))
        d21(1, 2, *(3,))
        d21(1, 2, **{'c':3})
        def d02(a=1, b=2): pass
        d02()
        d02(1)
        d02(1, 2)
        d02(*(1, 2))
        d02(1, *(2,))
        d02(1, **{'b':2})
        d02(**{'a': 1, 'b': 2})
        def d12(a, b=1, c=2): pass
        d12(1)
        d12(1, 2)
        d12(1, 2, 3)
        def d22(a, b, c=1, d=2): pass
        d22(1, 2)
        d22(1, 2, 3)
        d22(1, 2, 3, 4)
        def d01v(a=1, *rest): pass
        d01v()
        d01v(1)
        d01v(1, 2)
        d01v(*(1, 2, 3, 4))
        d01v(*(1,))
        d01v(**{'a':2})
        def d11v(a, b=1, *rest): pass
        d11v(1)
        d11v(1, 2)
        d11v(1, 2, 3)
        def d21v(a, b, c=1, *rest): pass
        d21v(1, 2)
        d21v(1, 2, 3)
        d21v(1, 2, 3, 4)
        d21v(*(1, 2, 3, 4))
        d21v(1, 2, **{'c': 3})
        def d02v(a=1, b=2, *rest): pass
        d02v()
        d02v(1)
        d02v(1, 2)
        d02v(1, 2, 3)
        d02v(1, *(2, 3, 4))
        d02v(**{'a': 1, 'b': 2})
        def d12v(a, b=1, c=2, *rest): pass
        d12v(1)
        d12v(1, 2)
        d12v(1, 2, 3)
        d12v(1, 2, 3, 4)
        d12v(*(1, 2, 3, 4))
        d12v(1, 2, *(3, 4, 5))
        d12v(1, *(2,), **{'c': 3})
        def d22v(a, b, c=1, d=2, *rest): pass
        d22v(1, 2)
        d22v(1, 2, 3)
        d22v(1, 2, 3, 4)
        d22v(1, 2, 3, 4, 5)
        d22v(*(1, 2, 3, 4))
        d22v(1, 2, *(3, 4, 5))
        d22v(1, *(2, 3), **{'d': 4})

        # keyword argument type tests
        try:
            str('x', **{b'foo':1 })
        except TypeError:
            pass
        else:
            self.fail('Bytes should not work as keyword argument names')
        # keyword only argument tests
        def pos0key1(*, key): return key
        pos0key1(key=100)
        def pos2key2(p1, p2, *, k1, k2=100): return p1,p2,k1,k2
        pos2key2(1, 2, k1=100)
        pos2key2(1, 2, k1=100, k2=200)
        pos2key2(1, 2, k2=100, k1=200)
        def pos2key2dict(p1, p2, *, k1=100, k2, **kwarg): return p1,p2,k1,k2,kwarg
        pos2key2dict(1,2,k2=100,tokwarg1=100,tokwarg2=200)
        pos2key2dict(1,2,tokwarg1=100,tokwarg2=200, k2=100)

        # keyword arguments after *arglist
        def f(*args, **kwargs):
            return args, kwargs
        self.assertEquals(f(1, x=2, *[3, 4], y=5), ((1, 3, 4),
                                                    {'x':2, 'y':5}))
        self.assertRaises(SyntaxError, eval, "f(1, *(2,3), 4)")
        self.assertRaises(SyntaxError, eval, "f(1, x=2, *(3,4), x=5)")

        # argument annotation tests
        def f(x) -> list: pass
        self.assertEquals(f.__annotations__, {'return': list})
        def f(x:int): pass
        self.assertEquals(f.__annotations__, {'x': int})
        def f(*x:str): pass
        self.assertEquals(f.__annotations__, {'x': str})
        def f(**x:float): pass
        self.assertEquals(f.__annotations__, {'x': float})
        def f(x, y:1+2): pass
        self.assertEquals(f.__annotations__, {'y': 3})
        def f(a, b:1, c:2, d): pass
        self.assertEquals(f.__annotations__, {'b': 1, 'c': 2})
        def f(a, b:1, c:2, d, e:3=4, f=5, *g:6): pass
        self.assertEquals(f.__annotations__,
                          {'b': 1, 'c': 2, 'e': 3, 'g': 6})
        def f(a, b:1, c:2, d, e:3=4, f=5, *g:6, h:7, i=8, j:9=10,
              **k:11) -> 12: pass
        self.assertEquals(f.__annotations__,
                          {'b': 1, 'c': 2, 'e': 3, 'g': 6, 'h': 7, 'j': 9,
                           'k': 11, 'return': 12})
        # Check for SF Bug #1697248 - mixing decorators and a return annotation
        def null(x): return x
        @null
        def f(x) -> list: pass
        self.assertEquals(f.__annotations__, {'return': list})

        # test closures with a variety of oparg's
        closure = 1
        def f(): return closure
        def f(x=1): return closure
        def f(*, k=1): return closure
        def f() -> int: return closure

        # Check ast errors in *args and *kwargs
        check_syntax_error(self, "f(*g(1=2))")
        check_syntax_error(self, "f(**g(1=2))")

    def testLambdef(self):
        ### lambdef: 'lambda' [varargslist] ':' test
        l1 = lambda : 0
        self.assertEquals(l1(), 0)
        l2 = lambda : a[d] # XXX just testing the expression
        l3 = lambda : [2 < x for x in [-1, 3, 0]]
        self.assertEquals(l3(), [0, 1, 0])
        l4 = lambda x = lambda y = lambda z=1 : z : y() : x()
        self.assertEquals(l4(), 1)
        l5 = lambda x, y, z=2: x + y + z
        self.assertEquals(l5(1, 2), 5)
        self.assertEquals(l5(1, 2, 3), 6)
        check_syntax_error(self, "lambda x: x = 2")
        check_syntax_error(self, "lambda (None,): None")
        l6 = lambda x, y, *, k=20: x+y+k
        self.assertEquals(l6(1,2), 1+2+20)
        self.assertEquals(l6(1,2,k=10), 1+2+10)


    ### stmt: simple_stmt | compound_stmt
    # Tested below

    def testSimpleStmt(self):
        ### simple_stmt: small_stmt (';' small_stmt)* [';']
        x = 1; pass; del x
        def foo():
            # verify statements that end with semi-colons
            x = 1; pass; del x;
        foo()

    ### small_stmt: expr_stmt | pass_stmt | del_stmt | flow_stmt | import_stmt | global_stmt | access_stmt
    # Tested below

    def testExprStmt(self):
        # (exprlist '=')* exprlist
        1
        1, 2, 3
        x = 1
        x = 1, 2, 3
        x = y = z = 1, 2, 3
        x, y, z = 1, 2, 3
        abc = a, b, c = x, y, z = xyz = 1, 2, (3, 4)

        check_syntax_error(self, "x + 1 = 1")
        check_syntax_error(self, "a + 1 = b + 2")

    def testDelStmt(self):
        # 'del' exprlist
        abc = [1,2,3]
        x, y, z = abc
        xyz = x, y, z

        del abc
        del x, y, (z, xyz)

    def testPassStmt(self):
        # 'pass'
        pass

    # flow_stmt: break_stmt | continue_stmt | return_stmt | raise_stmt
    # Tested below

    def testBreakStmt(self):
        # 'break'
        while 1: break

    def testContinueStmt(self):
        # 'continue'
        i = 1
        while i: i = 0; continue

        msg = ""
        while not msg:
            msg = "ok"
            try:
                continue
                msg = "continue failed to continue inside try"
            except:
                msg = "continue inside try called except block"
        if msg != "ok":
            self.fail(msg)

        msg = ""
        while not msg:
            msg = "finally block not called"
            try:
                continue
            finally:
                msg = "ok"
        if msg != "ok":
            self.fail(msg)

    def test_break_continue_loop(self):
        # This test warrants an explanation. It is a test specifically for SF bugs
        # #463359 and #462937. The bug is that a 'break' statement executed or
        # exception raised inside a try/except inside a loop, *after* a continue
        # statement has been executed in that loop, will cause the wrong number of
        # arguments to be popped off the stack and the instruction pointer reset to
        # a very small number (usually 0.) Because of this, the following test
        # *must* written as a function, and the tracking vars *must* be function
        # arguments with default values. Otherwise, the test will loop and loop.

        def test_inner(extra_burning_oil = 1, count=0):
            big_hippo = 2
            while big_hippo:
                count += 1
                try:
                    if extra_burning_oil and big_hippo == 1:
                        extra_burning_oil -= 1
                        break
                    big_hippo -= 1
                    continue
                except:
                    raise
            if count > 2 or big_hippo != 1:
                self.fail("continue then break in try/except in loop broken!")
        test_inner()

    def testReturn(self):
        # 'return' [testlist]
        def g1(): return
        def g2(): return 1
        g1()
        x = g2()
        check_syntax_error(self, "class foo:return 1")

    def testYield(self):
        check_syntax_error(self, "class foo:yield 1")

    def testRaise(self):
        # 'raise' test [',' test]
        try: raise RuntimeError('just testing')
        except RuntimeError: pass
        try: raise KeyboardInterrupt
        except KeyboardInterrupt: pass

    def testImport(self):
        # 'import' dotted_as_names
        import sys
        import time, sys
        # 'from' dotted_name 'import' ('*' | '(' import_as_names ')' | import_as_names)
        from time import time
        from time import (time)
        # not testable inside a function, but already done at top of the module
        # from sys import *
        from sys import path, argv
        from sys import (path, argv)
        from sys import (path, argv,)

    def testGlobal(self):
        # 'global' NAME (',' NAME)*
        global a
        global a, b
        global one, two, three, four, five, six, seven, eight, nine, ten

    def testNonlocal(self):
        # 'nonlocal' NAME (',' NAME)*
        x = 0
        y = 0
        def f():
            nonlocal x
            nonlocal x, y

    def testAssert(self):
        # assert_stmt: 'assert' test [',' test]
        assert 1
        assert 1, 1
        assert lambda x:x
        assert 1, lambda x:x+1
        try:
            assert 0, "msg"
        except AssertionError as e:
            self.assertEquals(e.args[0], "msg")
        else:
            if __debug__:
                self.fail("AssertionError not raised by assert 0")

    ### compound_stmt: if_stmt | while_stmt | for_stmt | try_stmt | funcdef | classdef
    # Tested below

    def testIf(self):
        # 'if' test ':' suite ('elif' test ':' suite)* ['else' ':' suite]
        if 1: pass
        if 1: pass
        else: pass
        if 0: pass
        elif 0: pass
        if 0: pass
        elif 0: pass
        elif 0: pass
        elif 0: pass
        else: pass

    def testWhile(self):
        # 'while' test ':' suite ['else' ':' suite]
        while 0: pass
        while 0: pass
        else: pass

        # Issue1920: "while 0" is optimized away,
        # ensure that the "else" clause is still present.
        x = 0
        while 0:
            x = 1
        else:
            x = 2
        self.assertEquals(x, 2)

    def testFor(self):
        # 'for' exprlist 'in' exprlist ':' suite ['else' ':' suite]
        for i in 1, 2, 3: pass
        for i, j, k in (): pass
        else: pass
        class Squares:
            def __init__(self, max):
                self.max = max
                self.sofar = []
            def __len__(self): return len(self.sofar)
            def __getitem__(self, i):
                if not 0 <= i < self.max: raise IndexError
                n = len(self.sofar)
                while n <= i:
                    self.sofar.append(n*n)
                    n = n+1
                return self.sofar[i]
        n = 0
        for x in Squares(10): n = n+x
        if n != 285:
            self.fail('for over growing sequence')

        result = []
        for x, in [(1,), (2,), (3,)]:
            result.append(x)
        self.assertEqual(result, [1, 2, 3])

    def testTry(self):
        ### try_stmt: 'try' ':' suite (except_clause ':' suite)+ ['else' ':' suite]
        ###         | 'try' ':' suite 'finally' ':' suite
        ### except_clause: 'except' [expr ['as' expr]]
        try:
            1/0
        except ZeroDivisionError:
            pass
        else:
            pass
        try: 1/0
        except EOFError: pass
        except TypeError as msg: pass
        except RuntimeError as msg: pass
        except: pass
        else: pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError): pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError) as msg: pass
        try: pass
        finally: pass

    def testSuite(self):
        # simple_stmt | NEWLINE INDENT NEWLINE* (stmt NEWLINE*)+ DEDENT
        if 1: pass
        if 1:
            pass
        if 1:
            #
            #
            #
            pass
            pass
            #
            pass
            #

    def testTest(self):
        ### and_test ('or' and_test)*
        ### and_test: not_test ('and' not_test)*
        ### not_test: 'not' not_test | comparison
        if not 1: pass
        if 1 and 1: pass
        if 1 or 1: pass
        if not not not 1: pass
        if not 1 and 1 and 1: pass
        if 1 and 1 or 1 and 1 and 1 or not 1 and 1: pass

    def testComparison(self):
        ### comparison: expr (comp_op expr)*
        ### comp_op: '<'|'>'|'=='|'>='|'<='|'!='|'in'|'not' 'in'|'is'|'is' 'not'
        if 1: pass
        x = (1 == 1)
        if 1 == 1: pass
        if 1 != 1: pass
        if 1 < 1: pass
        if 1 > 1: pass
        if 1 <= 1: pass
        if 1 >= 1: pass
        if 1 is 1: pass
        if 1 is not 1: pass
        if 1 in (): pass
        if 1 not in (): pass
        if 1 < 1 > 1 == 1 >= 1 <= 1 != 1 in 1 not in 1 is 1 is not 1: pass

    def testBinaryMaskOps(self):
        x = 1 & 1
        x = 1 ^ 1
        x = 1 | 1

    def testShiftOps(self):
        x = 1 << 1
        x = 1 >> 1
        x = 1 << 1 >> 1

    def testAdditiveOps(self):
        x = 1
        x = 1 + 1
        x = 1 - 1 - 1
        x = 1 - 1 + 1 - 1 + 1

    def testMultiplicativeOps(self):
        x = 1 * 1
        x = 1 / 1
        x = 1 % 1
        x = 1 / 1 * 1 % 1

    def testUnaryOps(self):
        x = +1
        x = -1
        x = ~1
        x = ~1 ^ 1 & 1 | 1 & 1 ^ -1
        x = -1*1/1 + 1*1 - ---1*1

    def testSelectors(self):
        ### trailer: '(' [testlist] ')' | '[' subscript ']' | '.' NAME
        ### subscript: expr | [expr] ':' [expr]

        import sys, time
        c = sys.path[0]
        x = time.time()
        x = sys.modules['time'].time()
        a = '01234'
        c = a[0]
        c = a[-1]
        s = a[0:5]
        s = a[:5]
        s = a[0:]
        s = a[:]
        s = a[-5:]
        s = a[:-1]
        s = a[-4:-3]
        # A rough test of SF bug 1333982.  http://python.org/sf/1333982
        # The testing here is fairly incomplete.
        # Test cases should include: commas with 1 and 2 colons
        d = {}
        d[1] = 1
        d[1,] = 2
        d[1,2] = 3
        d[1,2,3] = 4
        L = list(d)
        L.sort(key=lambda x: x if isinstance(x, tuple) else ())
        self.assertEquals(str(L), '[1, (1,), (1, 2), (1, 2, 3)]')

    def testAtoms(self):
        ### atom: '(' [testlist] ')' | '[' [testlist] ']' | '{' [dictsetmaker] '}' | NAME | NUMBER | STRING
        ### dictsetmaker: (test ':' test (',' test ':' test)* [',']) | (test (',' test)* [','])

        x = (1)
        x = (1 or 2 or 3)
        x = (1 or 2 or 3, 2, 3)

        x = []
        x = [1]
        x = [1 or 2 or 3]
        x = [1 or 2 or 3, 2, 3]
        x = []

        x = {}
        x = {'one': 1}
        x = {'one': 1,}
        x = {'one' or 'two': 1 or 2}
        x = {'one': 1, 'two': 2}
        x = {'one': 1, 'two': 2,}
        x = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}

        x = {'one'}
        x = {'one', 1,}
        x = {'one', 'two', 'three'}
        x = {2, 3, 4,}

        x = x
        x = 'x'
        x = 123

    ### exprlist: expr (',' expr)* [',']
    ### testlist: test (',' test)* [',']
    # These have been exercised enough above

    def testClassdef(self):
        # 'class' NAME ['(' [testlist] ')'] ':' suite
        class B: pass
        class B2(): pass
        class C1(B): pass
        class C2(B): pass
        class D(C1, C2, B): pass
        class C:
            def meth1(self): pass
            def meth2(self, arg): pass
            def meth3(self, a1, a2): pass

        # decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        # decorators: decorator+
        # decorated: decorators (classdef | funcdef)
        def class_decorator(x): return x
        @class_decorator
        class G: pass

    def testDictcomps(self):
        # dictorsetmaker: ( (test ':' test (comp_for |
        #                                   (',' test ':' test)* [','])) |
        #                   (test (comp_for | (',' test)* [','])) )
        nums = [1, 2, 3]
        self.assertEqual({i:i+1 for i in nums}, {1: 2, 2: 3, 3: 4})

    def testListcomps(self):
        # list comprehension tests
        nums = [1, 2, 3, 4, 5]
        strs = ["Apple", "Banana", "Coconut"]
        spcs = ["  Apple", " Banana ", "Coco  nut  "]

        self.assertEqual([s.strip() for s in spcs], ['Apple', 'Banana', 'Coco  nut'])
        self.assertEqual([3 * x for x in nums], [3, 6, 9, 12, 15])
        self.assertEqual([x for x in nums if x > 2], [3, 4, 5])
        self.assertEqual([(i, s) for i in nums for s in strs],
                         [(1, 'Apple'), (1, 'Banana'), (1, 'Coconut'),
                          (2, 'Apple'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Apple'), (3, 'Banana'), (3, 'Coconut'),
                          (4, 'Apple'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Apple'), (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(i, s) for i in nums for s in [f for f in strs if "n" in f]],
                         [(1, 'Banana'), (1, 'Coconut'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Banana'), (3, 'Coconut'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(lambda a:[a**i for i in range(a+1)])(j) for j in range(5)],
                         [[1], [1, 1], [1, 2, 4], [1, 3, 9, 27], [1, 4, 16, 64, 256]])

        def test_in_func(l):
            return [0 < x < 3 for x in l if x > 2]

        self.assertEqual(test_in_func(nums), [False, False, False])

        def test_nested_front():
            self.assertEqual([[y for y in [x, x + 1]] for x in [1,3,5]],
                             [[1, 2], [3, 4], [5, 6]])

        test_nested_front()

        check_syntax_error(self, "[i, s for i in nums for s in strs]")
        check_syntax_error(self, "[x if y]")

        suppliers = [
          (1, "Boeing"),
          (2, "Ford"),
          (3, "Macdonalds")
        ]

        parts = [
          (10, "Airliner"),
          (20, "Engine"),
          (30, "Cheeseburger")
        ]

        suppart = [
          (1, 10), (1, 20), (2, 20), (3, 30)
        ]

        x = [
          (sname, pname)
            for (sno, sname) in suppliers
              for (pno, pname) in parts
                for (sp_sno, sp_pno) in suppart
                  if sno == sp_sno and pno == sp_pno
        ]

        self.assertEqual(x, [('Boeing', 'Airliner'), ('Boeing', 'Engine'), ('Ford', 'Engine'),
                             ('Macdonalds', 'Cheeseburger')])

    def testGenexps(self):
        # generator expression tests
        g = ([x for x in range(10)] for x in range(1))
        self.assertEqual(next(g), [x for x in range(10)])
        try:
            next(g)
            self.fail('should produce StopIteration exception')
        except StopIteration:
            pass

        a = 1
        try:
            g = (a for d in a)
            next(g)
            self.fail('should produce TypeError')
        except TypeError:
            pass

        self.assertEqual(list((x, y) for x in 'abcd' for y in 'abcd'), [(x, y) for x in 'abcd' for y in 'abcd'])
        self.assertEqual(list((x, y) for x in 'ab' for y in 'xy'), [(x, y) for x in 'ab' for y in 'xy'])

        a = [x for x in range(10)]
        b = (x for x in (y for y in a))
        self.assertEqual(sum(b), sum([x for x in range(10)]))

        self.assertEqual(sum(x**2 for x in range(10)), sum([x**2 for x in range(10)]))
        self.assertEqual(sum(x*x for x in range(10) if x%2), sum([x*x for x in range(10) if x%2]))
        self.assertEqual(sum(x for x in (y for y in range(10))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10)))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in [y for y in (z for z in range(10))]), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True)) if True), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True) if False) if True), 0)
        check_syntax_error(self, "foo(x for x in range(10), 100)")
        check_syntax_error(self, "foo(100, x for x in range(10))")

    def testComprehensionSpecials(self):
        # test for outmost iterable precomputation
        x = 10; g = (i for i in range(x)); x = 5
        self.assertEqual(len(list(g)), 10)

        # This should hold, since we're only precomputing outmost iterable.
        x = 10; t = False; g = ((i,j) for i in range(x) if t for j in range(x))
        x = 5; t = True;
        self.assertEqual([(i,j) for i in range(10) for j in range(5)], list(g))

        # Grammar allows multiple adjacent 'if's in listcomps and genexps,
        # even though it's silly. Make sure it works (ifelse broke this.)
        self.assertEqual([ x for x in range(10) if x % 2 if x % 3 ], [1, 5, 7])
        self.assertEqual(list(x for x in range(10) if x % 2 if x % 3), [1, 5, 7])

        # verify unpacking single element tuples in listcomp/genexp.
        self.assertEqual([x for x, in [(4,), (5,), (6,)]], [4, 5, 6])
        self.assertEqual(list(x for x, in [(7,), (8,), (9,)]), [7, 8, 9])

    def test_with_statement(self):
        class manager(object):
            def __enter__(self):
                return (1, 2)
            def __exit__(self, *args):
                pass

        with manager():
            pass
        with manager() as x:
            pass
        with manager() as (x, y):
            pass
        with manager(), manager():
            pass
        with manager() as x, manager() as y:
            pass
        with manager() as x, manager():
            pass

    def testIfElseExpr(self):
        # Test ifelse expressions in various cases
        def _checkeval(msg, ret):
            "helper to check that evaluation of expressions is done correctly"
            print(x)
            return ret

        # the next line is not allowed anymore
        #self.assertEqual([ x() for x in lambda: True, lambda: False if x() ], [True])
        self.assertEqual([ x() for x in (lambda: True, lambda: False) if x() ], [True])
        self.assertEqual([ x(False) for x in (lambda x: False if x else True, lambda x: True if x else False) if x(False) ], [True])
        self.assertEqual((5 if 1 else _checkeval("check 1", 0)), 5)
        self.assertEqual((_checkeval("check 2", 0) if 0 else 5), 5)
        self.assertEqual((5 and 6 if 0 else 1), 1)
        self.assertEqual(((5 and 6) if 0 else 1), 1)
        self.assertEqual((5 and (6 if 1 else 1)), 6)
        self.assertEqual((0 or _checkeval("check 3", 2) if 0 else 3), 3)
        self.assertEqual((1 or _checkeval("check 4", 2) if 1 else _checkeval("check 5", 3)), 1)
        self.assertEqual((0 or 5 if 1 else _checkeval("check 6", 3)), 5)
        self.assertEqual((not 5 if 1 else 1), False)
        self.assertEqual((not 5 if 0 else 1), 1)
        self.assertEqual((6 + 1 if 1 else 2), 7)
        self.assertEqual((6 - 1 if 1 else 2), 5)
        self.assertEqual((6 * 2 if 1 else 4), 12)
        self.assertEqual((6 / 2 if 1 else 3), 3)
        self.assertEqual((6 < 4 if 0 else 2), 2)

    def testStringLiterals(self):
        x = ''; y = ""; self.assert_(len(x) == 0 and x == y)
        x = '\''; y = "'"; self.assert_(len(x) == 1 and x == y and ord(x) == 39)
        x = '"'; y = "\""; self.assert_(len(x) == 1 and x == y and ord(x) == 34)
        x = "doesn't \"shrink\" does it"
        y = 'doesn\'t "shrink" does it'
        self.assert_(len(x) == 24 and x == y)
        x = "does \"shrink\" doesn't it"
        y = 'does "shrink" doesn\'t it'
        self.assert_(len(x) == 24 and x == y)
        x = """
The "quick"
brown fox
jumps over
the 'lazy' dog.
"""
        y = '\nThe "quick"\nbrown fox\njumps over\nthe \'lazy\' dog.\n'
        self.assertEquals(x, y)
        y = '''
The "quick"
brown fox
jumps over
the 'lazy' dog.
'''
        self.assertEquals(x, y)
        y = "\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the 'lazy' dog.\n\
"
        self.assertEquals(x, y)
        y = '\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the \'lazy\' dog.\n\
'
        self.assertEquals(x, y)


def test_main():
    run_unittest(TokenTests, GrammarTests)

if __name__ == '__main__':
    test_main()
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\python3-grammar.py\n# ==============================\n\n# Python test set -- part 1, grammar.
# This just tests whether the parser accepts them all.

# NOTE: When you run this test as a script from the command line, you
# get warnings about certain hex/oct constants.  Since those are
# issued by the parser, you can't suppress them by adding a
# filterwarnings() call to this module.  Therefore, to shut up the
# regression test, the filterwarnings() call has been added to
# regrtest.py.

from test.support import run_unittest, check_syntax_error
import unittest
import sys
# testing import *
from sys import *

class TokenTests(unittest.TestCase):

    def testBackslash(self):
        # Backslash means line continuation:
        x = 1 \
        + 1
        self.assertEquals(x, 2, 'backslash for line continuation')

        # Backslash does not means continuation in comments :\
        x = 0
        self.assertEquals(x, 0, 'backslash ending comment')

    def testPlainIntegers(self):
        self.assertEquals(type(000), type(0))
        self.assertEquals(0xff, 255)
        self.assertEquals(0o377, 255)
        self.assertEquals(2147483647, 0o17777777777)
        self.assertEquals(0b1001, 9)
        # "0x" is not a valid literal
        self.assertRaises(SyntaxError, eval, "0x")
        from sys import maxsize
        if maxsize == 2147483647:
            self.assertEquals(-2147483647-1, -0o20000000000)
            # XXX -2147483648
            self.assert_(0o37777777777 > 0)
            self.assert_(0xffffffff > 0)
            self.assert_(0b1111111111111111111111111111111 > 0)
            for s in ('2147483648', '0o40000000000', '0x100000000',
                      '0b10000000000000000000000000000000'):
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        elif maxsize == 9223372036854775807:
            self.assertEquals(-9223372036854775807-1, -0o1000000000000000000000)
            self.assert_(0o1777777777777777777777 > 0)
            self.assert_(0xffffffffffffffff > 0)
            self.assert_(0b11111111111111111111111111111111111111111111111111111111111111 > 0)
            for s in '9223372036854775808', '0o2000000000000000000000', \
                     '0x10000000000000000', \
                     '0b100000000000000000000000000000000000000000000000000000000000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        else:
            self.fail('Weird maxsize value %r' % maxsize)

    def testLongIntegers(self):
        x = 0
        x = 0xffffffffffffffff
        x = 0Xffffffffffffffff
        x = 0o77777777777777777
        x = 0O77777777777777777
        x = 123456789012345678901234567890
        x = 0b100000000000000000000000000000000000000000000000000000000000000000000
        x = 0B111111111111111111111111111111111111111111111111111111111111111111111

    def testUnderscoresInNumbers(self):
        # Integers
        x = 1_0
        x = 123_456_7_89
        x = 0xabc_123_4_5
        x = 0X_abc_123
        x = 0B11_01
        x = 0b_11_01
        x = 0o45_67
        x = 0O_45_67

        # Floats
        x = 3_1.4
        x = 03_1.4
        x = 3_1.
        x = .3_1
        x = 3.1_4
        x = 0_3.1_4
        x = 3e1_4
        x = 3_1e+4_1
        x = 3_1E-4_1

    def testFloats(self):
        x = 3.14
        x = 314.
        x = 0.314
        # XXX x = 000.314
        x = .314
        x = 3e14
        x = 3E14
        x = 3e-14
        x = 3e+14
        x = 3.e14
        x = .3e14
        x = 3.1e4

    def testEllipsis(self):
        x = ...
        self.assert_(x is Ellipsis)
        self.assertRaises(SyntaxError, eval, ".. .")

class GrammarTests(unittest.TestCase):

    # single_input: NEWLINE | simple_stmt | compound_stmt NEWLINE
    # XXX can't test in a script -- this rule is only used when interactive

    # file_input: (NEWLINE | stmt)* ENDMARKER
    # Being tested as this very moment this very module

    # expr_input: testlist NEWLINE
    # XXX Hard to test -- used only in calls to input()

    def testEvalInput(self):
        # testlist ENDMARKER
        x = eval('1, 0 or 1')

    def testFuncdef(self):
        ### [decorators] 'def' NAME parameters ['->' test] ':' suite
        ### decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        ### decorators: decorator+
        ### parameters: '(' [typedargslist] ')'
        ### typedargslist: ((tfpdef ['=' test] ',')*
        ###                ('*' [tfpdef] (',' tfpdef ['=' test])* [',' '**' tfpdef] | '**' tfpdef)
        ###                | tfpdef ['=' test] (',' tfpdef ['=' test])* [','])
        ### tfpdef: NAME [':' test]
        ### varargslist: ((vfpdef ['=' test] ',')*
        ###              ('*' [vfpdef] (',' vfpdef ['=' test])*  [',' '**' vfpdef] | '**' vfpdef)
        ###              | vfpdef ['=' test] (',' vfpdef ['=' test])* [','])
        ### vfpdef: NAME
        def f1(): pass
        f1()
        f1(*())
        f1(*(), **{})
        def f2(one_argument): pass
        def f3(two, arguments): pass
        self.assertEquals(f2.__code__.co_varnames, ('one_argument',))
        self.assertEquals(f3.__code__.co_varnames, ('two', 'arguments'))
        def a1(one_arg,): pass
        def a2(two, args,): pass
        def v0(*rest): pass
        def v1(a, *rest): pass
        def v2(a, b, *rest): pass

        f1()
        f2(1)
        f2(1,)
        f3(1, 2)
        f3(1, 2,)
        v0()
        v0(1)
        v0(1,)
        v0(1,2)
        v0(1,2,3,4,5,6,7,8,9,0)
        v1(1)
        v1(1,)
        v1(1,2)
        v1(1,2,3)
        v1(1,2,3,4,5,6,7,8,9,0)
        v2(1,2)
        v2(1,2,3)
        v2(1,2,3,4)
        v2(1,2,3,4,5,6,7,8,9,0)

        def d01(a=1): pass
        d01()
        d01(1)
        d01(*(1,))
        d01(**{'a':2})
        def d11(a, b=1): pass
        d11(1)
        d11(1, 2)
        d11(1, **{'b':2})
        def d21(a, b, c=1): pass
        d21(1, 2)
        d21(1, 2, 3)
        d21(*(1, 2, 3))
        d21(1, *(2, 3))
        d21(1, 2, *(3,))
        d21(1, 2, **{'c':3})
        def d02(a=1, b=2): pass
        d02()
        d02(1)
        d02(1, 2)
        d02(*(1, 2))
        d02(1, *(2,))
        d02(1, **{'b':2})
        d02(**{'a': 1, 'b': 2})
        def d12(a, b=1, c=2): pass
        d12(1)
        d12(1, 2)
        d12(1, 2, 3)
        def d22(a, b, c=1, d=2): pass
        d22(1, 2)
        d22(1, 2, 3)
        d22(1, 2, 3, 4)
        def d01v(a=1, *rest): pass
        d01v()
        d01v(1)
        d01v(1, 2)
        d01v(*(1, 2, 3, 4))
        d01v(*(1,))
        d01v(**{'a':2})
        def d11v(a, b=1, *rest): pass
        d11v(1)
        d11v(1, 2)
        d11v(1, 2, 3)
        def d21v(a, b, c=1, *rest): pass
        d21v(1, 2)
        d21v(1, 2, 3)
        d21v(1, 2, 3, 4)
        d21v(*(1, 2, 3, 4))
        d21v(1, 2, **{'c': 3})
        def d02v(a=1, b=2, *rest): pass
        d02v()
        d02v(1)
        d02v(1, 2)
        d02v(1, 2, 3)
        d02v(1, *(2, 3, 4))
        d02v(**{'a': 1, 'b': 2})
        def d12v(a, b=1, c=2, *rest): pass
        d12v(1)
        d12v(1, 2)
        d12v(1, 2, 3)
        d12v(1, 2, 3, 4)
        d12v(*(1, 2, 3, 4))
        d12v(1, 2, *(3, 4, 5))
        d12v(1, *(2,), **{'c': 3})
        def d22v(a, b, c=1, d=2, *rest): pass
        d22v(1, 2)
        d22v(1, 2, 3)
        d22v(1, 2, 3, 4)
        d22v(1, 2, 3, 4, 5)
        d22v(*(1, 2, 3, 4))
        d22v(1, 2, *(3, 4, 5))
        d22v(1, *(2, 3), **{'d': 4})

        # keyword argument type tests
        try:
            str('x', **{b'foo':1 })
        except TypeError:
            pass
        else:
            self.fail('Bytes should not work as keyword argument names')
        # keyword only argument tests
        def pos0key1(*, key): return key
        pos0key1(key=100)
        def pos2key2(p1, p2, *, k1, k2=100): return p1,p2,k1,k2
        pos2key2(1, 2, k1=100)
        pos2key2(1, 2, k1=100, k2=200)
        pos2key2(1, 2, k2=100, k1=200)
        def pos2key2dict(p1, p2, *, k1=100, k2, **kwarg): return p1,p2,k1,k2,kwarg
        pos2key2dict(1,2,k2=100,tokwarg1=100,tokwarg2=200)
        pos2key2dict(1,2,tokwarg1=100,tokwarg2=200, k2=100)

        # keyword arguments after *arglist
        def f(*args, **kwargs):
            return args, kwargs
        self.assertEquals(f(1, x=2, *[3, 4], y=5), ((1, 3, 4),
                                                    {'x':2, 'y':5}))
        self.assertRaises(SyntaxError, eval, "f(1, *(2,3), 4)")
        self.assertRaises(SyntaxError, eval, "f(1, x=2, *(3,4), x=5)")

        # argument annotation tests
        def f(x) -> list: pass
        self.assertEquals(f.__annotations__, {'return': list})
        def f(x:int): pass
        self.assertEquals(f.__annotations__, {'x': int})
        def f(*x:str): pass
        self.assertEquals(f.__annotations__, {'x': str})
        def f(**x:float): pass
        self.assertEquals(f.__annotations__, {'x': float})
        def f(x, y:1+2): pass
        self.assertEquals(f.__annotations__, {'y': 3})
        def f(a, b:1, c:2, d): pass
        self.assertEquals(f.__annotations__, {'b': 1, 'c': 2})
        def f(a, b:1, c:2, d, e:3=4, f=5, *g:6): pass
        self.assertEquals(f.__annotations__,
                          {'b': 1, 'c': 2, 'e': 3, 'g': 6})
        def f(a, b:1, c:2, d, e:3=4, f=5, *g:6, h:7, i=8, j:9=10,
              **k:11) -> 12: pass
        self.assertEquals(f.__annotations__,
                          {'b': 1, 'c': 2, 'e': 3, 'g': 6, 'h': 7, 'j': 9,
                           'k': 11, 'return': 12})
        # Check for SF Bug #1697248 - mixing decorators and a return annotation
        def null(x): return x
        @null
        def f(x) -> list: pass
        self.assertEquals(f.__annotations__, {'return': list})

        # test closures with a variety of oparg's
        closure = 1
        def f(): return closure
        def f(x=1): return closure
        def f(*, k=1): return closure
        def f() -> int: return closure

        # Check ast errors in *args and *kwargs
        check_syntax_error(self, "f(*g(1=2))")
        check_syntax_error(self, "f(**g(1=2))")

    def testLambdef(self):
        ### lambdef: 'lambda' [varargslist] ':' test
        l1 = lambda : 0
        self.assertEquals(l1(), 0)
        l2 = lambda : a[d] # XXX just testing the expression
        l3 = lambda : [2 < x for x in [-1, 3, 0]]
        self.assertEquals(l3(), [0, 1, 0])
        l4 = lambda x = lambda y = lambda z=1 : z : y() : x()
        self.assertEquals(l4(), 1)
        l5 = lambda x, y, z=2: x + y + z
        self.assertEquals(l5(1, 2), 5)
        self.assertEquals(l5(1, 2, 3), 6)
        check_syntax_error(self, "lambda x: x = 2")
        check_syntax_error(self, "lambda (None,): None")
        l6 = lambda x, y, *, k=20: x+y+k
        self.assertEquals(l6(1,2), 1+2+20)
        self.assertEquals(l6(1,2,k=10), 1+2+10)


    ### stmt: simple_stmt | compound_stmt
    # Tested below

    def testSimpleStmt(self):
        ### simple_stmt: small_stmt (';' small_stmt)* [';']
        x = 1; pass; del x
        def foo():
            # verify statements that end with semi-colons
            x = 1; pass; del x;
        foo()

    ### small_stmt: expr_stmt | pass_stmt | del_stmt | flow_stmt | import_stmt | global_stmt | access_stmt
    # Tested below

    def testExprStmt(self):
        # (exprlist '=')* exprlist
        1
        1, 2, 3
        x = 1
        x = 1, 2, 3
        x = y = z = 1, 2, 3
        x, y, z = 1, 2, 3
        abc = a, b, c = x, y, z = xyz = 1, 2, (3, 4)

        check_syntax_error(self, "x + 1 = 1")
        check_syntax_error(self, "a + 1 = b + 2")

    def testDelStmt(self):
        # 'del' exprlist
        abc = [1,2,3]
        x, y, z = abc
        xyz = x, y, z

        del abc
        del x, y, (z, xyz)

    def testPassStmt(self):
        # 'pass'
        pass

    # flow_stmt: break_stmt | continue_stmt | return_stmt | raise_stmt
    # Tested below

    def testBreakStmt(self):
        # 'break'
        while 1: break

    def testContinueStmt(self):
        # 'continue'
        i = 1
        while i: i = 0; continue

        msg = ""
        while not msg:
            msg = "ok"
            try:
                continue
                msg = "continue failed to continue inside try"
            except:
                msg = "continue inside try called except block"
        if msg != "ok":
            self.fail(msg)

        msg = ""
        while not msg:
            msg = "finally block not called"
            try:
                continue
            finally:
                msg = "ok"
        if msg != "ok":
            self.fail(msg)

    def test_break_continue_loop(self):
        # This test warrants an explanation. It is a test specifically for SF bugs
        # #463359 and #462937. The bug is that a 'break' statement executed or
        # exception raised inside a try/except inside a loop, *after* a continue
        # statement has been executed in that loop, will cause the wrong number of
        # arguments to be popped off the stack and the instruction pointer reset to
        # a very small number (usually 0.) Because of this, the following test
        # *must* written as a function, and the tracking vars *must* be function
        # arguments with default values. Otherwise, the test will loop and loop.

        def test_inner(extra_burning_oil = 1, count=0):
            big_hippo = 2
            while big_hippo:
                count += 1
                try:
                    if extra_burning_oil and big_hippo == 1:
                        extra_burning_oil -= 1
                        break
                    big_hippo -= 1
                    continue
                except:
                    raise
            if count > 2 or big_hippo != 1:
                self.fail("continue then break in try/except in loop broken!")
        test_inner()

    def testReturn(self):
        # 'return' [testlist]
        def g1(): return
        def g2(): return 1
        g1()
        x = g2()
        check_syntax_error(self, "class foo:return 1")

    def testYield(self):
        check_syntax_error(self, "class foo:yield 1")

    def testRaise(self):
        # 'raise' test [',' test]
        try: raise RuntimeError('just testing')
        except RuntimeError: pass
        try: raise KeyboardInterrupt
        except KeyboardInterrupt: pass

    def testImport(self):
        # 'import' dotted_as_names
        import sys
        import time, sys
        # 'from' dotted_name 'import' ('*' | '(' import_as_names ')' | import_as_names)
        from time import time
        from time import (time)
        # not testable inside a function, but already done at top of the module
        # from sys import *
        from sys import path, argv
        from sys import (path, argv)
        from sys import (path, argv,)

    def testGlobal(self):
        # 'global' NAME (',' NAME)*
        global a
        global a, b
        global one, two, three, four, five, six, seven, eight, nine, ten

    def testNonlocal(self):
        # 'nonlocal' NAME (',' NAME)*
        x = 0
        y = 0
        def f():
            nonlocal x
            nonlocal x, y

    def testAssert(self):
        # assert_stmt: 'assert' test [',' test]
        assert 1
        assert 1, 1
        assert lambda x:x
        assert 1, lambda x:x+1
        try:
            assert 0, "msg"
        except AssertionError as e:
            self.assertEquals(e.args[0], "msg")
        else:
            if __debug__:
                self.fail("AssertionError not raised by assert 0")

    ### compound_stmt: if_stmt | while_stmt | for_stmt | try_stmt | funcdef | classdef
    # Tested below

    def testIf(self):
        # 'if' test ':' suite ('elif' test ':' suite)* ['else' ':' suite]
        if 1: pass
        if 1: pass
        else: pass
        if 0: pass
        elif 0: pass
        if 0: pass
        elif 0: pass
        elif 0: pass
        elif 0: pass
        else: pass

    def testWhile(self):
        # 'while' test ':' suite ['else' ':' suite]
        while 0: pass
        while 0: pass
        else: pass

        # Issue1920: "while 0" is optimized away,
        # ensure that the "else" clause is still present.
        x = 0
        while 0:
            x = 1
        else:
            x = 2
        self.assertEquals(x, 2)

    def testFor(self):
        # 'for' exprlist 'in' exprlist ':' suite ['else' ':' suite]
        for i in 1, 2, 3: pass
        for i, j, k in (): pass
        else: pass
        class Squares:
            def __init__(self, max):
                self.max = max
                self.sofar = []
            def __len__(self): return len(self.sofar)
            def __getitem__(self, i):
                if not 0 <= i < self.max: raise IndexError
                n = len(self.sofar)
                while n <= i:
                    self.sofar.append(n*n)
                    n = n+1
                return self.sofar[i]
        n = 0
        for x in Squares(10): n = n+x
        if n != 285:
            self.fail('for over growing sequence')

        result = []
        for x, in [(1,), (2,), (3,)]:
            result.append(x)
        self.assertEqual(result, [1, 2, 3])

    def testTry(self):
        ### try_stmt: 'try' ':' suite (except_clause ':' suite)+ ['else' ':' suite]
        ###         | 'try' ':' suite 'finally' ':' suite
        ### except_clause: 'except' [expr ['as' expr]]
        try:
            1/0
        except ZeroDivisionError:
            pass
        else:
            pass
        try: 1/0
        except EOFError: pass
        except TypeError as msg: pass
        except RuntimeError as msg: pass
        except: pass
        else: pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError): pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError) as msg: pass
        try: pass
        finally: pass

    def testSuite(self):
        # simple_stmt | NEWLINE INDENT NEWLINE* (stmt NEWLINE*)+ DEDENT
        if 1: pass
        if 1:
            pass
        if 1:
            #
            #
            #
            pass
            pass
            #
            pass
            #

    def testTest(self):
        ### and_test ('or' and_test)*
        ### and_test: not_test ('and' not_test)*
        ### not_test: 'not' not_test | comparison
        if not 1: pass
        if 1 and 1: pass
        if 1 or 1: pass
        if not not not 1: pass
        if not 1 and 1 and 1: pass
        if 1 and 1 or 1 and 1 and 1 or not 1 and 1: pass

    def testComparison(self):
        ### comparison: expr (comp_op expr)*
        ### comp_op: '<'|'>'|'=='|'>='|'<='|'!='|'in'|'not' 'in'|'is'|'is' 'not'
        if 1: pass
        x = (1 == 1)
        if 1 == 1: pass
        if 1 != 1: pass
        if 1 < 1: pass
        if 1 > 1: pass
        if 1 <= 1: pass
        if 1 >= 1: pass
        if 1 is 1: pass
        if 1 is not 1: pass
        if 1 in (): pass
        if 1 not in (): pass
        if 1 < 1 > 1 == 1 >= 1 <= 1 != 1 in 1 not in 1 is 1 is not 1: pass

    def testBinaryMaskOps(self):
        x = 1 & 1
        x = 1 ^ 1
        x = 1 | 1

    def testShiftOps(self):
        x = 1 << 1
        x = 1 >> 1
        x = 1 << 1 >> 1

    def testAdditiveOps(self):
        x = 1
        x = 1 + 1
        x = 1 - 1 - 1
        x = 1 - 1 + 1 - 1 + 1

    def testMultiplicativeOps(self):
        x = 1 * 1
        x = 1 / 1
        x = 1 % 1
        x = 1 / 1 * 1 % 1

    def testUnaryOps(self):
        x = +1
        x = -1
        x = ~1
        x = ~1 ^ 1 & 1 | 1 & 1 ^ -1
        x = -1*1/1 + 1*1 - ---1*1

    def testSelectors(self):
        ### trailer: '(' [testlist] ')' | '[' subscript ']' | '.' NAME
        ### subscript: expr | [expr] ':' [expr]

        import sys, time
        c = sys.path[0]
        x = time.time()
        x = sys.modules['time'].time()
        a = '01234'
        c = a[0]
        c = a[-1]
        s = a[0:5]
        s = a[:5]
        s = a[0:]
        s = a[:]
        s = a[-5:]
        s = a[:-1]
        s = a[-4:-3]
        # A rough test of SF bug 1333982.  http://python.org/sf/1333982
        # The testing here is fairly incomplete.
        # Test cases should include: commas with 1 and 2 colons
        d = {}
        d[1] = 1
        d[1,] = 2
        d[1,2] = 3
        d[1,2,3] = 4
        L = list(d)
        L.sort(key=lambda x: x if isinstance(x, tuple) else ())
        self.assertEquals(str(L), '[1, (1,), (1, 2), (1, 2, 3)]')

    def testAtoms(self):
        ### atom: '(' [testlist] ')' | '[' [testlist] ']' | '{' [dictsetmaker] '}' | NAME | NUMBER | STRING
        ### dictsetmaker: (test ':' test (',' test ':' test)* [',']) | (test (',' test)* [','])

        x = (1)
        x = (1 or 2 or 3)
        x = (1 or 2 or 3, 2, 3)

        x = []
        x = [1]
        x = [1 or 2 or 3]
        x = [1 or 2 or 3, 2, 3]
        x = []

        x = {}
        x = {'one': 1}
        x = {'one': 1,}
        x = {'one' or 'two': 1 or 2}
        x = {'one': 1, 'two': 2}
        x = {'one': 1, 'two': 2,}
        x = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}

        x = {'one'}
        x = {'one', 1,}
        x = {'one', 'two', 'three'}
        x = {2, 3, 4,}

        x = x
        x = 'x'
        x = 123

    ### exprlist: expr (',' expr)* [',']
    ### testlist: test (',' test)* [',']
    # These have been exercised enough above

    def testClassdef(self):
        # 'class' NAME ['(' [testlist] ')'] ':' suite
        class B: pass
        class B2(): pass
        class C1(B): pass
        class C2(B): pass
        class D(C1, C2, B): pass
        class C:
            def meth1(self): pass
            def meth2(self, arg): pass
            def meth3(self, a1, a2): pass

        # decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        # decorators: decorator+
        # decorated: decorators (classdef | funcdef)
        def class_decorator(x): return x
        @class_decorator
        class G: pass

    def testDictcomps(self):
        # dictorsetmaker: ( (test ':' test (comp_for |
        #                                   (',' test ':' test)* [','])) |
        #                   (test (comp_for | (',' test)* [','])) )
        nums = [1, 2, 3]
        self.assertEqual({i:i+1 for i in nums}, {1: 2, 2: 3, 3: 4})

    def testListcomps(self):
        # list comprehension tests
        nums = [1, 2, 3, 4, 5]
        strs = ["Apple", "Banana", "Coconut"]
        spcs = ["  Apple", " Banana ", "Coco  nut  "]

        self.assertEqual([s.strip() for s in spcs], ['Apple', 'Banana', 'Coco  nut'])
        self.assertEqual([3 * x for x in nums], [3, 6, 9, 12, 15])
        self.assertEqual([x for x in nums if x > 2], [3, 4, 5])
        self.assertEqual([(i, s) for i in nums for s in strs],
                         [(1, 'Apple'), (1, 'Banana'), (1, 'Coconut'),
                          (2, 'Apple'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Apple'), (3, 'Banana'), (3, 'Coconut'),
                          (4, 'Apple'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Apple'), (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(i, s) for i in nums for s in [f for f in strs if "n" in f]],
                         [(1, 'Banana'), (1, 'Coconut'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Banana'), (3, 'Coconut'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(lambda a:[a**i for i in range(a+1)])(j) for j in range(5)],
                         [[1], [1, 1], [1, 2, 4], [1, 3, 9, 27], [1, 4, 16, 64, 256]])

        def test_in_func(l):
            return [0 < x < 3 for x in l if x > 2]

        self.assertEqual(test_in_func(nums), [False, False, False])

        def test_nested_front():
            self.assertEqual([[y for y in [x, x + 1]] for x in [1,3,5]],
                             [[1, 2], [3, 4], [5, 6]])

        test_nested_front()

        check_syntax_error(self, "[i, s for i in nums for s in strs]")
        check_syntax_error(self, "[x if y]")

        suppliers = [
          (1, "Boeing"),
          (2, "Ford"),
          (3, "Macdonalds")
        ]

        parts = [
          (10, "Airliner"),
          (20, "Engine"),
          (30, "Cheeseburger")
        ]

        suppart = [
          (1, 10), (1, 20), (2, 20), (3, 30)
        ]

        x = [
          (sname, pname)
            for (sno, sname) in suppliers
              for (pno, pname) in parts
                for (sp_sno, sp_pno) in suppart
                  if sno == sp_sno and pno == sp_pno
        ]

        self.assertEqual(x, [('Boeing', 'Airliner'), ('Boeing', 'Engine'), ('Ford', 'Engine'),
                             ('Macdonalds', 'Cheeseburger')])

    def testGenexps(self):
        # generator expression tests
        g = ([x for x in range(10)] for x in range(1))
        self.assertEqual(next(g), [x for x in range(10)])
        try:
            next(g)
            self.fail('should produce StopIteration exception')
        except StopIteration:
            pass

        a = 1
        try:
            g = (a for d in a)
            next(g)
            self.fail('should produce TypeError')
        except TypeError:
            pass

        self.assertEqual(list((x, y) for x in 'abcd' for y in 'abcd'), [(x, y) for x in 'abcd' for y in 'abcd'])
        self.assertEqual(list((x, y) for x in 'ab' for y in 'xy'), [(x, y) for x in 'ab' for y in 'xy'])

        a = [x for x in range(10)]
        b = (x for x in (y for y in a))
        self.assertEqual(sum(b), sum([x for x in range(10)]))

        self.assertEqual(sum(x**2 for x in range(10)), sum([x**2 for x in range(10)]))
        self.assertEqual(sum(x*x for x in range(10) if x%2), sum([x*x for x in range(10) if x%2]))
        self.assertEqual(sum(x for x in (y for y in range(10))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10)))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in [y for y in (z for z in range(10))]), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True)) if True), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True) if False) if True), 0)
        check_syntax_error(self, "foo(x for x in range(10), 100)")
        check_syntax_error(self, "foo(100, x for x in range(10))")

    def testComprehensionSpecials(self):
        # test for outmost iterable precomputation
        x = 10; g = (i for i in range(x)); x = 5
        self.assertEqual(len(list(g)), 10)

        # This should hold, since we're only precomputing outmost iterable.
        x = 10; t = False; g = ((i,j) for i in range(x) if t for j in range(x))
        x = 5; t = True;
        self.assertEqual([(i,j) for i in range(10) for j in range(5)], list(g))

        # Grammar allows multiple adjacent 'if's in listcomps and genexps,
        # even though it's silly. Make sure it works (ifelse broke this.)
        self.assertEqual([ x for x in range(10) if x % 2 if x % 3 ], [1, 5, 7])
        self.assertEqual(list(x for x in range(10) if x % 2 if x % 3), [1, 5, 7])

        # verify unpacking single element tuples in listcomp/genexp.
        self.assertEqual([x for x, in [(4,), (5,), (6,)]], [4, 5, 6])
        self.assertEqual(list(x for x, in [(7,), (8,), (9,)]), [7, 8, 9])

    def test_with_statement(self):
        class manager(object):
            def __enter__(self):
                return (1, 2)
            def __exit__(self, *args):
                pass

        with manager():
            pass
        with manager() as x:
            pass
        with manager() as (x, y):
            pass
        with manager(), manager():
            pass
        with manager() as x, manager() as y:
            pass
        with manager() as x, manager():
            pass

    def testIfElseExpr(self):
        # Test ifelse expressions in various cases
        def _checkeval(msg, ret):
            "helper to check that evaluation of expressions is done correctly"
            print(x)
            return ret

        # the next line is not allowed anymore
        #self.assertEqual([ x() for x in lambda: True, lambda: False if x() ], [True])
        self.assertEqual([ x() for x in (lambda: True, lambda: False) if x() ], [True])
        self.assertEqual([ x(False) for x in (lambda x: False if x else True, lambda x: True if x else False) if x(False) ], [True])
        self.assertEqual((5 if 1 else _checkeval("check 1", 0)), 5)
        self.assertEqual((_checkeval("check 2", 0) if 0 else 5), 5)
        self.assertEqual((5 and 6 if 0 else 1), 1)
        self.assertEqual(((5 and 6) if 0 else 1), 1)
        self.assertEqual((5 and (6 if 1 else 1)), 6)
        self.assertEqual((0 or _checkeval("check 3", 2) if 0 else 3), 3)
        self.assertEqual((1 or _checkeval("check 4", 2) if 1 else _checkeval("check 5", 3)), 1)
        self.assertEqual((0 or 5 if 1 else _checkeval("check 6", 3)), 5)
        self.assertEqual((not 5 if 1 else 1), False)
        self.assertEqual((not 5 if 0 else 1), 1)
        self.assertEqual((6 + 1 if 1 else 2), 7)
        self.assertEqual((6 - 1 if 1 else 2), 5)
        self.assertEqual((6 * 2 if 1 else 4), 12)
        self.assertEqual((6 / 2 if 1 else 3), 3)
        self.assertEqual((6 < 4 if 0 else 2), 2)

    def testStringLiterals(self):
        x = ''; y = ""; self.assert_(len(x) == 0 and x == y)
        x = '\''; y = "'"; self.assert_(len(x) == 1 and x == y and ord(x) == 39)
        x = '"'; y = "\""; self.assert_(len(x) == 1 and x == y and ord(x) == 34)
        x = "doesn't \"shrink\" does it"
        y = 'doesn\'t "shrink" does it'
        self.assert_(len(x) == 24 and x == y)
        x = "does \"shrink\" doesn't it"
        y = 'does "shrink" doesn\'t it'
        self.assert_(len(x) == 24 and x == y)
        x = f"""
The "quick"
brown fo{ok()}x
jumps over
the 'lazy' dog.
"""
        y = '\nThe "quick"\nbrown fox\njumps over\nthe \'lazy\' dog.\n'
        self.assertEquals(x, y)
        y = '''
The "quick"
brown fox
jumps over
the 'lazy' dog.
'''
        self.assertEquals(x, y)
        y = "\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the 'lazy' dog.\n\
"
        self.assertEquals(x, y)
        y = '\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the \'lazy\' dog.\n\
'
        self.assertEquals(x, y)


def test_main():
    run_unittest(TokenTests, GrammarTests)

if __name__ == '__main__':
    test_main()
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\python3.8_grammar.py\n# ==============================\n\n# Python test set -- part 1, grammar.
# This just tests whether the parser accepts them all.

from test.support import check_syntax_error
import inspect
import unittest
import sys
# testing import *
from sys import *

# different import patterns to check that __annotations__ does not interfere
# with import machinery
import test.ann_module as ann_module
import typing
from collections import ChainMap
from test import ann_module2
import test

# These are shared with test_tokenize and other test modules.
#
# Note: since several test cases filter out floats by looking for "e" and ".",
# don't add hexadecimal literals that contain "e" or "E".
VALID_UNDERSCORE_LITERALS = [
    '0_0_0',
    '4_2',
    '1_0000_0000',
    '0b1001_0100',
    '0xffff_ffff',
    '0o5_7_7',
    '1_00_00.5',
    '1_00_00.5e5',
    '1_00_00e5_1',
    '1e1_0',
    '.1_4',
    '.1_4e1',
    '0b_0',
    '0x_f',
    '0o_5',
    '1_00_00j',
    '1_00_00.5j',
    '1_00_00e5_1j',
    '.1_4j',
    '(1_2.5+3_3j)',
    '(.5_6j)',
]
INVALID_UNDERSCORE_LITERALS = [
    # Trailing underscores:
    '0_',
    '42_',
    '1.4j_',
    '0x_',
    '0b1_',
    '0xf_',
    '0o5_',
    '0 if 1_Else 1',
    # Underscores in the base selector:
    '0_b0',
    '0_xf',
    '0_o5',
    # Old-style octal, still disallowed:
    '0_7',
    '09_99',
    # Multiple consecutive underscores:
    '4_______2',
    '0.1__4',
    '0.1__4j',
    '0b1001__0100',
    '0xffff__ffff',
    '0x___',
    '0o5__77',
    '1e1__0',
    '1e1__0j',
    # Underscore right before a dot:
    '1_.4',
    '1_.4j',
    # Underscore right after a dot:
    '1._4',
    '1._4j',
    '._5',
    '._5j',
    # Underscore right after a sign:
    '1.0e+_1',
    '1.0e+_1j',
    # Underscore right before j:
    '1.4_j',
    '1.4e5_j',
    # Underscore right before e:
    '1_e1',
    '1.4_e1',
    '1.4_e1j',
    # Underscore right after e:
    '1e_1',
    '1.4e_1',
    '1.4e_1j',
    # Complex cases with parens:
    '(1+1.5_j_)',
    '(1+1.5_j)',
]


class TokenTests(unittest.TestCase):

    def test_backslash(self):
        # Backslash means line continuation:
        x = 1 \
        + 1
        self.assertEqual(x, 2, 'backslash for line continuation')

        # Backslash does not means continuation in comments :\
        x = 0
        self.assertEqual(x, 0, 'backslash ending comment')

    def test_plain_integers(self):
        self.assertEqual(type(000), type(0))
        self.assertEqual(0xff, 255)
        self.assertEqual(0o377, 255)
        self.assertEqual(2147483647, 0o17777777777)
        self.assertEqual(0b1001, 9)
        # "0x" is not a valid literal
        self.assertRaises(SyntaxError, eval, "0x")
        from sys import maxsize
        if maxsize == 2147483647:
            self.assertEqual(-2147483647-1, -0o20000000000)
            # XXX -2147483648
            self.assertTrue(0o37777777777 > 0)
            self.assertTrue(0xffffffff > 0)
            self.assertTrue(0b1111111111111111111111111111111 > 0)
            for s in ('2147483648', '0o40000000000', '0x100000000',
                      '0b10000000000000000000000000000000'):
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        elif maxsize == 9223372036854775807:
            self.assertEqual(-9223372036854775807-1, -0o1000000000000000000000)
            self.assertTrue(0o1777777777777777777777 > 0)
            self.assertTrue(0xffffffffffffffff > 0)
            self.assertTrue(0b11111111111111111111111111111111111111111111111111111111111111 > 0)
            for s in '9223372036854775808', '0o2000000000000000000000', \
                     '0x10000000000000000', \
                     '0b100000000000000000000000000000000000000000000000000000000000000':
                try:
                    x = eval(s)
                except OverflowError:
                    self.fail("OverflowError on huge integer literal %r" % s)
        else:
            self.fail('Weird maxsize value %r' % maxsize)

    def test_long_integers(self):
        x = 0
        x = 0xffffffffffffffff
        x = 0Xffffffffffffffff
        x = 0o77777777777777777
        x = 0O77777777777777777
        x = 123456789012345678901234567890
        x = 0b100000000000000000000000000000000000000000000000000000000000000000000
        x = 0B111111111111111111111111111111111111111111111111111111111111111111111

    def test_floats(self):
        x = 3.14
        x = 314.
        x = 0.314
        # XXX x = 000.314
        x = .314
        x = 3e14
        x = 3E14
        x = 3e-14
        x = 3e+14
        x = 3.e14
        x = .3e14
        x = 3.1e4

    def test_float_exponent_tokenization(self):
        # See issue 21642.
        self.assertEqual(1 if 1else 0, 1)
        self.assertEqual(1 if 0else 0, 0)
        self.assertRaises(SyntaxError, eval, "0 if 1Else 0")

    def test_underscore_literals(self):
        for lit in VALID_UNDERSCORE_LITERALS:
            self.assertEqual(eval(lit), eval(lit.replace('_', '')))
        for lit in INVALID_UNDERSCORE_LITERALS:
            self.assertRaises(SyntaxError, eval, lit)
        # Sanity check: no literal begins with an underscore
        self.assertRaises(NameError, eval, "_0")

    def test_string_literals(self):
        x = ''; y = ""; self.assertTrue(len(x) == 0 and x == y)
        x = '\''; y = "'"; self.assertTrue(len(x) == 1 and x == y and ord(x) == 39)
        x = '"'; y = "\""; self.assertTrue(len(x) == 1 and x == y and ord(x) == 34)
        x = "doesn't \"shrink\" does it"
        y = 'doesn\'t "shrink" does it'
        self.assertTrue(len(x) == 24 and x == y)
        x = "does \"shrink\" doesn't it"
        y = 'does "shrink" doesn\'t it'
        self.assertTrue(len(x) == 24 and x == y)
        x = """
The "quick"
brown fox
jumps over
the 'lazy' dog.
"""
        y = '\nThe "quick"\nbrown fox\njumps over\nthe \'lazy\' dog.\n'
        self.assertEqual(x, y)
        y = '''
The "quick"
brown fox
jumps over
the 'lazy' dog.
'''
        self.assertEqual(x, y)
        y = "\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the 'lazy' dog.\n\
"
        self.assertEqual(x, y)
        y = '\n\
The \"quick\"\n\
brown fox\n\
jumps over\n\
the \'lazy\' dog.\n\
'
        self.assertEqual(x, y)

    def test_ellipsis(self):
        x = ...
        self.assertTrue(x is Ellipsis)
        self.assertRaises(SyntaxError, eval, ".. .")

    def test_eof_error(self):
        samples = ("def foo(", "\ndef foo(", "def foo(\n")
        for s in samples:
            with self.assertRaises(SyntaxError) as cm:
                compile(s, "<test>", "exec")
            self.assertIn("unexpected EOF", str(cm.exception))

# var_annot_global: int # a global annotated is necessary for test_var_annot

# custom namespace for testing __annotations__

class CNS:
    def __init__(self):
        self._dct = {}
    def __setitem__(self, item, value):
        self._dct[item.lower()] = value
    def __getitem__(self, item):
        return self._dct[item]


class GrammarTests(unittest.TestCase):

    check_syntax_error = check_syntax_error

    # single_input: NEWLINE | simple_stmt | compound_stmt NEWLINE
    # XXX can't test in a script -- this rule is only used when interactive

    # file_input: (NEWLINE | stmt)* ENDMARKER
    # Being tested as this very moment this very module

    # expr_input: testlist NEWLINE
    # XXX Hard to test -- used only in calls to input()

    def test_eval_input(self):
        # testlist ENDMARKER
        x = eval('1, 0 or 1')

    def test_var_annot_basics(self):
        # all these should be allowed
        var1: int = 5
        # var2: [int, str]
        my_lst = [42]
        def one():
            return 1
        # int.new_attr: int
        # [list][0]: type
        my_lst[one()-1]: int = 5
        self.assertEqual(my_lst, [5])

    def test_var_annot_syntax_errors(self):
        # parser pass
        check_syntax_error(self, "def f: int")
        check_syntax_error(self, "x: int: str")
        check_syntax_error(self, "def f():\n"
                                 "    nonlocal x: int\n")
        # AST pass
        check_syntax_error(self, "[x, 0]: int\n")
        check_syntax_error(self, "f(): int\n")
        check_syntax_error(self, "(x,): int")
        check_syntax_error(self, "def f():\n"
                                 "    (x, y): int = (1, 2)\n")
        # symtable pass
        check_syntax_error(self, "def f():\n"
                                 "    x: int\n"
                                 "    global x\n")
        check_syntax_error(self, "def f():\n"
                                 "    global x\n"
                                 "    x: int\n")

    def test_var_annot_basic_semantics(self):
        # execution order
        with self.assertRaises(ZeroDivisionError):
            no_name[does_not_exist]: no_name_again = 1/0
        with self.assertRaises(NameError):
            no_name[does_not_exist]: 1/0 = 0
        global var_annot_global

        # function semantics
        def f():
            st: str = "Hello"
            a.b: int = (1, 2)
            return st
        self.assertEqual(f.__annotations__, {})
        def f_OK():
            # x: 1/0
        f_OK()
        def fbad():
            # x: int
            print(x)
        with self.assertRaises(UnboundLocalError):
            fbad()
        def f2bad():
            # (no_such_global): int
            print(no_such_global)
        try:
            f2bad()
        except Exception as e:
            self.assertIs(type(e), NameError)

        # class semantics
        class C:
            # __foo: int
            s: str = "attr"
            z = 2
            def __init__(self, x):
                self.x: int = x
        self.assertEqual(C.__annotations__, {'_C__foo': int, 's': str})
        with self.assertRaises(NameError):
            class CBad:
                no_such_name_defined.attr: int = 0
        with self.assertRaises(NameError):
            class Cbad2(C):
                # x: int
                x.y: list = []

    def test_var_annot_metaclass_semantics(self):
        class CMeta(type):
            @classmethod
            def __prepare__(metacls, name, bases, **kwds):
                return {'__annotations__': CNS()}
        class CC(metaclass=CMeta):
            # XX: 'ANNOT'
        self.assertEqual(CC.__annotations__['xx'], 'ANNOT')

    def test_var_annot_module_semantics(self):
        with self.assertRaises(AttributeError):
            print(test.__annotations__)
        self.assertEqual(ann_module.__annotations__,
                     {1: 2, 'x': int, 'y': str, 'f': typing.Tuple[int, int]})
        self.assertEqual(ann_module.M.__annotations__,
                              {'123': 123, 'o': type})
        self.assertEqual(ann_module2.__annotations__, {})

    def test_var_annot_in_module(self):
        # check that functions fail the same way when executed
        # outside of module where they were defined
        from test.ann_module3 import f_bad_ann, g_bad_ann, D_bad_ann
        with self.assertRaises(NameError):
            f_bad_ann()
        with self.assertRaises(NameError):
            g_bad_ann()
        with self.assertRaises(NameError):
            D_bad_ann(5)

    def test_var_annot_simple_exec(self):
        gns = {}; lns= {}
        exec("'docstring'\n"
             "__annotations__[1] = 2\n"
             "x: int = 5\n", gns, lns)
        self.assertEqual(lns["__annotations__"], {1: 2, 'x': int})
        with self.assertRaises(KeyError):
            gns['__annotations__']

    def test_var_annot_custom_maps(self):
        # tests with custom locals() and __annotations__
        ns = {'__annotations__': CNS()}
        exec('X: int; Z: str = "Z"; (w): complex = 1j', ns)
        self.assertEqual(ns['__annotations__']['x'], int)
        self.assertEqual(ns['__annotations__']['z'], str)
        with self.assertRaises(KeyError):
            ns['__annotations__']['w']
        nonloc_ns = {}
        class CNS2:
            def __init__(self):
                self._dct = {}
            def __setitem__(self, item, value):
                nonlocal nonloc_ns
                self._dct[item] = value
                nonloc_ns[item] = value
            def __getitem__(self, item):
                return self._dct[item]
        exec('x: int = 1', {}, CNS2())
        self.assertEqual(nonloc_ns['__annotations__']['x'], int)

    def test_var_annot_refleak(self):
        # complex case: custom locals plus custom __annotations__
        # this was causing refleak
        cns = CNS()
        nonloc_ns = {'__annotations__': cns}
        class CNS2:
            def __init__(self):
                self._dct = {'__annotations__': cns}
            def __setitem__(self, item, value):
                nonlocal nonloc_ns
                self._dct[item] = value
                nonloc_ns[item] = value
            def __getitem__(self, item):
                return self._dct[item]
        exec('X: str', {}, CNS2())
        self.assertEqual(nonloc_ns['__annotations__']['x'], str)

    def test_funcdef(self):
        ### [decorators] 'def' NAME parameters ['->' test] ':' suite
        ### decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        ### decorators: decorator+
        ### parameters: '(' [typedargslist] ')'
        ### typedargslist: ((tfpdef ['=' test] ',')*
        ###                ('*' [tfpdef] (',' tfpdef ['=' test])* [',' '**' tfpdef] | '**' tfpdef)
        ###                | tfpdef ['=' test] (',' tfpdef ['=' test])* [','])
        ### tfpdef: NAME [':' test]
        ### varargslist: ((vfpdef ['=' test] ',')*
        ###              ('*' [vfpdef] (',' vfpdef ['=' test])*  [',' '**' vfpdef] | '**' vfpdef)
        ###              | vfpdef ['=' test] (',' vfpdef ['=' test])* [','])
        ### vfpdef: NAME
        def f1(): pass
        f1()
        f1(*())
        f1(*(), **{})
        def f2(one_argument): pass
        def f3(two, arguments): pass
        self.assertEqual(f2.__code__.co_varnames, ('one_argument',))
        self.assertEqual(f3.__code__.co_varnames, ('two', 'arguments'))
        def a1(one_arg,): pass
        def a2(two, args,): pass
        def v0(*rest): pass
        def v1(a, *rest): pass
        def v2(a, b, *rest): pass

        f1()
        f2(1)
        f2(1,)
        f3(1, 2)
        f3(1, 2,)
        v0()
        v0(1)
        v0(1,)
        v0(1,2)
        v0(1,2,3,4,5,6,7,8,9,0)
        v1(1)
        v1(1,)
        v1(1,2)
        v1(1,2,3)
        v1(1,2,3,4,5,6,7,8,9,0)
        v2(1,2)
        v2(1,2,3)
        v2(1,2,3,4)
        v2(1,2,3,4,5,6,7,8,9,0)

        def d01(a=1): pass
        d01()
        d01(1)
        d01(*(1,))
        d01(*[] or [2])
        d01(*() or (), *{} and (), **() or {})
        d01(**{'a':2})
        d01(**{'a':2} or {})
        def d11(a, b=1): pass
        d11(1)
        d11(1, 2)
        d11(1, **{'b':2})
        def d21(a, b, c=1): pass
        d21(1, 2)
        d21(1, 2, 3)
        d21(*(1, 2, 3))
        d21(1, *(2, 3))
        d21(1, 2, *(3,))
        d21(1, 2, **{'c':3})
        def d02(a=1, b=2): pass
        d02()
        d02(1)
        d02(1, 2)
        d02(*(1, 2))
        d02(1, *(2,))
        d02(1, **{'b':2})
        d02(**{'a': 1, 'b': 2})
        def d12(a, b=1, c=2): pass
        d12(1)
        d12(1, 2)
        d12(1, 2, 3)
        def d22(a, b, c=1, d=2): pass
        d22(1, 2)
        d22(1, 2, 3)
        d22(1, 2, 3, 4)
        def d01v(a=1, *rest): pass
        d01v()
        d01v(1)
        d01v(1, 2)
        d01v(*(1, 2, 3, 4))
        d01v(*(1,))
        d01v(**{'a':2})
        def d11v(a, b=1, *rest): pass
        d11v(1)
        d11v(1, 2)
        d11v(1, 2, 3)
        def d21v(a, b, c=1, *rest): pass
        d21v(1, 2)
        d21v(1, 2, 3)
        d21v(1, 2, 3, 4)
        d21v(*(1, 2, 3, 4))
        d21v(1, 2, **{'c': 3})
        def d02v(a=1, b=2, *rest): pass
        d02v()
        d02v(1)
        d02v(1, 2)
        d02v(1, 2, 3)
        d02v(1, *(2, 3, 4))
        d02v(**{'a': 1, 'b': 2})
        def d12v(a, b=1, c=2, *rest): pass
        d12v(1)
        d12v(1, 2)
        d12v(1, 2, 3)
        d12v(1, 2, 3, 4)
        d12v(*(1, 2, 3, 4))
        d12v(1, 2, *(3, 4, 5))
        d12v(1, *(2,), **{'c': 3})
        def d22v(a, b, c=1, d=2, *rest): pass
        d22v(1, 2)
        d22v(1, 2, 3)
        d22v(1, 2, 3, 4)
        d22v(1, 2, 3, 4, 5)
        d22v(*(1, 2, 3, 4))
        d22v(1, 2, *(3, 4, 5))
        d22v(1, *(2, 3), **{'d': 4})

        # keyword argument type tests
        try:
            str('x', **{b'foo':1 })
        except TypeError:
            pass
        else:
            self.fail('Bytes should not work as keyword argument names')
        # keyword only argument tests
        def pos0key1(*, key): return key
        pos0key1(key=100)
        def pos2key2(p1, p2, *, k1, k2=100): return p1,p2,k1,k2
        pos2key2(1, 2, k1=100)
        pos2key2(1, 2, k1=100, k2=200)
        pos2key2(1, 2, k2=100, k1=200)
        def pos2key2dict(p1, p2, *, k1=100, k2, **kwarg): return p1,p2,k1,k2,kwarg
        pos2key2dict(1,2,k2=100,tokwarg1=100,tokwarg2=200)
        pos2key2dict(1,2,tokwarg1=100,tokwarg2=200, k2=100)

        self.assertRaises(SyntaxError, eval, "def f(*): pass")
        self.assertRaises(SyntaxError, eval, "def f(*,): pass")
        self.assertRaises(SyntaxError, eval, "def f(*, **kwds): pass")

        # keyword arguments after *arglist
        def f(*args, **kwargs):
            return args, kwargs
        self.assertEqual(f(1, x=2, *[3, 4], y=5), ((1, 3, 4),
                                                    {'x':2, 'y':5}))
        self.assertEqual(f(1, *(2,3), 4), ((1, 2, 3, 4), {}))
        self.assertRaises(SyntaxError, eval, "f(1, x=2, *(3,4), x=5)")
        self.assertEqual(f(**{'eggs':'scrambled', 'spam':'fried'}),
                         ((), {'eggs':'scrambled', 'spam':'fried'}))
        self.assertEqual(f(spam='fried', **{'eggs':'scrambled'}),
                         ((), {'eggs':'scrambled', 'spam':'fried'}))

        # Check ast errors in *args and *kwargs
        check_syntax_error(self, "f(*g(1=2))")
        check_syntax_error(self, "f(**g(1=2))")

        # argument annotation tests
        def f(x) -> list: pass
        self.assertEqual(f.__annotations__, {'return': list})
        def f(x: int): pass
        self.assertEqual(f.__annotations__, {'x': int})
        def f(*x: str): pass
        self.assertEqual(f.__annotations__, {'x': str})
        def f(**x: float): pass
        self.assertEqual(f.__annotations__, {'x': float})
        def f(x, y: 1+2): pass
        self.assertEqual(f.__annotations__, {'y': 3})
        def f(a, b: 1, c: 2, d): pass
        self.assertEqual(f.__annotations__, {'b': 1, 'c': 2})
        def f(a, b: 1, c: 2, d, e: 3 = 4, f=5, *g: 6): pass
        self.assertEqual(f.__annotations__,
                         {'b': 1, 'c': 2, 'e': 3, 'g': 6})
        def f(a, b: 1, c: 2, d, e: 3 = 4, f=5, *g: 6, h: 7, i=8, j: 9 = 10,
              **k: 11) -> 12: pass
        self.assertEqual(f.__annotations__,
                         {'b': 1, 'c': 2, 'e': 3, 'g': 6, 'h': 7, 'j': 9,
                          'k': 11, 'return': 12})
        # Check for issue #20625 -- annotations mangling
        class Spam:
            def f(self, *, __kw: 1):
                pass
        class Ham(Spam): pass
        self.assertEqual(Spam.f.__annotations__, {'_Spam__kw': 1})
        self.assertEqual(Ham.f.__annotations__, {'_Spam__kw': 1})
        # Check for SF Bug #1697248 - mixing decorators and a return annotation
        def null(x): return x
        @null
        def f(x) -> list: pass
        self.assertEqual(f.__annotations__, {'return': list})

        # test closures with a variety of opargs
        closure = 1
        def f(): return closure
        def f(x=1): return closure
        def f(*, k=1): return closure
        def f() -> int: return closure

        # Check trailing commas are permitted in funcdef argument list
        def f(a,): pass
        def f(*args,): pass
        def f(**kwds,): pass
        def f(a, *args,): pass
        def f(a, **kwds,): pass
        def f(*args, b,): pass
        def f(*, b,): pass
        def f(*args, **kwds,): pass
        def f(a, *args, b,): pass
        def f(a, *, b,): pass
        def f(a, *args, **kwds,): pass
        def f(*args, b, **kwds,): pass
        def f(*, b, **kwds,): pass
        def f(a, *args, b, **kwds,): pass
        def f(a, *, b, **kwds,): pass

    def test_lambdef(self):
        ### lambdef: 'lambda' [varargslist] ':' test
        l1 = lambda : 0
        self.assertEqual(l1(), 0)
        l2 = lambda : a[d] # XXX just testing the expression
        l3 = lambda : [2 < x for x in [-1, 3, 0]]
        self.assertEqual(l3(), [0, 1, 0])
        l4 = lambda x = lambda y = lambda z=1 : z : y() : x()
        self.assertEqual(l4(), 1)
        l5 = lambda x, y, z=2: x + y + z
        self.assertEqual(l5(1, 2), 5)
        self.assertEqual(l5(1, 2, 3), 6)
        check_syntax_error(self, "lambda x: x = 2")
        check_syntax_error(self, "lambda (None,): None")
        l6 = lambda x, y, *, k=20: x+y+k
        self.assertEqual(l6(1,2), 1+2+20)
        self.assertEqual(l6(1,2,k=10), 1+2+10)

        # check that trailing commas are permitted
        l10 = lambda a,: 0
        l11 = lambda *args,: 0
        l12 = lambda **kwds,: 0
        l13 = lambda a, *args,: 0
        l14 = lambda a, **kwds,: 0
        l15 = lambda *args, b,: 0
        l16 = lambda *, b,: 0
        l17 = lambda *args, **kwds,: 0
        l18 = lambda a, *args, b,: 0
        l19 = lambda a, *, b,: 0
        l20 = lambda a, *args, **kwds,: 0
        l21 = lambda *args, b, **kwds,: 0
        l22 = lambda *, b, **kwds,: 0
        l23 = lambda a, *args, b, **kwds,: 0
        l24 = lambda a, *, b, **kwds,: 0


    ### stmt: simple_stmt | compound_stmt
    # Tested below

    def test_simple_stmt(self):
        ### simple_stmt: small_stmt (';' small_stmt)* [';']
        x = 1; pass; del x
        def foo():
            # verify statements that end with semi-colons
            x = 1; pass; del x;
        foo()

    ### small_stmt: expr_stmt | pass_stmt | del_stmt | flow_stmt | import_stmt | global_stmt | access_stmt
    # Tested below

    def test_expr_stmt(self):
        # (exprlist '=')* exprlist
        1
        1, 2, 3
        x = 1
        x = 1, 2, 3
        x = y = z = 1, 2, 3
        x, y, z = 1, 2, 3
        abc = a, b, c = x, y, z = xyz = 1, 2, (3, 4)

        check_syntax_error(self, "x + 1 = 1")
        check_syntax_error(self, "a + 1 = b + 2")

    # Check the heuristic for print & exec covers significant cases
    # As well as placing some limits on false positives
    def test_former_statements_refer_to_builtins(self):
        keywords = "print", "exec"
        # Cases where we want the custom error
        cases = [
            "{} foo",
            "{} {{1:foo}}",
            "if 1: {} foo",
            "if 1: {} {{1:foo}}",
            "if 1:\n    {} foo",
            "if 1:\n    {} {{1:foo}}",
        ]
        for keyword in keywords:
            custom_msg = "call to '{}'".format(keyword)
            for case in cases:
                source = case.format(keyword)
                with self.subTest(source=source):
                    with self.assertRaisesRegex(SyntaxError, custom_msg):
                        exec(source)
                source = source.replace("foo", "(foo.)")
                with self.subTest(source=source):
                    with self.assertRaisesRegex(SyntaxError, "invalid syntax"):
                        exec(source)

    def test_del_stmt(self):
        # 'del' exprlist
        abc = [1,2,3]
        x, y, z = abc
        xyz = x, y, z

        del abc
        del x, y, (z, xyz)

    def test_pass_stmt(self):
        # 'pass'
        pass

    # flow_stmt: break_stmt | continue_stmt | return_stmt | raise_stmt
    # Tested below

    def test_break_stmt(self):
        # 'break'
        while 1: break

    def test_continue_stmt(self):
        # 'continue'
        i = 1
        while i: i = 0; continue

        msg = ""
        while not msg:
            msg = "ok"
            try:
                continue
                msg = "continue failed to continue inside try"
            except:
                msg = "continue inside try called except block"
        if msg != "ok":
            self.fail(msg)

        msg = ""
        while not msg:
            msg = "finally block not called"
            try:
                continue
            finally:
                msg = "ok"
        if msg != "ok":
            self.fail(msg)

    def test_break_continue_loop(self):
        # This test warrants an explanation. It is a test specifically for SF bugs
        # #463359 and #462937. The bug is that a 'break' statement executed or
        # exception raised inside a try/except inside a loop, *after* a continue
        # statement has been executed in that loop, will cause the wrong number of
        # arguments to be popped off the stack and the instruction pointer reset to
        # a very small number (usually 0.) Because of this, the following test
        # *must* written as a function, and the tracking vars *must* be function
        # arguments with default values. Otherwise, the test will loop and loop.

        def test_inner(extra_burning_oil = 1, count=0):
            big_hippo = 2
            while big_hippo:
                count += 1
                try:
                    if extra_burning_oil and big_hippo == 1:
                        extra_burning_oil -= 1
                        break
                    big_hippo -= 1
                    continue
                except:
                    raise
            if count > 2 or big_hippo != 1:
                self.fail("continue then break in try/except in loop broken!")
        test_inner()

    def test_return(self):
        # 'return' [testlist]
        def g1(): return
        def g2(): return 1
        g1()
        x = g2()
        check_syntax_error(self, "class foo:return 1")

    def test_break_in_finally(self):
        count = 0
        while count < 2:
            count += 1
            try:
                pass
            finally:
                break
        self.assertEqual(count, 1)

        count = 0
        while count < 2:
            count += 1
            try:
                continue
            finally:
                break
        self.assertEqual(count, 1)

        count = 0
        while count < 2:
            count += 1
            try:
                1/0
            finally:
                break
        self.assertEqual(count, 1)

        for count in [0, 1]:
            self.assertEqual(count, 0)
            try:
                pass
            finally:
                break
        self.assertEqual(count, 0)

        for count in [0, 1]:
            self.assertEqual(count, 0)
            try:
                continue
            finally:
                break
        self.assertEqual(count, 0)

        for count in [0, 1]:
            self.assertEqual(count, 0)
            try:
                1/0
            finally:
                break
        self.assertEqual(count, 0)

    def test_continue_in_finally(self):
        count = 0
        while count < 2:
            count += 1
            try:
                pass
            finally:
                continue
            break
        self.assertEqual(count, 2)

        count = 0
        while count < 2:
            count += 1
            try:
                break
            finally:
                continue
        self.assertEqual(count, 2)

        count = 0
        while count < 2:
            count += 1
            try:
                1/0
            finally:
                continue
            break
        self.assertEqual(count, 2)

        for count in [0, 1]:
            try:
                pass
            finally:
                continue
            break
        self.assertEqual(count, 1)

        for count in [0, 1]:
            try:
                break
            finally:
                continue
        self.assertEqual(count, 1)

        for count in [0, 1]:
            try:
                1/0
            finally:
                continue
            break
        self.assertEqual(count, 1)

    def test_return_in_finally(self):
        def g1():
            try:
                pass
            finally:
                return 1
        self.assertEqual(g1(), 1)

        def g2():
            try:
                return 2
            finally:
                return 3
        self.assertEqual(g2(), 3)

        def g3():
            try:
                1/0
            finally:
                return 4
        self.assertEqual(g3(), 4)

    def test_yield(self):
        # Allowed as standalone statement
        def g(): yield 1
        def g(): yield from ()
        # Allowed as RHS of assignment
        def g(): x = yield 1
        def g(): x = yield from ()
        # Ordinary yield accepts implicit tuples
        def g(): yield 1, 1
        def g(): x = yield 1, 1
        # 'yield from' does not
        check_syntax_error(self, "def g(): yield from (), 1")
        check_syntax_error(self, "def g(): x = yield from (), 1")
        # Requires parentheses as subexpression
        def g(): 1, (yield 1)
        def g(): 1, (yield from ())
        check_syntax_error(self, "def g(): 1, yield 1")
        check_syntax_error(self, "def g(): 1, yield from ()")
        # Requires parentheses as call argument
        def g(): f((yield 1))
        def g(): f((yield 1), 1)
        def g(): f((yield from ()))
        def g(): f((yield from ()), 1)
        check_syntax_error(self, "def g(): f(yield 1)")
        check_syntax_error(self, "def g(): f(yield 1, 1)")
        check_syntax_error(self, "def g(): f(yield from ())")
        check_syntax_error(self, "def g(): f(yield from (), 1)")
        # Not allowed at top level
        check_syntax_error(self, "yield")
        check_syntax_error(self, "yield from")
        # Not allowed at class scope
        check_syntax_error(self, "class foo:yield 1")
        check_syntax_error(self, "class foo:yield from ()")
        # Check annotation refleak on SyntaxError
        check_syntax_error(self, "def g(a:(yield)): pass")

    def test_yield_in_comprehensions(self):
        # Check yield in comprehensions
        def g(): [x for x in [(yield 1)]]
        def g(): [x for x in [(yield from ())]]

        check = self.check_syntax_error
        check("def g(): [(yield x) for x in ()]",
              "'yield' inside list comprehension")
        check("def g(): [x for x in () if not (yield x)]",
              "'yield' inside list comprehension")
        check("def g(): [y for x in () for y in [(yield x)]]",
              "'yield' inside list comprehension")
        check("def g(): {(yield x) for x in ()}",
              "'yield' inside set comprehension")
        check("def g(): {(yield x): x for x in ()}",
              "'yield' inside dict comprehension")
        check("def g(): {x: (yield x) for x in ()}",
              "'yield' inside dict comprehension")
        check("def g(): ((yield x) for x in ())",
              "'yield' inside generator expression")
        check("def g(): [(yield from x) for x in ()]",
              "'yield' inside list comprehension")
        check("class C: [(yield x) for x in ()]",
              "'yield' inside list comprehension")
        check("[(yield x) for x in ()]",
              "'yield' inside list comprehension")

    def test_raise(self):
        # 'raise' test [',' test]
        try: raise RuntimeError('just testing')
        except RuntimeError: pass
        try: raise KeyboardInterrupt
        except KeyboardInterrupt: pass

    def test_import(self):
        # 'import' dotted_as_names
        import sys
        import time, sys
        # 'from' dotted_name 'import' ('*' | '(' import_as_names ')' | import_as_names)
        from time import time
        from time import (time)
        # not testable inside a function, but already done at top of the module
        # from sys import *
        from sys import path, argv
        from sys import (path, argv)
        from sys import (path, argv,)

    def test_global(self):
        # 'global' NAME (',' NAME)*
        global a
        global a, b
        global one, two, three, four, five, six, seven, eight, nine, ten

    def test_nonlocal(self):
        # 'nonlocal' NAME (',' NAME)*
        x = 0
        y = 0
        def f():
            nonlocal x
            nonlocal x, y

    def test_assert(self):
        # assertTruestmt: 'assert' test [',' test]
        assert 1
        assert 1, 1
        assert lambda x:x
        assert 1, lambda x:x+1

        try:
            assert True
        except AssertionError as e:
            self.fail("'assert True' should not have raised an AssertionError")

        try:
            assert True, 'this should always pass'
        except AssertionError as e:
            self.fail("'assert True, msg' should not have "
                      "raised an AssertionError")

    # these tests fail if python is run with -O, so check __debug__
    @unittest.skipUnless(__debug__, "Won't work if __debug__ is False")
    def testAssert2(self):
        try:
            assert 0, "msg"
        except AssertionError as e:
            self.assertEqual(e.args[0], "msg")
        else:
            self.fail("AssertionError not raised by assert 0")

        try:
            assert False
        except AssertionError as e:
            self.assertEqual(len(e.args), 0)
        else:
            self.fail("AssertionError not raised by 'assert False'")


    ### compound_stmt: if_stmt | while_stmt | for_stmt | try_stmt | funcdef | classdef
    # Tested below

    def test_if(self):
        # 'if' test ':' suite ('elif' test ':' suite)* ['else' ':' suite]
        if 1: pass
        if 1: pass
        else: pass
        if 0: pass
        elif 0: pass
        if 0: pass
        elif 0: pass
        elif 0: pass
        elif 0: pass
        else: pass

    def test_while(self):
        # 'while' test ':' suite ['else' ':' suite]
        while 0: pass
        while 0: pass
        else: pass

        # Issue1920: "while 0" is optimized away,
        # ensure that the "else" clause is still present.
        x = 0
        while 0:
            x = 1
        else:
            x = 2
        self.assertEqual(x, 2)

    def test_for(self):
        # 'for' exprlist 'in' exprlist ':' suite ['else' ':' suite]
        for i in 1, 2, 3: pass
        for i, j, k in (): pass
        else: pass
        class Squares:
            def __init__(self, max):
                self.max = max
                self.sofar = []
            def __len__(self): return len(self.sofar)
            def __getitem__(self, i):
                if not 0 <= i < self.max: raise IndexError
                n = len(self.sofar)
                while n <= i:
                    self.sofar.append(n*n)
                    n = n+1
                return self.sofar[i]
        n = 0
        for x in Squares(10): n = n+x
        if n != 285:
            self.fail('for over growing sequence')

        result = []
        for x, in [(1,), (2,), (3,)]:
            result.append(x)
        self.assertEqual(result, [1, 2, 3])

    def test_try(self):
        ### try_stmt: 'try' ':' suite (except_clause ':' suite)+ ['else' ':' suite]
        ###         | 'try' ':' suite 'finally' ':' suite
        ### except_clause: 'except' [expr ['as' expr]]
        try:
            1/0
        except ZeroDivisionError:
            pass
        else:
            pass
        try: 1/0
        except EOFError: pass
        except TypeError as msg: pass
        except: pass
        else: pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError): pass
        try: 1/0
        except (EOFError, TypeError, ZeroDivisionError) as msg: pass
        try: pass
        finally: pass

    def test_suite(self):
        # simple_stmt | NEWLINE INDENT NEWLINE* (stmt NEWLINE*)+ DEDENT
        if 1: pass
        if 1:
            pass
        if 1:
            #
            #
            #
            pass
            pass
            #
            pass
            #

    def test_test(self):
        ### and_test ('or' and_test)*
        ### and_test: not_test ('and' not_test)*
        ### not_test: 'not' not_test | comparison
        if not 1: pass
        if 1 and 1: pass
        if 1 or 1: pass
        if not not not 1: pass
        if not 1 and 1 and 1: pass
        if 1 and 1 or 1 and 1 and 1 or not 1 and 1: pass

    def test_comparison(self):
        ### comparison: expr (comp_op expr)*
        ### comp_op: '<'|'>'|'=='|'>='|'<='|'!='|'in'|'not' 'in'|'is'|'is' 'not'
        if 1: pass
        x = (1 == 1)
        if 1 == 1: pass
        if 1 != 1: pass
        if 1 < 1: pass
        if 1 > 1: pass
        if 1 <= 1: pass
        if 1 >= 1: pass
        if 1 is 1: pass
        if 1 is not 1: pass
        if 1 in (): pass
        if 1 not in (): pass
        if 1 < 1 > 1 == 1 >= 1 <= 1 != 1 in 1 not in 1 is 1 is not 1: pass

    def test_binary_mask_ops(self):
        x = 1 & 1
        x = 1 ^ 1
        x = 1 | 1

    def test_shift_ops(self):
        x = 1 << 1
        x = 1 >> 1
        x = 1 << 1 >> 1

    def test_additive_ops(self):
        x = 1
        x = 1 + 1
        x = 1 - 1 - 1
        x = 1 - 1 + 1 - 1 + 1

    def test_multiplicative_ops(self):
        x = 1 * 1
        x = 1 / 1
        x = 1 % 1
        x = 1 / 1 * 1 % 1

    def test_unary_ops(self):
        x = +1
        x = -1
        x = ~1
        x = ~1 ^ 1 & 1 | 1 & 1 ^ -1
        x = -1*1/1 + 1*1 - ---1*1

    def test_selectors(self):
        ### trailer: '(' [testlist] ')' | '[' subscript ']' | '.' NAME
        ### subscript: expr | [expr] ':' [expr]

        import sys, time
        c = sys.path[0]
        x = time.time()
        x = sys.modules['time'].time()
        a = '01234'
        c = a[0]
        c = a[-1]
        s = a[0:5]
        s = a[:5]
        s = a[0:]
        s = a[:]
        s = a[-5:]
        s = a[:-1]
        s = a[-4:-3]
        # A rough test of SF bug 1333982.  http://python.org/sf/1333982
        # The testing here is fairly incomplete.
        # Test cases should include: commas with 1 and 2 colons
        d = {}
        d[1] = 1
        d[1,] = 2
        d[1,2] = 3
        d[1,2,3] = 4
        L = list(d)
        L.sort(key=lambda x: (type(x).__name__, x))
        self.assertEqual(str(L), '[1, (1,), (1, 2), (1, 2, 3)]')

    def test_atoms(self):
        ### atom: '(' [testlist] ')' | '[' [testlist] ']' | '{' [dictsetmaker] '}' | NAME | NUMBER | STRING
        ### dictsetmaker: (test ':' test (',' test ':' test)* [',']) | (test (',' test)* [','])

        x = (1)
        x = (1 or 2 or 3)
        x = (1 or 2 or 3, 2, 3)

        x = []
        x = [1]
        x = [1 or 2 or 3]
        x = [1 or 2 or 3, 2, 3]
        x = []

        x = {}
        x = {'one': 1}
        x = {'one': 1,}
        x = {'one' or 'two': 1 or 2}
        x = {'one': 1, 'two': 2}
        x = {'one': 1, 'two': 2,}
        x = {'one': 1, 'two': 2, 'three': 3, 'four': 4, 'five': 5, 'six': 6}

        x = {'one'}
        x = {'one', 1,}
        x = {'one', 'two', 'three'}
        x = {2, 3, 4,}

        x = x
        x = 'x'
        x = 123

    ### exprlist: expr (',' expr)* [',']
    ### testlist: test (',' test)* [',']
    # These have been exercised enough above

    def test_classdef(self):
        # 'class' NAME ['(' [testlist] ')'] ':' suite
        class B: pass
        class B2(): pass
        class C1(B): pass
        class C2(B): pass
        class D(C1, C2, B): pass
        class C:
            def meth1(self): pass
            def meth2(self, arg): pass
            def meth3(self, a1, a2): pass

        # decorator: '@' dotted_name [ '(' [arglist] ')' ] NEWLINE
        # decorators: decorator+
        # decorated: decorators (classdef | funcdef)
        def class_decorator(x): return x
        @class_decorator
        class G: pass

    def test_dictcomps(self):
        # dictorsetmaker: ( (test ':' test (comp_for |
        #                                   (',' test ':' test)* [','])) |
        #                   (test (comp_for | (',' test)* [','])) )
        nums = [1, 2, 3]
        self.assertEqual({i:i+1 for i in nums}, {1: 2, 2: 3, 3: 4})

    def test_listcomps(self):
        # list comprehension tests
        nums = [1, 2, 3, 4, 5]
        strs = ["Apple", "Banana", "Coconut"]
        spcs = ["  Apple", " Banana ", "Coco  nut  "]

        self.assertEqual([s.strip() for s in spcs], ['Apple', 'Banana', 'Coco  nut'])
        self.assertEqual([3 * x for x in nums], [3, 6, 9, 12, 15])
        self.assertEqual([x for x in nums if x > 2], [3, 4, 5])
        self.assertEqual([(i, s) for i in nums for s in strs],
                         [(1, 'Apple'), (1, 'Banana'), (1, 'Coconut'),
                          (2, 'Apple'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Apple'), (3, 'Banana'), (3, 'Coconut'),
                          (4, 'Apple'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Apple'), (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(i, s) for i in nums for s in [f for f in strs if "n" in f]],
                         [(1, 'Banana'), (1, 'Coconut'), (2, 'Banana'), (2, 'Coconut'),
                          (3, 'Banana'), (3, 'Coconut'), (4, 'Banana'), (4, 'Coconut'),
                          (5, 'Banana'), (5, 'Coconut')])
        self.assertEqual([(lambda a:[a**i for i in range(a+1)])(j) for j in range(5)],
                         [[1], [1, 1], [1, 2, 4], [1, 3, 9, 27], [1, 4, 16, 64, 256]])

        def test_in_func(l):
            return [0 < x < 3 for x in l if x > 2]

        self.assertEqual(test_in_func(nums), [False, False, False])

        def test_nested_front():
            self.assertEqual([[y for y in [x, x + 1]] for x in [1,3,5]],
                             [[1, 2], [3, 4], [5, 6]])

        test_nested_front()

        check_syntax_error(self, "[i, s for i in nums for s in strs]")
        check_syntax_error(self, "[x if y]")

        suppliers = [
          (1, "Boeing"),
          (2, "Ford"),
          (3, "Macdonalds")
        ]

        parts = [
          (10, "Airliner"),
          (20, "Engine"),
          (30, "Cheeseburger")
        ]

        suppart = [
          (1, 10), (1, 20), (2, 20), (3, 30)
        ]

        x = [
          (sname, pname)
            for (sno, sname) in suppliers
              for (pno, pname) in parts
                for (sp_sno, sp_pno) in suppart
                  if sno == sp_sno and pno == sp_pno
        ]

        self.assertEqual(x, [('Boeing', 'Airliner'), ('Boeing', 'Engine'), ('Ford', 'Engine'),
                             ('Macdonalds', 'Cheeseburger')])

    def test_genexps(self):
        # generator expression tests
        g = ([x for x in range(10)] for x in range(1))
        self.assertEqual(next(g), [x for x in range(10)])
        try:
            next(g)
            self.fail('should produce StopIteration exception')
        except StopIteration:
            pass

        a = 1
        try:
            g = (a for d in a)
            next(g)
            self.fail('should produce TypeError')
        except TypeError:
            pass

        self.assertEqual(list((x, y) for x in 'abcd' for y in 'abcd'), [(x, y) for x in 'abcd' for y in 'abcd'])
        self.assertEqual(list((x, y) for x in 'ab' for y in 'xy'), [(x, y) for x in 'ab' for y in 'xy'])

        a = [x for x in range(10)]
        b = (x for x in (y for y in a))
        self.assertEqual(sum(b), sum([x for x in range(10)]))

        self.assertEqual(sum(x**2 for x in range(10)), sum([x**2 for x in range(10)]))
        self.assertEqual(sum(x*x for x in range(10) if x%2), sum([x*x for x in range(10) if x%2]))
        self.assertEqual(sum(x for x in (y for y in range(10))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10)))), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in [y for y in (z for z in range(10))]), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True)) if True), sum([x for x in range(10)]))
        self.assertEqual(sum(x for x in (y for y in (z for z in range(10) if True) if False) if True), 0)
        check_syntax_error(self, "foo(x for x in range(10), 100)")
        check_syntax_error(self, "foo(100, x for x in range(10))")

    def test_comprehension_specials(self):
        # test for outmost iterable precomputation
        x = 10; g = (i for i in range(x)); x = 5
        self.assertEqual(len(list(g)), 10)

        # This should hold, since we're only precomputing outmost iterable.
        x = 10; t = False; g = ((i,j) for i in range(x) if t for j in range(x))
        x = 5; t = True;
        self.assertEqual([(i,j) for i in range(10) for j in range(5)], list(g))

        # Grammar allows multiple adjacent 'if's in listcomps and genexps,
        # even though it's silly. Make sure it works (ifelse broke this.)
        self.assertEqual([ x for x in range(10) if x % 2 if x % 3 ], [1, 5, 7])
        self.assertEqual(list(x for x in range(10) if x % 2 if x % 3), [1, 5, 7])

        # verify unpacking single element tuples in listcomp/genexp.
        self.assertEqual([x for x, in [(4,), (5,), (6,)]], [4, 5, 6])
        self.assertEqual(list(x for x, in [(7,), (8,), (9,)]), [7, 8, 9])

    def test_with_statement(self):
        class manager(object):
            def __enter__(self):
                return (1, 2)
            def __exit__(self, *args):
                pass

        with manager():
            pass
        with manager() as x:
            pass
        with manager() as (x, y):
            pass
        with manager(), manager():
            pass
        with manager() as x, manager() as y:
            pass
        with manager() as x, manager():
            pass

    def test_if_else_expr(self):
        # Test ifelse expressions in various cases
        def _checkeval(msg, ret):
            "helper to check that evaluation of expressions is done correctly"
            print(msg)
            return ret

        # the next line is not allowed anymore
        #self.assertEqual([ x() for x in lambda: True, lambda: False if x() ], [True])
        self.assertEqual([ x() for x in (lambda: True, lambda: False) if x() ], [True])
        self.assertEqual([ x(False) for x in (lambda x: False if x else True, lambda x: True if x else False) if x(False) ], [True])
        self.assertEqual((5 if 1 else _checkeval("check 1", 0)), 5)
        self.assertEqual((_checkeval("check 2", 0) if 0 else 5), 5)
        self.assertEqual((5 and 6 if 0 else 1), 1)
        self.assertEqual(((5 and 6) if 0 else 1), 1)
        self.assertEqual((5 and (6 if 1 else 1)), 6)
        self.assertEqual((0 or _checkeval("check 3", 2) if 0 else 3), 3)
        self.assertEqual((1 or _checkeval("check 4", 2) if 1 else _checkeval("check 5", 3)), 1)
        self.assertEqual((0 or 5 if 1 else _checkeval("check 6", 3)), 5)
        self.assertEqual((not 5 if 1 else 1), False)
        self.assertEqual((not 5 if 0 else 1), 1)
        self.assertEqual((6 + 1 if 1 else 2), 7)
        self.assertEqual((6 - 1 if 1 else 2), 5)
        self.assertEqual((6 * 2 if 1 else 4), 12)
        self.assertEqual((6 / 2 if 1 else 3), 3)
        self.assertEqual((6 < 4 if 0 else 2), 2)

    def test_paren_evaluation(self):
        self.assertEqual(16 // (4 // 2), 8)
        self.assertEqual((16 // 4) // 2, 2)
        self.assertEqual(16 // 4 // 2, 2)
        self.assertTrue(False is (2 is 3))
        self.assertFalse((False is 2) is 3)
        self.assertFalse(False is 2 is 3)

    def test_matrix_mul(self):
        # This is not intended to be a comprehensive test, rather just to be few
        # samples of the @ operator in test_grammar.py.
        class M:
            def __matmul__(self, o):
                return 4
            def __imatmul__(self, o):
                self.other = o
                return self
        m = M()
        self.assertEqual(m @ m, 4)
        m @= 42
        self.assertEqual(m.other, 42)

    def test_async_await(self):
        async def test():
            def sum():
                pass
            if 1:
                await someobj()

        self.assertEqual(test.__name__, 'test')
        self.assertTrue(bool(test.__code__.co_flags & inspect.CO_COROUTINE))

        def decorator(func):
            setattr(func, '_marked', True)
            return func

        @decorator
        async def test2():
            return 22
        self.assertTrue(test2._marked)
        self.assertEqual(test2.__name__, 'test2')
        self.assertTrue(bool(test2.__code__.co_flags & inspect.CO_COROUTINE))

    def test_async_for(self):
        class Done(Exception): pass

        class AIter:
            def __aiter__(self):
                return self
            async def __anext__(self):
                raise StopAsyncIteration

        async def foo():
            async for i in AIter():
                pass
            async for i, j in AIter():
                pass
            async for i in AIter():
                pass
            else:
                pass
            raise Done

        with self.assertRaises(Done):
            foo().send(None)

    def test_async_with(self):
        class Done(Exception): pass

        class manager:
            async def __aenter__(self):
                return (1, 2)
            async def __aexit__(self, *exc):
                return False

        async def foo():
            async with manager():
                pass
            async with manager() as x:
                pass
            async with manager() as (x, y):
                pass
            async with manager(), manager():
                pass
            async with manager() as x, manager() as y:
                pass
            async with manager() as x, manager():
                pass
            raise Done

        with self.assertRaises(Done):
            foo().send(None)


if __name__ == '__main__':
    unittest.main()
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\simple-statements-without-trailing-newline.py\n# ==============================\n\npass; print "hi"\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\tabs.py\n# ==============================\n\ndef set_password(args):
	password = args.password
	while not password  :
		password1 = getpass("" if args.quiet else "Provide password: ")
		password_repeat = getpass("" if args.quiet else "Repeat password:  ")
		if password1 != password_repeat:
			print("Passwords do not match, try again")
		elif len(password1) < 4:
			print("Please provide at least 4 characters")
		else:
			password = password1

	password_hash = passwd(password)
	cfg = BaseJSONConfigManager(config_dir=jupyter_config_dir())
	cfg.update('jupyter_notebook_config', {
		'NotebookApp': {
			'password': password_hash,
		}
	})
	if not args.quiet:
		print("password stored in config dir: %s" % jupyter_config_dir())

def main(argv):
	parser = argparse.ArgumentParser(argv[0])
	subparsers = parser.add_subparsers()
	parser_password = subparsers.add_parser('password', help='sets a password for your notebook server')
	parser_password.add_argument("password", help="password to set, if not given, a password will be queried for (NOTE: this may not be safe)",
			nargs="?")
	parser_password.add_argument("--quiet", help="suppress messages", action="store_true")
	parser_password.set_defaults(function=set_password)
	args = parser.parse_args(argv[1:])
	args.function(args)
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\examples\trailing-whitespace.py\n# ==============================\n\nprint a    

if b:    
    if c:    
        d
    e     
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\setup.py\n# ==============================\n\nfrom os.path import isdir, join
from platform import system

from setuptools import Extension, find_packages, setup
from setuptools.command.build import build
from wheel.bdist_wheel import bdist_wheel


class Build(build):
    def run(self):
        if isdir("queries"):
            dest = join(self.build_lib, "tree_sitter_python", "queries")
            self.copy_tree("queries", dest)
        super().run()


class BdistWheel(bdist_wheel):
    def get_tag(self):
        python, abi, platform = super().get_tag()
        if python.startswith("cp"):
            python, abi = "cp39", "abi3"
        return python, abi, platform


setup(
    packages=find_packages("bindings/python"),
    package_dir={"": "bindings/python"},
    package_data={
        "tree_sitter_python": ["*.pyi", "py.typed"],
        "tree_sitter_python.queries": ["*.scm"],
    },
    ext_package="tree_sitter_python",
    ext_modules=[
        Extension(
            name="_binding",
            sources=[
                "bindings/python/tree_sitter_python/binding.c",
                "src/parser.c",
                "src/scanner.c",
            ],
            extra_compile_args=[
                "-std=c11",
                "-fvisibility=hidden",
            ] if system() != "Windows" else [
                "/std:c11",
                "/utf-8",
            ],
            define_macros=[
                ("Py_LIMITED_API", "0x03090000"),
                ("PY_SSIZE_T_CLEAN", None),
                ("TREE_SITTER_HIDE_SYMBOLS", None),
            ],
            include_dirs=["src"],
            py_limited_api=True,
        )
    ],
    cmdclass={
        "build": Build,
        "bdist_wheel": BdistWheel
    },
    zip_safe=False
)
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\test\highlight\keywords.py\n# ==============================\n\nif foo():
# <- keyword
    pass
    # <- keyword
elif bar():
# <- keyword
    pass
else:
# <- keyword
    foo

return
# ^ keyword
raise e
# ^ keyword

for i in foo():
# <- keyword
#   ^ variable
#     ^ operator
#        ^ function
    continue
    # <- keyword
    break
    # <- keyword

a and b or c
# ^ operator
#     ^ variable
#       ^ operator
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\test\highlight\parameters.py\n# ==============================\n\ndef g(h, i, /, j, *, k=100, **kwarg):
    #       ^ operator
    #             ^ operator
    pass
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\test\highlight\pattern_matching.py\n# ==============================\n\nmatch command.split():
# ^ keyword
    case ["quit"]:
    # ^ keyword
        print("Goodbye!")
        quit_game()
    case ["look"]:
    # ^ keyword
        current_room.describe()
    case ["get", obj]:
    # ^ keyword
        character.get(obj, current_room)
    case ["go", direction]:
    # ^ keyword
        current_room = current_room.neighbor(direction)
    # The rest of your commands go here

match command.split():
# ^ keyword
    case ["drop", *objects]:
    # ^ keyword
        for obj in objects:
            character.drop(obj, current_room)

match command.split():
# ^ keyword
    case ["quit"]: ... # Code omitted for brevity
    case ["go", direction]: pass
    case ["drop", *objects]: pass
    case _:
        print(f"Sorry, I couldn't understand {command!r}")

match command.split():
# ^ keyword
    case ["north"] | ["go", "north"]:
    # ^ keyword
        current_room = current_room.neighbor("north")
    case ["get", obj] | ["pick", "up", obj] | ["pick", obj, "up"]:
    # ^ keyword
        pass

match = 2
#   ^ variable
match, a = 2, 3
#   ^ variable
match: int = secret
#   ^ variable
x, match: str = 2, "hey, what's up?"
# <- variable
#   ^ variable

if match := re.fullmatch(r"(-)?(\d+:)?\d?\d:\d\d(\.\d*)?", time, flags=re.ASCII):
    # ^ variable
    return match
\n\n# ==============================\n# Filename: utils\vendor\tree-sitter-python\test\tags\main.py\n# ==============================\n\nclass MyClass:
  #    ^ definition.class
  def hello():
    #  ^ definition.function
    print "hello from MyClass"

MyClass.hello()
#        ^ reference.call

def main():
  #  ^ definition.function
  print "Hello, world!"

main()
# <- reference.call
\n\n