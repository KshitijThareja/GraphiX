from fastapi import FastAPI, HTTPException, Depends, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, HttpUrl
from typing import List, Dict, Any, Optional
import httpx
import os
import json
from datetime import datetime
import random

app = FastAPI(title="GraphiX API", description="GitHub Codebase Evaluation Tool with Callgraphs and LLMs")

# Add CORS middleware to allow requests from the Next.js frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class Repository(BaseModel):
    url: HttpUrl
    branch: str = "main"
    
class CallgraphNode(BaseModel):
    id: str
    group: int
    type: str
    complexity: int
    
class CallgraphLink(BaseModel):
    source: str
    target: str
    value: int
    
class Callgraph(BaseModel):
    nodes: List[CallgraphNode]
    links: List[CallgraphLink]
    
class ChatMessage(BaseModel):
    role: str
    content: str
    
class ChatRequest(BaseModel):
    messages: List[ChatMessage]
    repository_url: HttpUrl
    
class RefactoringSuggestion(BaseModel):
    id: str
    title: str
    description: str
    severity: str
    location: str
    before: str
    after: str

# Mock data for development
def generate_mock_callgraph():
    # This would be replaced with actual callgraph generation logic
    nodes = [
        {"id": "main", "group": 1, "type": "function", "complexity": 5},
        {"id": "process_data", "group": 2, "type": "function", "complexity": 8},
        {"id": "validate_input", "group": 2, "type": "function", "complexity": 3},
        {"id": "transform_data", "group": 2, "type": "function", "complexity": 7},
        {"id": "save_results", "group": 3, "type": "function", "complexity": 4},
        {"id": "log_error", "group": 4, "type": "function", "complexity": 2},
        {"id": "display_output", "group": 5, "type": "function", "complexity": 6},
    ]
    
    links = [
        {"source": "main", "target": "process_data", "value": 1},
        {"source": "main", "target": "display_output", "value": 1},
        {"source": "process_data", "target": "validate_input", "value": 1},
        {"source": "process_data", "target": "transform_data", "value": 1},
        {"source": "process_data", "target": "save_results", "value": 1},
        {"source": "process_data", "target": "log_error", "value": 1},
        {"source": "transform_data", "target": "log_error", "value": 1},
        {"source": "save_results", "target": "log_error", "value": 1},
    ]
    
    return {"nodes": nodes, "links": links}

# Routes
@app.get("/")
async def root():
    return {"message": "Welcome to GraphiX API"}

@app.post("/analyze", response_model=Callgraph)
async def analyze_repository(repository: Repository):
    """
    Analyze a GitHub repository and generate a callgraph
    """
    # In a real implementation, this would:
    # 1. Clone the repository
    # 2. Run static analysis to generate callgraph
    # 3. Enrich with LLM insights
    # 4. Return the result
    
    # For now, return mock data
    return generate_mock_callgraph()

@app.post("/chat", response_model=Dict[str, Any])
async def chat_with_llm(request: ChatRequest):
    """
    Chat with LLM about the repository
    """
    # In a real implementation, this would:
    # 1. Process the chat history
    # 2. Provide context about the repository to the LLM
    # 3. Generate a response
    
    # Mock response
    responses = [
        "Based on the callgraph analysis, the `process_data` function is the most complex with a cyclomatic complexity of 8. It has multiple dependencies and might be a good candidate for refactoring.",
        "The repository structure shows a typical MVC pattern. The controller functions have high coupling with the model layer, which could be improved by introducing a service layer.",
        "Looking at the code, I notice that error handling is inconsistent across modules. The `log_error` function is called from multiple places but with different parameters.",
        "The `validate_input` function is well-designed with clear validation rules. It's called by `process_data` and helps maintain data integrity throughout the application.",
        "There appears to be a potential memory leak in the `transform_data` function. It allocates resources but doesn't properly release them in all code paths.",
    ]
    
    return {
        "response": random.choice(responses),
        "timestamp": datetime.now().isoformat()
    }

