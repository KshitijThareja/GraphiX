"""
GitHub integration module for GraphiX.
This module is responsible for integrating with GitHub.
"""

import os
import tempfile
import shutil
import httpx
from typing import Dict, List, Any, Optional
import asyncio
import subprocess

class GitHubIntegration:
    def __init__(self, token: Optional[str] = None):
        """
        Initialize the GitHub integration.
        
        Args:
            token: GitHub API token (default: None, will use environment variable)
        """
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.base_url = "https://api.github.com"
        self.headers = {}
        
        if self.token:
            self.headers["Authorization"] = f"token {self.token}"
    
    async def search_repositories(self, query: str, language: Optional[str] = None, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Search for repositories on GitHub.
        
        Args:
            query: Search query
            language: Filter by programming language (default: None)
            limit: Maximum number of results to return (default: 10)
            
        Returns:
            List of repository information
        """
        search_query = query
        if language:
            search_query += f" language:{language}"
        
        url = f"{self.base_url}/search/repositories"
        params = {
            "q": search_query,
            "sort": "stars",
            "order": "desc",
            "per_page": limit
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            repositories = []
            for item in data.get("items", []):
                repositories.append({
                    "id": item["id"],
                    "name": item["full_name"],
                    "description": item["description"],
                    "url": item["html_url"],
                    "stars": item["stargazers_count"],
                    "language": item["language"],
                    "updated_at": item["updated_at"]
                })
            
            return repositories
    
    async def get_repository_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        Get information about a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            
        Returns:
            Repository information
        """
        url = f"{self.base_url}/repos/{owner}/{repo}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            return response.json()
    
    async def clone_repository(self, repo_url: str, branch: str = "main") -> str:
        """
        Clone a repository to a temporary directory.
        
        Args:
            repo_url: Repository URL
            branch: Branch to clone (default: main)
            
        Returns:
            Path to the cloned repository
        """
        temp_dir = tempfile.mkdtemp()
        
        try:
            # Use git command to clone the repository
            process = await asyncio.create_subprocess_exec(
                "git", "clone", "--branch", branch, "--single-branch", repo_url, temp_dir,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            if process.returncode != 0:
                raise Exception(f"Failed to clone repository: {stderr.decode()}")
            
            return temp_dir
        
        except Exception as e:
            # Clean up on error
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise e
    
    async def get_file_content(self, owner: str, repo: str, path: str, ref: str = "main") -> str:
        """
        Get the content of a file from a repository.
        
        Args:
            owner: Repository owner
            repo: Repository name
            path: Path to the file
            ref: Git reference (default: main)
            
        Returns:
            File content
        """
        url = f"{self.base_url}/repos/{owner}/{repo}/contents/{path}"
        params = {"ref": ref}
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers, params=params)
            response.raise_for_status()
            data = response.json()
            
            if data.get("type") != "file":
                raise ValueError(f"Path does not point to a file: {path}")
            
            # Content is base64 encoded
            import base64
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content
    
    def parse_github_url(self, url: str) -> Dict[str, str]:
        """
        Parse a GitHub URL into owner and repo.
        
        Args:
            url: GitHub repository URL
            
        Returns:
            Dictionary with owner and repo
        """
        # Remove .git suffix if present
        if url.endswith(".git"):
            url = url[:-4]
        
        # Handle both HTTPS and SSH URLs
        if url.startswith("https://github.com/"):
            parts = url.replace("https://github.com/", "").split("/")
        elif url.startswith("git@github.com:"):
            parts = url.replace("git@github.com:", "").split("/")
        else:
            raise ValueError(f"Invalid GitHub URL: {url}")
        
        if len(parts) < 2:
            raise ValueError(f"Invalid GitHub URL: {url}")
        
        return {
            "owner": parts[0],
            "repo": parts[1]
        }

# Example usage
if __name__ == "__main__":
    import asyncio
    
    async def main():
        # This is just an example; in a real application, you would use your actual token
        github = GitHubIntegration(token="your_github_token_here")
        
        # Search for repositories
        repositories = await github.search_repositories("tensorflow", language="python", limit=5)
        print(f"Found {len(repositories)} repositories:")
        for repo in repositories:
            print(f"- {repo['name']} ({repo['stars']} stars)")
        
        # Get repository info
        if repositories:
            owner, repo = repositories[0]["name"].split("/")
            info = await github.get_repository_info(owner, repo)
            print(f"\nRepository info for {info['full_name']}:")
            print(f"Description: {info['description']}")
            print(f"Stars: {info['stargazers_count']}")
            print(f"Forks: {info['forks_count']}")
        
        # Parse GitHub URL
        url = "https://github.com/tensorflow/tensorflow"
        parsed = github.parse_github_url(url)
        print(f"\nParsed URL {url}:")
        print(f"Owner: {parsed['owner']}")
        print(f"Repo: {parsed['repo']}")
    
    asyncio.run(main())
