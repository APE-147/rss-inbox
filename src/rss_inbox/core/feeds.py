"""RSS feed processing and management."""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, Iterator, List, Optional

import feedparser
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .classify import ContentClassifier
from ..config import Config, FeedConfig
from ..services.state import StateManager


class FeedEntry:
    """Represents a processed RSS feed entry."""
    
    def __init__(
        self,
        entry: feedparser.FeedParserDict,
        feed_url: str,
        classification: str,
        action: str,
        *,
        feed_name: Optional[str] = None,
        custom_params: Optional[Dict[str, Any]] = None,
    ):
        """
        Initialize feed entry.
        
        Args:
            entry: Raw feedparser entry
            feed_url: URL of the source feed
            classification: Content classification (webpage/video)
            action: Action to take (singlefile/applescript/none)
        """
        self.entry = entry
        self.feed_url = feed_url
        self.classification = classification
        self.action = action
        self.feed_name = feed_name
        self.custom_params = custom_params or {}
        
        # Extract common fields
        self.title = entry.get('title', 'Untitled')
        self.link = entry.get('link', '')
        self.description = entry.get('description', '') or entry.get('summary', '')
        self.published = self._parse_published_date(entry)
        self.id = self._generate_id(entry)
    
    def _parse_published_date(self, entry: feedparser.FeedParserDict) -> Optional[datetime]:
        """Parse published date from entry."""
        # Try different date fields
        for date_field in ['published_parsed', 'updated_parsed']:
            date_tuple = entry.get(date_field)
            if date_tuple:
                try:
                    return datetime(*date_tuple[:6], tzinfo=timezone.utc)
                except (ValueError, TypeError):
                    continue
        
        return None
    
    def _generate_id(self, entry: feedparser.FeedParserDict) -> str:
        """Generate a unique ID for the entry."""
        # Try to use existing ID first
        entry_id = entry.get('id') or entry.get('guid')
        if entry_id:
            return str(entry_id)
        
        # Fall back to link + title combination
        link = entry.get('link', '')
        title = entry.get('title', '')
        return f"{link}#{title}"
    
    def __str__(self) -> str:
        feed_label = self.feed_name or self.feed_url
        return f"FeedEntry({self.title}, {self.classification}, {self.action}, feed={feed_label})"
    
    def __repr__(self) -> str:
        return self.__str__()


class FeedProcessor:
    """Processes RSS feeds and classifies entries."""
    
    def __init__(self, config: Config, state_manager: StateManager):
        """
        Initialize feed processor.
        
        Args:
            config: Application configuration
            state_manager: State management instance
        """
        self.config = config
        self.state_manager = state_manager
        self.classifier = ContentClassifier(config.classification)
        self.session = self._create_session()
    
    def _create_session(self) -> requests.Session:
        """Create HTTP session with retry strategy."""
        session = requests.Session()
        
        # Configure retry strategy
        retry_strategy = Retry(
            total=self.config.retry_attempts,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        
        # Set reasonable timeout and headers
        session.timeout = 30
        session.headers.update({
            'User-Agent': 'RSS-Inbox/1.0 (+https://github.com/user/rss-inbox)'
        })
        
        return session
    
    def process_all_feeds(self, once: bool = False) -> Iterator[FeedEntry]:
        """
        Process all enabled feeds.
        
        Args:
            once: If True, process once and exit. If False, run continuously.
            
        Yields:
            FeedEntry objects for new entries
        """
        while True:
            enabled_feeds = [feed for feed in self.config.feeds if feed.enabled]
            
            if not enabled_feeds:
                logging.warning("No enabled feeds configured")
                if once:
                    break
                time.sleep(self.config.poll_interval)
                continue
            
            logging.info(f"Processing {len(enabled_feeds)} enabled feeds")
            
            for feed_config in enabled_feeds:
                try:
                    yield from self.process_feed(feed_config)
                except Exception as e:
                    logging.error(f"Error processing feed {feed_config.url}: {e}")
                    self.state_manager.increment_error_count(feed_config.url)
            
            if once:
                break
            
            logging.info(f"Sleeping for {self.config.poll_interval} seconds")
            time.sleep(self.config.poll_interval)
    
    def process_feed(self, feed_config: FeedConfig) -> Iterator[FeedEntry]:
        """
        Process a single RSS feed.
        
        Args:
            feed_config: Feed configuration
            
        Yields:
            FeedEntry objects for new entries
        """
        feed_label = feed_config.name or feed_config.url
        logging.info(f"Processing feed: {feed_label} ({feed_config.url})")
        
        try:
            # Fetch and parse feed
            response = self.session.get(feed_config.url)
            response.raise_for_status()
            
            feed = feedparser.parse(response.content)
            
            if feed.bozo and feed.bozo_exception:
                logging.warning(f"Feed parsing warning for {feed_config.url}: {feed.bozo_exception}")
            
            # Get processed entries for this feed
            processed_entries = self.state_manager.get_processed_entries(feed_config.url)
            
            # Process entries (limit to max_entries)
            entries = feed.entries[:self.config.max_entries]
            new_entries_count = 0
            
            for entry in entries:
                entry_id = self._generate_entry_id(entry)
                
                # Skip if already processed
                if entry_id in processed_entries:
                    continue
                
                # Classify entry
                classification = self.classifier.classify_entry(entry, feed_config.category)

                # Determine action for this entry
                action = feed_config.get_action(classification)

                # Create feed entry context
                feed_entry = FeedEntry(
                    entry,
                    feed_config.url,
                    classification,
                    action,
                    feed_name=feed_config.name,
                    custom_params=dict(feed_config.custom_params),
                )

                # Mark locally as processed for this run to avoid duplicates
                processed_entries.add(entry_id)
                new_entries_count += 1
                
                logging.info(
                    "New entry from %s: %s (%s -> %s)",
                    feed_label,
                    feed_entry.title,
                    classification,
                    action,
                )
                
                yield feed_entry
            
            # Update last check time
            self.state_manager.update_last_check(feed_config.url)
            
            # Reset error count on successful processing
            if new_entries_count > 0 or self.state_manager.get_error_count(feed_config.url) > 0:
                self.state_manager.reset_error_count(feed_config.url)
            
            # Clean up old entries periodically
            self.state_manager.cleanup_old_entries(feed_config.url)
            
            logging.info(f"Processed {new_entries_count} new entries from {feed_config.url}")
            
        except requests.RequestException as e:
            logging.error(f"HTTP error fetching feed {feed_config.url}: {e}")
            self.state_manager.increment_error_count(feed_config.url)
            raise
        
        except Exception as e:
            logging.error(f"Error processing feed {feed_config.url}: {e}")
            self.state_manager.increment_error_count(feed_config.url)
            raise
    
    def _generate_entry_id(self, entry: feedparser.FeedParserDict) -> str:
        """Generate a unique ID for an entry."""
        # Try to use existing ID first
        entry_id = entry.get('id') or entry.get('guid')
        if entry_id:
            return str(entry_id)
        
        # Fall back to link + title combination
        link = entry.get('link', '')
        title = entry.get('title', '')
        return f"{link}#{title}"