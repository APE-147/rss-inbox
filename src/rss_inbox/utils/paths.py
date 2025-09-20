"""Path utilities for RSS Inbox project."""

import json
import os
import re
from pathlib import Path
from typing import Optional


def slugify(name: str) -> str:
    """
    Normalize project name to slug format.
    
    Rules:
    - Convert to lowercase
    - Replace all hyphens with underscores
    - Replace any sequence of non-alphanumeric characters with a single underscore
    - Trim leading/trailing underscores
    
    Args:
        name: The name to slugify
        
    Returns:
        The slugified name
    """
    # Convert to lowercase
    slug = name.lower()
    
    # Replace hyphens with underscores
    slug = slug.replace('-', '_')
    
    # Replace any sequence of non-alphanumeric characters with a single underscore
    slug = re.sub(r'[^a-zA-Z0-9_]+', '_', slug)
    
    # Trim leading/trailing underscores
    slug = slug.strip('_')
    
    return slug


def get_project_dir() -> Path:
    """
    Get the project data directory based on the configured scheme.
    
    Returns:
        Path to the project data directory
        
    Raises:
        RuntimeError: If project configuration is missing or invalid
    """
    # Get project root (where .project_config.json should be)
    project_root = Path(__file__).parent.parent.parent.parent
    config_file = project_root / ".project_config.json"
    
    if not config_file.exists():
        raise RuntimeError(f"Project configuration not found: {config_file}")
    
    try:
        with open(config_file, 'r') as f:
            config = json.load(f)
    except (json.JSONDecodeError, IOError) as e:
        raise RuntimeError(f"Failed to read project configuration: {e}")
    
    data_scheme = config.get('data_scheme')
    if not data_scheme:
        raise RuntimeError("Missing 'data_scheme' in project configuration")
    
    if data_scheme == "project_local":
        # Scheme A: project-local data
        data_dir = project_root / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    elif data_scheme == "data_root":
        # Scheme B: Data Root
        data_root = os.path.expanduser("~/Developer/Cloud/Dropbox/-Code-/Data/srv")
        slug = config.get('slug', slugify(project_root.name))
        data_dir = Path(data_root) / slug
        data_dir.mkdir(parents=True, exist_ok=True)
        return data_dir
    else:
        raise RuntimeError(f"Invalid data_scheme: {data_scheme}")


def get_project_root() -> Path:
    """
    Get the project root directory.
    
    Returns:
        Path to the project root directory
    """
    return Path(__file__).parent.parent.parent.parent


def ensure_data_dir() -> Path:
    """
    Ensure the data directory exists and return its path.
    
    Returns:
        Path to the data directory
    """
    data_dir = get_project_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


def get_config_file_path() -> Path:
    """Get the path to the configuration file."""
    # Look for config.yaml in project root first
    project_root = get_project_root()
    config_path = project_root / "config.yaml"
    if config_path.exists():
        return config_path
    
    # Fallback to data directory
    return get_project_dir() / "config.yaml"


def get_state_file_path() -> Path:
    """Get the path to the state file."""
    return get_log_dir() / "state.json"


def get_log_dir() -> Path:
    """Get the log directory path."""
    log_dir = get_project_dir() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir
