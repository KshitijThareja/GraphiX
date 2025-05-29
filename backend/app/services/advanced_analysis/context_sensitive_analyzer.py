import ast
from typing import List, Set, Dict
import networkx as nx


class TypeLattice:
    def __init__(self):
        self.types = {"Any", "int", "str", "list", "dict", "CustomType"}

    def get_least_upper_bound(self, type1: str, type2: str) -> str:
        if type1 == type2:
            return type1
        return "Any"


class ContextSensitiveAnalyzer:
    def __init__(self, k: int = 2):
        self.k = k
        self.call_graph = nx.MultiDiGraph()
        self.type_lattice = TypeLattice()
        self.resolved_calls: Dict[tuple, Set[str]] = {}

    def _get_call_site_hash(self, call_site_node: ast.Call) -> int:
        return hash(
            (
                getattr(call_site_node, "lineno", 0),
                getattr(call_site_node, "col_offset", 0),
            )
        )

    def analyze_method_call(
        self,
        call_site: ast.Call,
        current_context: List[str],
        available_types: Dict[str, str],
    ) -> Set[str]:
        """
        Analyzes a method call in a context-sensitive manner.
        'current_context' is a list of function/method names representing the call stack.
        'available_types' is a dictionary mapping variable names to their inferred types.
        Returns a set of possible target function/method names.
        """
        effective_context = (
            tuple(current_context[-self.k :])
            if len(current_context) > self.k
            else tuple(current_context)
        )
        call_site_id = self._get_call_site_hash(call_site)
        cache_key = (call_site_id, effective_context)
        if cache_key in self.resolved_calls:
            return self.resolved_calls[cache_key]
        possible_targets = self._resolve_call_targets(
            call_site, effective_context, available_types
        )
        self.resolved_calls[cache_key] = possible_targets
        return possible_targets

    def _resolve_call_targets(
        self, call_site: ast.Call, context: tuple, available_types: Dict[str, str]
    ) -> Set[str]:
        """
        Placeholder for the actual call target resolution logic.
        This would typically involve Abstract Interpretation, type analysis, etc.
        """
        if isinstance(call_site.func, ast.Attribute):
            obj_name_node = call_site.func.value
            method_name = call_site.func.attr
            obj_name = ast.unparse(obj_name_node)
            obj_type = available_types.get(obj_name, "Any")
            if obj_type != "Any":
                return {f"{obj_type}.{method_name}"}
            else:
                return {f"<UnknownClass>.{method_name}"}
        elif isinstance(call_site.func, ast.Name):
            return {call_site.func.id}
        return {f"<complex_target_for_{ast.unparse(call_site.func)}>"}

    def get_call_graph(self):
        return self.call_graph

    def update_type_information(
        self, variable_name: str, inferred_type: str, context: List[str]
    ):
        pass


if __name__ == "__main__":
    csa = ContextSensitiveAnalyzer(k=1)
    call_node_example = ast.Call(
        func=ast.Attribute(
            value=ast.Name(id="x", ctx=ast.Load()), attr="do_something", ctx=ast.Load()
        ),
        args=[],
        keywords=[],
    )
    setattr(call_node_example, "lineno", 10)
    setattr(call_node_example, "col_offset", 0)
    current_call_stack = ["main_function", "caller_function"]
    inferred_variable_types = {"x": "MyClass"}
    targets = csa.analyze_method_call(
        call_node_example, current_call_stack, inferred_variable_types
    )
    print(
        f"Possible targets for 'x.do_something()' in context {current_call_stack[-1:]}: {targets}"
    )
    call_node_example_2 = ast.Call(
        func=ast.Attribute(
            value=ast.Name(id="y", ctx=ast.Load()), attr="process_data", ctx=ast.Load()
        ),
        args=[],
        keywords=[],
    )
    setattr(call_node_example_2, "lineno", 15)
    setattr(call_node_example_2, "col_offset", 0)
    inferred_variable_types_2 = {"y": "AnotherClass"}
    targets_2 = csa.analyze_method_call(
        call_node_example_2, current_call_stack, inferred_variable_types_2
    )
    print(
        f"Possible targets for 'y.process_data()' in context {current_call_stack[-1:]}: {targets_2}"
    )
    current_call_stack_3 = ["another_main", "different_caller"]
    targets_3 = csa.analyze_method_call(
        call_node_example, current_call_stack_3, inferred_variable_types
    )
    print(
        f"Possible targets for 'x.do_something()' in context {current_call_stack_3[-1:]}: {targets_3}"
    )
    print("Built Call Graph Edges:")
    for edge in csa.get_call_graph().edges(data=True):
        print(edge)
