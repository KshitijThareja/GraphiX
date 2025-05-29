import ast
import logging
import os
from typing import Dict, Set, List, Tuple, Optional, Any, Union
from enum import Enum
import itertools
from contextlib import contextmanager


class AbstractValue:
    class ValueType(Enum):
        TOP = "⊤"
        INT = "Int"
        FLOAT = "Float"
        STR = "Str"
        BOOL = "Bool"
        LIST = "List"
        DICT = "Dict"
        SET = "Set"
        TUPLE = "Tuple"
        FUNCTION = "Function"
        CLASS = "Class"
        INSTANCE = "Instance"
        MODULE = "Module"
        NONE = "None"
        BOTTOM = "⊥"

    def __init__(
        self,
        value_type: ValueType = ValueType.TOP,
        concrete_values: Optional[Set[Any]] = None,
        origin: Optional[ast.AST] = None,
        is_tainted: bool = False,
    ):
        self.value_type = value_type
        self.concrete_values = concrete_values or set()
        self.origin = origin
        self.is_tainted = is_tainted

    def __str__(self) -> str:
        if self.concrete_values:
            return f"{self.value_type.value}: {self.concrete_values}"
        return self.value_type.value

    def __repr__(self) -> str:
        return self.__str__()

    def join(self, other: "AbstractValue") -> "AbstractValue":
        if self.value_type == AbstractValue.ValueType.BOTTOM:
            return other
        if other.value_type == AbstractValue.ValueType.BOTTOM:
            return self
        if (
            self.value_type == AbstractValue.ValueType.TOP
            or other.value_type == AbstractValue.ValueType.TOP
        ):
            return AbstractValue(AbstractValue.ValueType.TOP)
        if self.value_type == other.value_type:
            concrete_values = self.concrete_values.union(other.concrete_values)
            if len(concrete_values) > 10:
                concrete_values = set()
            return AbstractValue(
                self.value_type,
                concrete_values,
                self.origin or other.origin,
                self.is_tainted or other.is_tainted,
            )
        return AbstractValue(
            AbstractValue.ValueType.TOP,
            set(),
            None,
            self.is_tainted or other.is_tainted,
        )

    @staticmethod
    def from_literal(node: ast.AST) -> "AbstractValue":
        if isinstance(node, ast.Num):
            if isinstance(node.n, int):
                return AbstractValue(AbstractValue.ValueType.INT, {node.n}, node)
            else:
                return AbstractValue(AbstractValue.ValueType.FLOAT, {node.n}, node)
        elif isinstance(node, ast.Str):
            return AbstractValue(AbstractValue.ValueType.STR, {node.s}, node)
        elif isinstance(node, ast.NameConstant):
            if node.value is None:
                return AbstractValue(AbstractValue.ValueType.NONE, {None}, node)
            elif isinstance(node.value, bool):
                return AbstractValue(AbstractValue.ValueType.BOOL, {node.value}, node)
        elif isinstance(node, ast.List):
            return AbstractValue(AbstractValue.ValueType.LIST, set(), node)
        elif isinstance(node, ast.Dict):
            return AbstractValue(AbstractValue.ValueType.DICT, set(), node)
        elif isinstance(node, ast.Set):
            return AbstractValue(AbstractValue.ValueType.SET, set(), node)
        elif isinstance(node, ast.Tuple):
            return AbstractValue(AbstractValue.ValueType.TUPLE, set(), node)
        return AbstractValue(AbstractValue.ValueType.TOP, set(), node)


