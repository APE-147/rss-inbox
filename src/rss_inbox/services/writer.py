"""Atomic key-value writer for RSS Inbox state management."""

import json
import tempfile
from pathlib import Path
from typing import Any, Dict

from ..utils.paths import get_log_dir


class StateWriter:
    """Atomic key-value writer for state management."""

    def __init__(self, filename: str = "state.json") -> None:
        """
        Initialize the state writer.
        
        Args:
            filename: Name of the state file (default: state.json)
        """
        self.state_file = get_log_dir() / filename

    def read_state(self) -> Dict[str, Any]:
        """
        Read the current state from the state file.
        
        Returns:
            Dictionary containing the current state
        """
        if not self.state_file.exists():
            return {}
        
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            # Return empty dict if file is corrupted or unreadable
            return {}

    def write_key(self, key: str, value: Any) -> None:
        """
        Atomically write a key-value pair to the state file.
        
        Args:
            key: The key to write
            value: The value to write (must be JSON serializable)
            
        Raises:
            ValueError: If the value is not JSON serializable
            IOError: If writing fails
        """
        # Read current state
        current_state = self.read_state()
        
        # Update the key
        current_state[key] = value
        
        # Write atomically using temporary file
        self._write_state_atomic(current_state)

    def write_multiple(self, updates: Dict[str, Any]) -> None:
        """
        Atomically write multiple key-value pairs to the state file.
        
        Args:
            updates: Dictionary of key-value pairs to write
            
        Raises:
            ValueError: If any value is not JSON serializable
            IOError: If writing fails
        """
        # Read current state
        current_state = self.read_state()
        
        # Update with new values
        current_state.update(updates)
        
        # Write atomically using temporary file
        self._write_state_atomic(current_state)

    def delete_key(self, key: str) -> bool:
        """
        Delete a key from the state file.
        
        Args:
            key: The key to delete
            
        Returns:
            True if the key was deleted, False if it didn't exist
            
        Raises:
            IOError: If writing fails
        """
        current_state = self.read_state()
        
        if key not in current_state:
            return False
        
        del current_state[key]
        self._write_state_atomic(current_state)
        return True

    def get_key(self, key: str, default: Any = None) -> Any:
        """
        Get a value from the state file.
        
        Args:
            key: The key to retrieve
            default: Default value if key doesn't exist
            
        Returns:
            The value associated with the key, or default if not found
        """
        current_state = self.read_state()
        return current_state.get(key, default)

    def _write_state_atomic(self, state: Dict[str, Any]) -> None:
        """
        Atomically write state to file using temporary file.
        
        Args:
            state: The state dictionary to write
            
        Raises:
            ValueError: If the state is not JSON serializable
            IOError: If writing fails
        """
        # Ensure parent directory exists
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        
        # Create temporary file in the same directory as target
        temp_dir = self.state_file.parent
        
        try:
            with tempfile.NamedTemporaryFile(
                mode='w',
                encoding='utf-8',
                dir=temp_dir,
                delete=False,
                suffix='.tmp'
            ) as temp_file:
                json.dump(state, temp_file, indent=2, ensure_ascii=False)
                temp_file.flush()
                temp_path = Path(temp_file.name)
            
            # Atomic move to final location
            temp_path.replace(self.state_file)
            
        except Exception as e:
            # Clean up temporary file if it exists
            if 'temp_path' in locals() and temp_path.exists():
                temp_path.unlink(missing_ok=True)
            raise IOError(f"Failed to write state file: {e}")


# Convenience functions for the default state writer
_default_writer = StateWriter()

def write_key(key: str, value: Any) -> None:
    """Write a key-value pair using the default state writer."""
    _default_writer.write_key(key, value)

def get_key(key: str, default: Any = None) -> Any:
    """Get a value using the default state writer."""
    return _default_writer.get_key(key, default)

def read_state() -> Dict[str, Any]:
    """Read the current state using the default state writer."""
    return _default_writer.read_state()

def write_multiple(updates: Dict[str, Any]) -> None:
    """Write multiple key-value pairs using the default state writer."""
    _default_writer.write_multiple(updates)

def delete_key(key: str) -> bool:
    """Delete a key using the default state writer."""
    return _default_writer.delete_key(key)
