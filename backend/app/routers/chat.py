import os
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
