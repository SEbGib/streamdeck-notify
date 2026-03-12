"""HTTP client for the notify-bridge daemon. Uses stdlib only (Flatpak safe)."""

from __future__ import annotations

import json
import time
import urllib.request

DEFAULT_URL = "http://127.0.0.1:9120"


class BridgeClient:
    """Fetch notification state from the bridge daemon with shared cache."""

    _cache: dict = {}
    _cache_ts: float = 0

    @classmethod
    def get_status(cls, base_url: str = DEFAULT_URL, cache_ttl: float = 2.0) -> dict:
        """GET /status with shared cache to avoid N calls/sec for N buttons."""
        now = time.time()
        if now - cls._cache_ts < cache_ttl and cls._cache:
            return cls._cache

        req = urllib.request.Request(f"{base_url}/status", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                cls._cache = json.loads(resp.read())
                cls._cache_ts = now
                return cls._cache
        except Exception:
            return cls._cache  # Return stale cache on error

    @classmethod
    def post_action(cls, source: str, base_url: str = DEFAULT_URL) -> None:
        """POST /action/{source} to trigger on_press."""
        req = urllib.request.Request(f"{base_url}/action/{source}", method="POST")
        try:
            urllib.request.urlopen(req, timeout=3)
        except Exception:
            pass

    @classmethod
    def get_plugin_state(cls, source: str, base_url: str = DEFAULT_URL) -> dict:
        """Get state for a specific plugin source."""
        data = cls.get_status(base_url)
        return data.get("plugins", {}).get(source, {})

    @classmethod
    def is_bridge_available(cls, base_url: str = DEFAULT_URL) -> bool:
        """Check if bridge is reachable."""
        try:
            cls.get_status(base_url, cache_ttl=0)
            return True
        except Exception:
            return False
