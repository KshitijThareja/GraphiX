"""
LLM integration module for GraphiX.
This module is responsible for integrating with Large Language Models.
"""

import os
import json
from typing import List, Dict, Any, Optional
import httpx

class LLMIntegration:
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the LLM integration.
        
        Args:
            api_key: API key for the LLM service (default: None, will use environment variable)
        """
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        if not self.api_key:
            raise ValueError("API key is required. Set OPENAI_API_KEY environment variable or pass it to the constructor.")
        
        self.base_url = "https://api.openai.com/v1"
        self.model = "gpt-4"  # Default model
    
    async def chat_completion(self, messages: List[Dict[str, str]]) -> Dict[str, Any]:
        """
        Generate a chat completion using the OpenAI API.
        
        Args:
            messages: List of message objects with role and content
            
        Returns:
            Response from the API
        """
        url = f"{self.base_url}/chat/completions"
        
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}"
        }
        
        data = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.7
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
    
    async def analyze_code(self, code: str) -> Dict[str, Any]:
        """
        Analyze code using the LLM.
        
        Args:
            code: Code to analyze
            
        Returns:
            Analysis results
        """
        messages = [
            {"role": "system", "content": "You are a code analysis assistant. Analyze the following code and provide insights."},
            {"role": "user", "content": f"Analyze this code:\n\n```python\n{code}\n```"}
        ]
        
        response = await self.chat_completion(messages)
        return {
            "analysis": response["choices"][0]["message"]["content"],
            "model": response["model"]
        }
    
    async def generate_documentation(self, code: str, callgraph: Dict[str, Any]) -> str:
        """
        Generate documentation for code using the LLM.
        
        Args:
            code: Code to document
            callgraph: Callgraph data
            
        Returns:
            Generated documentation in Markdown format
        """
        # Convert callgraph to a readable format for the LLM
        callgraph_summary = self._format_callgraph_for_prompt(callgraph)
        
        messages = [
            {"role": "system", "content": "You are a documentation assistant. Generate comprehensive documentation for the following code and its callgraph."},
            {"role": "user", "content": f"Generate documentation in Markdown format for this code and its callgraph:\n\nCode:\n```python\n{code}\n```\n\nCallgraph Summary:\n{callgraph_summary}"}
        ]
        
        response = await self.chat_completion(messages)
        return response["choices"][0]["message"]["content"]
    
    async def suggest_refactoring(self, code: str, callgraph: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Suggest refactoring for code using the LLM.
        
        Args:
            code: Code to refactor
            callgraph: Callgraph data
            
        Returns:
            List of refactoring suggestions
        """
        # Convert callgraph to a readable format for the LLM
        callgraph_summary = self._format_callgraph_for_prompt(callgraph)
        
        messages = [
            {"role": "system", "content": "You are a code refactoring assistant. Suggest improvements for the following code based on its callgraph."},
            {"role": "user", "content": f"Suggest refactoring for this code and its callgraph. For each suggestion, provide a title, description, severity (high/medium/low), location, and before/after code examples:\n\nCode:\n```python\n{code}\n```\n\nCallgraph Summary:\n{callgraph_summary}"}
        ]
        
        response = await self.chat_completion(messages)
        
        # Parse the response to extract structured refactoring suggestions
        # This is a simplified version; in a real implementation, you would need more robust parsing
        suggestions_text = response["choices"][0]["message"]["content"]
        
        # For demonstration purposes, return a mock structured response
        # In a real implementation, you would parse the LLM's response
        return [
            {
                "id": "REF-001",
                "title": "Extract Method",
                "description": "Extract complex logic into a separate method",
                "severity": "high",
                "location": "main.py:45-67",
                "before": "def complex_function():\n    # Complex logic here",
                "after": "def complex_function():\n    extracted_method()\n\ndef extracted_method():\n    # Complex logic here"
            }
        ]
    
    async def answer_question(self, question: str, code: str, callgraph: Dict[str, Any]) -> str:
        """
        Answer a question about code using the LLM.
        
        Args:
            question: Question to answer
            code: Code context
            callgraph: Callgraph data
            
        Returns:
            Answer to the question
        """
        # Convert callgraph to a readable format for the LLM
        callgraph_summary = self._format_callgraph_for_prompt(callgraph)
        
        messages = [
            {"role": "system", "content": "You are a code assistant. Answer questions about the following code and its callgraph."},
            {"role": "user", "content": f"Code:\n```python\n{code}\n```\n\nCallgraph Summary:\n{callgraph_summary}\n\nQuestion: {question}"}
        ]
        
        response = await self.chat_completion(messages)
        return response["choices"][0]["message"]["content"]
    
    def _format_callgraph_for_prompt(self, callgraph: Dict[str, Any]) -> str:
        """
        Format callgraph data for inclusion in a prompt.
        
        Args:
            callgraph: Callgraph data
            
        Returns:
            Formatted callgraph summary
        """
        nodes = callgraph.get("nodes", [])
        links = callgraph.get("links", [])
        
        summary = "Functions:\n"
        for node in nodes:
            summary += f"- {node['id']} (complexity: {node['complexity']})\n"
        
        summary += "\nDependencies:\n"
        for link in links:
            summary += f"- {link['source']} calls {link['target']}\n"
        
        return summary

# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # This is just an example; in a real application, you would use your actual API key
        llm = LLMIntegration(api_key="your_api_key_here")
        
        code = """
def calculate_total(items):
    total = 0
    for item in items:
        total += item['price'] * item['quantity']
    return total
        """
        
        callgraph = {
            "nodes": [
                {"id": "calculate_total", "group": 1, "type": "function", "complexity": 3}
            ],
            "links": []
        }
        
        analysis = await llm.analyze_code(code)
        print("Analysis:", analysis)
        
        documentation = await llm.generate_documentation(code, callgraph)
        print("Documentation:", documentation)
        
        refactoring = await llm.suggest_refactoring(code, callgraph)
        print("Refactoring:", refactoring)
        
        answer = await llm.answer_question("What does this function do?", code, callgraph)
        print("Answer:", answer)
    
    asyncio.run(main())
