import logging
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
            # Read and parse the source file
            with open(file_path, 'r', encoding='utf-8') as f:
                source_code = f.read()
            
            tree = ast.parse(source_code, filename=file_path)
            
            # Identify the target node in the AST
            target_ast_node = self._find_ast_node(tree, node_id, node_type)
            
            if not target_ast_node:
                logger.debug(f"AST enrichment skipped: Could not find node {node_id} in {file_path}")
                return enriched_data
            
            # Extract detailed information based on node type
            if node_type == 'function' or node_type == 'method':
                # Extract function/method details
                func_details = self._extract_function_details(target_ast_node, source_code)
                enriched_data.update(func_details)
                
            elif node_type == 'class':
                # Extract class details
                class_details = self._extract_class_details(target_ast_node, source_code, tree)
                enriched_data.update(class_details)
                
            elif node_type == 'module':
                # Extract module details
                module_details = self._extract_module_details(tree, source_code)
                enriched_data.update(module_details)
            
            logger.info(f"Successfully enriched node {node_id} with AST data")
            return enriched_data
            
        except Exception as e:
            logger.warning(f"Error enriching node data with AST for {node_data.get('id')}: {e}")
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
        prompt.append("Please generate documentation in the following JSON format:")
        prompt.append("""```json
{
  "docstring": "A clear, concise docstring describing the code element.\n\nArgs:\n    param1: Description of param1\n    param2: Description of param2\n\nReturns:\n    Description of return value\n\nRaises:\n    ExceptionType: When and why this exception is raised",
  "signature": "function_name(param1: type1, param2: type2 = default_value) -> return_type"
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
