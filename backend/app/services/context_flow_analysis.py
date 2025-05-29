import ast
import os
import logging
from typing import Dict, Set, List, Tuple, Optional, Any, Union
import networkx as nx
from collections import defaultdict
from .abstract_interpretation import AbstractInterpreter, KCFACallGraphBuilder


class ContextualCallPath:
    def __init__(
        self,
        source: str,
        target: str,
        source_context: Tuple[str, ...] = None,
        target_context: Tuple[str, ...] = None,
    ):
        self.source = source
        self.target = target
        self.source_context = source_context or tuple()
        self.target_context = target_context or tuple()

    def __eq__(self, other):
        if not isinstance(other, ContextualCallPath):
            return False
        return (
            self.source == other.source
            and self.target == other.target
            and self.source_context == other.source_context
            and self.target_context == other.target_context
        )

    def __hash__(self):
        return hash(
            (self.source, self.target, self.source_context, self.target_context)
        )

    def __str__(self):
        source_ctx = f"[{':'.join(self.source_context)}]" if self.source_context else ""
        target_ctx = f"[{':'.join(self.target_context)}]" if self.target_context else ""
        return f"{self.source}{source_ctx} -> {self.target}{target_ctx}"

    def __repr__(self):
        return self.__str__()


class ContextFlowAnalyzer:
    def __init__(self, k: int = 2, max_depth: int = 8):
        self.k = k
        self.max_depth = max_depth
        self.callgraph_builder = KCFACallGraphBuilder(k, max_depth)
        self.context_paths = set()
        self.infeasible_paths = set()
        self.value_flow = {}
        self.polymorphic_calls = defaultdict(set)

    def analyze_files(self, file_paths: List[str], file_contents: List[str]) -> Dict:
        results = {}
        for path, content in zip(file_paths, file_contents):
            file_result = self.callgraph_builder.analyze_file(path, content)
            if "error" not in file_result:
                results[path] = file_result
                for caller, callees in file_result["context_callgraph"].items():
                    caller_parts = caller.split(":")
                    caller_context = tuple(caller_parts[:-1])
                    caller_function = caller_parts[-1]
                    for callee in callees:
                        callee_parts = callee.split(":")
                        callee_context = tuple(callee_parts[:-1])
                        callee_function = callee_parts[-1]
                        path = ContextualCallPath(
                            caller_function,
                            callee_function,
                            caller_context,
                            callee_context,
                        )
                        self.context_paths.add(path)
        self._identify_infeasible_paths()
        self._analyze_value_flow()
        self._detect_polymorphic_calls()
        return {
            "context_paths": self.context_paths,
            "infeasible_paths": self.infeasible_paths,
            "polymorphic_calls": self.polymorphic_calls,
            "value_flow": self.value_flow,
        }

    def _identify_infeasible_paths(self) -> None:
        graph = nx.DiGraph()
        for path in self.context_paths:
            source_key = f"{':'.join(path.source_context)}:{path.source}"
            target_key = f"{':'.join(path.target_context)}:{path.target}"
            graph.add_edge(source_key, target_key)
        entry_points = [
            node
            for node in graph.nodes()
            if graph.in_degree(node) == 0 or node.count(":") == 0
        ]
        reachable = set()
        for entry in entry_points:
            reachable.update(nx.descendants(graph, entry))
            reachable.add(entry)
        for path in self.context_paths:
            source_key = f"{':'.join(path.source_context)}:{path.source}"
            target_key = f"{':'.join(path.target_context)}:{path.target}"
            if source_key not in reachable or target_key not in reachable:
                self.infeasible_paths.add(path)

    def _analyze_value_flow(self) -> None:
        pass

    def _detect_polymorphic_calls(self) -> None:
        call_sites = defaultdict(set)
        for path in self.context_paths:
            if path not in self.infeasible_paths:
                source_with_ctx = (path.source, path.source_context)
                call_sites[source_with_ctx].add(path.target)
        for source, targets in call_sites.items():
            if len(targets) > 1:
                function, context = source
                self.polymorphic_calls[function].update(targets)

    def to_enhanced_callgraph(self) -> Dict:
        nodes = []
        links = []
        node_ids = set()
        for path in self.context_paths:
            if path.source not in node_ids:
                nodes.append(
                    {
                        "id": path.source,
                        "name": path.source.split(".")[-1],
                        "type": "function",
                        "group": 1,
                        "complexity": 1,
                        "metadata": {
                            "contexts": [":".join(path.source_context)],
                            "polymorphic": path.source in self.polymorphic_calls,
                        },
                    }
                )
                node_ids.add(path.source)
            if path.target not in node_ids:
                nodes.append(
                    {
                        "id": path.target,
                        "name": path.target.split(".")[-1],
                        "type": "function",
                        "group": 1,
                        "complexity": 1,
                        "metadata": {
                            "contexts": [":".join(path.target_context)],
                            "polymorphic": path.target in self.polymorphic_calls,
                        },
                    }
                )
                node_ids.add(path.target)
        basic_links = defaultdict(int)
        context_counts = defaultdict(int)
        for path in self.context_paths:
            if path not in self.infeasible_paths:
                key = (path.source, path.target)
                basic_links[key] += 1
                context_counts[key] += 1
        for (source, target), count in basic_links.items():
            links.append(
                {
                    "source": source,
                    "target": target,
                    "value": count,
                    "type": "call",
                    "context_count": context_counts[(source, target)],
                }
            )
        return {
            "nodes": nodes,
            "links": links,
            "metadata": {
                "context_sensitive": True,
                "k": self.k,
                "infeasible_paths_count": len(self.infeasible_paths),
                "polymorphic_calls_count": sum(
                    len(targets) for targets in self.polymorphic_calls.values()
                ),
            },
        }


class TypeInferenceEngine:
    def __init__(self, analyzer: ContextFlowAnalyzer):
        self.analyzer = analyzer
        self.inferred_types = {}

    def infer_types(self) -> Dict:
        return self.inferred_types

    def _add_visualization_attributes(self, callgraph: Dict) -> None:
        types = self.infer_types()
        for node in callgraph["nodes"]:
            node_id = node["id"]
            if node_id in types:
                if "metadata" not in node:
                    node["metadata"] = {}
                node["metadata"]["inferred_types"] = types[node_id]

    def enhance_callgraph(self, callgraph: Dict) -> Dict:
        types = self.infer_types()
        for node in callgraph["nodes"]:
            node_id = node["id"]
            if node_id in types:
                if "metadata" not in node:
                    node["metadata"] = {}
                node["metadata"]["inferred_types"] = types[node_id]
        return callgraph
