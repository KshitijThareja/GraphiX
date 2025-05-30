import os
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