class AbstractState:
    def __init__(
        self,
        environment: Optional[Dict[str, AbstractValue]] = None,
        call_context: Optional[Tuple[str, ...]] = None,
        path_constraints: Optional[List[ast.AST]] = None,
    ):
        self.environment = environment or {}
        self.call_context = call_context or tuple()
        self.path_constraints = path_constraints or []

    def copy(self) -> "AbstractState":
        return AbstractState(
            environment={k: v for k, v in self.environment.items()},
            call_context=self.call_context,
            path_constraints=list(self.path_constraints),
        )

    def join(self, other: "AbstractState") -> "AbstractState":
        result = AbstractState(call_context=self.call_context)
        all_vars = set(self.environment.keys()).union(other.environment.keys())
        for var in all_vars:
            if var in self.environment and var in other.environment:
                result.environment[var] = self.environment[var].join(
                    other.environment[var]
                )
            elif var in self.environment:
                result.environment[var] = self.environment[var]
            else:
                result.environment[var] = other.environment[var]
        result.path_constraints = [
            c for c in self.path_constraints if c in other.path_constraints
        ]
        return result

    def assign(self, name: str, value: AbstractValue) -> None:
        self.environment[name] = value

    def lookup(self, name: str) -> AbstractValue:
        return self.environment.get(name, AbstractValue(AbstractValue.ValueType.TOP))

    def add_constraint(self, constraint: ast.AST) -> None:
        self.path_constraints.append(constraint)

    def extend_context(self, function_name: str, k: int) -> "AbstractState":
        new_state = self.copy()
        if k <= 0:
            new_state.call_context = tuple()
        else:
            new_ctx = self.call_context + (function_name,)
            if len(new_ctx) > k:
                new_ctx = new_ctx[-k:]
            new_state.call_context = new_ctx
        return new_state


