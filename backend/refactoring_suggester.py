"""
Refactoring suggester module for GraphiX.
This module is responsible for suggesting code refactorings based on callgraph analysis.
"""

import ast
import re
from typing import Dict, List, Any, Optional

class RefactoringSuggester:
    def __init__(self, llm_integration=None):
        """
        Initialize the refactoring suggester.
        
        Args:
            llm_integration: LLM integration instance for enhanced suggestions
        """
        self.llm_integration = llm_integration
    
    def suggest_refactorings(self, code_files: Dict[str, str], callgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Suggest refactorings for code files based on callgraph analysis.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            callgraph: Callgraph data
            
        Returns:
            List of refactoring suggestions
        """
        suggestions = []
        
        # Check for high complexity functions
        suggestions.extend(self._check_high_complexity(code_files, callgraph))
        
        # Check for error handling
        suggestions.extend(self._check_error_handling(code_files, callgraph))
        
        # Check for magic strings/numbers
        suggestions.extend(self._check_magic_values(code_files))
        
        return suggestions
    
    async def suggest_enhanced_refactorings(self, code_files: Dict[str, str], callgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Suggest enhanced refactorings using LLM.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            callgraph: Callgraph data
            
        Returns:
            List of refactoring suggestions
        """
        if not self.llm_integration:
            return self.suggest_refactorings(code_files, callgraph)
        
        # Combine all code files into a single string for the LLM
        combined_code = ""
        for file_path, code in code_files.items():
            combined_code += f"# File: {file_path}\n{code}\n\n"
        
        # Use LLM to suggest refactorings
        suggestions = await self.llm_integration.suggest_refactoring(combined_code, callgraph)
        return suggestions
    
    def _check_high_complexity(self, code_files: Dict[str, str], callgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Check for high complexity functions and suggest refactorings.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            callgraph: Callgraph data
            
        Returns:
            List of refactoring suggestions
        """
        suggestions = []
        
        # Find functions with high complexity
        high_complexity_nodes = [node for node in callgraph.get("nodes", []) if node.get("complexity", 0) > 7]
        
        for node in high_complexity_nodes:
            function_id = node.get("id", "")
            
            # Extract module and function name
            parts = function_id.split(".")
            if len(parts) < 2:
                continue
            
            module_name = parts[0]
            function_name = parts[-1]
            
            # Find the file containing this function
            for file_path, code in code_files.items():
                if module_name in file_path:
                    try:
                        tree = ast.parse(code)
                        
                        for ast_node in ast.walk(tree):
                            if isinstance(ast_node, (ast.FunctionDef, ast.AsyncFunctionDef)) and ast_node.name == function_name:
                                # Get the function code
                                function_code = self._get_function_code(code, ast_node)
                                
                                # Generate a refactored version
                                refactored_code = self._extract_complex_logic(function_code, function_name)
                                
                                if refactored_code != function_code:
                                    suggestions.append({
                                        "id": f"REF-COMPLEX-{len(suggestions) + 1}",
                                        "title": f"Extract Method in {function_name}",
                                        "description": f"The {function_name} function is too complex (complexity: {node.get('complexity')}). Extract complex logic into separate methods.",
                                        "severity": "high",
                                        "location": f"{file_path}:{ast_node.lineno}-{ast_node.end_lineno}",
                                        "before": function_code,
                                        "after": refactored_code
                                    })
                    
                    except Exception as e:
                        print(f"Error analyzing {file_path}: {str(e)}")
        
        return suggestions
    
    def _check_error_handling(self, code_files: Dict[str, str], callgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Check for missing error handling and suggest refactorings.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            callgraph: Callgraph data
            
        Returns:
            List of refactoring suggestions
        """
        suggestions = []
        
        for file_path, code in code_files.items():
            try:
                tree = ast.parse(code)
                
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Check if the function has try-except blocks
                        has_try_except = any(isinstance(child, ast.Try) for child in ast.walk(node))
                        
                        # Check if the function has potentially risky operations
                        has_risky_ops = (
                            any(isinstance(child, ast.Call) and hasattr(child.func, 'attr') and child.func.attr in ['open', 'read', 'write'] for child in ast.walk(node)) or
                            any(isinstance(child, ast.Subscript) for child in ast.walk(node))
                        )
                        
                        if has_risky_ops and not has_try_except:
                            function_code = self._get_function_code(code, node)
                            refactored_code = self._add_error_handling(function_code, node.name)
                            
                            if refactored_code != function_code:
                                suggestions.append({
                                    "id": f"REF-ERROR-{len(suggestions) + 1}",
                                    "title": f"Add Error Handling in {node.name}",
                                    "description": f"The {node.name} function has potentially risky operations but no error handling.",
                                    "severity": "medium",
                                    "location": f"{file_path}:{node.lineno}-{node.end_lineno}",
                                    "before": function_code,
                                    "after": refactored_code
                                })
            
            except Exception as e:
                print(f"Error analyzing {file_path}: {str(e)}")
        
        return suggestions
    
    def _check_magic_values(self, code_files: Dict[str, str]) -> List[Dict[str, Any]]:
        """
        Check for magic strings/numbers and suggest refactorings.
        
        Args:
            code_files: Dictionary mapping file paths to code content
            
        Returns:
            List of refactoring suggestions
        """
        suggestions = []
        
        for file_path, code in code_files.items():
            try:
                tree = ast.parse(code)
                
                # Find functions with magic strings
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        # Check for string literals used in comparisons
                        magic_strings = {}
                        
                        for child in ast.walk(node):
                            if isinstance(child, ast.Compare):
                                for value in [child.left] + child.comparators:
                                    if isinstance(value, ast.Str) and len(value.s) <= 3:
                                        if value.s not in magic_strings:
                                            magic_strings[value.s] = 0
                                        magic_strings[value.s] += 1
                        
                        # If the same magic string is used multiple times, suggest refactoring
                        repeated_magic_strings = {s: count for s, count in magic_strings.items() if count > 1}
                        
                        if repeated_magic_strings:
                            function_code = self._get_function_code(code, node)
                            refactored_code = self._replace_magic_strings(function_code, repeated_magic_strings, node.name)
                            
                            if refactored_code != function_code:
                                suggestions.append({
                                    "id": f"REF-MAGIC-{len(suggestions) + 1}",
                                    "title": f"Use Constants for Magic Strings in {node.name}",
                                    "description": f"The {node.name} function uses magic strings that should be replaced with named constants.",
                                    "severity": "low",
                                    "location": f"{file_path}:{node.lineno}-{node.end_lineno}",
                                    "before": function_code,
                                    "after": refactored_code
                                })
            
            except Exception as e:
                print(f"Error analyzing {file_path}: {str(e)}")
        
        return suggestions
    
    def _get_function_code(self, full_code: str, node: ast.AST) -> str:
        """
        Extract the code of a function from the full code.
        
        Args:
            full_code: Full code content
            node: AST node of the function
            
        Returns:
            Function code as a string
        """
        lines = full_code.splitlines()
        return "\n".join(lines[node.lineno - 1:node.end_lineno])
    
    def _extract_complex_logic(self, function_code: str, function_name: str) -> str:
        """
        Extract complex logic from a function into a separate method.
        
        Args:
            function_code: Original function code
            function_name: Function name
            
        Returns:
            Refactored function code
        """
        # This is a simplified implementation
        # In a real implementation, you would use more sophisticated analysis
        
        # Look for comment indicating complex logic
        match = re.search(r"(\s*# .* complex.*\n)(\s*)(.*\n)(\s*.*\n)*?(\s*)", function_code, re.IGNORECASE)
        
        if match:
            indent = match.group(2)
            complex_code = match.group(0)
            
            # Create a new function for the complex logic
            helper_name = f"_{function_name}_helper"
            
            # Replace the complex code with a call to the helper function
            simplified_code = function_code.replace(complex_code, f"{indent}# Extract complex logic to helper function\n{indent}{helper_name}()\n{indent}\n")
            
            # Create the helper function
            helper_function = f"\ndef {helper_name}():\n    \"\"\"Helper function for {function_name}.\"\"\"\n{complex_code}"
            
            return simplified_code + helper_function
        
        return function_code
    
    def _add_error_handling(self, function_code: str, function_name: str) -> str:
        """
        Add error handling to a function.
        
        Args:
            function_code: Original function code
            function_name: Function name
            
        Returns:
            Refactored function code with error handling
        """
        # This is a simplified implementation
        # In a real implementation, you would use more sophisticated analysis
        
        lines = function_code.splitlines()
        
        # Find the indentation level
        match = re.match(r"(\s*)def", lines[0])
        base_indent = match.group(1) if match else ""
        body_indent = base_indent + "    "
        
        # Find the function body (skip the function signature and docstring)
        body_start = 1
        while body_start < len(lines) and (not lines[body_start].strip() or lines[body_start].strip().startswith('"""') or lines[body_start].strip().startswith("'''")):
            body_start += 1
        
        # Add try-except block
        result = lines[:body_start]
        result.append(f"{body_indent}try:")
        
        # Indent the function body
        for i in range(body_start, len(lines)):
            result.append(f"    {lines[i]}")
        
        # Add except block
        result.append(f"{body_indent}except Exception as e:")
        result.append(f"{body_indent}    print(f\"Error in {function_name}: {{str(e)}}\")") 
        result.append(f"{body_indent}    # Consider proper error handling here")
        result.append(f"{body_indent}    raise")
        
        return "\n".join(result)
    
    def _replace_magic_strings(self, function_code: str, magic_strings: Dict[str, int], function_name: str) -> str:
        """
        Replace magic strings with constants.
        
        Args:
            function_code: Original function code
            magic_strings: Dictionary mapping magic strings to their occurrence count
            function_name: Function name
            
        Returns:
            Refactored function code with constants
        """
        # This is a simplified implementation
        # In a real implementation, you would use more sophisticated analysis
        
        lines = function_code.splitlines()
        
        # Find the indentation level
        match = re.match(r"(\s*)def", lines[0])
        base_indent = match.group(1) if match else ""
        
        # Create constants for magic strings
        constants = []
        for string, _ in magic_strings.items():
            constant_name = f"STATUS_{string.upper()}" if string.isalpha() else f"CODE_{ord(string[0])}"
            constants.append(f"{base_indent}# Define constants at the module level")
            constants.append(f"{base_indent}{constant_name} = \"{string}\"")
        
        constants.append("")  # Add an empty line
        
        # Replace magic strings with constants in the function body
        modified_function = function_code
        for string, _ in magic_strings.items():
            constant_name = f"STATUS_{string.upper()}" if string.isalpha() else f"CODE_{ord(string[0])}"
            modified_function = modified_function.replace(f"\"{string}\"", constant_name)
            modified_function = modified_function.replace(f"'{string}'", constant_name)
        
        return "\n".join(constants) + "\n" + modified_function

# Example usage
if __name__ == "__main__":
    # Sample code files
    code_files = {
        "utils.py": """
def get_status(code):
    if code == "A":
        return "Active"
    elif code == "I":
        return "Inactive"
    elif code == "P":
        return "Pending"
    return "Unknown"
"""
    }
    
    # Sample callgraph
    callgraph = {
        "nodes": [
            {"id": "utils.get_status", "group": 1, "type": "function", "complexity": 3}
        ],
        "links": []
    }
    
    suggester = RefactoringSuggester()
    suggestions = suggester.suggest_refactorings(code_files, callgraph)
    
    print(f"Found {len(suggestions)} refactoring suggestions:")
    for suggestion in suggestions:
        print(f"\n{suggestion['id']}: {suggestion['title']} ({suggestion['severity']} priority)")
        print(f"Description: {suggestion['description']}")
        print(f"Location: {suggestion['location']}")
        print("\nBefore:")
        print(suggestion['before'])
        print("\nAfter:")
        print(suggestion['after'])
