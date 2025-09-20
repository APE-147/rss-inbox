"""RSS entry processing and filtering."""

import logging
import re
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional, Callable
from hashlib import md5

from ..services.writer import StateWriter


logger = logging.getLogger(__name__)


class EntryProcessor:
    """Processes RSS entries with filtering and deduplication."""

    def __init__(self) -> None:
        """Initialize the entry processor."""
        self.state_writer = StateWriter("processor_state.json")
        self.seen_entries_key = "seen_entries"

    def process_feeds(self, feed_data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Process multiple feeds and return filtered, deduplicated entries.
        
        Args:
            feed_data_list: List of feed data dictionaries from FeedManager
            
        Returns:
            List of processed entry dictionaries
        """
        all_entries = []
        
        # Extract entries from all feeds
        for feed_data in feed_data_list:
            feed_url = feed_data['url']
            feed_config = feed_data['config']
            entries = feed_data.get('entries', [])
            
            logger.info(f"Processing {len(entries)} entries from {feed_config.get('name', feed_url)}")
            
            for entry in entries:
                processed_entry = self._process_entry(entry, feed_url, feed_config)
                if processed_entry:
                    all_entries.append(processed_entry)
        
        # Sort by publication date (newest first)
        all_entries.sort(key=lambda x: x.get('published_timestamp', 0), reverse=True)
        
        # Remove duplicates
        deduplicated_entries = self._deduplicate_entries(all_entries)
        
        logger.info(f"Processed {len(deduplicated_entries)} unique entries from {len(feed_data_list)} feeds")
        return deduplicated_entries

    def _process_entry(self, entry: Dict[str, Any], feed_url: str, feed_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Process a single RSS entry.
        
        Args:
            entry: Raw RSS entry from feedparser
            feed_url: URL of the source feed
            feed_config: Feed configuration
            
        Returns:
            Processed entry dictionary or None if filtered out
        """
        # Generate unique ID for the entry
        entry_id = self._generate_entry_id(entry, feed_url)
        
        # Check if we've already seen this entry
        if self._is_seen_entry(entry_id):
            return None
        
        # Extract and normalize entry data
        processed_entry = {
            'id': entry_id,
            'title': self._clean_text(entry.get('title', 'Untitled')),
            'link': entry.get('link', ''),
            'description': self._clean_text(entry.get('description', '')),
            'summary': self._clean_text(entry.get('summary', '')),
            'published': entry.get('published', ''),
            'published_timestamp': self._parse_timestamp(entry.get('published_parsed')),
            'author': entry.get('author', ''),
            'tags': self._extract_tags(entry),
            'source': {
                'feed_url': feed_url,
                'feed_name': feed_config.get('name', ''),
                'feed_title': feed_config.get('metadata', {}).get('title', ''),
            },
            'processed_at': datetime.now(timezone.utc).isoformat(),
        }
        
        # Apply filters
        if not self._passes_filters(processed_entry):
            return None
        
        # Mark as seen
        self._mark_entry_seen(entry_id)
        
        return processed_entry

    def _generate_entry_id(self, entry: Dict[str, Any], feed_url: str) -> str:
        """
        Generate a unique ID for an RSS entry.
        
        Args:
            entry: RSS entry from feedparser
            feed_url: URL of the source feed
            
        Returns:
            Unique string identifier
        """
        # Use entry GUID if available, otherwise generate from content
        guid = entry.get('id') or entry.get('guid')
        if guid:
            return md5(f"{feed_url}:{guid}".encode()).hexdigest()
        
        # Fallback to generating from title and link
        title = entry.get('title', '')
        link = entry.get('link', '')
        content = f"{feed_url}:{title}:{link}"
        
        return md5(content.encode()).hexdigest()

    def _clean_text(self, text: str) -> str:
        """
        Clean and normalize text content.
        
        Args:
            text: Raw text content
            
        Returns:
            Cleaned text
        """
        if not text:
            return ''
        
        # Remove HTML tags
        text = re.sub(r'<[^>]+>', '', text)
        
        # Normalize whitespace
        text = re.sub(r'\s+', ' ', text).strip()
        
        return text

    def _parse_timestamp(self, time_struct) -> float:
        """
        Parse feedparser time struct to timestamp.
        
        Args:
            time_struct: feedparser time struct or None
            
        Returns:
            Unix timestamp or 0 if parsing failed
        """
        if not time_struct:
            return 0.0
        
        try:
            import time
            return time.mktime(time_struct)
        except (TypeError, ValueError):
            return 0.0

    def _extract_tags(self, entry: Dict[str, Any]) -> List[str]:
        """
        Extract tags from RSS entry.
        
        Args:
            entry: RSS entry from feedparser
            
        Returns:
            List of tag strings
        """
        tags = []
        
        # Extract from tags field
        if 'tags' in entry:
            for tag in entry['tags']:
                if isinstance(tag, dict) and 'term' in tag:
                    tags.append(tag['term'])
                elif isinstance(tag, str):
                    tags.append(tag)
        
        # Extract from categories
        if 'category' in entry:
            tags.append(entry['category'])
        
        return list(set(tags))  # Remove duplicates

    def _passes_filters(self, entry: Dict[str, Any]) -> bool:
        """
        Check if entry passes all configured filters.
        
        Args:
            entry: Processed entry dictionary
            
        Returns:
            True if entry passes all filters
        """
        # TODO: Implement configurable filters
        # For now, accept all entries
        return True

    def _is_seen_entry(self, entry_id: str) -> bool:
        """
        Check if an entry has been seen before.
        
        Args:
            entry_id: Unique entry identifier
            
        Returns:
            True if entry has been seen
        """
        seen_entries = self.state_writer.get_key(self.seen_entries_key, {})
        return entry_id in seen_entries

    def _mark_entry_seen(self, entry_id: str) -> None:
        """
        Mark an entry as seen.
        
        Args:
            entry_id: Unique entry identifier
        """
        seen_entries = self.state_writer.get_key(self.seen_entries_key, {})
        seen_entries[entry_id] = datetime.now(timezone.utc).isoformat()
        
        # Keep only recent entries to prevent unbounded growth
        # Remove entries older than 30 days
        cutoff_timestamp = datetime.now(timezone.utc).timestamp() - (30 * 24 * 3600)
        
        cleaned_entries = {}
        for eid, timestamp_str in seen_entries.items():
            try:
                entry_timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00')).timestamp()
                if entry_timestamp > cutoff_timestamp:
                    cleaned_entries[eid] = timestamp_str
            except (ValueError, AttributeError):
                # Keep entries with invalid timestamps (better safe than sorry)
                cleaned_entries[eid] = timestamp_str
        
        self.state_writer.write_key(self.seen_entries_key, cleaned_entries)

    def _deduplicate_entries(self, entries: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Remove duplicate entries from the list.
        
        Args:
            entries: List of processed entries
            
        Returns:
            Deduplicated list of entries
        """
        seen_ids = set()
        deduplicated = []
        
        for entry in entries:
            entry_id = entry['id']
            if entry_id not in seen_ids:
                seen_ids.add(entry_id)
                deduplicated.append(entry)
        
        return deduplicated

    def get_processing_stats(self) -> Dict[str, Any]:
        """
        Get processing statistics.
        
        Returns:
            Statistics dictionary
        """
        seen_entries = self.state_writer.get_key(self.seen_entries_key, {})
        
        return {
            'total_seen_entries': len(seen_entries),
            'oldest_seen_entry': min(seen_entries.values()) if seen_entries else None,
            'newest_seen_entry': max(seen_entries.values()) if seen_entries else None,
        }