class AbstractInterpreter:
    def __init__(self, max_depth: int = 15, k: int = 2):
        self.max_depth = max_depth
        self.k = k
        self.function_cache = {}
        self.callgraph = {}
        self.depth = 0
        self.scope_stack = []
        self.definitions = {}
        self.class_hierarchy = {}
        self.imported_modules = set()
        self.type_constraints = {}
        self.flow_sensitive_state = {
            "variables": {},
            "return_values": {},
            "yield_values": {},
            "exceptions": set(),
        }

    def analyze_module(self, node: ast.Module, filename: str):
        if self.depth > self.max_depth:
            logging.warning(f"Max depth {self.max_depth} reached in {filename}")
            return {}
        self.depth += 1
        module_name = os.path.splitext(os.path.basename(filename))[0]
        state = AbstractState()
        self.imported_modules.add(module_name)
        try:
            imports, other_nodes = self._extract_imports(node.body)
            for import_node in imports:
                self._analyze_import(import_node, state, filename)
            with self._enter_scope("module", module_name):
                self._analyze_statements(
                    other_nodes, state, filename, is_module_level=True
                )
                self._process_deferred_analysis()
        except Exception as e:
            logging.error(
                f"Error analyzing module {module_name}: {str(e)}", exc_info=True
            )
        self.depth -= 1
        return self.callgraph

    def _extract_imports(self, nodes):
        imports = []
        other = []
        for node in nodes:
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imports.append(node)
            else:
                other.append(node)
        return imports, other

    def _analyze_import(self, node, state, filename):
        if isinstance(node, ast.Import):
            for name in node.names:
                module_name = name.name
                alias = name.asname or module_name.split(".")[-1]
                self.imported_modules.add(module_name)
                self.definitions[alias] = {
                    "type": "module",
                    "name": module_name,
                    "node": node,
                }
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            for name in node.names:
                full_name = f"{module}.{name.name}" if module else name.name
                alias = name.asname or name.name
                self.definitions[alias] = {
                    "type": "import",
                    "name": full_name,
                    "node": node,
                }

    @contextmanager
    def _enter_scope(self, scope_type, name):
        self.scope_stack.append((scope_type, name))
        try:
            yield
        finally:
            self.scope_stack.pop()

    def _process_deferred_analysis(self):
        pass

    def _analyze_statements(
        self,
        statements: List[ast.AST],
        state: AbstractState,
        filename: str,
        is_module_level: bool = False,
    ) -> AbstractState:
        current_state = state.copy()
        for stmt in statements:
            if isinstance(stmt, ast.FunctionDef):
                self._analyze_function_def(stmt, current_state, filename)
            elif isinstance(stmt, ast.ClassDef):
                self._analyze_class_def(stmt, current_state, filename)
            elif isinstance(stmt, ast.Assign):
                self._analyze_assignment(stmt, current_state)
            elif isinstance(stmt, ast.If):
                self._analyze_if(stmt, current_state, filename)
            elif isinstance(stmt, ast.While):
                self._analyze_while(stmt, current_state, filename)
            elif isinstance(stmt, ast.For):
                self._analyze_for(stmt, current_state, filename)
            elif isinstance(stmt, ast.Try):
                self._analyze_try(stmt, current_state, filename)
            elif isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Call):
                self._analyze_call_expr(stmt.value, current_state, filename)
            elif isinstance(stmt, ast.Return) and is_module_level:
                if stmt.value:
                    return_value = self._evaluate_expression(stmt.value, current_state)
                    return current_state
        return current_state

    def _analyze_function_def(
        self, node: ast.FunctionDef, state: AbstractState, filename: str
    ):
        if self.depth > self.max_depth:
            return
        func_name = node.name
        context_key = self._context_key(func_name, state.call_context)
        if context_key not in self.callgraph:
            self.callgraph[context_key] = set()
        func_def = {
            "type": "function",
            "name": func_name,
            "node": node,
            "args": [arg.arg for arg in node.args.args],
            "returns": (
                self._extract_return_type(node.returns) if node.returns else None
            ),
            "decorators": [self._expr_to_str(d) for d in node.decorator_list],
        }
        self.definitions[func_name] = func_def
        with self._enter_scope("function", func_name):
            for decorator in node.decorator_list:
                self._analyze_decorator(decorator, state, filename)
            param_types = {}
            for arg in node.args.args:
                param_types[arg.arg] = AbstractValue(AbstractValue.ValueType.TOP)
                state.assign(arg.arg, param_types[arg.arg])
            self._process_annotations(node, state)
            new_state = state.copy()
            new_state.call_context = self._extend_context(state.call_context, func_name)
            return_values = []
            try:
                self._analyze_statements(
                    node.body, new_state, filename, is_function_body=True
                )
            except Exception as e:
                logging.warning(f"Error analyzing function {func_name}: {e}")
            if return_values:
                func_def["return_type"] = self._unify_types(return_values)

    def _analyze_decorator(self, decorator, state, filename):
        if isinstance(decorator, ast.Call):
            self._analyze_call_expr(decorator, state, filename)
        elif isinstance(decorator, ast.Name):
            self._resolve_name_reference(decorator.id, state.call_context)

    def _process_annotations(self, node, state):
        if node.returns:
            return_type = self._extract_annotation(node.returns)
            if return_type:
                self.type_constraints[f"return:{node.name}"] = return_type
        for arg in node.args.args:
            if arg.annotation:
                param_type = self._extract_annotation(arg.annotation)
                if param_type:
                    self.type_constraints[f"param:{arg.arg}"] = param_type

    def _extract_annotation(self, node):
        self.depth += 1
        body_state = self._analyze_statements(node.body, func_state, filename, True)
        self.depth -= 1
        self.function_cache[func_key] = {
            "params": {arg.arg: func_state.lookup(arg.arg) for arg in node.args.args},
            "body_state": body_state,
        }

    def _analyze_class_def(
        self, node: ast.ClassDef, state: AbstractState, filename: str
    ) -> None:
        class_name = node.name
        context_key = self._context_key(class_name, state.call_context)
        class_def = {
            "type": "class",
            "name": class_name,
            "node": node,
            "bases": [],
            "methods": {},
            "class_attributes": {},
            "instance_attributes": set(),
            "mro": [],
        }
        self.definitions[class_name] = class_def
        base_classes = []
        for base in node.bases:
            base_name = self._expr_to_str(base)
            if base_name:
                base_classes.append(base_name)
                class_def["bases"].append(base_name)
        self._build_mro(class_def, base_classes)
        with self._enter_scope("class", class_name):
            for decorator in node.decorator_list:
                self._analyze_decorator(decorator, state, filename)
            for stmt in node.body:
                if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_def["methods"][stmt.name] = stmt
                elif isinstance(stmt, ast.AnnAssign) and isinstance(
                    stmt.target, ast.Name
                ):
                    class_def["class_attributes"][stmt.target.id] = {
                        "annotation": (
                            self._expr_to_str(stmt.annotation)
                            if stmt.annotation
                            else None
                        ),
                        "value": self._expr_to_str(stmt.value) if stmt.value else None,
                    }
            for method_name, method_node in class_def["methods"].items():
                self._analyze_method(method_node, class_def, state, filename)

    def _build_mro(self, class_def, base_classes):
        mro = [class_def["name"]]
        for base in base_classes:
            if base in self.definitions and "mro" in self.definitions[base]:
                mro.extend([b for b in self.definitions[base]["mro"] if b not in mro])
            else:
                mro.append(base)
        class_def["mro"] = mro

    def _analyze_method(self, node, class_def, state, filename):
        method_name = node.name
        is_static = any(
            isinstance(d, ast.Name) and d.id == "staticmethod"
            for d in node.decorator_list
        )
        is_classmethod = any(
            isinstance(d, ast.Name) and d.id == "classmethod"
            for d in node.decorator_list
        )
        method_def = {
            "type": "method",
            "name": method_name,
            "node": node,
            "is_static": is_static,
            "is_classmethod": is_classmethod,
            "class_name": class_def["name"],
            "args": [arg.arg for arg in node.args.args],
            "returns": (
                self._extract_return_type(node.returns) if node.returns else None
            ),
            "decorators": [self._expr_to_str(d) for d in node.decorator_list],
        }
        class_def["methods"][method_name] = method_def
        if not is_static:
            first_param = "cls" if is_classmethod else "self"
            if node.args.args and node.args.args[0].arg not in ("self", "cls"):
                node.args.args.insert(0, ast.arg(arg=first_param, annotation=None))
        with self._enter_scope("method", f"{class_def['name']}.{method_name}"):
            for decorator in node.decorator_list:
                self._analyze_decorator(decorator, state, filename)
            method_state = state.copy()
            for arg in node.args.args:
                method_state.assign(arg.arg, AbstractValue(AbstractValue.ValueType.TOP))
            self._process_annotations(node, method_state)
            try:
                self._analyze_statements(
                    node.body, method_state, filename, is_function_body=True
                )
            except Exception as e:
                logging.warning(
                    f"Error analyzing method {class_def['name']}.{method_name}: {e}"
                )

    def _analyze_assignment(self, node: ast.Assign, state: AbstractState) -> None:
        value = self._evaluate_expression(node.value, state)
        for target in node.targets:
            if isinstance(target, ast.Name):
                state.assign(target.id, value)
            elif isinstance(target, ast.Attribute):
                pass
            elif isinstance(target, ast.Subscript):
                pass

    def _analyze_if(self, node: ast.If, state: AbstractState, filename: str) -> None:
        condition_value = self._evaluate_expression(node.test, state)
        true_state = state.copy()
        true_state.add_constraint(node.test)
        true_result = self._analyze_statements(node.body, true_state, filename)
        false_state = state.copy()
        false_state.add_constraint(ast.UnaryOp(op=ast.Not(), operand=node.test))
        false_result = self._analyze_statements(node.orelse, false_state, filename)
        joined_state = true_result.join(false_result)
        state.environment.update(joined_state.environment)

    def _analyze_while(
        self, node: ast.While, state: AbstractState, filename: str
    ) -> None:
        loop_state = state.copy()
        loop_state.add_constraint(node.test)
        after_first = self._analyze_statements(node.body, loop_state, filename)
        after_second = self._analyze_statements(node.body, after_first, filename)
        exit_state = state.copy()
        exit_state.add_constraint(ast.UnaryOp(op=ast.Not(), operand=node.test))
        joined_state = after_second.join(exit_state)
        state.environment.update(joined_state.environment)

    def _analyze_for(self, node: ast.For, state: AbstractState, filename: str) -> None:
        iterable_value = self._evaluate_expression(node.iter, state)
        loop_state = state.copy()
        if isinstance(node.target, ast.Name):
            element_type = AbstractValue(AbstractValue.ValueType.TOP)
            loop_state.assign(node.target.id, element_type)
        after_first = self._analyze_statements(node.body, loop_state, filename)
        after_second = self._analyze_statements(node.body, after_first, filename)
        joined_state = state.join(after_second)
        state.environment.update(joined_state.environment)

    def _analyze_try(self, node: ast.Try, state: AbstractState, filename: str) -> None:
        try_state = state.copy()
        try_result = self._analyze_statements(node.body, try_state, filename)
        except_states = []
        for handler in node.handlers:
            handler_state = state.copy()
            if handler.name:
                exception_value = AbstractValue(
                    AbstractValue.ValueType.INSTANCE, set(), handler
                )
                handler_state.assign(handler.name, exception_value)
            except_result = self._analyze_statements(
                handler.body, handler_state, filename
            )
            except_states.append(except_result)
        else_result = None
        if node.orelse:
            else_state = try_result.copy()
            else_result = self._analyze_statements(node.orelse, else_state, filename)
        if node.finalbody:
            finally_state = state.copy()
            finally_result = self._analyze_statements(
                node.finalbody, finally_state, filename
            )
        all_results = [try_result] + except_states
        if else_result:
            all_results.append(else_result)
        result = all_results[0]
        for other in all_results[1:]:
            result = result.join(other)
        state.environment.update(result.environment)

    def _analyze_call_expr(
        self, node: ast.Call, state: AbstractState, filename: str
    ) -> None:
        try:
            if isinstance(node.func, ast.Name):
                self._analyze_direct_call(node.func.id, node, state, filename)
            elif isinstance(node.func, ast.Attribute):
                self._analyze_method_call(node.func, node, state, filename)
            elif isinstance(node.func, ast.Call):
                self._analyze_call_expr(node.func, state, filename)
            for arg in node.args:
                self._evaluate_expression(arg, state)
        except Exception as e:
            logging.warning(f"Error analyzing call expression: {e}")

    def _analyze_direct_call(
        self, func_name: str, call_node: ast.Call, state: AbstractState, filename: str
    ) -> None:
        context_key = self._context_key(func_name, state.call_context)
        if context_key not in self.callgraph:
            self.callgraph[context_key] = set()
        if func_name in __builtins__:
            return
        if (
            func_name in self.definitions
            and self.definitions[func_name].get("type") == "class"
        ):
            self._analyze_constructor_call(func_name, call_node, state, filename)

    def _analyze_method_call(
        self,
        attr_node: ast.Attribute,
        call_node: ast.Call,
        state: AbstractState,
        filename: str,
    ) -> None:
        if not isinstance(attr_node.value, (ast.Name, ast.Attribute)):
            return
        obj_expr = attr_node.value
        method_name = attr_node.attr
        obj_type = self._resolve_expression_type(obj_expr, state)
        if obj_type and isinstance(obj_type, str):
            if (
                obj_type in self.definitions
                and self.definitions[obj_type].get("type") == "class"
            ):
                class_def = self.definitions[obj_type]
                method_def = class_def.get("methods", {}).get(method_name)
                if method_def:
                    method_key = self._context_key(
                        f"{obj_type}.{method_name}", state.call_context
                    )
                    if method_key not in self.callgraph:
                        self.callgraph[method_key] = set()
                    caller_context = (
                        state.call_context[-self.k :] if state.call_context else ()
                    )
                    callee_context = self._extend_context(
                        caller_context, f"{obj_type}.{method_name}"
                    )
                    caller_key = self._context_key(filename, caller_context)
                    if caller_key not in self.callgraph:
                        self.callgraph[caller_key] = set()
                    self.callgraph[caller_key].add(method_key)
                    if "node" in method_def and method_key not in self.function_cache:
                        self._analyze_function_def(method_def["node"], state, filename)
                        self.function_cache[method_key] = True

    def _analyze_constructor_call(
        self, class_name: str, call_node: ast.Call, state: AbstractState, filename: str
    ) -> None:
        new_key = self._context_key(f"{class_name}.__new__", state.call_context)
        if new_key not in self.callgraph:
            self.callgraph[new_key] = set()
        init_key = self._context_key(f"{class_name}.__init__", state.call_context)
        if init_key not in self.callgraph:
            self.callgraph[init_key] = set()
        caller_context = state.call_context[-self.k :] if state.call_context else ()
        caller_key = self._context_key(filename, caller_context)
        if caller_key not in self.callgraph:
            self.callgraph[caller_key] = set()
        self.callgraph[caller_key].update([new_key, init_key])

    def _resolve_expression_type(
        self, node: ast.AST, state: AbstractState
    ) -> Optional[str]:
        if isinstance(node, ast.Name):
            if node.id in self.definitions:
                return self.definitions[node.id].get("type")
        elif isinstance(node, ast.Attribute):
            obj_type = self._resolve_expression_type(node.value, state)
            if obj_type and obj_type in self.definitions:
                class_def = self.definitions[obj_type]
                if "methods" in class_def and node.attr in class_def["methods"]:
                    return "method"
                elif (
                    "class_attributes" in class_def
                    and node.attr in class_def["class_attributes"]
                ):
                    return class_def["class_attributes"][node.attr].get("type")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in self.definitions:
                func_def = self.definitions[node.func.id]
                if "returns" in func_def:
                    return func_def["returns"]
        return None

    def _evaluate_expression(
        self, node: ast.AST, state: AbstractState
    ) -> AbstractValue:
        if isinstance(node, ast.Name):
            return state.lookup(node.id)
        elif (
            isinstance(node, ast.Num)
            or isinstance(node, ast.Str)
            or isinstance(node, ast.NameConstant)
        ):
            return AbstractValue.from_literal(node)
        elif (
            isinstance(node, ast.List)
            or isinstance(node, ast.Dict)
            or isinstance(node, ast.Set)
            or isinstance(node, ast.Tuple)
        ):
            return AbstractValue.from_literal(node)
        elif isinstance(node, ast.BinOp):
            left = self._evaluate_expression(node.left, state)
            right = self._evaluate_expression(node.right, state)
            return AbstractValue(AbstractValue.ValueType.TOP)
        elif isinstance(node, ast.Compare):
            left = self._evaluate_expression(node.left, state)
            return AbstractValue(AbstractValue.ValueType.BOOL)
        elif isinstance(node, ast.Call):
            return AbstractValue(AbstractValue.ValueType.TOP)
        elif isinstance(node, ast.Attribute):
            value = self._evaluate_expression(node.value, state)
            return AbstractValue(AbstractValue.ValueType.TOP)
        return AbstractValue(AbstractValue.ValueType.TOP)

    def _extract_function_name(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            return node.id
        elif isinstance(node, ast.Attribute):
            base = self._extract_function_name(node.value)
            if base:
                return f"{base}.{node.attr}"
            return node.attr
        return None

    def _context_key(self, function_name: str, context: Tuple[str, ...]) -> str:
        if not context:
            return function_name
        return f"{':'.join(context)}:{function_name}"

    def _extend_context(
        self, context: Tuple[str, ...], function_name: str
    ) -> Tuple[str, ...]:
        if self.k <= 0:
            return tuple()
        new_ctx = context + (function_name,)
        if len(new_ctx) > self.k:
            new_ctx = new_ctx[-self.k :]
        return new_ctx


class KCFACallGraphBuilder:
    def __init__(self, k: int = 2, max_depth: int = 10):
        self.k = k
        self.max_depth = max_depth
        self.interpreter = AbstractInterpreter(max_depth, k)
        self.context_callgraph = {}
        self.collapsed_callgraph = {}

    def analyze_file(self, file_path: str, file_content: str) -> Dict:
        try:
            tree = ast.parse(file_content)
            results = self.interpreter.analyze_module(tree, file_path)
            self.context_callgraph.update(results["callgraph"])
            self._collapse_callgraph()
            return {
                "context_callgraph": self.context_callgraph,
                "callgraph": self.collapsed_callgraph,
                "function_summaries": results["function_summaries"],
            }
        except SyntaxError as e:
            logging.error(f"Syntax error in {file_path}: {e}")
            return {"error": str(e)}

    def _collapse_callgraph(self) -> None:
        self.collapsed_callgraph = {}
        for caller_key, callees in self.context_callgraph.items():
            caller_function = caller_key.split(":")[-1]
            if caller_function not in self.collapsed_callgraph:
                self.collapsed_callgraph[caller_function] = set()
            for callee_key in callees:
                callee_function = callee_key.split(":")[-1]
                self.collapsed_callgraph[caller_function].add(callee_function)

    def get_context_sensitive_edges(self) -> List[Dict]:
        edges = []
        for caller, callees in self.context_callgraph.items():
            for callee in callees:
                caller_parts = caller.split(":")
                callee_parts = callee.split(":")
                caller_context = caller_parts[:-1]
                caller_function = caller_parts[-1]
                callee_context = callee_parts[:-1]
                callee_function = callee_parts[-1]
                edges.append(
                    {
                        "source": caller_function,
                        "target": callee_function,
                        "source_context": caller_context,
                        "target_context": callee_context,
                    }
                )
        return edges

    def get_context_sensitive_edges(self, callgraph: Dict) -> List[Dict]:
        for node in callgraph["nodes"]:
            node_id = node["id"]
            metadata = node.get("metadata", {})
            if metadata.get("polymorphic", False):
                node["highPolymorphism"] = True
            if "inferred_types" in metadata:
                confidence = self._calculate_type_confidence(metadata["inferred_types"])
                node["confidence"] = confidence
                if confidence < 0.3:
                    node["group"] = 10
                elif confidence < 0.7:
                    node["group"] = 11
                else:
                    node["group"] = 12
