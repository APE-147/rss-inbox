"""Main RSS Inbox application."""

import logging
import sys
from pathlib import Path
from typing import Dict, Optional

from .plugins.actions import AppleScriptAction, SingleFileAction, VideoDownloaderAction
from .config import Config, load_config, save_config, create_example_config
from .core.feeds import FeedProcessor
from .services.cookies import CookieManager
from .services.state import StateManager
from .utils.paths import get_project_dir


def get_log_dir() -> Path:
    """Get the log directory path."""
    log_dir = get_project_dir() / "logs"
    log_dir.mkdir(exist_ok=True)
    return log_dir


class RSSInboxApp:
    """Main RSS Inbox application."""
    
    def __init__(self, config_file: Optional[Path] = None):
        """
        Initialize the RSS Inbox application.
        
        Args:
            config_file: Optional path to configuration file
        """
        # Load configuration
        self.config = load_config(config_file)
        
        # Setup logging
        self._setup_logging()
        
        # Initialize components
        self.state_manager = StateManager()
        self.feed_processor = FeedProcessor(self.config, self.state_manager)

        actions_config = self.config.actions
        self.cookie_manager = CookieManager(
            cache_dir=Path(actions_config.cookie_cache_dir),
            temp_dir=Path(actions_config.cookie_temp_dir),
            cookie_update_project_dir=(
                Path(actions_config.cookie_update_project_dir)
                if actions_config.cookie_update_project_dir
                else None
            ),
            enable_remote_fetch=bool(actions_config.cookie_remote_fetch),
        )
        
        # Initialize actions
        self.actions = {
            "singlefile": SingleFileAction(
                self.config.actions,
                self.state_manager,
                self.cookie_manager,
            ),
            "applescript": AppleScriptAction(self.config.actions, self.state_manager),
            "video_downloader": VideoDownloaderAction(
                self.config.actions,
                self.state_manager,
                self.cookie_manager,
            ),
        }
        
        logging.info("RSS Inbox initialized")
    
    def _setup_logging(self) -> None:
        """Setup logging configuration."""
        log_dir = get_log_dir()
        log_file = log_dir / "rss-inbox.log"
        
        # Convert string log level to logging constant
        log_level = getattr(logging, self.config.log_level.upper(), logging.INFO)
        
        # Create formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # Setup file handler
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(log_level)
        file_handler.setFormatter(formatter)
        
        # Setup console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(log_level)
        console_handler.setFormatter(formatter)
        
        # Configure root logger
        root_logger = logging.getLogger()
        root_logger.setLevel(log_level)
        root_logger.handlers = []  # Clear existing handlers
        root_logger.addHandler(file_handler)
        root_logger.addHandler(console_handler)
    
    def run(self, once: bool = False, dry_run: bool = False, verbose: bool = False) -> int:
        """
        Run the RSS inbox processing.
        
        Args:
            once: If True, process once and exit
            dry_run: If True, show what would be done without executing actions
            verbose: If True, show detailed output
            
        Returns:
            Exit code (0 for success)
        """
        if verbose:
            logging.getLogger().setLevel(logging.DEBUG)
        
        logging.info(f"Starting RSS Inbox (once={once}, dry_run={dry_run}, verbose={verbose})")
        
        if dry_run:
            logging.info("[DRY RUN MODE] No actions will be executed")
        
        try:
            processed_count = 0
            
            for entry in self.feed_processor.process_all_feeds(once=once):
                # Execute action for entry
                if entry.action == "none":
                    logging.info(f"Skipping action for: {entry.title} (action=none)")
                    if not dry_run:
                        self.state_manager.add_processed_entry(entry.feed_url, entry.id)
                    processed_count += 1
                    continue
                
                action = self.actions.get(entry.action)
                if not action:
                    logging.error(f"Unknown action '{entry.action}' for entry: {entry.title}")
                    continue
                
                success = action.execute(entry, dry_run=dry_run, verbose=verbose)
                if success:
                    processed_count += 1
                    if not dry_run:
                        self.state_manager.add_processed_entry(entry.feed_url, entry.id)
                else:
                    logging.error(f"Action failed for entry: {entry.title}")
            
            if once:
                logging.info(f"Processing completed. Processed {processed_count} entries.")
            
            return 0
            
        except KeyboardInterrupt:
            logging.info("Interrupted by user")
            return 0
            
        except Exception as e:
            logging.error(f"Application error: {e}")
            if verbose:
                logging.exception("Full traceback:")
            return 1
    
    def get_info(self) -> Dict:
        """
        Get application information.
        
        Returns:
            Dictionary with application info
        """
        from . import __version__
        
        project_dir = get_project_dir()
        stats = self.state_manager.get_stats()
        
        info = {
            "version": __version__,
            "project_dir": str(project_dir),
            "config_file": str(self.config),
            "log_level": self.config.log_level,
            "enabled_feeds": len([f for f in self.config.feeds if f.enabled]),
            "total_feeds": len(self.config.feeds),
            "poll_interval": self.config.poll_interval,
            "stats": stats
        }
        
        # Add action statistics
        for action_name, action in self.actions.items():
            info[f"{action_name}_stats"] = action.get_stats()
        
        return info
    
    def create_example_config(self) -> str:
        """Create example configuration."""
        return create_example_config()
    
    def write_state(self, key: str, value) -> None:
        """Write a key-value pair to state."""
        self.state_manager.write_key_value(key, value)
        logging.info(f"Wrote state: {key} = {value}")
    
    def read_state(self, key: str):
        """Read a key-value pair from state."""
        value = self.state_manager.read_key_value(key)
        logging.info(f"Read state: {key} = {value}")
        return value
