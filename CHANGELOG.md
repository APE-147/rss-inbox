# Changelog

All notable changes to RSS Inbox will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project structure and CLI framework
- Typer-based command-line interface
- Project-local data storage (Scheme A)
- Atomic key-value state management
- macOS launchd integration for autostart functionality
- RSS feed management system
- Entry processing with deduplication
- Comprehensive installation script with uv/venv fallback
- Modern Python packaging with pyproject.toml

### Features
- `rss-inbox info` - Show version and project information
- `rss-inbox write` - Write key-value pairs to state
- `rss-inbox read` - Read keys from state
- `rss-inbox autostart` - Manage macOS launchd agents

## [0.1.0] - 2024-01-XX

### Added
- Initial release
- Basic CLI structure
- State management system
- RSS feed processing foundation
- macOS autostart support

### Technical Details
- Python 3.9+ support
- Built with Typer framework
- Atomic file operations for reliability
- Project-local data storage pattern
- Comprehensive error handling
- Cross-platform path management

### Installation
- Automatic uv detection with venv fallback
- Wrapper script generation
- PATH validation and warnings
- Development mode installation support