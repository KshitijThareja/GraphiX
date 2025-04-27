"""
Documentation generator module for GraphiX.
This module is responsible for generating documentation from code and callgraphs.
"""

import os
import json
from typing import Dict, List, Any, Optional
import ast
import re

class DocumentationGenerator:
    def __init__(self, llm_integration=None):
        """
        Initialize the documentation generator.
        
        Args:
            llm_integration: LLM integration instance for enhanced documentation
        """
        self.llm_integration = llm_integration
    
    def generate_documentation(self, code_files: Dict[str, str], callgraph: Dict[str, Any]) -> str:
        """
        Generate documentation for code files and callgraph.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            callgraph: Callgraph data
            
        Returns:
            Generated documentation in Markdown format
        """
        documentation = "# Repository Documentation\n\n"
        
        # Add overview section
        documentation += "## Overview\n\n"
        documentation += "This repository contains a software application with the following components.\n\n"
        
        # Add functions section
        documentation += "## Functions\n\n"
        
        # Process each function from the callgraph
        for node in callgraph.get("nodes", []):
            function_id = node.get("id", "")
            complexity = node.get("complexity", 0)
            
            # Find the file containing this function
            function_info = self._find_function_in_files(function_id, code_files)
            
            if function_info:
                documentation += f"### {function_id}\n\n"
                
                # Add description
                if function_info.get("docstring"):
                    documentation += f"**Description**: {function_info['docstring']}\n\n"
                else:
                    documentation += "**Description**: No description available.\n\n"
                
                # Add parameters
                if function_info.get("parameters"):
                    documentation += "**Parameters**:\n"
                    for param in function_info["parameters"]:
                        documentation += f"- {param}\n"
                    documentation += "\n"
                else:
                    documentation += "**Parameters**: None\n\n"
                
                # Add returns
                if function_info.get("returns"):
                    documentation += f"**Returns**: {function_info['returns']}\n\n"
                else:
                    documentation += "**Returns**: Not specified\n\n"
                
                # Add dependencies
                dependencies = self._find_dependencies(function_id, callgraph)
                if dependencies:
                    documentation += "**Dependencies**:\n"
                    for dep in dependencies:
                        documentation += f"- {dep}\n"
                    documentation += "\n"
                else:
                    documentation += "**Dependencies**: None\n\n"
                
                # Add complexity
                documentation += f"**Complexity**: {complexity}\n\n"
        
        # Add architecture section
        documentation += "## Architecture\n\n"
        documentation += "The application has the following call structure:\n\n"
        
        # Create a simple representation of the call hierarchy
        root_functions = self._find_root_functions(callgraph)
        for root in root_functions:
            documentation += self._generate_call_hierarchy(root, callgraph, 0)
        
        # Add recommendations section
        documentation += "## Recommendations\n\n"
        documentation += "Based on the callgraph analysis:\n\n"
        
        # Find high complexity functions
        high_complexity = [node for node in callgraph.get("nodes", []) if node.get("complexity", 0) > 5]
        if high_complexity:
            documentation += "1. The following functions have high complexity and might benefit from refactoring:\n"
            for node in high_complexity:
                documentation += f"   - {node['id']} (complexity: {node['complexity']})\n"
            documentation += "\n"
        
        # Find highly coupled functions
        function_calls = {}
        for link in callgraph.get("links", []):
            source = link.get("source", "")
            if source not in function_calls:
                function_calls[source] = 0
            function_calls[source] += 1
        
        highly_coupled = [(func, calls) for func, calls in function_calls.items() if calls > 3]
        if highly_coupled:
            documentation += "2. The following functions have high coupling and might benefit from restructuring:\n"
            for func, calls in highly_coupled:
                documentation += f"   - {func} (calls {calls} other functions)\n"
            documentation += "\n"
        
        return documentation
    
    async def generate_enhanced_documentation(self, code_files: Dict[str, str], callgraph: Dict[str, Any]) -> str:
        """
        Generate enhanced documentation using LLM.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            callgraph: Callgraph data
            
        Returns:
            Enhanced documentation in Markdown format
        """
        if not self.llm_integration:
            return self.generate_documentation(code_files, callgraph)
        
        # Combine all code files into a single string for the LLM
        combined_code = ""
        for file_path, code in code_files.items():
            combined_code += f"# File: {file_path}\n{code}\n\n"
        
        # Use LLM to generate documentation
        documentation = await self.llm_integration.generate_documentation(combined_code, callgraph)
        return documentation
    
    def _find_function_in_files(self, function_id: str, code_files: Dict[str, str]) -> Dict[str, Any]:
        """
        Find a function in code files and extract its information.
        
        Args:
            function_id: Function identifier
            code_files: Dictionary mapping file paths to code content
            
        Returns:
            Dictionary with function information
        """
        # Extract module and function name from function_id
        parts = function_id.split(".")
        if len(parts) < 2:
            return {}
        
        module_name = parts[0]
        function_name = parts[-1]
        
        for file_path, code in code_files.items():
            if module_name in file_path:
                try:
                    tree = ast.parse(code)
                    
                    for node in ast.walk(tree):
                        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == function_name:
                            # Extract docstring
                            docstring = ast.get_docstring(node)
                            
                            # Extract parameters
                            parameters = []
                            for arg in node.args.args:
                                if arg.arg != "self":  # Skip 'self' for methods
                                    parameters.append(arg.arg)
                            
                            # Try to extract return information from docstring
                            returns = None
                            if docstring:
                                returns_match = re.search(r"Returns:(.+?)(?:\n\n|\Z)", docstring, re.DOTALL)
                                if returns_match:
                                    returns = returns_match.group(1).strip()
                            
                            return {
                                "docstring": docstring,
                                "parameters": parameters,
                                "returns": returns,
                                "file_path": file_path
                            }
                
                except Exception as e:
                    print(f"Error parsing {file_path}: {str(e)}")
        
        return {}
    
    def _find_dependencies(self, function_id: str, callgraph: Dict[str, Any]) -> List[str]:
        """
        Find dependencies of a function in the callgraph.
        
        Args:
            function_id: Function identifier
            callgraph: Callgraph data
            
        Returns:
            List of function identifiers that are called by the function
        """
        dependencies = []
        
        for link in callgraph.get("links", []):
            if link.get("source") == function_id:
                dependencies.append(link.get("target"))
        
        return dependencies
    
    def _find_root_functions(self, callgraph: Dict[str, Any]) -> List[str]:
        """
        Find root functions in the callgraph (functions that are not called by others).
        
        Args:
            callgraph: Callgraph data
            
        Returns:
            List of root function identifiers
        """
        all_functions = set(node.get("id") for node in callgraph.get("nodes", []))
        called_functions = set()
        
        for link in callgraph.get("links", []):
            called_functions.add(link.get("target"))
        
        # Root functions are those that are not called by any other function
        root_functions = all_functions - called_functions
        
        return list(root_functions)
    
    def _generate_call_hierarchy(self, function_id: str, callgraph: Dict[str, Any], level: int) -> str:
        """
        Generate a textual representation of the call hierarchy.
        
        Args:
            function_id: Function identifier
            callgraph: Callgraph data
            level: Current indentation level
            
        Returns:
            Textual representation of the call hierarchy
        """
        indent = "  " * level
        result = f"{indent}- {function_id}\n"
        
        # Find functions called by this function
        called_functions = []
        for link in callgraph.get("links", []):
            if link.get("source") == function_id:
                called_functions.append(link.get("target"))
        
        # Recursively add called functions
        for called in called_functions:
            result += self._generate_call_hierarchy(called, callgraph, level + 1)
        
        return result

