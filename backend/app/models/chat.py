from typing import Dict, List, Optional, Any, Union
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