@app.get("/documentation", response_model=Dict[str, Any])
async def generate_documentation(repository_url: HttpUrl = Query(...)):
    """
    Generate documentation for a repository
    """
    # In a real implementation, this would:
    # 1. Analyze the repository
    # 2. Generate documentation using LLM
    
    # Mock documentation
    documentation = """# Repository Documentation

## Overview

This repository contains a data processing application with several key components. The application follows a modular design pattern with clear separation of concerns.

## Functions

### main()

**Description**: Entry point of the application. Coordinates the overall flow by calling other functions.

**Parameters**: None

**Returns**: Exit code (0 for success, non-zero for failure)

**Dependencies**:
- process_data()
- display_output()

**Complexity**: 5

### process_data()

**Description**: Core function that handles data processing logic. It validates input, transforms data, and saves results.

**Parameters**:
- data (object): The input data to process

**Returns**: Processed data object

**Dependencies**:
- validate_input()
- transform_data()
- save_results()
- log_error()

**Complexity**: 8

### validate_input()

**Description**: Validates the input data against a schema to ensure it meets requirements.

**Parameters**:
- input (object): The input data to validate

**Returns**: Boolean indicating validity

**Dependencies**: None

**Complexity**: 3

### transform_data()

**Description**: Applies transformations to the validated data.

**Parameters**:
- data (object): The validated data to transform

**Returns**: Transformed data object

**Dependencies**:
- log_error()

**Complexity**: 7

### save_results()

**Description**: Persists the processed data to storage.

**Parameters**:
- results (object): The processed data to save

**Returns**: Boolean indicating success

**Dependencies**:
- log_error()

**Complexity**: 4

### log_error()

**Description**: Handles error logging throughout the application.

**Parameters**:
- message (string): Error message
- level (string, optional): Error severity level

**Returns**: None

**Dependencies**: None

**Complexity**: 2

### display_output()

**Description**: Renders the processed data for user viewing.

**Parameters**:
- data (object): The processed data to display

**Returns**: None

**Dependencies**: None

**Complexity**: 6

## Architecture

The application follows a linear processing flow:
1. Main entry point coordinates the process
2. Input data is validated
3. Valid data is transformed
4. Results are saved
5. Output is displayed to the user

Error handling is implemented throughout the process with the log_error function.

## Recommendations

Based on the callgraph analysis:

1. The process_data function has high complexity (8) and multiple dependencies. Consider refactoring into smaller, more focused functions.

2. The transform_data function also has relatively high complexity (7). Look for opportunities to break it down into simpler transformations.

3. Error handling is centralized through log_error, which is a good practice. Consider expanding with different severity levels.

4. The application has a clear flow but could benefit from more modular architecture, possibly introducing a service layer."""
    
    return {
        "documentation": documentation,
        "format": "markdown",
        "timestamp": datetime.now().isoformat()
    }

@app.get("/refactoring", response_model=List[RefactoringSuggestion])
async def get_refactoring_suggestions(repository_url: HttpUrl = Query(...)):
    """
    Get refactoring suggestions for a repository
    """
    # In a real implementation, this would:
    # 1. Analyze the repository
    # 2. Generate refactoring suggestions using LLM
    
    # Mock suggestions
    suggestions = [
        {
            "id": "REF-001",
            "title": "Extract Method in process_data",
            "description": "The process_data function is too complex (complexity: 8). Extract the data transformation logic into a separate method.",
            "severity": "high",
            "location": "main.py:45-67",
            "before": """def process_data(data):
    # Validate input
    if not validate_input(data):
        log_error("Invalid input data")
        return None
        
    # Transform data - this part is complex and should be extracted
    result = {}
    for key, value in data.items():
        if key.startswith("user_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["name"] = value
        elif key.startswith("score_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["score"] = int(value)
    
    # Save results
    if not save_results(result):
        log_error("Failed to save results")
        return None
        
    return result""",
            "after": """def process_data(data):
    # Validate input
    if not validate_input(data):
        log_error("Invalid input data")
        return None
        
    # Extract transformation to a new method
    result = transform_user_data(data)
    
    # Save results
    if not save_results(result):
        log_error("Failed to save results")
        return None
        
    return result
    
def transform_user_data(data):
    result = {}
    for key, value in data.items():
        if key.startswith("user_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["name"] = value
        elif key.startswith("score_"):
            user_id = key.split("_")[1]
            if user_id not in result:
                result[user_id] = {}
            result[user_id]["score"] = int(value)
    return result"""
        },
        {
            "id": "REF-002",
            "title": "Add Error Handling in transform_data",
            "description": "The transform_data function doesn't handle potential exceptions when processing data.",
            "severity": "medium",
            "location": "transform.py:23-35",
            "before": """def transform_data(data):
    result = {}
    for item in data:
        key = item["id"]
        value = process_item(item)
        result[key] = value
    return result""",
            "after": """def transform_data(data):
    result = {}
    for item in data:
        try:
            key = item["id"]
            value = process_item(item)
            result[key] = value
        except KeyError:
            log_error(f"Missing 'id' in item: {item}")
        except Exception as e:
            log_error(f"Error processing item: {str(e)}")
    return result"""
        },
        {
            "id": "REF-003",
            "title": "Use Constants for Magic Strings",
            "description": "Replace magic strings with named constants for better maintainability.",
            "severity": "low",
            "location": "utils.py:12-18",
            "before": """def get_status(code):
    if code == "A":
        return "Active"
    elif code == "I":
        return "Inactive"
    elif code == "P":
        return "Pending"
    return "Unknown\"""",
            "after": """# Define constants at the module level
STATUS_ACTIVE = "A"
STATUS_INACTIVE = "I"
STATUS_PENDING = "P"

def get_status(code):
    if code == STATUS_ACTIVE:
        return "Active"
    elif code == STATUS_INACTIVE:
        return "Inactive"
    elif code == STATUS_PENDING:
        return "Pending"
    return "Unknown\""""
        }
    ]
    
    return suggestions

