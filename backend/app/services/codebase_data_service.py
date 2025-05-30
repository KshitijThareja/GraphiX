import logging
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
