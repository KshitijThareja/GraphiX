import os
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
