"""Configuration management for RSS Inbox."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, validator
from pydantic import ConfigDict, model_validator

from .utils.paths import get_config_file_path


class FeedConfig(BaseModel):
    """Configuration for a single RSS feed."""

    model_config = ConfigDict(extra="ignore")

    name: Optional[str] = None
    url: str
    handler: str = "webpage"
    action: str = Field(default="auto", description="Action to perform: auto|singlefile|video_downloader|applescript|none")
    enabled: bool = True
    custom_params: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def _apply_legacy_aliases(cls, data: Any) -> Any:
        """Support legacy config keys like category/action/type."""
        if not isinstance(data, dict):
            return data

        data = data.copy()

        # Map legacy category/type fields to handler when handler missing
        if not data.get("handler"):
            for key in ("category", "type", "kind"):
                value = data.get(key)
                if isinstance(value, str) and value:
                    data["handler"] = value
                    break

        # Derive handler from legacy action names if still missing
        if not data.get("handler") and isinstance(data.get("action"), str):
            action_lower = data["action"].lower()
            if action_lower in {"applescript", "video_downloader", "video", "downie"}:
                data["handler"] = "video"
            elif action_lower in {"singlefile", "singlefile_cli", "webpage"}:
                data["handler"] = "webpage"

        # Normalize handler casing early
        if isinstance(data.get("handler"), str):
            data["handler"] = data["handler"].lower()

        return data

    @validator('handler')
    def validate_handler(cls, value: str) -> str:
        allowed = {"webpage", "video"}
        if value not in allowed:
            raise ValueError(f"Handler must be one of {sorted(allowed)}")
        return value

    @validator('action')
    def normalize_action(cls, value: str) -> str:
        normalized = value.lower()
        mapping = {
            "singlefile_cli": "singlefile",
            "singlefile": "singlefile",
            "webpage": "singlefile",
            "video": "video_downloader",
            "downie": "video_downloader",
            "downloader": "video_downloader",
        }
        normalized = mapping.get(normalized, normalized)
        allowed = {"auto", "singlefile", "applescript", "video_downloader", "none"}
        if normalized not in allowed:
            raise ValueError(f"Action must be one of {sorted(allowed)}")
        return normalized

    @property
    def category(self) -> str:
        """Legacy alias for handler."""
        return self.handler

    def get_action(self, classification: Optional[str]) -> str:
        """Resolve the action for the feed given a classification."""
        if self.action != "auto":
            return self.action

        # Default mapping when action is auto
        default_mapping = {
            "webpage": "singlefile",
            "video": "video_downloader",
        }

        base = classification or self.handler
        return default_mapping.get(base, "singlefile")


class ClassificationConfig(BaseModel):
    """Configuration for content classification."""
    
    video_domains: List[str] = Field(default_factory=lambda: [
        "youtube.com", "youtu.be", "vimeo.com", "twitch.tv"
    ])
    video_keywords: List[str] = Field(default_factory=lambda: [
        "video", "youtube", "vimeo", "twitch"
    ])


class ActionConfig(BaseModel):
    """Configuration for actions."""
    # Legacy local SingleFile Node CLI (fallback)
    singlefile_command: str = "single-file"
    singlefile_output_dir: str = "~/Downloads/SingleFile"

    # Preferred SingleFile Archiver (service/singlefile)
    singlefile_archiver_bin: str = (
        "/Users/niceday/Developer/Cloud/Dropbox/-Code-/Scripts/service/singlefile/.venv/bin/singlefile-archiver"
    )
    singlefile_archiver_module_exec: str = (
        "/Users/niceday/Developer/Cloud/Dropbox/-Code-/Scripts/service/singlefile/.venv/bin/python -m singlefile_archiver.cli"
    )
    singlefile_prefer: str = Field(default="bin", description="bin|module|legacy")
    singlefile_archive_output_dir: Optional[str] = "/Users/niceday/Developer/Cloud/Dropbox/-File-/Archive/Web"
    singlefile_cookies_file: Optional[str] = "/Users/niceday/Developer/cookie/singlefile/xcom.cookies.json"

    # AppleScript
    applescript_file: str = "applescripts/handle_video.applescript"
    applescript_args_template: List[str] = Field(
        default_factory=lambda: ["{url}", "{title}"]
    )

    # Video downloader (Downie dispatcher)
    video_downloader_python: str = "python3"
    video_downloader_script: str = (
        "/Users/niceday/Developer/Cloud/Dropbox/-Code-/Scripts/service/video-downloader/downie_dispatch.py"
    )
    video_downloader_args_template: List[str] = Field(
        default_factory=lambda: ["{url}"]
    )
    video_downloader_timeout: int = Field(default=180, description="Timeout for video downloader command")

    @validator('singlefile_output_dir')
    def expand_path(cls, v):
        return str(Path(v).expanduser())

    @validator('singlefile_cookies_file')
    def expand_cookies_file(cls, v):
        if not v:
            return None
        return str(Path(v).expanduser())


class Config(BaseModel):
    """Main configuration for RSS Inbox."""
    
    model_config = ConfigDict(extra="ignore")

    @model_validator(mode="before")
    @classmethod
    def _apply_legacy_defaults(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data

        data = data.copy()

        if "max_entries" not in data and "max_entries_per_feed" in data:
            data["max_entries"] = data["max_entries_per_feed"]

        return data

    feeds: List[FeedConfig] = Field(default_factory=list)
    poll_interval: int = Field(default=900, description="Poll interval in seconds")
    max_entries: int = Field(default=20, description="Maximum entries to process per feed")
    
    # Legacy compatibility properties
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    actions: ActionConfig = Field(default_factory=ActionConfig)
    retry_attempts: int = Field(default=3, description="Number of retry attempts for failed operations")
    retry_delay: int = Field(default=60, description="Delay between retries in seconds")
    log_level: str = Field(default="INFO", description="Logging level")
    
    @property
    def max_entries_per_feed(self) -> int:
        """Backward compatibility property."""
        return self.max_entries
    
    @validator('log_level')
    def validate_log_level(cls, v):
        allowed = ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
        if v.upper() not in allowed:
            raise ValueError(f"Log level must be one of {allowed}")
        return v.upper()


def load_config(config_file: Optional[Path] = None) -> Config:
    """
    Load configuration from YAML file.
    
    Args:
        config_file: Optional path to config file. If None, uses default path.
        
    Returns:
        Config object
    """
    if config_file is None:
        config_file = get_config_file_path()
    
    if not config_file.exists():
        # Create default config
        config = Config()
        save_config(config, config_file)
        logging.info(f"Created default config at {config_file}")
        return config
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
        
        config = Config(**data)
        logging.debug(f"Loaded config from {config_file}")
        return config
        
    except (yaml.YAMLError, ValueError) as e:
        logging.error(f"Error loading config from {config_file}: {e}")
        raise


def save_config(config: Config, config_file: Optional[Path] = None) -> None:
    """
    Save configuration to YAML file.
    
    Args:
        config: Config object to save
        config_file: Optional path to config file. If None, uses default path.
    """
    if config_file is None:
        config_file = get_config_file_path()
    
    config_file.parent.mkdir(parents=True, exist_ok=True)
    
    try:
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config.dict(), f, default_flow_style=False, indent=2)
        
        logging.debug(f"Saved config to {config_file}")
        
    except (OSError, yaml.YAMLError) as e:
        logging.error(f"Error saving config to {config_file}: {e}")
        raise


def create_example_config() -> str:
    """Create an example configuration YAML string."""
    example_config = Config(
        feeds=[
            FeedConfig(
                url="https://feeds.feedburner.com/oreilly",
                handler="webpage",
                action="singlefile",
                enabled=True
            ),
            FeedConfig(
                url="https://www.youtube.com/feeds/videos.xml?channel_id=UCBJycsmduvYEL83R_U4JriQ",
                handler="video",
                action="video_downloader",
                enabled=True
            )
        ],
        poll_interval=3600,
        max_entries=50,
        log_level="INFO"
    )
    
    return yaml.dump(example_config.dict(), default_flow_style=False, indent=2)
