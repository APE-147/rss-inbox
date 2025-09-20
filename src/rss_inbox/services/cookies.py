"""Cookie management utilities for RSS Inbox."""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


def _normalize_same_site(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    normalized = str(value).strip().lower()
    mapping = {
        "no_restriction": "None",
        "no_restrictions": "None",
        "none": "None",
        "lax": "Lax",
        "strict": "Strict",
        "unspecified": None,
    }
    return mapping.get(normalized, None)


def _prepare_singlefile_cookie(cookie: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    name = cookie.get("name")
    value = cookie.get("value")
    if not name or value is None:
        return None

    prepared: Dict[str, Any] = {
        "name": str(name),
        "value": str(value),
        "path": cookie.get("path") or "/",
    }

    domain = cookie.get("domain")
    if domain:
        prepared["domain"] = str(domain)

    for key in ("secure", "httpOnly"):
        if key in cookie:
            prepared[key] = bool(cookie[key])

    same_site = cookie.get("sameSite") or cookie.get("same_site")
    prepared_same_site = _normalize_same_site(same_site)
    if prepared_same_site:
        prepared["sameSite"] = prepared_same_site

    expires = (
        cookie.get("expires")
        or cookie.get("expiry")
        or cookie.get("expirationDate")
    )
    if expires is not None:
        try:
            prepared["expires"] = float(expires)
        except (TypeError, ValueError):
            pass

    return prepared


def _cookie_header(cookies: Iterable[Dict[str, Any]]) -> Optional[str]:
    parts: List[str] = []
    for item in cookies:
        name = item.get("name")
        value = item.get("value")
        if not name or value is None:
            continue
        parts.append(f"{name}={value}")
    return "; ".join(parts) if parts else None


def _sanitize_domain(domain: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", domain)


@dataclass
class CookieBundle:
    """Resolved cookie metadata for a URL/domain."""

    domain: str
    cookies: List[Dict[str, Any]]
    singlefile_cookies: List[Dict[str, Any]]
    source: str
    singlefile_cookie_file: Optional[Path]
    cookie_header: Optional[str]


class CookieManager:
    """Resolve cookies for URLs using local cache and cookie-update helpers."""

    def __init__(
        self,
        cache_dir: Path,
        temp_dir: Path,
        cookie_update_project_dir: Optional[Path] = None,
        enable_remote_fetch: bool = True,
    ) -> None:
        self.cache_dir = Path(cache_dir).expanduser()
        self.temp_dir = Path(temp_dir).expanduser()
        self.cookie_update_project_dir = (
            Path(cookie_update_project_dir).expanduser()
            if cookie_update_project_dir
            else None
        )
        self.enable_remote_fetch = enable_remote_fetch

        self.temp_dir.mkdir(parents=True, exist_ok=True)

        self._local_cache_path = self.cache_dir / "cookies_by_domain.json"
        self._local_cache: Optional[Dict[str, Dict[str, Any]]] = None
        self._bundle_cache: Dict[str, Optional[CookieBundle]] = {}

        self._downloader_module = None
        self._downloader = None

    def get_bundle_for_url(self, url: str) -> Optional[CookieBundle]:
        """Return cookie bundle for the URL if available."""
        parsed = urlparse(url)
        host = parsed.netloc or parsed.path
        if not host:
            return None
        host = host.split("@").pop()
        host = host.split(":", 1)[0]
        host = host.strip().lower().rstrip(".")
        if not host:
            return None

        cached = self._bundle_cache.get(host)
        if cached is not None:
            return cached

        candidates = self._candidate_domains(host)
        for candidate in candidates:
            info = self._get_cookie_info_for_domain(candidate)
            if info is None:
                continue
            bundle = self._build_bundle(candidate, info)
            self._bundle_cache[host] = bundle
            return bundle

        self._bundle_cache[host] = None
        return None

    def _candidate_domains(self, host: str) -> List[str]:
        segments = host.split(".")
        if len(segments) < 2:
            return [host]
        candidates = [host]
        for i in range(1, len(segments) - 1):
            part = ".".join(segments[i:])
            if part not in candidates:
                candidates.append(part)
        if segments[-1] and segments[-2]:
            base = ".".join(segments[-2:])
            if base not in candidates:
                candidates.append(base)
        return candidates

    def _load_local_cache(self) -> Dict[str, Dict[str, Any]]:
        if self._local_cache is not None:
            return self._local_cache

        cache: Dict[str, Dict[str, Any]] = {}
        if not self._local_cache_path.exists():
            self._local_cache = cache
            return cache

        try:
            with self._local_cache_path.open("r", encoding="utf-8") as fh:
                data = json.load(fh) or {}
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to load cookie cache %s: %s", self._local_cache_path, exc)
            self._local_cache = cache
            return cache

        domains = data.get("domains") if isinstance(data, dict) else None
        if not isinstance(domains, dict):
            self._local_cache = cache
            return cache

        for stored_domain, info in domains.items():
            if not isinstance(info, dict):
                continue
            normalized = stored_domain.lstrip(".").lower()
            entry = cache.setdefault(
                normalized,
                {
                    "matchedDomains": [],
                    "cookies": [],
                    "localStorageItems": [],
                    "createTime": None,
                    "updateTime": None,
                    "source": "local_cache",
                },
            )
            entry["matchedDomains"].append(stored_domain)

            cookies = info.get("cookies") or []
            if isinstance(cookies, list):
                entry["cookies"].extend([c for c in cookies if isinstance(c, dict)])

            local_storage = info.get("localStorageItems") or []
            if isinstance(local_storage, list):
                entry["localStorageItems"].extend(
                    [item for item in local_storage if isinstance(item, dict)]
                )

            for key in ("createTime", "updateTime"):
                value = info.get(key)
                if value is None:
                    continue
                try:
                    value_int = int(value)
                except (TypeError, ValueError):
                    continue
                current = entry.get(key)
                if current is None or value_int > int(current):
                    entry[key] = value_int

        for entry in cache.values():
            entry["matchedDomains"] = sorted(set(entry["matchedDomains"]))
        self._local_cache = cache
        return cache

    def _get_cookie_info_for_domain(self, domain: str) -> Optional[Dict[str, Any]]:
        normalized = domain.strip().lstrip(".").lower()
        if not normalized:
            return None

        local_cache = self._load_local_cache()
        if normalized in local_cache:
            info = local_cache[normalized].copy()
            info.setdefault("source", "local_cache")
            return info

        if not self.enable_remote_fetch:
            return None

        downloader = self._ensure_downloader()
        if downloader is None:
            return None

        try:
            from contextlib import redirect_stdout
            import io

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                result = downloader.get_cookies_for_domain(normalized)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to fetch cookies for %s: %s", normalized, exc)
            return None

        if not result:
            return None

        result.setdefault("source", "remote")
        return result

    def _ensure_downloader(self):  # type: ignore[override]
        if self._downloader is not None or not self.enable_remote_fetch:
            return self._downloader

        module = self._load_cookie_update_module()
        if module is None:
            self.enable_remote_fetch = False
            return None

        if hasattr(module, "load_env_file"):
            try:
                module.load_env_file()
            except Exception as exc:  # pragma: no cover - defensive
                logger.debug("Failed to load cookie-update env: %s", exc)

        account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID", "").strip()
        api_token = os.getenv("CLOUDFLARE_API_TOKEN", "").strip()
        namespace_id = os.getenv("CLOUDFLARE_KV_NAMESPACE_ID", "").strip()
        if not (account_id and api_token and namespace_id):
            logger.debug("Cookie remote fetch disabled due to missing Cloudflare credentials")
            self.enable_remote_fetch = False
            return None

        try:
            downloader = module.CloudflareCookieDownloader(account_id, api_token, namespace_id)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to initialize cookie downloader: %s", exc)
            self.enable_remote_fetch = False
            return None

        self._downloader = downloader
        return downloader

    def _load_cookie_update_module(self):
        if not self.cookie_update_project_dir:
            return None
        script_path = self.cookie_update_project_dir / "download_cookies.py"
        if not script_path.exists():
            logger.debug("Cookie update script not found at %s", script_path)
            return None

        if self._downloader_module is not None:
            return self._downloader_module

        import importlib.util

        spec = importlib.util.spec_from_file_location("cookie_update_download", script_path)
        if spec is None or spec.loader is None:
            logger.debug("Unable to load cookie update module from %s", script_path)
            return None

        module = importlib.util.module_from_spec(spec)
        try:
            spec.loader.exec_module(module)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to import cookie update module: %s", exc)
            return None

        self._downloader_module = module
        return module

    def _build_bundle(self, domain: str, info: Dict[str, Any]) -> Optional[CookieBundle]:
        cookies = [c for c in info.get("cookies", []) if isinstance(c, dict)]
        if not cookies:
            return None

        singlefile_cookies = []
        for cookie in cookies:
            prepared = _prepare_singlefile_cookie(cookie)
            if prepared:
                singlefile_cookies.append(prepared)

        if not singlefile_cookies:
            return None

        cookie_header = _cookie_header(cookies)
        file_path = self._write_singlefile_cookie(domain, singlefile_cookies)

        return CookieBundle(
            domain=domain,
            cookies=cookies,
            singlefile_cookies=singlefile_cookies,
            source=str(info.get("source") or "unknown"),
            singlefile_cookie_file=file_path,
            cookie_header=cookie_header,
        )

    def _write_singlefile_cookie(self, domain: str, cookies: List[Dict[str, Any]]) -> Path:
        safe_name = _sanitize_domain(domain)
        path = self.temp_dir / f"{safe_name}.singlefile.cookies.json"
        try:
            with path.open("w", encoding="utf-8") as fh:
                json.dump(cookies, fh, ensure_ascii=True, indent=2, sort_keys=True)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to write cookie file %s: %s", path, exc)
        return path


__all__ = ["CookieBundle", "CookieManager"]
