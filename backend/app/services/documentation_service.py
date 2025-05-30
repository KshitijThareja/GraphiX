import os
import ast
import logging
import re
from typing import Dict, List, Set, Optional, Tuple, Any, Union
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
    
    def __init__(self, framework_hint: str = "generic"):
        """
        Initialize the DocumentationService.
        
        Args:
            framework_hint: Optional hint about the framework used in the codebase
        """
        self.framework_hint = framework_hint
        self.callgraph_generator = ResearchCallgraphGenerator(framework=framework_hint)
        self.codebase_data_service = CodebaseDataService()
        self.repo_path = None
        self.repository_id = None
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
        Analyze the repository to extract documentation.
        First attempts to use existing callgraph data via CodebaseDataService.
        Falls back to ResearchCallgraphGenerator if no data exists.
        
        Args:
            repo_path: Path to repository
            timeout: Timeout for analysis in seconds
            clone: Whether to clone the repository
            perform_cleanup: Whether to clean up temporary files after analysis
            repository_id: Optional identifier for the repository
            
        Returns:
            Dict containing documentation data
        """
        start_time = datetime.now()
        self.repository_id = repository_id or os.path.basename(repo_path)
        logger.info(f"Starting documentation analysis for repository: {self.repository_id}")
        
        # First try to get existing callgraph data
        callgraph_data = await self.codebase_data_service.get_callgraph(self.repository_id)
        
        if callgraph_data:
            logger.info(f"Using existing callgraph data for {self.repository_id}")
            # Convert from database model to the format expected by _generate_documentation
            callgraph_result = {
                "nodes": [node.dict() for node in callgraph_data.nodes],
                "links": [link.dict() for link in callgraph_data.links],
                "metadata": callgraph_data.metadata.dict()
            }
            self.repo_path = repo_path
            
            # For existing callgraph data, we still need to extract docstrings
            # but we'll only process files referenced in the callgraph nodes
            await self._extract_documentation_from_callgraph(callgraph_result)
        else:
            logger.info(f"No existing callgraph data found for {self.repository_id}, performing full analysis")
            # Leverage the existing callgraph generator to analyze the repository
            callgraph_result = await self.callgraph_generator.analyze_repository(
                repo_path=repo_path,
                timeout=timeout,
                clone=clone,
                perform_cleanup=False,  # We'll handle cleanup ourselves
                repository_id=self.repository_id
            )
            
            self.repo_path = self.callgraph_generator.repo_path
            
            # Extract docstrings and other documentation from the analyzed files
            await self._extract_documentation()
        
        # Generate structured documentation
        doc_result = self._generate_documentation(callgraph_result)
        
        # Clean up if necessary
        if perform_cleanup and clone and hasattr(self.callgraph_generator, 'cleanup'):
            await self.callgraph_generator.cleanup()
        
        end_time = datetime.now()
        elapsed = (end_time - start_time).total_seconds()
        
        logger.info(f"Documentation analysis completed in {elapsed:.2f} seconds")
        
        return doc_result
    
    async def generate_from_callgraph(self, repo_path: Optional[str], callgraph_result: Dict, clone: bool = False, perform_cleanup: bool = True) -> Dict:
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
        self.modules = {}
        self.classes = {}
        self.functions = {}
        
        # Set repository path if provided
        self.repo_path = None
        tmp_dir = None
        
        if repo_path:
            if clone and (repo_path.startswith("http://") or repo_path.startswith("https://")):
                logger.info(f"Cloning repository {repo_path} for documentation generation")
                generator = CallgraphGenerator()
                self.repo_path = await generator.clone_repository(repo_path)
                tmp_dir = self.repo_path  # Store tmp_dir for cleanup
            else:
                self.repo_path = repo_path
        
        try:
            # Extract documentation from callgraph
            logger.info("Extracting documentation from callgraph data")
            await self._extract_documentation_from_callgraph(callgraph_result)
            
            # Prepare the documentation result structure
            doc_result = {
                "modules": [],
                "classes": [],
                "functions": [],
                "metadata": callgraph_result.get("metadata", {})
            }
            
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
            if perform_cleanup and tmp_dir:
                logger.info(f"Cleaning up temporary directory {tmp_dir}")
                await CallgraphGenerator.cleanup_temp_dir(tmp_dir)
                
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
                
    async def _extract_documentation_from_callgraph(self, callgraph_result: Dict) -> None:
        """
        Extract docstrings and signatures only for files referenced in the callgraph nodes.
        This is more efficient than processing all files when we already have callgraph data.
        
        Args:
            callgraph_result: Callgraph data with nodes and links
        """
        # Check if we have a valid local repository path
        has_local_repo = self.repo_path and os.path.isdir(self.repo_path)
        if not has_local_repo:
            logger.warning("Repository path is not available for full documentation extraction")
            logger.info("Falling back to extracting documentation from callgraph metadata only")
        
        # Extract unique file paths from callgraph nodes if we have a local repo
        unique_files = set()
        
        # Always extract documentation from the callgraph data itself
        nodes = callgraph_result.get("nodes", [])
        links = callgraph_result.get("links", [])
        
        # Create module, class, and function entries from callgraph nodes
        for node in nodes:
            node_id = node.get("id", "")
            if not node_id:
                continue
                
            # Extract information from node
            node_parts = node_id.split(".")
            file_path = node.get("file", "")
            docstring = node.get("docstring", "")
            node_type = node.get("type", "").lower()
            signature = node.get("signature", "")
            complexity = node.get("complexity", 0)
            
            # Determine the module name from the node ID
            module_name = ".".join(node_parts[:-1]) if len(node_parts) > 1 else node_parts[0]
            
            # Create or update module entry
            if module_name not in self.modules:
                self.modules[module_name] = {
                    "name": module_name,
                    "qualified_name": module_name,
                    "file": file_path,
                    "docstring": "",
                    "classes": [],
                    "functions": []
                }
            
            # Handle different node types
            if node_type == "class" or "class" in node_id.lower():
                # Add class to documentation
                class_name = node_parts[-1]
                self.classes[node_id] = {
                    "name": class_name,
                    "qualified_name": node_id,
                    "module": module_name,
                    "file": file_path,
                    "docstring": docstring,
                    "bases": node.get("bases", []),
                    "methods": []
                }
                # Add to module's classes list
                if node_id not in self.modules[module_name]["classes"]:
                    self.modules[module_name]["classes"].append(node_id)
            elif node_type == "function" or "function" in node_id.lower() or len(node_parts) > 0:
                # Determine if this is a method
                is_method = False
                class_name = None
                
                # Check if this belongs to a class
                for class_id in self.classes:
                    if node_id.startswith(class_id + "."):
                        is_method = True
                        class_name = class_id
                        break
                
                # Add function to documentation
                func_data = {
                    "name": node_parts[-1],
                    "qualified_name": node_id,
                    "module": module_name,
                    "file": file_path,
                    "docstring": docstring,
                    "is_method": is_method,
                    "class_name": class_name,
                    "signature": signature or node_parts[-1] + "()",
                    "complexity": complexity
                }
                self.functions[node_id] = func_data
                
                # Add to module's functions list or class's methods list
                if is_method and class_name in self.classes:
                    if func_data not in self.classes[class_name]["methods"]:
                        self.classes[class_name]["methods"].append(func_data)
                else:
                    if node_id not in self.modules[module_name]["functions"]:
                        self.modules[module_name]["functions"].append(node_id)
        
        # If we have a local repo, extract additional documentation from files
        if has_local_repo:
            for node in callgraph_result.get("nodes", []):
                if "file" in node and node["file"]:
                    # If the file path is absolute, make it relative to repo_path
                    file_path = node["file"]
                    if os.path.isabs(file_path):
                        try:
                            # Handle paths that might be from temp directories during original analysis
                            file_name = os.path.basename(file_path)
                            # Try to find the file in the current repo_path
                            for root, _, files in os.walk(self.repo_path):
                                if file_name in files:
                                    possible_path = os.path.join(root, file_name)
                                    unique_files.add(possible_path)
                                    break
                        except Exception:
                            # If we can't find it, just continue
                            continue
                    else:
                        # If it's already relative, join with repo_path
                        unique_files.add(os.path.join(self.repo_path, file_path))
            
            # Process each unique file
            logger.info(f"Extracting additional documentation from {len(unique_files)} files referenced in callgraph")
            for file_path in unique_files:
                if os.path.exists(file_path) and file_path.endswith(".py"):
                    try:
                        await self._extract_file_documentation(file_path)
                    except Exception as e:
                        logger.error(f"Error extracting documentation from {file_path}: {str(e)}")
                else:
                    logger.warning(f"File referenced in callgraph not found: {file_path}")
        
        logger.info(f"Documentation extracted: {len(self.modules)} modules, {len(self.classes)} classes, {len(self.functions)} functions")
    
    async def _extract_file_documentation(self, file_path: str) -> None:
        """
        Extract documentation from a single Python file.
        
        Args:
            file_path: Path to the Python file
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
                
            tree = ast.parse(content, filename=file_path)
            rel_path = os.path.relpath(file_path, self.repo_path)
            module_name = rel_path.replace(".py", "").replace(os.sep, ".")
            
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
