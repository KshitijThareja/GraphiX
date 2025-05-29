import ast
import logging
from typing import Dict, List, Set, Optional, Tuple, Any, Union

logger = logging.getLogger(__name__)


class DynamicCallAnalyzer:
    def __init__(self, definition_manager=None):
        self.definition_manager = definition_manager
        self.dynamic_calls: List[Dict[str, Any]] = []

    def analyze_node(
        self, node: ast.AST, module_context: str = None
    ) -> List[Dict[str, Any]]:
        self.dynamic_calls = []
        self.module_context = module_context
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                self._analyze_call(subnode)
        return self.dynamic_calls

    def _analyze_call(self, node: ast.Call) -> None:
        if self._is_getattr_call(node):
            self._handle_getattr_call(node)
        elif self._is_dict_dispatch(node):
            self._handle_dict_dispatch(node)
        elif self._is_dynamic_import(node):
            self._handle_dynamic_import(node)
        elif self._is_apply_pattern(node):
            self._handle_apply_pattern(node)
        elif self._is_dependency_injection(node):
            self._handle_dependency_injection(node)

    def _is_getattr_call(self, node: ast.Call) -> bool:
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id == "getattr"
        ):
            return True
        if isinstance(node.func, ast.Name) and hasattr(node, "getattr_info"):
            return True
        return False

    def _handle_getattr_call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Call)
            and isinstance(node.func.func, ast.Name)
            and node.func.func.id == "getattr"
        ):
            if len(node.func.args) >= 2 and isinstance(node.func.args[1], ast.Str):
                obj_node = node.func.args[0]
                method_name = node.func.args[1].s
                obj_type = self._get_node_type(obj_node)
                self.dynamic_calls.append(
                    {
                        "type": "getattr",
                        "object_type": obj_type,
                        "method_name": method_name,
                        "node": node,
                        "possible_targets": self._resolve_getattr_targets(
                            obj_node, method_name
                        ),
                    }
                )

    def _is_dict_dispatch(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Subscript):
            return True
        return False

    def _handle_dict_dispatch(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Subscript):
            dict_name = self._get_node_name(node.func.value)
            key_repr = self._get_subscript_key_repr(node.func.slice)
            self.dynamic_calls.append(
                {
                    "type": "dict_dispatch",
                    "dict_name": dict_name,
                    "key": key_repr,
                    "node": node,
                    "possible_targets": self._resolve_dict_dispatch_targets(
                        node.func.value, node.func.slice
                    ),
                }
            )

    def _is_dynamic_import(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            return True
        if isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if node.func.value.id == "importlib" and node.func.attr == "import_module":
                return True
        return False

    def _handle_dynamic_import(self, node: ast.Call) -> None:
        module_name = None
        if isinstance(node.func, ast.Name) and node.func.id == "__import__":
            if node.args and isinstance(node.args[0], ast.Str):
                module_name = node.args[0].s
        elif isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            if node.func.value.id == "importlib" and node.func.attr == "import_module":
                if node.args and isinstance(node.args[0], ast.Str):
                    module_name = node.args[0].s
        if module_name:
            self.dynamic_calls.append(
                {
                    "type": "dynamic_import",
                    "module_name": module_name,
                    "node": node,
                    "possible_targets": [module_name],
                }
            )

    def _is_apply_pattern(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Name) and node.func.id in (
            "map",
            "filter",
            "apply",
        ):
            return True
        return False

    def _handle_apply_pattern(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Name) and node.func.id in ("map", "filter"):
            if node.args and isinstance(node.args[0], ast.Name):
                func_name = node.args[0].id
                self.dynamic_calls.append(
                    {
                        "type": "higher_order",
                        "function": node.func.id,
                        "argument_function": func_name,
                        "node": node,
                        "possible_targets": self._resolve_name(func_name),
                    }
                )

    def _is_dependency_injection(self, node: ast.Call) -> bool:
        if isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id in (
                "container",
                "provider",
                "injector",
            ):
                if node.func.attr in ("get", "provide", "inject"):
                    return True
        return False

    def _handle_dependency_injection(self, node: ast.Call) -> None:
        if isinstance(node.func, ast.Attribute) and isinstance(
            node.func.value, ast.Name
        ):
            container_name = node.func.value.id
            method_name = node.func.attr
            if node.args and isinstance(node.args[0], ast.Str):
                service_name = node.args[0].s
                self.dynamic_calls.append(
                    {
                        "type": "dependency_injection",
                        "container": container_name,
                        "method": method_name,
                        "service": service_name,
                        "node": node,
                        "possible_targets": [service_name],
                    }
                )

    def _get_node_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            value_name = self._get_node_name(node.value)
            if value_name:
                return f"{value_name}.{node.attr}"
        return None

    def _get_node_type(self, node: ast.AST) -> str:
        if isinstance(node, ast.Name):
            if self.definition_manager:
                qualified_names = self.definition_manager.resolve_name(
                    node.id, self.module_context
                )
                if qualified_names:
                    for qname in qualified_names:
                        if qname in self.definition_manager.classes:
                            return qname
            return f"variable:{node.id}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return f"call_result:{node.func.id}"
            elif isinstance(node.func, ast.Attribute):
                return f"call_result:{self._get_node_name(node.func)}"
        elif isinstance(node, ast.Str):
            return "str"
        elif isinstance(node, ast.Num):
            return "num"
        elif isinstance(node, ast.Dict):
            return "dict"
        elif isinstance(node, ast.List):
            return "list"
        return "unknown"

    def _get_subscript_key_repr(self, node: ast.AST) -> str:
        if isinstance(node, ast.Index):
            return self._get_subscript_key_repr(node.value)
        elif isinstance(node, ast.Str):
            return f"'{node.s}'"
        elif isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            return f"{self._get_node_name(node)}"
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                return f"{node.func.id}(...)"
        return "unknown_key"

    def _resolve_name(self, name: str) -> List[str]:
        if self.definition_manager:
            return self.definition_manager.resolve_name(name, self.module_context)
        return [name]

    def _resolve_getattr_targets(
        self, obj_node: ast.AST, method_name: str
    ) -> List[str]:
        targets = []
        if isinstance(obj_node, ast.Name) and self.definition_manager:
            obj_name = obj_node.id
            qualified_names = self.definition_manager.resolve_name(
                obj_name, self.module_context
            )
            for qname in qualified_names:
                if qname in self.definition_manager.classes:
                    class_def = self.definition_manager.classes[qname]
                    method_qname = f"{qname}.{method_name}"
                    if method_qname in self.definition_manager.functions:
                        targets.append(method_qname)
                    else:
                        for base in class_def.base_classes:
                            base_method = f"{base}.{method_name}"
                            if base_method in self.definition_manager.functions:
                                targets.append(base_method)
        return targets

    def _resolve_dict_dispatch_targets(
        self, dict_node: ast.AST, key_node: ast.AST
    ) -> List[str]:
        targets = []
        if isinstance(key_node, ast.Index) and isinstance(key_node.value, ast.Str):
            key_str = key_node.value.s
            if isinstance(dict_node, ast.Name) and hasattr(dict_node, "parent_scope"):
                parent_scope = dict_node.parent_scope
                for node in ast.walk(parent_scope):
                    if isinstance(node, ast.Assign) and any(
                        isinstance(target, ast.Name) and target.id == dict_node.id
                        for target in node.targets
                    ):
                        if isinstance(node.value, ast.Dict):
                            for i, k in enumerate(node.value.keys):
                                if (
                                    isinstance(k, ast.Str)
                                    and k.s == key_str
                                    and i < len(node.value.values)
                                ):
                                    value = node.value.values[i]
                                    if isinstance(value, ast.Name):
                                        targets.extend(self._resolve_name(value.id))
        return targets
