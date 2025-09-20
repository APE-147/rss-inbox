"""CLI interface for RSS Inbox using Typer."""

import json
import os
import subprocess
from pathlib import Path
from typing import Optional

import typer
from typing_extensions import Annotated

from . import __version__
from .main import RSSInboxApp
from .services.writer import StateWriter, write_key
from .utils.paths import get_log_dir, get_project_dir, get_project_root


app = typer.Typer(
    name="rss-inbox",
    help="RSS feed processing and inbox management CLI tool",
    add_completion=False,
)

state_writer = StateWriter()


@app.command()
def run(
    once: Annotated[bool, typer.Option("--once", help="Process feeds once and exit")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show what would be done without executing")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show detailed output")] = False,
    config_file: Annotated[Optional[Path], typer.Option("--config", "-c", help="Path to config file")] = None,
) -> None:
    """Run the RSS inbox processing."""
    try:
        app_instance = RSSInboxApp(config_file)
        exit_code = app_instance.run(once=once, dry_run=dry_run, verbose=verbose)
    except Exception as e:
        typer.echo(f"✗ Error: {e}", err=True)
        raise typer.Exit(1)
    raise typer.Exit(exit_code)


@app.command()
def config(
    show: Annotated[bool, typer.Option("--show", help="Show current config")] = False,
    example: Annotated[bool, typer.Option("--example", help="Generate example config")] = False,
) -> None:
    """Manage RSS Inbox configuration."""
    if example:
        try:
            app_instance = RSSInboxApp()
            example_config = app_instance.create_example_config()
            typer.echo(example_config)
        except Exception as e:
            typer.echo(f"✗ Error generating example config: {e}", err=True)
            raise typer.Exit(1)
    elif show:
        try:
            from .config import load_config
            config_obj = load_config()
            import yaml
            typer.echo(yaml.dump(config_obj.dict(), default_flow_style=False, indent=2))
        except Exception as e:
            typer.echo(f"✗ Error loading config: {e}", err=True)
            raise typer.Exit(1)
    else:
        typer.echo("Use --show to view config or --example to generate example")


@app.command()
def info(
    config_file: Annotated[Optional[Path], typer.Option("--config", "-c", help="Path to config file")] = None,
) -> None:
    """Show version and project information."""
    project_dir = get_project_dir()
    
    typer.echo(f"RSS Inbox v{__version__}")
    typer.echo(f"Project Directory: {project_dir}")
    typer.echo(f"Data Scheme: {_get_data_scheme()}")
    
    # Show state file info if it exists
    state_file = get_log_dir() / "state.json"
    if state_file.exists():
        try:
            state = state_writer.read_state()
            typer.echo(f"State entries: {len(state)}")
        except Exception as e:
            typer.echo(f"State file error: {e}")
    else:
        typer.echo("State file: not found")
    
    # Show application info if config is available
    try:
        app_instance = RSSInboxApp(config_file)
        info_data = app_instance.get_info()
        typer.echo(f"\nApplication Info:")
        typer.echo(f"  Config file: {info_data.get('config_file', 'N/A')}")
        typer.echo(f"  Log level: {info_data.get('log_level', 'N/A')}")
        typer.echo(f"  Enabled feeds: {info_data.get('enabled_feeds', 0)}")
        typer.echo(f"  Total feeds: {info_data.get('total_feeds', 0)}")
        typer.echo(f"  Poll interval: {info_data.get('poll_interval', 'N/A')} seconds")
        
        stats = info_data.get('stats', {})
        if stats:
            typer.echo(f"\nStats:")
            for key, value in stats.items():
                typer.echo(f"  {key}: {value}")
    except Exception as e:
        typer.echo(f"Warning: Could not load application info: {e}")


@app.command()
def write(
    key: Annotated[str, typer.Option("--key", "-k", help="Key to write")],
    value: Annotated[str, typer.Option("--value", "-v", help="Value to write")],
    config_file: Annotated[Optional[Path], typer.Option("--config", "-c", help="Path to config file")] = None,
) -> None:
    """Write a key-value pair to the state."""
    try:
        # Try to parse value as JSON, fallback to string
        try:
            parsed_value = json.loads(value)
        except json.JSONDecodeError:
            parsed_value = value
        
        # Use app instance for state writing if available
        if config_file:
            app_instance = RSSInboxApp(config_file)
            app_instance.write_state(key, parsed_value)
        else:
            write_key(key, parsed_value)
        
        typer.echo(f"✓ Wrote {key} = {parsed_value}")
    except Exception as e:
        typer.echo(f"✗ Error writing key: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def read(
    key: Annotated[Optional[str], typer.Option("--key", "-k", help="Key to read")] = None,
    config_file: Annotated[Optional[Path], typer.Option("--config", "-c", help="Path to config file")] = None,
) -> None:
    """Read a key from the state, or show all keys if no key specified."""
    try:
        if key:
            # Use app instance for state reading if available
            if config_file:
                app_instance = RSSInboxApp(config_file)
                value = app_instance.read_state(key)
            else:
                value = state_writer.get_key(key)
            
            if value is None:
                typer.echo(f"Key '{key}' not found")
            else:
                typer.echo(f"{key} = {json.dumps(value, indent=2)}")
        else:
            state = state_writer.read_state()
            if not state:
                typer.echo("No state data found")
            else:
                typer.echo(json.dumps(state, indent=2))
    except Exception as e:
        typer.echo(f"✗ Error reading state: {e}", err=True)
        raise typer.Exit(1)


