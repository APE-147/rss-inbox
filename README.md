
# RSS Inbox

RSS feed processing and inbox management CLI tool built with Python and Typer.

## Features

- **RSS Feed Management**: Add, remove, and monitor RSS feeds
- **Atomic State Management**: Key-value storage with atomic writes
- **macOS Launchd Integration**: Autostart functionality for background processing
- **Project-local Data Storage**: All data stored in `<project_root>/data`
- **Modern Python CLI**: Built with Typer framework for excellent UX

## Installation

Run the installation script:

```bash
bash scripts/install.sh
```

The installer will:
1. Try to use `uv` if available, fall back to `venv`
2. Install the package in development mode
3. Create a wrapper script in `~/.local/bin` or `~/bin`
4. Test the installation

## Usage

### Basic Commands

```bash
# Show version and project info
rss-inbox info

# Write a key-value pair to state
rss-inbox write --key demo --value ok

# Read a key from state
rss-inbox read --key demo

# Read all state data
rss-inbox read
```

### macOS Autostart

```bash
# Show what would be done (dry-run)
rss-inbox autostart --dry-run

# Load the launchd agent
rss-inbox autostart --load

# Unload the launchd agent
rss-inbox autostart --unload
```

## Project Structure

```
rss-inbox/
├─ .project_config.json      # Project configuration
├─ pyproject.toml            # Python package configuration
├─ README.md                 # This file
├─ CHANGELOG.md              # Version history
├─ src/rss_inbox/           # Main package
│  ├─ __init__.py           # Package metadata
│  ├─ cli.py                # CLI interface
│  ├─ core/                 # Core RSS processing
│  │  ├─ feed_manager.py    # Feed management
│  │  └─ processor.py       # Entry processing
│  ├─ services/             # Services
│  │  └─ writer.py          # Atomic K-V writer
│  ├─ utils/                # Utilities
│  │  └─ paths.py           # Path management
│  └─ plugins/              # Plugin system
└─ scripts/                 # Installation and deployment
   ├─ install.sh            # Installation script
   └─ macos/launchd/        # macOS launchd templates
      └─ rss-inbox.plist.template
```

## Data Storage

This project uses **Scheme A (project-local)** data storage:
- All runtime and persistent data is stored in `<project_root>/data`
- State files, logs, and RSS data are kept locally with the project
- Easy to backup, move, or clean up the entire project

## Development

### Requirements

- Python 3.9+
- Optional: `uv` for faster package management

### Setup

```bash
# Clone and enter the project
cd rss-inbox

# Install in development mode
bash scripts/install.sh

# Test the installation
rss-inbox info
```

### Testing

```bash
# Validate the CLI commands
rss-inbox info
rss-inbox write --key test --value "hello world"
rss-inbox read --key test
rss-inbox autostart --dry-run
```

## Configuration

The project configuration is stored in `.project_config.json`:

```json
{
  "data_scheme": "project_local",
  "label_prefix": "com.user.rss-inbox",
  "slug": "rss_inbox"
}
```

## License

MIT License - see LICENSE file for details.
