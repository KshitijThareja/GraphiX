import ast
from typing import Dict, List, Optional
from . import Relationship, RelationshipType


class DynamicRelationshipAnalyzer:
    def __init__(self):
        self.relationship_handlers = {
            "django": self._analyze_django_relationships,
            "flask": self._analyze_flask_relationships,
            "fastapi": self._analyze_fastapi_relationships,
        }

    def analyze(
        self, framework: str, ast_node: ast.AST, context: Dict
    ) -> List[Relationship]:
        handler = self.relationship_handlers.get(framework)
        if handler:
            return handler(ast_node, context)
        return self._analyze_generic_relationships(ast_node, context)

    def _analyze_django_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.Call):
            if (
                isinstance(node.func, ast.Attribute)
                and hasattr(node.func.value, "id")
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "models"
                and node.func.attr in ["ForeignKey", "OneToOneField", "ManyToManyField"]
            ):
                target_model = (
                    node.args[0].id
                    if node.args and isinstance(node.args[0], ast.Name)
                    else "unknown"
                )
                relationships.append(
                    Relationship(
                        source=context.get("current_class", ""),
                        target=target_model,
                        type=RelationshipType.MODEL_ACCESS,
                        metadata={"relationship_type": node.func.attr},
                    )
                )
        return relationships

    def _analyze_flask_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Attribute
                ):
                    if decorator.func.attr == "route":
                        route_path = (
                            decorator.args[0].s
                            if decorator.args
                            and isinstance(decorator.args[0], ast.Constant)
                            else "unknown_route"
                        )
                        relationships.append(
                            Relationship(
                                source=context.get("module_name", "flask_app"),
                                target=node.name,
                                type=RelationshipType.URL_ROUTE,
                                metadata={"path": route_path, "framework": "flask"},
                            )
                        )
        return relationships

    def _analyze_fastapi_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.FunctionDef):
            for decorator in node.decorator_list:
                if isinstance(decorator, ast.Call) and isinstance(
                    decorator.func, ast.Attribute
                ):
                    if decorator.func.attr in [
                        "get",
                        "post",
                        "put",
                        "delete",
                        "patch",
                        "head",
                        "options",
                        "trace",
                    ]:
                        route_path = (
                            decorator.args[0].s
                            if decorator.args
                            and isinstance(decorator.args[0], ast.Constant)
                            else "unknown_route"
                        )
                        relationships.append(
                            Relationship(
                                source=context.get("module_name", "fastapi_app"),
                                target=node.name,
                                type=RelationshipType.URL_ROUTE,
                                metadata={
                                    "path": route_path,
                                    "method": decorator.func.attr.upper(),
                                    "framework": "fastapi",
                                },
                            )
                        )
        return relationships

    def _analyze_generic_relationships(
        self, node: ast.AST, context: Dict
    ) -> List[Relationship]:
        relationships = []
        if isinstance(node, ast.Call):
            func_name = ""
            if isinstance(node.func, ast.Name):
                func_name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                path_parts = []
                curr_attr = node.func
                while isinstance(curr_attr, ast.Attribute):
                    path_parts.append(curr_attr.attr)
                    curr_attr = curr_attr.value
                if isinstance(curr_attr, ast.Name):
                    path_parts.append(curr_attr.id)
                    func_name = ".".join(reversed(path_parts))
                else:
                    func_name = path_parts[0] if path_parts else "complex_call_target"
            if func_name:
                source_name = context.get(
                    "current_function",
                    context.get(
                        "current_class", context.get("module_name", "unknown_source")
                    ),
                )
                relationships.append(
                    Relationship(
                        source=source_name,
                        target=func_name,
                        type=RelationshipType.FUNCTION_CALL,
                    )
                )
        if isinstance(node, ast.ClassDef):
            class_name = node.name
            for base in node.bases:
                base_name = ""
                if isinstance(base, ast.Name):
                    base_name = base.id
                elif isinstance(base, ast.Attribute):
                    parts = []
                    curr = base
                    while isinstance(curr, ast.Attribute):
                        parts.append(curr.attr)
                        curr = curr.value
                    if isinstance(curr, ast.Name):
                        parts.append(curr.id)
                    base_name = ".".join(reversed(parts))
                if base_name:
                    relationships.append(
                        Relationship(
                            source=class_name,
                            target=base_name,
                            type=RelationshipType.INHERITANCE,
                        )
                    )
        return relationships
