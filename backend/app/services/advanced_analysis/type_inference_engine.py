import ast
from typing import Dict, List, Any, Set, Tuple, Union

PyType = Union[str, "TypeVariable", "FunctionType"]


class TypeVariable:
    _count = 0

    def __init__(self):
        self.id = TypeVariable._count
        TypeVariable._count += 1

    def __repr__(self):
        return f"T{self.id}"

    def __hash__(self):
        return hash(self.id)

    def __eq__(self, other):
        return isinstance(other, TypeVariable) and self.id == other.id


class FunctionType:
    def __init__(self, arg_types: List[PyType], return_type: PyType):
        self.arg_types = arg_types
        self.return_type = return_type

    def __repr__(self):
        return f"({', '.join(map(str, self.arg_types))}) -> {self.return_type}"


class TypeInferenceEngine:
    def __init__(self):
        self.constraints: List[Tuple[PyType, PyType]] = []
        self.environment: Dict[str, PyType] = {}
        self.substitutions: Dict[TypeVariable, PyType] = {}

    def new_type_variable(self) -> TypeVariable:
        return TypeVariable()

    def infer_types(self, ast_root: ast.AST) -> Dict[str, PyType]:
        """Public method to start type inference on an AST.
        Returns a simplified environment of inferred types for names.
        """
        self.constraints = []
        self.environment = {}
        self.substitutions = {}
        self._collect_constraints(ast_root, self.environment)
        self._solve_constraints()
        final_types = {}
        for name, type_val in self.environment.items():
            final_types[name] = self._apply_substitutions(type_val)
        return final_types

    def _collect_constraints(self, node: ast.AST, env: Dict[str, PyType]) -> PyType:
        """Recursively traverses the AST to collect type constraints."""
        node_type_name = type(node).__name__
        handler_method_name = f"_visit_{node_type_name.lower()}"
        handler = getattr(self, handler_method_name, self._visit_default)
        return handler(node, env)

    def _visit_default(self, node: ast.AST, env: Dict[str, PyType]) -> PyType:
        """Default visitor for AST nodes not explicitly handled."""
        for child_node in ast.iter_child_nodes(node):
            self._collect_constraints(child_node, env)
        return self.new_type_variable()

    def _visit_name(self, node: ast.Name, env: Dict[str, PyType]) -> PyType:
        if node.id not in env:
            env[node.id] = self.new_type_variable()
        return env[node.id]

    def _visit_constant(self, node: ast.Constant, env: Dict[str, PyType]) -> PyType:
        if isinstance(node.value, int):
            return "int"
        elif isinstance(node.value, str):
            return "str"
        elif isinstance(node.value, float):
            return "float"
        elif isinstance(node.value, bool):
            return "bool"
        return self.new_type_variable()

    def _visit_assign(self, node: ast.Assign, env: Dict[str, PyType]):
        value_type = self._collect_constraints(node.value, env)
        for target in node.targets:
            if isinstance(target, ast.Name):
                target_type = self._visit_name(target, env)
                self.constraints.append((target_type, value_type))
        return value_type

    def _visit_functiondef(
        self, node: ast.FunctionDef, env: Dict[str, PyType]
    ) -> PyType:
        func_env = env.copy()
        arg_types = []
        for arg in node.args.args:
            arg_type = self.new_type_variable()
            func_env[arg.arg] = arg_type
            arg_types.append(arg_type)
        body_type = self.new_type_variable()
        for stmt in node.body:
            self._collect_constraints(stmt, func_env)
            if isinstance(stmt, ast.Return) and stmt.value:
                return_value_type = self._collect_constraints(stmt.value, func_env)
                self.constraints.append((body_type, return_value_type))
        func_type = FunctionType(arg_types, body_type)
        env[node.name] = func_type
        return func_type

    def _visit_call(self, node: ast.Call, env: Dict[str, PyType]) -> PyType:
        func_type_var = self._collect_constraints(node.func, env)
        arg_expr_types = [self._collect_constraints(arg, env) for arg in node.args]
        call_return_type = self.new_type_variable()
        expected_func_type = FunctionType(arg_expr_types, call_return_type)
        self.constraints.append((func_type_var, expected_func_type))
        return call_return_type

    def _visit_binop(self, node: ast.BinOp, env: Dict[str, PyType]) -> PyType:
        left_type = self._collect_constraints(node.left, env)
        right_type = self._collect_constraints(node.right, env)
        if isinstance(node.op, ast.Add):
            self.constraints.append((left_type, right_type))
            return left_type
        return self.new_type_variable()

    def _unify(self, type1: PyType, type2: PyType):
        """Unifies two types. Modifies self.substitutions."""
        t1 = self._apply_substitutions(type1)
        t2 = self._apply_substitutions(type2)
        if t1 == t2:
            return
        elif isinstance(t1, TypeVariable):
            self._add_substitution(t1, t2)
        elif isinstance(t2, TypeVariable):
            self._add_substitution(t2, t1)
        elif isinstance(t1, FunctionType) and isinstance(t2, FunctionType):
            if len(t1.arg_types) != len(t2.arg_types):
                raise TypeError("Function arity mismatch")
            for arg1_t, arg2_t in zip(t1.arg_types, t2.arg_types):
                self._unify(arg1_t, arg2_t)
            self._unify(t1.return_type, t2.return_type)
        elif isinstance(t1, str) and isinstance(t2, str) and t1 != t2:
            raise TypeError(f"Type mismatch: cannot unify {t1} and {t2}")
        else:
            raise TypeError(
                f"Cannot unify {t1} and {t2}. Unhandled type structure or mismatch."
            )

    def _add_substitution(self, var: TypeVariable, type_val: PyType):
        """Adds a substitution, checking for circular dependencies."""
        if self._occurs_in(var, type_val):
            raise TypeError(f"Circular type detected: {var} occurs in {type_val}")
        self.substitutions[var] = type_val

    def _apply_substitutions(self, type_val: PyType) -> PyType:
        """Applies current substitutions to a type, resolving it as much as possible."""
        if isinstance(type_val, TypeVariable):
            if type_val in self.substitutions:
                self.substitutions[type_val] = self._apply_substitutions(
                    self.substitutions[type_val]
                )
                return self.substitutions[type_val]
            return type_val
        elif isinstance(type_val, FunctionType):
            return FunctionType(
                [self._apply_substitutions(arg_t) for arg_t in type_val.arg_types],
                self._apply_substitutions(type_val.return_type),
            )
        return type_val

    def _occurs_in(self, var: TypeVariable, type_val: PyType) -> bool:
        """Checks if a type variable occurs in a type expression (for cycle detection)."""
        resolved_type = self._apply_substitutions(type_val)
        if var == resolved_type:
            return True
        elif isinstance(resolved_type, FunctionType):
            return any(
                self._occurs_in(var, arg_t) for arg_t in resolved_type.arg_types
            ) or self._occurs_in(var, resolved_type.return_type)
        return False

    def _solve_constraints(self):
        """Iteratively solves the collected type constraints using unification."""
        changed = True
        iterations = 0
        max_iterations = 100
        while changed and iterations < max_iterations:
            changed = False
            iterations += 1
            for i in range(len(self.constraints)):
                t1, t2 = self.constraints[i]
                try:
                    current_subs_snapshot = self.substitutions.copy()
                    self._unify(t1, t2)
                    if self.substitutions != current_subs_snapshot:
                        changed = True
                except TypeError as e:
                    pass
            if not changed and iterations > 1:
                break
        if iterations >= max_iterations:
            print(
                "Warning: Type inference reached max iterations. Results may be incomplete."
            )


