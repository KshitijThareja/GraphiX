import ast
from typing import Dict, List, Optional, Set, Any, Tuple
import os


class Definition:
    def __init__(self, name: str, qualified_name: str, node: ast.AST, file_path: str):
        self.name = name
        self.qualified_name = qualified_name
        self.node = node
        self.file_path = file_path
        self.references: List[Tuple[ast.AST, str]] = []
        self.lineno = getattr(node, "lineno", 0)
        self.end_lineno = getattr(node, "end_lineno", 0)

    def add_reference(self, node: ast.AST, file_path: str) -> None:
        self.references.append((node, file_path))

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} {self.qualified_name}>"


class FunctionDefinition(Definition):
    def __init__(
        self, name: str, qualified_name: str, node: ast.FunctionDef, file_path: str
    ):
        super().__init__(name, qualified_name, node, file_path)
        self.is_method = False
        self.class_name = None
        self.parameters = []
        self.return_type = None
        self.docstring = ast.get_docstring(node)
        self.calls: List[Tuple[str, ast.Call]] = []
        self.complexity = 1
        self.is_async = isinstance(node, ast.AsyncFunctionDef)
        if hasattr(node, "args"):
            self._extract_parameters(node.args)
        if "." in qualified_name:
            parent_name = qualified_name.rsplit(".", 1)[0]
            if parent_name:
                self.is_method = True
                self.class_name = parent_name

    def _extract_parameters(self, args: ast.arguments) -> None:
        if hasattr(args, "args"):
            for arg in args.args:
                param_name = getattr(arg, "arg", None)
                if param_name:
                    self.parameters.append(param_name)
        if hasattr(args, "vararg") and args.vararg:
            vararg_name = getattr(args.vararg, "arg", args.vararg)
            if vararg_name:
                self.parameters.append(f"*{vararg_name}")
        if hasattr(args, "kwonlyargs"):
            for kwarg in args.kwonlyargs:
                param_name = getattr(kwarg, "arg", None)
                if param_name:
                    self.parameters.append(param_name)
        if hasattr(args, "kwarg") and args.kwarg:
            kwarg_name = getattr(args.kwarg, "arg", args.kwarg)
            if kwarg_name:
                self.parameters.append(f"**{kwarg_name}")

    def add_call(self, target_qualified_name: str, call_node: ast.Call) -> None:
        self.calls.append((target_qualified_name, call_node))

    def calculate_complexity(self) -> int:
        complexity = 1
        for node in ast.walk(self.node):
            if isinstance(node, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
                complexity += len(node.values) - 1
            elif isinstance(node, ast.Try):
                complexity += len(node.handlers)
        self.complexity = complexity
        return complexity


class ClassDefinition(Definition):
    def __init__(
        self, name: str, qualified_name: str, node: ast.ClassDef, file_path: str
    ):
        super().__init__(name, qualified_name, node, file_path)
        self.methods: Dict[str, FunctionDefinition] = {}
        self.attributes: Dict[str, Any] = {}
        self.base_classes: List[str] = []
        self.docstring = ast.get_docstring(node)
        for base in node.bases:
            if isinstance(base, ast.Name):
                self.base_classes.append(base.id)
            elif isinstance(base, ast.Attribute):
                self.base_classes.append(self._get_attribute_name(base))

    def _get_attribute_name(self, node: ast.Attribute) -> str:
        if isinstance(node.value, ast.Name):
            return f"{node.value.id}.{node.attr}"
        elif isinstance(node.value, ast.Attribute):
            return f"{self._get_attribute_name(node.value)}.{node.attr}"
        return node.attr

    def add_method(self, method: FunctionDefinition) -> None:
        if method.name not in self.methods:
            self.methods[method.name] = method
            method.is_method = True
            method.class_name = self.qualified_name

    def add_attribute(self, name: str, value: Any) -> None:
        self.attributes[name] = value


class DefinitionManager:
    def __init__(self):
        self.functions: Dict[str, FunctionDefinition] = {}
        self.classes: Dict[str, ClassDefinition] = {}
        self.modules: Dict[str, str] = {}
        self.qualified_names: Dict[str, str] = {}

    def add_function(
        self, node: ast.FunctionDef, module_name: str, file_path: str
    ) -> FunctionDefinition:
        name = node.name
        qualified_name = f"{module_name}.{name}" if module_name else name
        func_def = FunctionDefinition(name, qualified_name, node, file_path)
        self.functions[qualified_name] = func_def
        if name not in self.qualified_names:
            self.qualified_names[name] = set()
        self.qualified_names[name].add(qualified_name)
        return func_def

    def add_class(
        self, node: ast.ClassDef, module_name: str, file_path: str
    ) -> ClassDefinition:
        name = node.name
        qualified_name = f"{module_name}.{name}" if module_name else name
        class_def = ClassDefinition(name, qualified_name, node, file_path)
        self.classes[qualified_name] = class_def
        if name not in self.qualified_names:
            self.qualified_names[name] = set()
        self.qualified_names[name].add(qualified_name)
        for item in node.body:
            if isinstance(item, ast.FunctionDef):
                method_name = item.name
                method_qualified_name = f"{qualified_name}.{method_name}"
                method_def = FunctionDefinition(
                    method_name, method_qualified_name, item, file_path
                )
                method_def.is_method = True
                method_def.class_name = qualified_name
                self.functions[method_qualified_name] = method_def
                class_def.add_method(method_def)
                if method_name not in self.qualified_names:
                    self.qualified_names[method_name] = set()
                self.qualified_names[method_name].add(method_qualified_name)
        return class_def

    def add_module(self, module_name: str, file_path: str) -> None:
        self.modules[module_name] = file_path

    def get_function(self, qualified_name: str) -> Optional[FunctionDefinition]:
        return self.functions.get(qualified_name)

    def get_class(self, qualified_name: str) -> Optional[ClassDefinition]:
        return self.classes.get(qualified_name)

    def get_module_path(self, module_name: str) -> Optional[str]:
        return self.modules.get(module_name)

    def resolve_name(self, name: str, module_context: str = None) -> List[str]:
        qualified_names = []
        if name in self.qualified_names:
            qualified_names.extend(self.qualified_names[name])
        if module_context:
            module_qualified = f"{module_context}.{name}"
            if module_qualified in self.functions or module_qualified in self.classes:
                qualified_names.append(module_qualified)
            for func_name in self.functions:
                if func_name.endswith(f".{name}"):
                    qualified_names.append(func_name)
            for class_name in self.classes:
                if class_name.endswith(f".{name}"):
                    qualified_names.append(class_name)
        return qualified_names

    def resolve_call(self, node: ast.Call, module_context: str = None) -> List[str]:
        targets = []
        if isinstance(node.func, ast.Name):
            name = node.func.id
            targets.extend(self.resolve_name(name, module_context))
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name):
                obj_name = node.func.value.id
                method_name = node.func.attr
                if obj_name == "self" and module_context:
                    if "." in module_context:
                        class_context = module_context.rsplit(".", 1)[0]
                        qualified_method = f"{class_context}.{method_name}"
                        if qualified_method in self.functions:
                            targets.append(qualified_method)
                obj_targets = self.resolve_name(obj_name, module_context)
                for obj_target in obj_targets:
                    if obj_target in self.classes:
                        class_def = self.classes[obj_target]
                        qualified_method = f"{obj_target}.{method_name}"
                        if qualified_method in self.functions:
                            targets.append(qualified_method)
            elif isinstance(node.func.value, ast.Attribute):
                attr_name = self._get_attribute_name(node.func)
                if attr_name:
                    if attr_name in self.functions:
                        targets.append(attr_name)
                    parts = attr_name.split(".")
                    for i in range(1, len(parts)):
                        prefix = ".".join(parts[:i])
                        suffix = ".".join(parts[i:])
                        prefix_targets = self.resolve_name(prefix, module_context)
                        for prefix_target in prefix_targets:
                            qualified_name = f"{prefix_target}.{suffix}"
                            if qualified_name in self.functions:
                                targets.append(qualified_name)
        return targets

    def _get_attribute_name(self, node: ast.Attribute) -> str:
        parts = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.insert(0, current.attr)
            current = current.value
        if isinstance(current, ast.Name):
            parts.insert(0, current.id)
            return ".".join(parts)
        return None

    def analyze_file(self, file_path: str, tree: Optional[ast.AST] = None) -> None:
        if tree is None:
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    content = f.read()
            except Exception as e:
                print(f"Error reading file {file_path}: {e}")
                return
            try:
                tree = ast.parse(content, filename=file_path)
            except SyntaxError as e:
                print(f"Syntax error in {file_path}: {e}")
                return
        for node_walker in ast.walk(tree):
            for child in ast.iter_child_nodes(node_walker):
                child.parent = node_walker
        module_name = os.path.splitext(os.path.basename(file_path))[0]
        self.add_module(module_name, file_path)
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) or isinstance(
                node, ast.AsyncFunctionDef
            ):
                if isinstance(node.parent, ast.Module):
                    self.add_function(node, module_name, file_path)
            elif isinstance(node, ast.ClassDef):
                if isinstance(node.parent, ast.Module):
                    self.add_class(node, module_name, file_path)
        for func_name, func_def in self.functions.items():
            self._analyze_function_calls(func_def, module_name)

    def _analyze_function_calls(
        self, func_def: FunctionDefinition, module_context: str
    ) -> None:
        for node in ast.walk(func_def.node):
            if isinstance(node, ast.Call):
                targets = self.resolve_call(node, module_context)
                for target in targets:
                    func_def.add_call(target, node)
        func_def.calculate_complexity()