@app.get("/search", response_model=List[Dict[str, Any]])
async def search_repositories(query: str = Query(...)):
    """
    Search for GitHub repositories
    """
    # In a real implementation, this would:
    # 1. Call GitHub API to search for repositories
    # 2. Return the results
    
    # Mock repositories
    repositories = [
        {
            "id": 1,
            "name": "tensorflow/tensorflow",
            "description": "An Open Source Machine Learning Framework for Everyone",
            "url": "https://github.com/tensorflow/tensorflow",
            "stars": 178000,
            "lastAnalyzed": "2023-10-15",
        },
        {
            "id": 2,
            "name": "facebook/react",
            "description": "A declarative, efficient, and flexible JavaScript library for building user interfaces",
            "url": "https://github.com/facebook/react",
            "stars": 215000,
        },
        {
            "id": 3,
            "name": "django/django",
            "description": "The Web framework for perfectionists with deadlines",
            "url": "https://github.com/django/django",
            "stars": 72000,
            "lastAnalyzed": "2023-11-02",
        },
        {
            "id": 4,
            "name": "microsoft/vscode",
            "description": "Visual Studio Code",
            "url": "https://github.com/microsoft/vscode",
            "stars": 154000,
        },
    ]
    
    # Filter by query (in a real implementation, this would be done by the GitHub API)
    filtered = [repo for repo in repositories if query.lower() in repo["name"].lower() or query.lower() in repo["description"].lower()]
    
    return filtered

@app.post("/research/dataset", response_model=Dict[str, Any])
async def generate_research_dataset(
    language: str = Query("python"),
    repo_count: int = Query(10),
    metrics: List[str] = Query(["complexity", "coupling", "cohesion"])
):
    """
    Generate a research dataset
    """
    # In a real implementation, this would:
    # 1. Fetch repositories
    # 2. Analyze them
    # 3. Generate a dataset
    
    return {
        "status": "success",
        "message": f"Dataset generation started for {repo_count} {language} repositories with metrics: {', '.join(metrics)}",
        "job_id": "dataset_job_123",
        "estimated_completion_time": "10 minutes"
    }

@app.post("/research/benchmark", response_model=Dict[str, Any])
    

@app.post("/research/benchmark", response_model=Dict[str, Any])
async def run_benchmark(
    baseline: str = Query("sonarqube"),
    metric: str = Query("precision"),
    repository_url: HttpUrl = Query(...)
):
    """
    Run a benchmark against a baseline tool
    """
    # In a real implementation, this would:
    # 1. Run the baseline tool on the repository
    # 2. Run GraphiX on the repository
    # 3. Compare the results
    
    return {
        "status": "success",
        "message": f"Benchmark started comparing GraphiX with {baseline} using {metric} metric",
        "job_id": "benchmark_job_456",
        "estimated_completion_time": "15 minutes"
    }

@app.post("/research/metrics", response_model=Dict[str, Any])
async def collect_metrics(
    repositories: List[HttpUrl],
    output_format: str = Query("csv"),
    reproducible: bool = Query(False)
):
    """
    Collect empirical metrics for research
    """
    # In a real implementation, this would:
    # 1. Analyze the repositories
    # 2. Collect metrics
    # 3. Generate a report
    
    return {
        "status": "success",
        "message": f"Metrics collection started for {len(repositories)} repositories in {output_format} format",
        "job_id": "metrics_job_789",
        "estimated_completion_time": "20 minutes"
    }

# Run the application
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