if __name__ == "__main__":
    engine = TypeInferenceEngine()
    source_code = """
def foo(a):
  return a + 1
b = foo(10)
c = foo('hello')
"""
    ast_example = ast.parse(source_code)
    inferred_types = engine.infer_types(ast_example)
    print("Inferred Types:")
    for name, var_type in inferred_types.items():
        print(f"  {name}: {engine._apply_substitutions(var_type)}")
    print("\nSubstitutions:")
    for var, type_val in engine.substitutions.items():
        print(f"  {var}: {engine._apply_substitutions(type_val)}")
    source_code_func_call = """
def add(x, y):
    return x + y
result = add(1, 2)
"""
    ast_fc = ast.parse(source_code_func_call)
    types_fc = engine.infer_types(ast_fc)
    print("\nInferred Types (Function Call Example):")
    for name, var_type in types_fc.items():
        print(f"  {name}: {engine._apply_substitutions(var_type)}")
    source_code_error = """
def identity(x):
    return x
a = identity(5)
b = identity('text')
"""
    ast_err = ast.parse(source_code_error)
    types_err = engine.infer_types(ast_err)
    print("\nInferred Types (Potential Error Example):")
    for name, var_type in types_err.items():
        print(f"  {name}: {engine._apply_substitutions(var_type)}")
