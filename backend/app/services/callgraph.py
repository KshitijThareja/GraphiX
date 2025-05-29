import os
import ast
from typing import Dict, List, Set, Optional
import tempfile
import shutil
from git import Repo
from fastapi import HTTPException
import google.generativeai as genai
import logging
import traceback
import time
import asyncio
from functools import wraps
from datetime import datetime, timedelta
from ..models.base import settings


def rate_limited(max_per_minute: int):
    min_interval = 60.0
    last_called = 0

    def decorator(func):
        @wraps(func)
        async def wrapper(self, *args, **kwargs):
            nonlocal last_called
            elapsed = time.time() - last_called
            if elapsed < min_interval:
                wait_time = min_interval - elapsed
                await asyncio.sleep(wait_time)
            last_called = time.time()
            return await func(self, *args, **kwargs)

        return wrapper

    return decorator


logging.basicConfig(level=logging.INFO)
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
        GEMINI_API_KEY = settings.GEMINI_API_KEY
        genai.configure(api_key=GEMINI_API_KEY)
        self.model = genai.GenerativeModel("gemini-2.0-flash-lite")
        self.last_api_call = 0
        self.min_interval = 2.0

    async def clone_repository(
        self, repo_url: str, access_token: Optional[str] = None, timeout: int = 300
    ) -> str:
        repo_name = os.path.splitext(os.path.basename(repo_url.rstrip("/")))[0]
        temp_dir = tempfile.mkdtemp(prefix=f"graphix_{repo_name}_")
        logger.info(
            f"Cloning repository {repo_url} to {temp_dir} (timeout: {timeout}s)"
        )

        async def _clone_repo():
            try:
                repo_url_clean = repo_url.strip()
                if repo_url_clean.endswith(".git"):
                    repo_url_clean = repo_url_clean[:-4]
                if access_token:
                    if repo_url_clean.startswith("https://"):
                        auth_url = repo_url_clean.replace(
                            "https://", f"https://{access_token}@", 1
                        )
                    elif repo_url_clean.startswith("http://"):
                        auth_url = repo_url_clean.replace(
                            "http://", f"http://{access_token}@", 1
                        )
                    else:
                        auth_url = f"https://{access_token}@{repo_url_clean}"
                    logger.debug(
                        f"Using authenticated URL: {auth_url.split('@')[0]}@[REDACTED]"
                    )
                    cmd = [
                        "git",
                        "clone",
                        "--progress",
                        "--depth",
                        "1",
                        auth_url,
                        temp_dir,
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    while True:
                        output = await process.stderr.readline()
                        if process.returncode is not None:
                            break
                        if output:
                            line = output.decode().strip()
                            logger.debug(f"git clone: {line}")
                    await process.wait()
                    if process.returncode != 0:
                        error_output = await process.stderr.read()
                        raise Exception(
                            f"Git clone failed: {error_output.decode().strip()}"
                        )
                else:
                    cmd = [
                        "git",
                        "clone",
                        "--progress",
                        "--depth",
                        "1",
                        repo_url_clean,
                        temp_dir,
                    ]
                    process = await asyncio.create_subprocess_exec(
                        *cmd,
                        stdout=asyncio.subprocess.PIPE,
                        stderr=asyncio.subprocess.PIPE,
                    )
                    while True:
                        output = await process.stderr.readline()
                        if process.returncode is not None:
                            break
                        if output:
                            line = output.decode().strip()
                            logger.debug(f"git clone: {line}")
                    await process.wait()
                    if process.returncode != 0:
                        error_output = await process.stderr.read()
                        raise Exception(
                            f"Git clone failed: {error_output.decode().strip()}"
                        )
                if not os.path.exists(os.path.join(temp_dir, ".git")):
                    raise Exception("Repository was not cloned successfully")
                return temp_dir
            except Exception as e:
                logger.error(f"Error in clone operation: {str(e)}")
                raise

        try:
            clone_task = asyncio.create_task(_clone_repo())
            done, pending = await asyncio.wait(
                [clone_task], timeout=timeout, return_when=asyncio.FIRST_COMPLETED
            )
            if pending:
                logger.warning(f"Clone operation timed out after {timeout} seconds")
                for task in pending:
                    task.cancel()
                raise asyncio.TimeoutError(
                    f"Clone operation timed out after {timeout} seconds"
                )
            temp_dir = await clone_task
            self.repo_path = os.path.abspath(temp_dir)
            logger.info(f"Successfully cloned repository to {self.repo_path}")
            return self.repo_path
        except asyncio.TimeoutError as e:
            logger.error(f"Repository clone timed out after {timeout} seconds")
            raise HTTPException(
                status_code=408,
                detail=f"Repository clone timed out after {timeout} seconds. The repository might be too large or the connection is slow.",
            )
        except Exception as e:
            error_msg = str(e)
            logger.error(
                f"Failed to clone repository: {error_msg}\n{traceback.format_exc()}"
            )
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
            if any(msg in error_msg.lower() for msg in ["not found", "does not exist"]):
                error_msg = "Repository not found. Please check the URL and try again."
            elif any(
                msg in error_msg.lower() for msg in ["auth", "permission", "access"]
            ):
                error_msg = "Authentication failed. Please check your access token and try again."
            elif "timed out" in error_msg.lower():
                error_msg = f"Connection timed out. The repository might be too large or the connection is slow."
            raise HTTPException(status_code=400, detail=error_msg)

    @rate_limited(max_per_minute=25)
    async def analyze_repository(
        self,
        repo_path: str,
        timeout: int = 300,
        clone: bool = False,
        perform_cleanup: bool = True,
    ) -> Dict[str, List]:
        cleanup_needed = False
        temp_dir = None
        try:
            start_time = time.time()
            max_files = 25
            if clone:
                logger.info(f"Cloning repository from {repo_path}")
                try:
                    clone_timeout = min(180, timeout // 2)
                    repo_path = await self.clone_repository(
                        repo_path, timeout=clone_timeout
                    )
                    cleanup_needed = True
                    temp_dir = repo_path
                    logger.info(f"Repository cloned to {repo_path}")
                except Exception as e:
                    logger.error(f"Failed to clone repository: {str(e)}")
                    raise
            logger.info(f"Starting repository analysis in: {repo_path}")
            repo_root = repo_path
            while (
                not os.path.exists(os.path.join(repo_root, ".git"))
                and os.path.dirname(repo_root) != repo_root
            ):
                repo_root = os.path.dirname(repo_root)
            logger.info(f"Using repository root: {repo_root}")
            self.repo_path = repo_root
            py_files = []
            try:
                for root, dirs, files in os.walk(repo_root):
                    dirs[:] = [
                        d
                        for d in dirs
                        if not d.startswith((".", "_"))
                        and d not in ("venv", "env", "node_modules", "__pycache__")
                    ]
                    for file in files:
                        if file.endswith(".py"):
                            full_path = os.path.join(root, file)
                            try:
                                if os.path.getsize(full_path) > 0:
                                    py_files.append(full_path)
                            except (IOError, OSError) as e:
                                logger.warning(
                                    f"Skipping unreadable file {full_path}: {str(e)}"
                                )
                                continue
            except Exception as e:
                logger.error(f"Error walking directory {repo_root}: {str(e)}")
                raise
            if not py_files:
                logger.warning(f"No Python files found in {repo_root}")
                return {"nodes": [], "links": []}
            logger.info(
                f"Found {len(py_files)} Python files, analyzing up to {max_files}..."
            )
            processed_files = 0
            for file_path in py_files[:max_files]:
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
                        f"Analyzed {file_path} ({processed_files}/{min(len(py_files), max_files)})"
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
            callgraph = await self.generate_callgraph()
            if not callgraph.get("nodes") or not callgraph.get("links"):
                logger.warning("Generated empty callgraph")
            else:
                logger.info(
                    f"Generated callgraph with {len(callgraph.get('nodes', []))} nodes and {len(callgraph.get('links', []))} links"
                )
            analysis_time = time.time() - start_time
            logger.info(f"Analysis completed in {analysis_time:.2f} seconds")
            callgraph["metadata"] = {
                "analysis_time_seconds": analysis_time,
                "files_analyzed": processed_files,
                "total_files_found": len(py_files),
                "repository": os.path.basename(repo_root),
                "framework_analyzed_as": self.detected_framework_name,
            }
            return callgraph
        except asyncio.TimeoutError:
            logger.warning(f"Analysis timed out after {timeout} seconds")
            raise
        except Exception as e:
            logger.error(
                f"Error in analyze_repository: {str(e)}\n{traceback.format_exc()}"
            )
            raise
        finally:
            if (
                perform_cleanup
                and cleanup_needed
                and temp_dir
                and os.path.exists(temp_dir)
            ):
                try:
                    logger.info(f"Cleaning up temporary directory: {temp_dir}")
                    shutil.rmtree(temp_dir, ignore_errors=True)
                except Exception as e:
                    logger.error(
                        f"Error cleaning up temporary directory {temp_dir}: {str(e)}"
                    )

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
                }
                for item in node.body:
                    if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        method_name = f"{class_name}.{item.name}"
                        try:
                            complexity = self._calculate_complexity(item)
                            docstring = ast.get_docstring(item) or ""
                            self.functions[method_name] = {
                                "node": item,
                                "file": file_path,
                                "complexity": complexity,
                                "type": "method",
                                "class": class_name,
                                "module": module_name,
                                "docstring": docstring,
                                "lineno": item.lineno,
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
                        self.functions[func_name] = {
                            "node": node,
                            "file": file_path,
                            "complexity": complexity,
                            "type": "function",
                            "module": module_name,
                            "docstring": docstring,
                            "lineno": node.lineno,
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
        for func_name, func_info in self.functions.items():
            group = self._determine_group(func_name)
            try:
                response = await self._generate_llm_content_with_rate_limit(
                    func_name, func_info
                )
                func_info["llm_summary"] = response
            except Exception as e:
                logger.warning(
                    f"Failed to generate LLM content for {func_name}: {str(e)}"
                )
                purpose = "Function documentation unavailable."
                suggestion = "No suggestion."
            self.nodes.append(
                {
                    "id": func_name,
                    "group": group,
                    "type": func_info["type"],
                    "complexity": func_info["complexity"],
                    "file": func_info["file"],
                    "class": func_info.get("class", ""),
                    "metadata": {"docstring": purpose, "refactoring": suggestion},
                }
            )
        already_linked = set()
        view_functions = set()
        if is_django:
            for func_name, func_info in self.functions.items():
                if self._is_django_view(func_name, func_info):
                    view_functions.add(func_name)
            logger.info(f"Found {len(view_functions)} Django view functions")
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
        if self.repo_path and os.path.exists(self.repo_path):
            shutil.rmtree(self.repo_path, ignore_errors=True)
