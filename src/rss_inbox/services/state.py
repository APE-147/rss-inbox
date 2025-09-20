"""State management for RSS Inbox."""

import csv
import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

from ..utils.paths import get_log_dir


class AtomicWriter:
    """Simplified atomic writer for JSON operations."""
    
    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
    
    def write(self, key: str, value: Any) -> None:
        """Atomically write a key-value pair to the JSON file."""
        data = self._load_data()
        data[key] = value
        
        with tempfile.NamedTemporaryFile(
            mode='w', dir=self.file_path.parent, delete=False, suffix='.tmp'
        ) as tmp_file:
            json.dump(data, tmp_file, indent=2, ensure_ascii=False)
            tmp_file.flush()
            temp_path = Path(tmp_file.name)
        
        temp_path.replace(self.file_path)
    
    def read(self, key: Optional[str] = None) -> Any:
        """Read data from the JSON file."""
        data = self._load_data()
        return data.get(key) if key else data
    
    def _load_data(self) -> Dict[str, Any]:
        """Load data from the JSON file."""
        if not self.file_path.exists():
            return {}
        
        try:
            with open(self.file_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}


class StateManager:
    """Manages persistent state for RSS feed processing."""
    
    def __init__(self, state_file: Optional[Path] = None):
        """
        Initialize state manager.
        
        Args:
            state_file: Optional path to state file. If None, uses default path.
        """
        if state_file is None:
            state_file = get_log_dir() / "state.json"

        self.writer = AtomicWriter(state_file)
        self.state_file = state_file
        self.failure_log_file = self.state_file.parent / "failures.csv"
    
    def get_last_check(self, feed_url: str) -> Optional[datetime]:
        """
        Get the last check time for a feed.
        
        Args:
            feed_url: URL of the feed
            
        Returns:
            Last check datetime or None if never checked
        """
        data = self.writer.read("last_checks") or {}
        timestamp_str = data.get(feed_url)
        
        if timestamp_str:
            try:
                return datetime.fromisoformat(timestamp_str)
            except ValueError:
                logging.warning(f"Invalid timestamp for feed {feed_url}: {timestamp_str}")
        
        return None
    
    def update_last_check(self, feed_url: str, check_time: Optional[datetime] = None) -> None:
        """
        Update the last check time for a feed.
        
        Args:
            feed_url: URL of the feed
            check_time: Check time (defaults to now)
        """
        if check_time is None:
            check_time = datetime.now(timezone.utc)
        
        data = self.writer.read("last_checks") or {}
        data[feed_url] = check_time.isoformat()
        self.writer.write("last_checks", data)
        
        logging.debug(f"Updated last check for {feed_url}: {check_time}")
    
    def get_processed_entries(self, feed_url: str) -> Set[str]:
        """
        Get the set of processed entry IDs for a feed.
        
        Args:
            feed_url: URL of the feed
            
        Returns:
            Set of processed entry IDs
        """
        data = self.writer.read("processed_entries") or {}
        return set(data.get(feed_url, []))
    
    def add_processed_entry(self, feed_url: str, entry_id: str) -> None:
        """
        Add an entry ID to the processed set for a feed.
        
        Args:
            feed_url: URL of the feed
            entry_id: ID of the processed entry
        """
        data = self.writer.read("processed_entries") or {}
        if feed_url not in data:
            data[feed_url] = []
        
        if entry_id not in data[feed_url]:
            data[feed_url].append(entry_id)
            self.writer.write("processed_entries", data)
            logging.debug(f"Added processed entry {entry_id} for feed {feed_url}")
    
    def cleanup_old_entries(self, feed_url: str, max_entries: int = 1000) -> None:
        """
        Clean up old processed entries to prevent unbounded growth.
        
        Args:
            feed_url: URL of the feed
            max_entries: Maximum number of entries to keep
        """
        data = self.writer.read("processed_entries") or {}
        if feed_url in data and len(data[feed_url]) > max_entries:
            # Keep only the most recent entries (assuming they're added chronologically)
            data[feed_url] = data[feed_url][-max_entries:]
            self.writer.write("processed_entries", data)
            logging.debug(f"Cleaned up old entries for feed {feed_url}")
    
    def get_error_count(self, feed_url: str) -> int:
        """
        Get the error count for a feed.
        
        Args:
            feed_url: URL of the feed
            
        Returns:
            Error count
        """
        data = self.writer.read("error_counts") or {}
        return data.get(feed_url, 0)
    
    def increment_error_count(self, feed_url: str) -> int:
        """
        Increment the error count for a feed.
        
        Args:
            feed_url: URL of the feed
            
        Returns:
            New error count
        """
        data = self.writer.read("error_counts") or {}
        data[feed_url] = data.get(feed_url, 0) + 1
        self.writer.write("error_counts", data)
        
        new_count = data[feed_url]
        logging.debug(f"Incremented error count for {feed_url}: {new_count}")
        return new_count
    
    def reset_error_count(self, feed_url: str) -> None:
        """
        Reset the error count for a feed.
        
        Args:
            feed_url: URL of the feed
        """
        data = self.writer.read("error_counts") or {}
        if feed_url in data:
            del data[feed_url]
            self.writer.write("error_counts", data)
            logging.debug(f"Reset error count for {feed_url}")
    
    def get_stats(self) -> Dict:
        """
        Get processing statistics.

        Returns:
            Dictionary with statistics
        """
        last_checks = self.writer.read("last_checks") or {}
        processed_entries = self.writer.read("processed_entries") or {}
        error_counts = self.writer.read("error_counts") or {}
        
        total_feeds = len(last_checks)
        total_entries = sum(len(entries) for entries in processed_entries.values())
        total_errors = sum(error_counts.values())
        
        return {
            "total_feeds": total_feeds,
            "total_processed_entries": total_entries,
            "total_errors": total_errors,
            "feeds_with_errors": len(error_counts),
            "last_updated": datetime.now(timezone.utc).isoformat()
        }

    def record_failure(
        self,
        *,
        feed_url: str,
        entry_id: str,
        url: str,
        action: str,
        reason: str,
    ) -> None:
        """Append a failure row to the shared CSV log."""
        self.failure_log_file.parent.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).isoformat()
        cleaned_reason = " ".join((reason or "").split())
        cleaned_url = url or ""
        cleaned_entry = entry_id or cleaned_url

        write_header = not self.failure_log_file.exists()
        with self.failure_log_file.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            if write_header:
                writer.writerow([
                    "timestamp",
                    "feed_url",
                    "entry_id",
                    "url",
                    "action",
                    "reason",
                ])
            writer.writerow([
                timestamp,
                feed_url,
                cleaned_entry,
                cleaned_url,
                action,
                cleaned_reason,
            ])
    
    def write_key_value(self, key: str, value) -> None:
        """
        Write a key-value pair to state.
        
        Args:
            key: The key to write
            value: The value to write
        """
        self.writer.write(key, value)
    
    def read_key_value(self, key: str):
        """
        Read a key-value pair from state.
        
        Args:
            key: The key to read
            
        Returns:
            The value for the key
        """
        return self.writer.read(key)
