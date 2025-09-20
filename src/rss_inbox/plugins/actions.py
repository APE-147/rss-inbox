"""Actions for handling RSS inbox entries."""

import logging
import shlex
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import ActionConfig
from ..core.feeds import FeedEntry
from ..services.state import StateManager


class SingleFileAction:
    """Action to save webpages using SingleFile CLI."""
    
    def __init__(self, config: ActionConfig, state_manager: Optional[StateManager] = None):
        """Initialize SingleFile action."""
        self.config = config
        self.output_dir = Path(config.singlefile_output_dir).expanduser()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.state_manager = state_manager
    
    def execute(self, entry: FeedEntry, dry_run: bool = False, verbose: bool = False) -> bool:
        """Execute SingleFile action for an entry."""
        if not entry.link:
            logging.warning(f"No link found for entry: {entry.title}")
            self._record_failure(entry, "missing link")
            return False
        
        # Determine output directory with optional per-feed overrides
        custom_archive_dir = entry.custom_params.get("singlefile_archive_output_dir") if entry.custom_params else None
        custom_output_dir = entry.custom_params.get("singlefile_output_dir") if entry.custom_params else None

        if custom_archive_dir:
            output_base = custom_archive_dir
        elif self.config.singlefile_archive_output_dir:
            output_base = self.config.singlefile_archive_output_dir
        elif custom_output_dir:
            output_base = custom_output_dir
        else:
            output_base = str(self.output_dir)

        dest_output_dir = Path(output_base).expanduser()
        dest_output_dir.mkdir(parents=True, exist_ok=True)

        # Build command
        prefer_override = entry.custom_params.get("singlefile_prefer") if entry.custom_params else None
        cmd = self._build_command(entry.link, dest_output_dir, prefer_override, entry.custom_params)
        
        if dry_run:
            logging.info(f"[DRY RUN] Would execute SingleFile command:")
            logging.info(f"  Command: {' '.join(cmd)}")
            logging.info(f"  Output Dir: {dest_output_dir}")
            return True
        
        if verbose:
            logging.info(f"Executing SingleFile for: {entry.title}")
            logging.info(f"URL: {entry.link}")
        
        try:
            # Execute command
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode == 0:
                logging.info(f"Successfully archived: {entry.title}")
                if verbose and result.stdout:
                    logging.debug(f"SingleFile output: {result.stdout}")
                return True
            else:
                err = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                logging.error(f"SingleFile failed for {entry.title}: {err}")
                self._record_failure(entry, err)
                return False

        except subprocess.TimeoutExpired:
            logging.error(f"SingleFile timeout for {entry.title}")
            self._record_failure(entry, "timeout")
            return False
        
        except Exception as e:
            logging.error(f"Error executing SingleFile for {entry.title}: {e}")
            self._record_failure(entry, str(e))
            return False
    
    def _build_command(
        self,
        url: str,
        output_dir: Path,
        prefer_override: Optional[str],
        custom_params: Optional[Dict[str, Any]],
    ) -> List[str]:
        """Build command for SingleFile archiving."""
        custom_params = custom_params or {}
        prefer = (prefer_override or self.config.singlefile_prefer or "bin").lower()
        bin_path = Path(
            custom_params.get("singlefile_archiver_bin")
            or self.config.singlefile_archiver_bin
        ).expanduser()
        module_exec = custom_params.get("singlefile_archiver_module_exec") or self.config.singlefile_archiver_module_exec
        legacy_cmd = custom_params.get("singlefile_command") or self.config.singlefile_command

        cookies_path_value = custom_params.get("singlefile_cookies_file") or self.config.singlefile_cookies_file
        cookies_path: Optional[Path] = None
        cli_cookie_args: List[str] = []
        legacy_cookie_args: List[str] = []

        if cookies_path_value:
            candidate = Path(cookies_path_value).expanduser()
            if candidate.exists():
                cookies_path = candidate
                cli_cookie_args = ["--cookies-file", str(candidate)]
                legacy_cookie_args = ["--browser-cookies-file", str(candidate)]
            else:
                logging.warning(f"Cookies file not found, ignoring: {candidate}")

        if prefer in {"bin", "auto"} and bin_path.exists():
            cmd = [
                str(bin_path),
                "archive",
                "single",
                url,
                "--output",
                str(output_dir),
            ]
            return cmd + cli_cookie_args

        if prefer in {"bin", "module"}:
            module_cmd = shlex.split(module_exec)
            if module_cmd:
                return module_cmd + ["archive", "single", url, "--output", str(output_dir)] + cli_cookie_args

        # Legacy direct Node CLI fallback
        cmd = [
            legacy_cmd,
            url,
            "--filename-template",
            str(output_dir / "page.html"),
        ]
        if cookies_path:
            cmd += legacy_cookie_args
        return cmd

    def _record_failure(self, entry: FeedEntry, reason: str) -> None:
        if not self.state_manager:
            return
        try:
            self.state_manager.record_failure(
                feed_url=entry.feed_url,
                entry_id=getattr(entry, "id", entry.link or ""),
                url=entry.link or "",
                action="singlefile",
                reason=reason,
            )
        except Exception as exc:
            logging.debug("Failed to record SingleFile failure for %s: %s", entry.title, exc)
    
    def get_stats(self) -> Dict:
        """Get action statistics."""
        if not self.output_dir.exists():
            return {"saved_files": 0}
        
        saved_files = len([f for f in self.output_dir.iterdir() 
                          if f.is_file() and f.suffix == ".html"])
        
        return {
            "saved_files": saved_files,
            "output_directory": str(self.output_dir)
        }


