import os
import ast
import json
import subprocess
from pathlib import Path
from typing import Dict, List, Set, Optional
import tempfile
import shutil
import httpx
from git import Repo
from fastapi import HTTPException
from transformers import pipeline, AutoTokenizer, AutoModelForSeq2SeqLM
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class CallgraphGenerator:
    def __init__(self):
        self.nodes = []
        self.links = []
        self.functions = {}
        self.classes = {}
        self.imports = {}
        self.complexity_scores = {}
        self.repo_path = ""
        try:
            # Load Salesforce/codet5-base
            checkpoint = "Salesforce/codet5-base"
            self.tokenizer = AutoTokenizer.from_pretrained(checkpoint)
            self.model = AutoModelForSeq2SeqLM.from_pretrained(checkpoint)
            self.generator = pipeline(
                "text2text-generation",
                model=self.model,
                tokenizer=self.tokenizer,
                device=-1,  # CPU
            )
            logger.info(f"Successfully loaded model: {checkpoint}")
        except Exception as e:
            logger.error(f"Failed to load model {checkpoint}: {str(e)}")
            raise Exception(f"Model loading failed: {str(e)}")

    async def clone_repository(self, repo_url: str, access_token: Optional[str] = None) -> str:
        """Clone a GitHub repository to a temporary directory"""
        temp_dir = tempfile.mkdtemp()
        self.repo_path = temp_dir

        try:
            if access_token:
                auth_url = repo_url.replace("https://", f"https://{access_token}@")
                Repo.clone_from(auth_url, temp_dir)
            else:
                Repo.clone_from(repo_url, temp_dir)
            return temp_dir
        except Exception as e:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise HTTPException(
                status_code=400,
                detail=f"Failed to clone repository: {str(e)}"
            )

    async def analyze_repository(self, repo_path: str) -> Dict[str, List]:
        """Analyze all Python files in a repository"""
        for root, _, files in os.walk(repo_path):
            for file in files:
                if file.endswith('.py'):
                    file_path = os.path.join(root, file)
                    self.analyze_file(file_path)

        return self.generate_callgraph()

    def analyze_file(self, file_path: str) -> None:
        """Analyze a single Python file"""
        try:
            with open(file_path, 'r', encoding='utf-8') as file:
                content = file.read()

            tree = ast.parse(content)
            module_name = os.path.relpath(file_path, self.repo_path).replace('.py', '').replace(os.sep, '.')

            # Collect imports
            self.imports[module_name] = []
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.imports[module_name].append(alias.name)
                elif isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    for alias in node.names:
                        self.imports[module_name].append(f"{module}.{alias.name}")

            # Process class definitions
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef):
                    class_name = f"{module_name}.{node.name}"
                    self.classes[class_name] = {
                        'methods': [],
                        'file': file_path,
                        'lineno': node.lineno
                    }

                    # Process class methods
                    for item in node.body:
                        if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                            method_name = f"{class_name}.{item.name}"
                            complexity = self._calculate_complexity(item)

                            self.functions[method_name] = {
                                'node': item,
                                'file': file_path,
                                'complexity': complexity,
                                'type': 'method',
                                'class': class_name
                            }
                            self.classes[class_name]['methods'].append(method_name)

            # Process standalone functions
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    # Skip methods (already processed)
                    if any(isinstance(parent, ast.ClassDef) for parent in self._get_parents(node)):
                        continue

                    func_name = f"{module_name}.{node.name}"
                    complexity = self._calculate_complexity(node)

                    self.functions[func_name] = {
                        'node': node,
                        'file': file_path,
                        'complexity': complexity,
                        'type': 'function'
                    }

        except Exception as e:
            print(f"Error analyzing file {file_path}: {str(e)}")

    def _get_parents(self, node: ast.AST) -> List[ast.AST]:
        """Get all parent nodes of a given node"""
        parents = []
        current = node
        while hasattr(current, 'parent'):
            parents.append(current.parent)
            current = current.parent
        return parents

    def generate_callgraph(self) -> Dict[str, List]:
        """Generate the callgraph structure with LLM enrichment"""
        # Create nodes
        for func_name, func_info in self.functions.items():
            group = self._determine_group(func_name)

            # LLM-based enrichment
            prompt = f"Analyze function {func_name} with complexity {func_info['complexity']}. Provide a one-sentence description and a refactoring suggestion."
            llm_response = self.generator(prompt, max_length=100)[0]['generated_text']
            purpose = llm_response.split('.')[0] + '.' if '.' in llm_response else llm_response
            suggestion = llm_response.split('.')[-1] if '.' in llm_response else "No suggestion."

            self.nodes.append({
                'id': func_name,
                'group': group,
                'type': func_info['type'],
                'complexity': func_info['complexity'],
                'file': func_info['file'],
                'class': func_info.get('class', ''),
                'metadata': {
                    'docstring': purpose,
                    'refactoring': suggestion
                }
            })

            # Find calls within this function
            calls = self._find_function_calls(func_info['node'])

            # Create links for calls to functions we know about
            for called_func in calls:
                if called_func in self.functions:
                    self.links.append({
                        'source': func_name,
                        'target': called_func,
                        'value': 1,
                        'type': 'call'
                    })
                elif '.' in called_func:
                    class_name, method_name = called_func.rsplit('.', 1)
                    if class_name in self.classes and any(m.endswith(method_name) for m in self.classes[class_name]['methods']):
                        full_method_name = f"{class_name}.{method_name}"
                        self.links.append({
                            'source': func_name,
                            'target': full_method_name,
                            'value': 1,
                            'type': 'call'
                        })

        return {
            'nodes': self.nodes,
            'links': self.links,
            'classes': list(self.classes.keys()),
            'imports': self.imports,
            'metadata': {
                'total_nodes': len(self.nodes),
                'total_links': len(self.links),
                'avg_complexity': sum(n['complexity'] for n in self.nodes) / len(self.nodes) if self.nodes else 0
            }
        }

    def _calculate_complexity(self, node: ast.AST) -> int:
        """Calculate cyclomatic complexity"""
        complexity = 1

        for subnode in ast.walk(node):
            if isinstance(subnode, (ast.If, ast.While, ast.For, ast.AsyncFor)):
                complexity += 1
            elif isinstance(subnode, ast.BoolOp):
                complexity += len(subnode.values) - 1
            elif isinstance(subnode, ast.Try):
                complexity += len(subnode.handlers)
            elif isinstance(subnode, (ast.With, ast.AsyncWith)):
                complexity += 1

        return complexity

    def _find_function_calls(self, node: ast.AST) -> Set[str]:
        """Find all function calls in a node"""
        calls = set()

        for subnode in ast.walk(node):
            if isinstance(subnode, ast.Call):
                if isinstance(subnode.func, ast.Name):
                    calls.add(subnode.func.id)
                elif isinstance(subnode.func, ast.Attribute):
                    if isinstance(subnode.func.value, ast.Name):
                        calls.add(f"{subnode.func.value.id}.{subnode.func.attr}")

        return calls

    def _determine_group(self, func_name: str) -> int:
        """Determine group for visualization based on module/class"""
        if '.' in func_name:
            parts = func_name.split('.')
            if len(parts) > 2:  # Method of a class
                return hash(parts[0] + '.' + parts[1]) % 10
            return hash(parts[0]) % 10
        return 0

    async def cleanup(self):
        """Clean up the cloned repository"""
        if self.repo_path and os.path.exists(self.repo_path):
            shutil.rmtree(self.repo_path, ignore_errors=True)