@app.command()
def autostart(
    load: Annotated[bool, typer.Option("--load", help="Load the launchd agent")] = False,
    unload: Annotated[bool, typer.Option("--unload", help="Unload the launchd agent")] = False,
    dry_run: Annotated[bool, typer.Option("--dry-run", help="Show commands without executing")] = False,
) -> None:
    """Manage macOS launchd autostart for RSS Inbox."""
    
    if not _is_macos():
        typer.echo("✗ Autostart is only supported on macOS", err=True)
        raise typer.Exit(1)
    
    if load and unload:
        typer.echo("✗ Cannot specify both --load and --unload", err=True)
        raise typer.Exit(1)
    
    if not load and not unload:
        dry_run = True  # Default to dry-run if no action specified
    
    try:
        plist_content, plist_path, commands = _generate_launchd_config()
        
        if dry_run:
            typer.echo("=== Generated plist content ===")
            typer.echo(plist_content)
            typer.echo(f"\n=== Plist path: {plist_path} ===")
            typer.echo("\n=== Commands that would be executed ===")
            for cmd in commands:
                typer.echo(f"  {' '.join(cmd)}")
        else:
            # Write plist file
            plist_path.parent.mkdir(parents=True, exist_ok=True)
            plist_path.write_text(plist_content, encoding='utf-8')
            
            # Execute commands
            for cmd in commands:
                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    typer.echo(f"✗ Command failed: {' '.join(cmd)}", err=True)
                    typer.echo(f"  Error: {result.stderr}", err=True)
                    raise typer.Exit(1)
                else:
                    typer.echo(f"✓ Executed: {' '.join(cmd)}")
    
    except Exception as e:
        typer.echo(f"✗ Autostart error: {e}", err=True)
        raise typer.Exit(1)


def _get_data_scheme() -> str:
    """Get the configured data scheme."""
    try:
        project_root = get_project_root()
        config_file = project_root / ".project_config.json"
        
        if not config_file.exists():
            return "unknown"
        
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        return config.get('data_scheme', 'unknown')
    except Exception:
        return "unknown"


def _is_macos() -> bool:
    """Check if running on macOS."""
    return os.uname().sysname == "Darwin"


def _generate_launchd_config() -> tuple[str, Path, list[list[str]]]:
    """
    Generate launchd configuration and commands.
    
    Returns:
        Tuple of (plist_content, plist_path, commands)
    """
    project_root = get_project_root()
    config_file = project_root / ".project_config.json"
    
    # Load project configuration
    with open(config_file, 'r') as f:
        config = json.load(f)
    
    label_prefix = config.get('label_prefix', 'com.user.rss-inbox')
    bin_name = 'rss-inbox'
    label = f"{label_prefix}.{bin_name}"
    
    # Find the executable
    exec_path = _find_executable()
    if not exec_path:
        raise RuntimeError("Cannot find rss-inbox executable in PATH")
    
    working_directory = str(project_root)
    log_dir = str(get_project_dir() / "logs")
    
    # Create logs directory
    Path(log_dir).mkdir(parents=True, exist_ok=True)
    
    # Generate plist content
    plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{exec_path}</string>
        <string>info</string>
    </array>
    <key>WorkingDirectory</key>
    <string>{working_directory}</string>
    <key>StandardOutPath</key>
    <string>{log_dir}/stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/stderr.log</string>
    <key>RunAtLoad</key>
    <true/>
    <key>StartInterval</key>
    <integer>3600</integer>
</dict>
</plist>"""
    
    # Generate plist path
    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    plist_path = launch_agents_dir / f"{label}.plist"
    
    # Generate commands
    commands = [
        ["launchctl", "unload", str(plist_path)],  # Always try to unload first
        ["launchctl", "load", str(plist_path)],    # Then load
    ]
    
    return plist_content, plist_path, commands


def _find_executable() -> Optional[str]:
    """Find the rss-inbox executable in PATH."""
    result = subprocess.run(
        ["which", "rss-inbox"],
        capture_output=True,
        text=True
    )
    
    if result.returncode == 0:
        return result.stdout.strip()
    
    return None


if __name__ == "__main__":
    app()