class AppleScriptAction:
    """Action to execute AppleScript for handling entries."""
    
    def __init__(self, config: ActionConfig, state_manager: Optional[StateManager] = None):
        """Initialize AppleScript action."""
        self.config = config
        self.script_path = self._resolve_script_path()
        self.state_manager = state_manager
    
    def _resolve_script_path(self) -> Path:
        """Resolve the AppleScript file path."""
        script_file = self.config.applescript_file
        
        if Path(script_file).is_absolute():
            return Path(script_file)
        
        # Look in project root for applescripts directory
        project_root = Path(__file__).parent.parent.parent.parent
        return project_root / script_file
    
    def execute(self, entry: FeedEntry, dry_run: bool = False, verbose: bool = False) -> bool:
        """Execute AppleScript action for an entry."""
        if not entry.link:
            logging.warning(f"No link found for entry: {entry.title}")
            self._record_failure(entry, "missing link")
            return False
        
        if not self.script_path.exists():
            logging.error(f"AppleScript file not found: {self.script_path}")
            self._record_failure(entry, "script missing")
            return False
        
        if dry_run:
            logging.info(f"[DRY RUN] Would execute AppleScript:")
            logging.info(f"  Script: {self.script_path}")
            logging.info(f"  Title: {entry.title}")
            logging.info(f"  URL: {entry.link}")
            return True
        
        if verbose:
            logging.info(f"Executing AppleScript for: {entry.title}")
            logging.info(f"Script: {self.script_path}")
        
        try:
            # Prepare AppleScript arguments
            template = self.config.applescript_args_template or ["{title}", "{url}"]
            mapping = {
                "title": entry.title or "",
                "url": entry.link or "",
                "classification": entry.classification or ""
            }
            script_args = [arg.format(**mapping) for arg in template]
            
            # Execute AppleScript
            cmd = ["osascript", str(self.script_path)] + script_args
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60  # 1 minute timeout
            )
            
            if result.returncode == 0:
                logging.info(f"Successfully executed AppleScript for: {entry.title}")
                if verbose and result.stdout:
                    logging.debug(f"AppleScript output: {result.stdout.strip()}")
                return True
            else:
                err = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
                logging.error(f"AppleScript failed for {entry.title}: {err}")
                self._record_failure(entry, err)
                return False
        
        except subprocess.TimeoutExpired:
            logging.error(f"AppleScript timeout for {entry.title}")
            self._record_failure(entry, "timeout")
            return False
        
        except Exception as e:
            logging.error(f"Error executing AppleScript for {entry.title}: {e}")
            self._record_failure(entry, str(e))
            return False
    
    def get_stats(self) -> Dict:
        """Get action statistics."""
        return {
            "script_path": str(self.script_path),
            "script_exists": self.script_path.exists()
        }

    def _record_failure(self, entry: FeedEntry, reason: str) -> None:
        if not self.state_manager:
            return
        try:
            self.state_manager.record_failure(
                feed_url=entry.feed_url,
                entry_id=getattr(entry, "id", entry.link or ""),
                url=entry.link or "",
                action="applescript",
                reason=reason,
            )
        except Exception as exc:
            logging.debug(
                "Failed to record AppleScript failure for %s: %s",
                entry.title,
                exc,
            )


