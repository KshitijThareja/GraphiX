import os
import re
from urllib.parse import urlparse

def normalize_repository_id(repo_url_or_path: str) -> str:
    """
    Normalize a repository URL or path to a consistent repository ID format.
    
    Args:
        repo_url_or_path: A repository URL (e.g., https://github.com/user/repo) or local path
        
    Returns:
        A normalized repository ID (e.g., 'user-repo' or just 'repo')
    """
    # Handle empty or None input
    if not repo_url_or_path:
        return ""
    
    # Convert to string if not already
    repo_url_or_path = str(repo_url_or_path)
    
    # Check if it's a local path
    if os.path.exists(repo_url_or_path):
        # Extract the last directory name as the repository ID
        repo_id = os.path.basename(os.path.normpath(repo_url_or_path))
    else:
        # Assume it's a URL
        parsed_url = urlparse(repo_url_or_path)
        
        # Extract path without leading/trailing slashes
        path = parsed_url.path.strip('/')
        
        if path:
            # Get the last part of the path (the repository name)
            repo_id = path.split('/')[-1]
        else:
            # If there's no path, use the netloc (domain) as fallback
            repo_id = parsed_url.netloc.split('.')[0] if parsed_url.netloc else repo_url_or_path
    
    # Remove .git extension if present
    repo_id = repo_id.replace('.git', '')
    
    # Remove any query parameters or fragments that might be in the ID
    repo_id = repo_id.split('?')[0].split('#')[0]
    
    # Replace special characters with underscores
    repo_id = re.sub(r'[^\w\-]', '_', repo_id)
    
    # Convert to lowercase for case-insensitive matching
    repo_id = repo_id.lower()
    
    return repo_id