"""RSS feed management and processing."""

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..utils.paths import get_project_dir


logger = logging.getLogger(__name__)


class FeedManager:
    """Manages RSS feeds and their processing."""

    def __init__(self) -> None:
        """Initialize the feed manager."""
        self.data_dir = get_project_dir()
        self.feeds_file = self.data_dir / "feeds.json"
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        """Create a requests session with retry strategy."""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set user agent
        session.headers.update({
            'User-Agent': 'RSS-Inbox/0.1.0 (RSS feed processor)'
        })
        
        return session

    def add_feed(self, url: str, name: Optional[str] = None) -> Dict[str, Any]:
        """
        Add a new RSS feed.
        
        Args:
            url: The RSS feed URL
            name: Optional human-readable name for the feed
            
        Returns:
            Feed configuration dictionary
            
        Raises:
            ValueError: If the URL is invalid or feed cannot be fetched
        """
        # Validate URL
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid URL: {url}")
        
        # Test fetch the feed
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse the feed to validate it
            feed_data = feedparser.parse(response.content)
            if feed_data.bozo and not feed_data.entries:
                raise ValueError(f"Invalid or empty RSS feed: {url}")
                
        except requests.RequestException as e:
            raise ValueError(f"Cannot fetch feed from {url}: {e}")
        
        # Generate feed config
        feed_config = {
            'url': url,
            'name': name or feed_data.feed.get('title', f'Feed from {parsed.netloc}'),
            'added_at': datetime.now(timezone.utc).isoformat(),
            'last_fetched': None,
            'last_error': None,
            'active': True,
            'metadata': {
                'title': feed_data.feed.get('title', ''),
                'description': feed_data.feed.get('description', ''),
                'link': feed_data.feed.get('link', ''),
            }
        }
        
        # Load existing feeds
        feeds = self.load_feeds()
        
        # Check if feed already exists
        if url in feeds:
            raise ValueError(f"Feed already exists: {url}")
        
        # Add new feed
        feeds[url] = feed_config
        self.save_feeds(feeds)
        
        logger.info(f"Added RSS feed: {feed_config['name']} ({url})")
        return feed_config

    def remove_feed(self, url: str) -> bool:
        """
        Remove an RSS feed.
        
        Args:
            url: The RSS feed URL to remove
            
        Returns:
            True if feed was removed, False if it didn't exist
        """
        feeds = self.load_feeds()
        
        if url not in feeds:
            return False
        
        feed_name = feeds[url].get('name', url)
        del feeds[url]
        self.save_feeds(feeds)
        
        logger.info(f"Removed RSS feed: {feed_name} ({url})")
        return True

    def load_feeds(self) -> Dict[str, Any]:
        """
        Load feeds configuration from storage.
        
        Returns:
            Dictionary of feed configurations keyed by URL
        """
        if not self.feeds_file.exists():
            return {}
        
        try:
            import json
            with open(self.feeds_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError) as e:
            logger.error(f"Failed to load feeds configuration: {e}")
            return {}

    def save_feeds(self, feeds: Dict[str, Any]) -> None:
        """
        Save feeds configuration to storage.
        
        Args:
            feeds: Dictionary of feed configurations
        """
        import json
        import tempfile
        
        # Ensure data directory exists
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            # Write atomically using temporary file
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=self.data_dir,
                delete=False,
                suffix='.tmp'
            ) as temp_file:
                json.dump(feeds, temp_file, indent=2, ensure_ascii=False)
                temp_file.flush()
                temp_path = Path(temp_file.name)
            
            # Atomic move to final location
            temp_path.replace(self.feeds_file)
            
        except Exception as e:
            # Clean up temporary file if it exists
            if 'temp_path' in locals() and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise IOError(f"Failed to save feeds configuration: {e}")

    def fetch_feed(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Fetch and parse a single RSS feed.
        
        Args:
            url: The RSS feed URL
            
        Returns:
            Feed data dictionary or None if fetch failed
        """
        feeds = self.load_feeds()
        
        if url not in feeds:
            logger.error(f"Feed not found: {url}")
            return None
        
        feed_config = feeds[url]
        
        try:
            logger.info(f"Fetching feed: {feed_config.get('name', url)}")
            
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            
            # Parse the feed
            feed_data = feedparser.parse(response.content)
            
            if feed_data.bozo:
                logger.warning(f"Feed has parsing issues: {url}")
            
            # Update feed metadata
            now = datetime.now(timezone.utc).isoformat()
            feed_config['last_fetched'] = now
            feed_config['last_error'] = None
            feed_config['metadata'].update({
                'title': feed_data.feed.get('title', feed_config['metadata'].get('title', '')),
                'description': feed_data.feed.get('description', feed_config['metadata'].get('description', '')),
                'link': feed_data.feed.get('link', feed_config['metadata'].get('link', '')),
            })
            
            feeds[url] = feed_config
            self.save_feeds(feeds)
            
            # Return processed feed data
            return {
                'url': url,
                'config': feed_config,
                'feed': feed_data.feed,
                'entries': feed_data.entries,
                'fetched_at': now,
            }
            
        except Exception as e:
            logger.error(f"Failed to fetch feed {url}: {e}")
            
            # Update error information
            feed_config['last_error'] = str(e)
            feeds[url] = feed_config
            self.save_feeds(feeds)
            
            return None

    def fetch_all_feeds(self) -> List[Dict[str, Any]]:
        """
        Fetch all active RSS feeds.
        
        Returns:
            List of feed data dictionaries for successfully fetched feeds
        """
        feeds = self.load_feeds()
        active_feeds = [url for url, config in feeds.items() if config.get('active', True)]
        
        logger.info(f"Fetching {len(active_feeds)} active feeds")
        
        results = []
        for url in active_feeds:
            feed_data = self.fetch_feed(url)
            if feed_data:
                results.append(feed_data)
        
        logger.info(f"Successfully fetched {len(results)} out of {len(active_feeds)} feeds")
        return results

    def list_feeds(self) -> List[Dict[str, Any]]:
        """
        List all configured feeds.
        
        Returns:
            List of feed configuration dictionaries
        """
        feeds = self.load_feeds()
        return [
            {**config, 'url': url}
            for url, config in feeds.items()
        ]

    def get_feed_status(self) -> Dict[str, Any]:
        """
        Get status summary of all feeds.
        
        Returns:
            Status summary dictionary
        """
        feeds = self.load_feeds()
        
        total_feeds = len(feeds)
        active_feeds = sum(1 for config in feeds.values() if config.get('active', True))
        feeds_with_errors = sum(1 for config in feeds.values() if config.get('last_error'))
        
        return {
            'total_feeds': total_feeds,
            'active_feeds': active_feeds,
            'inactive_feeds': total_feeds - active_feeds,
            'feeds_with_errors': feeds_with_errors,
            'feeds': feeds,
        }