# Example usage
if __name__ == "__main__":
    # Sample code files
    code_files = {
        "main.py": """
def main():
    \"\"\"
    Main entry point of the application.
    
    Returns:
        int: Exit code (0 for success, non-zero for failure)
    \"\"\"
    data = get_data()
    processed_data = process_data(data)
    display_output(processed_data)
    return 0

def get_data():
    \"\"\"
    Get input data.
    
    Returns:
        dict: Input data
    \"\"\"
    return {"user_1": "John", "score_1": "10", "user_2": "Jane", "score_2": "20"}
"""
    }
    
    # Sample callgraph
    callgraph = {
        "nodes": [
            {"id": "main.main", "group": 1, "type": "function", "complexity": 3},
            {"id": "main.get_data", "group": 1, "type": "function", "complexity": 2},
            {"id": "process.process_data", "group": 2, "type": "function", "complexity": 7},
            {"id": "display.display_output", "group": 3, "type": "function", "complexity": 4}
        ],
        "links": [
            {"source": "main.main", "target": "main.get_data", "value": 1},
            {"source": "main.main", "target": "process.process_data", "value": 1},
            {"source": "main.main", "target": "display.display_output", "value": 1}
        ]
    }
    
    generator = DocumentationGenerator()
    documentation = generator.generate_documentation(code_files, callgraph)
    print(documentation)
