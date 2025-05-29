import ast
import json
import os
from typing import Dict, List, Any, Set, Tuple
from .relationship_analysis import Relationship, RelationshipType
from .relationship_analysis.dynamic_analyzer import DynamicRelationshipAnalyzer
from .advanced_analysis.type_inference_engine import TypeInferenceEngine, PyType
from .advanced_analysis.context_sensitive_analyzer import ContextSensitiveAnalyzer


class DynamicCallGraphBuilder:
    def __init__(self, framework_hint: str, project_root_path: str = ""):
        self.framework_to_analyze_as = framework_hint
        self.project_root_path = project_root_path
        self.relationship_analyzer = DynamicRelationshipAnalyzer()
        self.type_engine = TypeInferenceEngine()
        self.context_analyzer = ContextSensitiveAnalyzer(k=2)
        self.current_file_graph: Dict[str, List[Dict[str, Any]]] = {
            "nodes": [],
            "links": [],
        }
        self.current_file_node_ids: Set[str] = set()

    def _add_node_to_current_file_graph(
        self, node_id: str, node_type: str, file_path: str = "", metadata: Dict = None
    ):
        if node_id not in self.current_file_node_ids:
            full_metadata = metadata or {}
            if file_path and "file_path" not in full_metadata:
                full_metadata["file_path"] = file_path
            if node_type == "module" and "category" not in full_metadata:
                full_metadata["category"] = "module"
                if file_path.endswith("__init__.py"):
                    full_metadata["category"] = "package_init"
            elif node_type == "class" and "category" not in full_metadata:
                full_metadata["category"] = "class_definition"
            elif node_type == "function" and "category" not in full_metadata:
                full_metadata["category"] = "function_definition"
            self.current_file_graph["nodes"].append(
                {"id": node_id, "type": node_type, "metadata": full_metadata}
            )
            self.current_file_node_ids.add(node_id)

    def _add_link_to_current_file_graph(
        self,
        source_id: str,
        target_id: str,
        rel_type: RelationshipType,
        metadata: Dict = None,
    ):
        metadata = metadata or {}
        file_path = metadata.get("file_path", "")
        if source_id not in self.current_file_node_ids:
            if self._is_external_entity(source_id):
                source_type = self._infer_node_type_from_id(source_id)
                self._add_placeholder_node(source_id, source_type, file_path)
            else:
                source_type = self._infer_node_type_from_id(source_id)
                self._add_node_to_current_file_graph(
                    source_id, source_type, file_path, {"category": "fallback_node"}
                )
        if target_id not in self.current_file_node_ids:
            if self._is_external_entity(target_id):
                target_type = self._infer_node_type_from_id(target_id)
                self._add_placeholder_node(target_id, target_type, file_path)
            else:
                target_type = self._infer_node_type_from_id(target_id)
                self._add_node_to_current_file_graph(
                    target_id, target_type, file_path, {"category": "fallback_node"}
                )
        link_data = {
            "source": source_id,
            "target": target_id,
            "type": rel_type.name,
            "metadata": metadata,
        }
        link_key_tuple = (
            source_id,
            target_id,
            rel_type.name,
            json.dumps(metadata, sort_keys=True),
        )
        self.current_file_graph["links"].append(link_data)

    def build_callgraph_for_file(
        self, ast_root: ast.AST, file_path: str = ""
    ) -> Dict[str, List[Dict[str, Any]]]:
        self.current_file_graph = {"nodes": [], "links": []}
        self.current_file_node_ids = set()
        initial_types = self.type_engine.infer_types(ast_root)
        module_name = self._get_module_name(file_path)
        self._add_node_to_current_file_graph(
            node_id=module_name, node_type="module", file_path=file_path
        )
        self._analyze_node(
            ast_root,
            context=[module_name] if module_name else [],
            current_types=initial_types.copy(),
            file_path=file_path,
        )
        return self.current_file_graph

    def get_analysis_metadata(self) -> Dict[str, Any]:
        """Returns metadata about the analysis performed by this builder instance."""
        return {
            "framework_analyzed_as": self.framework_to_analyze_as,
            "context_sensitivity_k": self.context_analyzer.k,
        }

    def _get_module_name(self, file_path: str) -> str:
        if not file_path:
            return "<unknown_module>"
        if not self.project_root_path:
            return os.path.splitext(os.path.basename(file_path))[0]
        try:
            relative_path = os.path.relpath(file_path, self.project_root_path)
            module_path = os.path.splitext(relative_path)[0]
            return module_path.replace(os.sep, ".")
        except ValueError:
            return os.path.splitext(os.path.basename(file_path))[0]

    def _qualify_name(self, name: str, context: List[str]) -> str:
        if not context or len(context) == 1:
            return f"{context[0] if context else self._get_module_name('')}.{name}"
        return ".".join(context + [name])

    def _analyze_node(
        self,
        node: ast.AST,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        node_type_name = type(node).__name__
        handler_name = f"_analyze_{node_type_name.lower()}"
        handler = getattr(self, handler_name, self._analyze_generic_node)
        handler(node, context, current_types, file_path)

    def _analyze_generic_node(
        self,
        node: ast.AST,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        for child_node in ast.iter_child_nodes(node):
            self._analyze_node(child_node, context, current_types, file_path)

    def _analyze_module(
        self,
        node: ast.Module,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        module_context = context[:1]
        for stmt in node.body:
            self._analyze_node(stmt, module_context, current_types, file_path)

    def _analyze_functiondef(
        self,
        node: ast.FunctionDef,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        func_name = node.name
        full_func_name = self._qualify_name(func_name, context)
        node_metadata = {
            "args": [arg.arg for arg in node.args.args],
            "lineno": node.lineno,
            "file_path": file_path,
        }
        self._add_node_to_current_file_graph(
            node_id=full_func_name, node_type="function", metadata=node_metadata
        )
        analysis_ctx = {
            "current_module": (
                context[0] if context else self._get_module_name(file_path)
            ),
            "current_class": (
                context[1]
                if len(context) > 1 and self._is_class_context_heuristic(context[1])
                else None
            ),
            "current_function": func_name,
            "file_path": file_path,
            "project_root": self.project_root_path,
        }
        relationships = self.relationship_analyzer.analyze(
            self.framework_to_analyze_as, node, analysis_ctx
        )
        for rel in relationships:
            self._add_link_to_current_file_graph(
                rel.source or full_func_name, rel.target, rel.type, rel.metadata
            )
        new_context = context + [func_name]
        for stmt in node.body:
            self._analyze_node(stmt, new_context, current_types, file_path)

    def _analyze_classdef(
        self,
        node: ast.ClassDef,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ):
        class_name = node.name
        full_class_name = self._qualify_name(class_name, context)
        base_names = []
        for base in node.bases:
            base_name_str = ast.unparse(base)
            resolved_base_name = base_name_str
            inferred_type_for_base = current_types.get(base_name_str)
            if isinstance(inferred_type_for_base, str):
                resolved_base_name = inferred_type_for_base
            base_names.append(resolved_base_name)
        node_metadata = {
            "bases": base_names,
            "lineno": node.lineno,
            "file_path": file_path,
        }
        self._add_node_to_current_file_graph(
            node_id=full_class_name, node_type="class", metadata=node_metadata
        )
        for base_name_str in base_names:
            self._add_link_to_current_file_graph(
                full_class_name,
                base_name_str,
                RelationshipType.INHERITANCE,
                {"file_path": file_path},
            )
        analysis_ctx = {
            "current_module": (
                context[0] if context else self._get_module_name(file_path)
            ),
            "current_class": class_name,
            "file_path": file_path,
            "project_root": self.project_root_path,
        }
        relationships = self.relationship_analyzer.analyze(
            self.framework_to_analyze_as, node, analysis_ctx
        )
        for rel in relationships:
            self._add_link_to_current_file_graph(
                rel.source or full_class_name, rel.target, rel.type, rel.metadata
            )
        new_context = context + [class_name]
        for stmt in node.body:
            self._analyze_node(stmt, new_context, current_types, file_path)

    def _analyze_call(
        self,
        node: ast.Call,
        context: List[str],
        current_types: Dict[str, PyType],
        file_path: str,
    ) -> None:
        caller_name = ".".join(context) if context else "__main__"
        if isinstance(node.func, ast.Name):
            func_name = node.func.id
            target_name = self._qualify_name(func_name, context[:-1] if context else [])
            if target_name == func_name and "__main__" not in target_name:
                module_name = self._get_module_name(file_path)
                if module_name:
                    alternative_target = f"{module_name}.{func_name}"
                    if self.type_engine and self.type_engine.is_known_global(
                        alternative_target
                    ):
                        target_name = alternative_target
            if func_name in [
                "render",
                "redirect",
                "get_object_or_404",
                "Q",
                "path",
                "include",
                "static",
                "reverse",
            ]:
                target_name = (
                    f"django.{func_name}" if func_name != "Q" else "django.db.models.Q"
                )
            if func_name in [
                "ForeignKey",
                "OneToOneField",
                "ManyToManyField",
                "CharField",
                "TextField",
                "DateTimeField",
                "ImageField",
                "FileField",
                "BooleanField",
            ]:
                target_name = f"django.db.models.{func_name}"
                if (
                    func_name in ["ForeignKey", "OneToOneField", "ManyToManyField"]
                    and node.args
                ):
                    if isinstance(node.args[0], ast.Name):
                        related_model = node.args[0].id
                        if len(context) >= 2 and self._is_class_context_heuristic(
                            context[-2].split(".")[-1]
                        ):
                            current_model = context[-2]
                            relationship_metadata = {"relationship_type": func_name}
                            self._add_link_to_current_file_graph(
                                current_model.split(".")[-1],
                                related_model,
                                RelationshipType.MODEL_ACCESS,
                                relationship_metadata,
                            )
        elif isinstance(node.func, ast.Attribute):
            value_node = node.func.value
            attr_name = node.func.attr
            if isinstance(value_node, ast.Name):
                var_name = value_node.id
                var_type = None
                if var_name in current_types:
                    var_type = current_types[var_name]
                if var_type:
                    if isinstance(var_type, str):
                        target_name = f"{var_type}.{attr_name}"
                    else:
                        if hasattr(var_type, "qualified_name"):
                            target_name = f"{var_type.qualified_name}.{attr_name}"
                        else:
                            target_name = f"<UnknownClass>.{attr_name}"
                else:
                    if var_name == "self" and len(context) >= 1:
                        if len(context) >= 2 and self._is_class_context_heuristic(
                            context[-2].split(".")[-1]
                        ):
                            class_name = context[-2]
                            target_name = f"{class_name}.{attr_name}"
                        else:
                            target_name = f"<UnknownClass>.{attr_name}"
                    else:
                        module_prefix = (
                            ".".join(context[0:-1])
                            if len(context) > 1
                            else self._get_module_name(file_path)
                        )
                        if self._is_class_context_heuristic(var_name):
                            potential_class_name = (
                                f"{module_prefix}.{var_name}"
                                if module_prefix
                                else var_name
                            )
                            target_name = f"{potential_class_name}.{attr_name}"
                        else:
                            target_name = f"{var_name}.{attr_name}"
                if var_name in ["models"] and attr_name in [
                    "Model",
                    "CharField",
                    "TextField",
                    "ForeignKey",
                    "OneToOneField",
                    "ManyToManyField",
                    "DateTimeField",
                    "ImageField",
                    "FileField",
                ]:
                    target_name = f"django.db.models.{attr_name}"
                if var_name in ["forms"] and attr_name in [
                    "ModelForm",
                    "Form",
                    "CharField",
                    "EmailField",
                ]:
                    target_name = f"django.forms.{attr_name}"
            else:
                target_name = f"<ComplexCall>.{attr_name}"
        else:
            target_name = "<DynamicCall>"
        call_analysis_context = {
            "current_module": (
                context[0] if context else self._get_module_name(file_path)
            ),
            "current_class": (
                context[1]
                if len(context) > 1 and self._is_class_context_heuristic(context[1])
                else None
            ),
            "current_function": (
                context[-1]
                if len(context) > 1
                and not self._is_class_context_heuristic(context[-1])
                else (
                    context[-2]
                    if len(context) > 2
                    and not self._is_class_context_heuristic(context[-2])
                    else None
                )
            ),
            "file_path": file_path,
            "caller_name": caller_name,
            "project_root": self.project_root_path,
        }
        relationships = self.relationship_analyzer.analyze(
            self.framework_to_analyze_as, node, call_analysis_context
        )
        for rel in relationships:
            self._add_link_to_current_file_graph(
                rel.source or caller_name, rel.target, rel.type, rel.metadata
            )
        call_metadata = {
            "resolution": "context_sensitive",
            "lineno": node.lineno,
            "file_path": file_path,
        }
        self._add_link_to_current_file_graph(
            caller_name, target_name, RelationshipType.FUNCTION_CALL, call_metadata
        )
        for arg_node in node.args:
            self._analyze_node(arg_node, context, current_types, file_path)
        for kwarg_node in node.keywords:
            self._analyze_node(kwarg_node.value, context, current_types, file_path)
        self._analyze_node(node.func, context, current_types, file_path)

    def _is_class_context_heuristic(self, name_part: str) -> bool:
        return name_part and name_part[0].isupper()

    def _is_external_entity(self, node_id: str) -> bool:
        """Determine if a node ID represents an external entity that needs a placeholder."""
        external_patterns = [
            "<UnknownClass>",
            "models.Model",
            "ImportError",
            "UserCreationForm",
            "forms.ModelForm",
            "AppConfig",
            "ListView",
            "DetailView",
            "CreateView",
            "UpdateView",
            "DeleteView",
            "LoginRequiredMixin",
            "UserPassesTestMixin",
        ]
        if any(pattern in node_id for pattern in external_patterns):
            return True
        if "." not in node_id and node_id[0].isupper():
            return True
        return False

    def _infer_node_type_from_id(self, node_id: str) -> str:
        """Infer the type of node based on its ID pattern."""
        node_type = "module"
        if "<UnknownClass>" in node_id:
            node_type = "class"
        elif "." in node_id and node_id.split(".")[-1][0].islower():
            node_type = "function"
        elif "." in node_id and node_id.split(".")[-1][0].isupper():
            node_type = "class"
        elif node_id[0].isupper() and "." not in node_id:
            node_type = "class"
        return node_type

    def _add_placeholder_node(self, node_id: str, node_type: str, file_path: str = ""):
        """Add a placeholder node for an external or unresolved entity."""
        metadata = {"category": "external_entity", "is_placeholder": True}
        if file_path:
            metadata["file_path"] = file_path
        if "<UnknownClass>" in node_id:
            metadata["category"] = "unresolved_class"
        elif node_id[0].isupper() and "." not in node_id:
            metadata["category"] = "external_class"
        if node_type == "function" and any(
            field in node_id
            for field in ["Field", "CharField", "TextField", "ForeignKey"]
        ):
            metadata["category"] = "model_field"
        self._add_node_to_current_file_graph(node_id, node_type, file_path, metadata)


if __name__ == "__main__":
    source_code = """
class Greeter:
    def __init__(self, name):
        self.name = name
    def greet(self):
        print(f"Hello, {self.name}!")
class Person:
    def __init__(self, greeter: Greeter):
        self.greeter = greeter
    def introduce(self):
        self.greeter.greet()
def main_func():
    g = Greeter("World")
    p = Person(g)
    p.introduce()
main_func()
"""
    ast_tree = ast.parse(source_code)
    builder = DynamicCallGraphBuilder(
        framework_hint="generic", project_root_path="/dummy/project"
    )
    file_graph_data = builder.build_callgraph_for_file(
        ast_tree, file_path="/dummy/project/example.py"
    )
    print("--- File Specific Graph ---")
    print(json.dumps(file_graph_data, indent=2))
    metadata = builder.get_analysis_metadata()
    print("\n--- Analysis Metadata ---")
    print(json.dumps(metadata, indent=2))
