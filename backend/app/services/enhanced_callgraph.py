import os
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

        logger.info(f"[EnhancedCallgraphGenerator] Starting analysis, calling parent CallgraphGenerator.")

        # --- FIX STEP 1: Call the parent (CallgraphGenerator) FIRST. ---
        # This will handle cloning and perform the basic static analysis, populating
        # self.functions, self.classes, self.repo_path, etc.
        # We pass perform_cleanup=False because the top-level caller (Research) will handle it.
        await super().analyze_repository(
            repo_path, timeout, clone, perform_cleanup=False
        )

        # --- FIX STEP 2: Now that the parent has run, create the base copies. ---
        self.base_functions = self.functions.copy()
        self.base_classes = self.classes.copy()

        logger.info(f"Enhancing analysis with scope and definition management...")
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
            if "views.py" in func_info.get("file", ""):
                if not func_name.startswith("_"):
                    django_views.add(func_name)
        django_models = set()
        for class_name, class_info in self.base_classes.items():
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
                if view_func not in self.base_functions:
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
            if view_func not in self.base_functions:
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
                if view_func not in self.base_functions:
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
            for existing_func in self.base_functions.keys():
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
                for existing_func in self.base_functions.keys():
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
            "classes": list(self.base_classes.keys()),
            "imports": self.base_imports,
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
