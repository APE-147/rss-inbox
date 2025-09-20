"""Core RSS processing functionality."""

from .feeds import FeedProcessor, FeedEntry
from .classify import ContentClassifier

__all__ = ["FeedProcessor", "FeedEntry", "ContentClassifier"]