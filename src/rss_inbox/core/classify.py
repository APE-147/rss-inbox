"""Content classification for RSS entries."""

import logging
import re
from urllib.parse import urlparse
from typing import List, Optional

import feedparser

from ..config import ClassificationConfig


class ContentClassifier:
    """Classifies RSS entries as webpage or video content."""
    
    def __init__(self, config: ClassificationConfig):
        """
        Initialize the classifier.
        
        Args:
            config: Classification configuration
        """
        self.config = config
    
    def classify_entry(self, entry: feedparser.FeedParserDict, feed_category: str = "webpage") -> str:
        """
        Classify an RSS entry as 'webpage' or 'video'.
        
        Args:
            entry: RSS entry from feedparser
            feed_category: Default category from feed configuration
            
        Returns:
            Classification: 'webpage' or 'video'
        """
        # Start with feed's default category
        if feed_category in ["webpage", "video"]:
            classification = feed_category
        else:
            classification = "webpage"
        
        # Check URL domain
        url = entry.get('link', '')
        if url:
            domain = self._extract_domain(url)
            if any(video_domain in domain for video_domain in self.config.video_domains):
                classification = "video"
                logging.debug(f"Classified as video based on domain: {domain}")
        
        # Check title and description for video keywords
        text_content = self._get_text_content(entry)
        if self._contains_video_keywords(text_content):
            classification = "video"
            logging.debug(f"Classified as video based on keywords")
        
        # Check for video-specific tags in entry
        if self._has_video_tags(entry):
            classification = "video"
            logging.debug(f"Classified as video based on tags")
        
        logging.debug(f"Final classification for '{entry.get('title', 'Unknown')}': {classification}")
        return classification
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL."""
        try:
            parsed = urlparse(url)
            return parsed.netloc.lower()
        except Exception:
            return ""
    
    def _get_text_content(self, entry: feedparser.FeedParserDict) -> str:
        """Get combined text content from entry."""
        text_parts = []
        
        # Title
        title = entry.get('title', '')
        if title:
            text_parts.append(title)
        
        # Description/summary
        description = entry.get('description', '') or entry.get('summary', '')
        if description:
            # Strip HTML tags from description
            description = re.sub(r'<[^>]+>', ' ', description)
            text_parts.append(description)
        
        # Tags
        tags = entry.get('tags', [])
        if tags:
            tag_text = ' '.join(tag.get('term', '') for tag in tags)
            text_parts.append(tag_text)
        
        return ' '.join(text_parts).lower()
    
    def _contains_video_keywords(self, text: str) -> bool:
        """Check if text contains video-related keywords."""
        return any(keyword.lower() in text for keyword in self.config.video_keywords)
    
    def _has_video_tags(self, entry: feedparser.FeedParserDict) -> bool:
        """Check for video-specific tags or attributes in entry."""
        # Check for YouTube-specific attributes
        if hasattr(entry, 'yt_videoid') or 'youtube' in entry.get('link', '').lower():
            return True
        
        # Check for video media types
        enclosures = entry.get('enclosures', [])
        for enclosure in enclosures:
            media_type = enclosure.get('type', '')
            if media_type.startswith('video/'):
                return True
        
        # Check media:content elements (common in video feeds)
        media_content = entry.get('media_content', [])
        for media in media_content:
            media_type = media.get('type', '')
            if media_type.startswith('video/'):
                return True
        
        return False
    
    def get_action_for_classification(self, classification: str, default_action: str = "singlefile") -> str:
        """
        Get the appropriate action for a classification.
        
        Args:
            classification: Content classification ('webpage' or 'video')
            default_action: Default action if no specific mapping exists
            
        Returns:
            Action name
        """
        # Default mapping - can be overridden by feed configuration
        action_mapping = {
            "webpage": "singlefile",
            "video": "video_downloader"
        }
        
        return action_mapping.get(classification, default_action)