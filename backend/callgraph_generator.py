"""
Callgraph generator module for GraphiX.
This module is responsible for generating callgraphs from Python code.
"""

import ast
import os
import json
from typing import Dict, List, Set, Tuple, Any

class CallgraphGenerator:
    def __init__(self):
        self.nodes = []
        self.links = []
        self.functions = {}
        self.complexity_scores = {}
    
    def analyze_file(self, file_path: str) -> None:
        """
        Analyze a Python file and extract function definitions and calls.
        
        Args:
            file_path: Path to the Python file
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()
            
            tree = ast.parse(content)
            
            # First pass: collect all function definitions
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    function_name = node.name
                    module_name = os.path.basename(file_path).replace('.py', '')
                    qualified_name = f"{module_name}.{function_name}"
                    
                    # Calculate cyclomatic complexity
                    complexity = self._calculate_complexity(node)
                    
                    self.functions[qualified_name] = {
                        'node': node,
                        'file': file_path,
                        'complexity': complexity
                    }
                    
                    self.complexity_scores[qualified_name] = complexity
            
            # Second pass: collect function calls
            for func_name, func_info in self.functions.items():
                calls = self._find_function_calls(func_info['node'])
                
                for called_func in calls:
                    # Check if the called function is in our list of defined functions
                    for defined_func in self.functions.keys():
                        if defined_func.endswith(f".{called_func}"):
                            self.links.append({
                                'source': func_name,
                                'target': defined_func,
                                'value': 1
                            })
        
        except Exception as e:
            print(f"Error analyzing file {file_path}: {str(e)}")
    
    def analyze_directory(self, directory_path: str, file_extension: str = '.py') -> None:
        """
        Analyze all Python files in a directory.
        
        Args:
            directory_path: Path to the directory
            file_extension: File extension to look for (default: .py)
        """
        for root, _, files in os.walk(directory_path):
            for file in files:
                if file.endswith(file_extension):
                    file_path = os.path.join(root, file)
                    self.analyze_file(file_path)
    
    def generate_callgraph(self) -> Dict[str, List[Dict[str, Any]]]:
        """
        Generate a callgraph from the analyzed files.
        
        Returns:
            A dictionary with nodes and links for the callgraph
        """
        # Create nodes from functions
        for func_name, func_info in self.functions.items():
            # Determine the group (module) for visualization
            module_name = func_name.split('.')[0]
            module_hash = hash(module_name) % 10  # Simple hash for group assignment
            
            self.nodes.append({
                'id': func_name,
                'group': module_hash,
                'type': 'function',
                'complexity': func_info['complexity']
            })
        
        return {
            'nodes': self.nodes,
            'links': self.links
        }
    
    def _calculate_complexity(self, node: ast.AST) -> int:
        """
        Calculate the cyclomatic complexity of a function.
        
        Args:
            node: AST node of the function
            
        Returns:
            Cyclomatic complexity score
        """
        # Start with 1 (base complexity)
        complexity = 1
        
        # Count branches that increase complexity
        for subnode in ast.walk(node):
            if isinstance(subnode, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(subnode, ast.BoolOp) and isinstance(subnode.op, ast.And):
                complexity += len(subnode.values) - 1
            elif isinstance(subnode, ast.BoolOp) and isinstance(subnode.op, ast.Or):
                complexity += len(subnode.values) - 1
            elif isinstance(subnode, ast.Try):
                complexity += len(subnode.handlers)  # Add 1 for each except clause
        
        return complexity
    
    def _find_function_calls(self, node: ast.AST) -> Set[str]:
        """
        Find all function calls within a function.
        
        Args:
            node: AST node of the function
            
        Returns:
            Set of function names that are called
        """
        calls = set()
        
        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call) and isinstance(subnode.func, ast.Name):
                calls.add(subnode.func.id)
        
        return calls
    
    def export_to_json(self, output_file: str) -> None:
        """
        Export the callgraph to a JSON file.
        
        Args:
            output_file: Path to the output JSON file
        """
        callgraph = self.generate_callgraph()
        
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(callgraph, f, indent=2)
        
        print(f"Callgraph exported to {output_file}")

# Example usage
if __name__ == "__main__":
    generator = CallgraphGenerator()
    generator.analyze_directory("./sample_code")
    callgraph = generator.generate_callgraph()
    print(f"Generated callgraph with {len(callgraph['nodes'])} nodes and {len(callgraph['links'])} links")
    generator.export_to_json("callgraph.json")