class VideoDownloaderAction:
    """Action that forwards video URLs to the Downie dispatcher script."""

    def __init__(self, config: ActionConfig, state_manager: Optional[StateManager] = None):
        self.config = config
        self.default_script_path = self._resolve_script_path(config.video_downloader_script)
        self.state_manager = state_manager

    def _resolve_script_path(self, script_path: str) -> Path:
        path = Path(script_path).expanduser()
        if path.is_absolute():
            return path
        project_root = Path(__file__).parent.parent.parent.parent
        return (project_root / path).resolve()

    def _resolve_python(self, python_cmd: str) -> List[str]:
        """Split and normalize the Python command."""
        return shlex.split(python_cmd)

    def execute(self, entry: FeedEntry, dry_run: bool = False, verbose: bool = False) -> bool:
        if not entry.link:
            logging.warning(f"No link found for entry: {entry.title}")
            self._record_failure(entry, "missing link")
            return False

        script_override = entry.custom_params.get("video_downloader_script") if entry.custom_params else None
        python_override = entry.custom_params.get("video_downloader_python") if entry.custom_params else None
        args_override = entry.custom_params.get("video_downloader_args") if entry.custom_params else None
        timeout_override = entry.custom_params.get("video_downloader_timeout") if entry.custom_params else None

        if isinstance(args_override, str):
            args_override = shlex.split(args_override)
        if isinstance(python_override, str) and not python_override.strip():
            python_override = None

        script_path = (
            self._resolve_script_path(script_override)
            if script_override
            else self.default_script_path
        )

        if not script_path.exists():
            message = f"script not found: {script_path}"
            logging.error(f"Video downloader {message}")
            self._record_failure(entry, message)
            return False

        python_cmd = python_override or self.config.video_downloader_python
        python_parts = self._resolve_python(python_cmd)
        if not python_parts:
            message = f"invalid python command: {python_cmd}"
            logging.error("Invalid python command for video downloader: %s", python_cmd)
            self._record_failure(entry, message)
            return False

        template = args_override or self.config.video_downloader_args_template or ["{url}"]
        template = list(template)

        mapping = {
            "url": entry.link or "",
            "title": entry.title or "",
            "classification": entry.classification or "",
            "feed_url": entry.feed_url,
            "feed_name": entry.feed_name or "",
        }
        # Allow lightweight templating with additional custom params
        if entry.custom_params:
            for key, value in entry.custom_params.items():
                if isinstance(value, (str, int, float)):
                    mapping.setdefault(key, str(value))

        resolved_args = [arg.format(**mapping) for arg in template]
        if not any("{url}" in arg for arg in template):
            resolved_args.append(entry.link)

        timeout = int(timeout_override or self.config.video_downloader_timeout)

        cmd = python_parts + [str(script_path)] + resolved_args

        if dry_run:
            logging.info("[DRY RUN] Would execute video downloader:")
            logging.info("  Command: %s", " ".join(cmd))
            return True

        if verbose:
            logging.info("Executing video downloader for: %s", entry.title)
            logging.info("Command: %s", " ".join(cmd))

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
            )

            if result.returncode == 0:
                logging.info("Video downloader succeeded for: %s", entry.title)
                if verbose and result.stdout:
                    logging.debug("Video downloader output: %s", result.stdout.strip())
                return True

            err = result.stderr.strip() or result.stdout.strip() or f"exit code {result.returncode}"
            soft_reason = self._classify_soft_failure(err)
            if soft_reason:
                logging.info(
                    "Video unavailable for %s; marking as processed. Reason: %s",
                    entry.title,
                    soft_reason,
                )
                self._record_failure(entry, soft_reason)
                return True
            logging.error("Video downloader failed for %s: %s", entry.title, err)
            self._record_failure(entry, err)
            return False

        except subprocess.TimeoutExpired:
            logging.error(
                "Video downloader timeout for %s after %ss",
                entry.title,
                timeout,
            )
            self._record_failure(entry, f"timeout after {timeout}s")
            return False
        except Exception as exc:
            logging.error("Error executing video downloader for %s: %s", entry.title, exc)
            self._record_failure(entry, str(exc))
            return False

    def get_stats(self) -> Dict:
        return {
            "script_path": str(self.default_script_path),
            "script_exists": self.default_script_path.exists(),
            "python": self.config.video_downloader_python,
        }

    def _record_failure(self, entry: FeedEntry, reason: str) -> None:
        if not self.state_manager:
            return
        try:
            self.state_manager.record_failure(
                feed_url=entry.feed_url,
                entry_id=getattr(entry, "id", entry.link or ""),
                url=entry.link or "",
                action="video_downloader",
                reason=reason,
            )
        except Exception as exc:
            logging.debug("Failed to record video downloader failure for %s: %s", entry.title, exc)

    def _classify_soft_failure(self, err: str) -> Optional[str]:
        """Detect failures that should be recorded but not treated as hard errors."""
        if not err:
            return None

        normalized = err.lower()
        soft_indicators = (
            "tweet status:",
            "failed to scan your link",
            "private/suspended account",
            "deleted tweet",
            "no video links found",
        )

        if any(indicator in normalized for indicator in soft_indicators):
            return err

        return None
