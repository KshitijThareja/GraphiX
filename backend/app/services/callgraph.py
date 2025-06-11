import os
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
        repo_path_input_str = str(repo_path)

        # --- Correctly handle path setup and cloning ---
        try:
            if clone:
                self.status_log.append(f"Cloning repository from {repo_path_input_str}")
                logger.info(f"Cloning repository from {repo_path_input_str}")
                cloned_path = await self.clone_repository(repo_path_input_str, timeout=timeout)
                self.repo_path = os.path.abspath(cloned_path)
                self.tmp_dir = self.repo_path
                self.temp_repo_path = self.repo_path # Ensure temp_repo_path is also set
                self.cleanup_needed = True
                logger.info(f"Successfully cloned repository to {self.repo_path}")
            elif os.path.isdir(repo_path_input_str):
                self.repo_path = os.path.abspath(repo_path_input_str)
                self.tmp_dir = None
                self.temp_repo_path = self.repo_path # Ensure temp_repo_path is also set
                self.cleanup_needed = False
                logger.info(f"Using local repository path: {self.repo_path}")
            else:
                msg = f"Invalid repository path or URL: {repo_path_input_str}"
                logger.error(msg)
                self.status_log.append(msg)
                raise ValueError(msg)
        except Exception as e:
            logger.error(f"Failed to clone or set up repository: {e}", exc_info=True)
            self.status_log.append(f"Failed to set up repository: {e}")
            raise

        if not self.repo_path or not os.path.isdir(self.repo_path):
            logger.error(f"Invalid repository path after setup: {self.repo_path}")
            raise ValueError(f"Invalid repository path after setup: {self.repo_path}")

        # The rest of the analysis logic starts here, with correct indentation
        self.status_log.append(f"Starting analysis in: {self.repo_path}")
        logger.info(f"Starting analysis in: {self.repo_path}")

        repo_root = self.repo_path
        # ... (find .git root logic, if necessary, is fine)
        self.repository_id = os.path.basename(repo_root)
        
        log_message = f"Starting repository analysis for {self.repository_id}"
        logger.info(log_message)
        self.status_log.append(log_message)
        
        # Check for existing data
        existing_callgraph = await self.codebase_data_service.get_callgraph(self.repository_id)
        if existing_callgraph:
            logger.info(f"Found existing callgraph data for {self.repository_id}")
            result = {
                "nodes": [node.dict() for node in existing_callgraph.nodes],
                "links": [link.dict() for link in existing_callgraph.links],
                "metadata": existing_callgraph.metadata.dict()
            }
            return result

        # --- File walking and processing ---
        py_files = []
        total_files_found = 0
        for root, dirs, files in os.walk(self.repo_path):
            if "venv" in dirs: dirs.remove("venv")
            if ".venv" in dirs: dirs.remove(".venv")
            if ".git" in dirs: dirs.remove(".git")
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
            f"Analyzing up to {max_files_to_analyze or len(py_files)} Python files..."
        )
        processed_files = 0
        for file_path in py_files:
            if time.time() - start_time > timeout:
                logger.warning(f"Analysis timed out after {timeout} seconds")
                raise asyncio.TimeoutError(f"Analysis timed out after {timeout} seconds")
            try:
                await asyncio.sleep(0.01) # Yield control to event loop
                self.analyze_file(file_path)
                processed_files += 1
                logger.info(f"Analyzed {file_path} ({processed_files}/{min(len(py_files), max_files_to_analyze or len(py_files))})")
            except Exception as e:
                logger.error(f"Error analyzing {file_path}: {str(e)}\n{traceback.format_exc()}")
        
        if not self.functions:
            logger.warning("No functions found in any Python files")
            return {"nodes": [], "links": []}

        logger.info(f"Analyzed {processed_files} Python files, generating callgraph...")
        await self.generate_callgraph()
        self._detect_framework()
        
        # --- Metadata and result preparation ---
        analysis_time = time.time() - start_time
        metadata = {
            "framework_analyzed_as": self.detected_framework_name,
            "files_analyzed": len(py_files),
            "total_files_found": total_files_found,
            "analysis_time_seconds": round(analysis_time, 2),
            "timeout_seconds": timeout,
            "status": "completed",
            "status_log": self.status_log
        }
        
        if self.complexity_scores:
            # ... (your metric calculation logic is fine)
            pass

        result = {"nodes": self.nodes, "links": self.links, "metadata": metadata}
        
        # --- Database storage ---
        try:
            callgraph_data = CallgraphDataCreate(
                repository_id=self.repository_id,
                nodes=self.nodes,
                links=self.links,
                metadata=metadata
            )
            self.callgraph_id = await self.codebase_data_service.store_callgraph(callgraph_data)
            logger.info(f"Stored callgraph data with ID: {self.callgraph_id}")
            result["metadata"]["callgraph_id"] = self.callgraph_id
        except Exception as e:
            logger.error(f"Failed to store callgraph data: {str(e)}", exc_info=True)
            result["metadata"]["store_error"] = str(e)

        # --- Final cleanup ---
        if perform_cleanup and self.cleanup_needed:
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
