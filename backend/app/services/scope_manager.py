import ast
from typing import Dict, Optional, List, Any, Set


class Scope:
    def __init__(
        self,
        parent: Optional["Scope"] = None,
        name: str = "unknown",
        scope_type: str = "module",
    ):
        self.parent = parent
        self.name = name
        self.scope_type = scope_type
        self.children: List[Scope] = []
        self.variables: Dict[str, "Variable"] = {}
        self.defined_functions: Dict[str, "FunctionDefinition"] = {}
        self.defined_classes: Dict[str, "ClassDefinition"] = {}

    def add_variable(
        self, name: str, value_type: str = None, definition_node: ast.AST = None
    ) -> "Variable":
        var = Variable(name, value_type, definition_node, self)
        self.variables[name] = var
        return var

    def get_variable(self, name: str) -> Optional["Variable"]:
        return self.variables.get(name)

    def __repr__(self) -> str:
        return f"<Scope {self.scope_type}:{self.name}>"


class Variable:
    def __init__(
        self,
        name: str,
        value_type: str = None,
        definition_node: ast.AST = None,
        scope: Scope = None,
    ):
        self.name = name
        self.possible_types: Set[str] = {value_type} if value_type else set()
        self.definitions: List[ast.AST] = [definition_node] if definition_node else []
        self.scope = scope
        self.references: List[ast.AST] = []

    def add_type(self, value_type: str) -> None:
        if value_type:
            self.possible_types.add(value_type)

    def add_definition(self, node: ast.AST) -> None:
        if node and node not in self.definitions:
            self.definitions.append(node)

    def add_reference(self, node: ast.AST) -> None:
        if node and node not in self.references:
            self.references.append(node)

    def __repr__(self) -> str:
        types_str = ", ".join(self.possible_types) if self.possible_types else "unknown"
        return f"<Variable {self.name}: {types_str}>"


class ScopeManager:
    def __init__(self):
        self.global_scope = Scope(None, "global", "module")
        self.current_scope = self.global_scope

    def enter_scope(self, name: str, scope_type: str) -> Scope:
        new_scope = Scope(self.current_scope, name, scope_type)
        self.current_scope.children.append(new_scope)
        self.current_scope = new_scope
        return new_scope

    def exit_scope(self) -> Optional[Scope]:
        if self.current_scope.parent:
            self.current_scope = self.current_scope.parent
            return self.current_scope
        return None

    def lookup_variable(self, name: str) -> Optional[Variable]:
        scope = self.current_scope
        while scope:
            if name in scope.variables:
                return scope.variables[name]
            scope = scope.parent
        return None

    def add_variable(
        self, name: str, value_type: str = None, definition_node: ast.AST = None
    ) -> Variable:
        return self.current_scope.add_variable(name, value_type, definition_node)

    def process_assignment(self, node: ast.Assign) -> None:
        value_type = self._infer_type_of_node(node.value)
        for target in node.targets:
            if isinstance(target, ast.Name):
                var_name = target.id
                var = self.lookup_variable(var_name)
                if var:
                    var.add_type(value_type)
                    var.add_definition(node)
                else:
                    self.add_variable(var_name, value_type, node)
            elif isinstance(target, ast.Tuple) or isinstance(target, ast.List):
                self._process_unpacking_assignment(target, node.value, node)

    def _process_unpacking_assignment(
        self, target: ast.AST, value: ast.AST, node: ast.Assign
    ) -> None:
        if not hasattr(target, "elts"):
            return
        for i, elt in enumerate(target.elts):
            if isinstance(elt, ast.Name):
                var_name = elt.id
                value_type = None
                if isinstance(value, (ast.Tuple, ast.List)) and i < len(value.elts):
                    value_type = self._infer_type_of_node(value.elts[i])
                var = self.lookup_variable(var_name)
                if var:
                    var.add_type(value_type)
                    var.add_definition(node)
                else:
                    self.add_variable(var_name, value_type, node)

    def _infer_type_of_node(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Num):
            if isinstance(node.n, int):
                return "int"
            elif isinstance(node.n, float):
                return "float"
            return "num"
        elif isinstance(node, ast.Str):
            return "str"
        elif isinstance(node, ast.List):
            return "list"
        elif isinstance(node, ast.Dict):
            return "dict"
        elif isinstance(node, ast.Set):
            return "set"
        elif isinstance(node, ast.Tuple):
            return "tuple"
        elif isinstance(node, ast.NameConstant):
            if node.value is None:
                return "None"
            elif isinstance(node.value, bool):
                return "bool"
        elif isinstance(node, ast.Name):
            var = self.lookup_variable(node.id)
            if var and var.possible_types:
                return next(iter(var.possible_types))
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name):
                builtins_return_types = {
                    "int": "int",
                    "float": "float",
                    "str": "str",
                    "list": "list",
                    "dict": "dict",
                    "set": "set",
                    "tuple": "tuple",
                }
                if node.func.id in builtins_return_types:
                    return builtins_return_types[node.func.id]
        return None

    def analyze_scope(
        self, node: ast.AST, scope_name: str = "module", scope_type: str = "module"
    ) -> None:
        self.enter_scope(scope_name, scope_type)
        if isinstance(node, ast.Module):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    self.process_assignment(item)
                elif isinstance(item, ast.FunctionDef):
                    self.analyze_scope(item, item.name, "function")
                elif isinstance(item, ast.ClassDef):
                    self.analyze_scope(item, item.name, "class")
        elif isinstance(node, ast.FunctionDef) or isinstance(
            node, ast.AsyncFunctionDef
        ):
            for arg in node.args.args:
                arg_name = arg.arg if hasattr(arg, "arg") else arg.id
                self.add_variable(arg_name, None, arg)
            for item in node.body:
                if isinstance(item, ast.Assign):
                    self.process_assignment(item)
        elif isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.Assign):
                    self.process_assignment(item)
                elif isinstance(item, ast.FunctionDef):
                    self.analyze_scope(item, item.name, "method")
        self.exit_scope()
