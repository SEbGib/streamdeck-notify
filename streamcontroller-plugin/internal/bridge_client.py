"""HTTP client for the notify-bridge daemon. Uses stdlib only (Flatpak safe).

Supports two modes:
- Polling: GET /status every tick (fallback)
- SSE: GET /events stream for instant push updates
"""

from __future__ import annotations

import json
import threading
import time
import urllib.request

DEFAULT_URL = "http://127.0.0.1:9120"


class BridgeClient:
    """Fetch notification state from the bridge daemon with shared cache."""

    _cache: dict = {}
    _cache_ts: float = 0
    _fail_count: int = 0

    # SSE support
    _sse_thread: threading.Thread | None = None
    _sse_running: bool = False
    _sse_connected: bool = False

    @classmethod
    def _get_cache_ttl(cls) -> float:
        """Exponential backoff for cache TTL based on consecutive failures."""
        if cls._fail_count >= 6:
            return 10.0
        if cls._fail_count >= 3:
            return 5.0
        return 2.0

    @classmethod
    def start_sse(cls, base_url: str = DEFAULT_URL) -> None:
        """Start SSE listener thread for push-based updates."""
        if cls._sse_thread and cls._sse_thread.is_alive():
            return
        cls._sse_running = True
        cls._sse_thread = threading.Thread(
            target=cls._sse_loop, args=(base_url,), daemon=True
        )
        cls._sse_thread.start()

    @classmethod
    def stop_sse(cls) -> None:
        """Stop SSE listener."""
        cls._sse_running = False

    @classmethod
    def _sse_loop(cls, base_url: str) -> None:
        """Background thread: read SSE events from /events."""
        while cls._sse_running:
            try:
                req = urllib.request.Request(f"{base_url}/events")
                with urllib.request.urlopen(req, timeout=30) as resp:
                    cls._sse_connected = True
                    cls._fail_count = 0
                    buffer = ""
                    while cls._sse_running:
                        chunk = resp.read(4096)
                        if not chunk:
                            break
                        buffer += chunk.decode("utf-8", errors="replace")
                        while "\n\n" in buffer:
                            event_str, buffer = buffer.split("\n\n", 1)
                            cls._process_sse_event(event_str)
            except Exception:
                cls._sse_connected = False
                cls._fail_count += 1
                if cls._fail_count >= 3:
                    cls._cache = {}
                # Reconnect backoff
                time.sleep(min(cls._fail_count * 2, 10))

    @classmethod
    def _process_sse_event(cls, raw: str) -> None:
        """Parse SSE event and update cache."""
        data_line = ""
        for line in raw.split("\n"):
            if line.startswith("data: "):
                data_line = line[6:]
            elif line.startswith(":"):
                return  # Comment/keepalive
        if not data_line:
            return
        try:
            plugin_states = json.loads(data_line)
            if not cls._cache:
                cls._cache = {"plugins": {}, "timestamp": ""}
            cls._cache.setdefault("plugins", {}).update(plugin_states)
            cls._cache_ts = time.time()
        except (json.JSONDecodeError, TypeError):
            pass

    @classmethod
    def get_status(cls, base_url: str = DEFAULT_URL, cache_ttl: float = -1) -> dict:
        """GET /status with shared cache to avoid N calls/sec for N buttons.

        If SSE is connected, always return cache (push-updated).
        cache_ttl<0 means use the adaptive TTL based on failure count.
        cache_ttl=0 means bypass cache entirely.
        """
        # If SSE is feeding us, just return cache
        if cls._sse_connected and cls._cache:
            return cls._cache

        if cache_ttl < 0:
            cache_ttl = cls._get_cache_ttl()

        now = time.time()
        if now - cls._cache_ts < cache_ttl and cls._cache:
            return cls._cache

        req = urllib.request.Request(f"{base_url}/status", method="GET")
        try:
            with urllib.request.urlopen(req, timeout=3) as resp:
                cls._cache = json.loads(resp.read())
                cls._cache_ts = now
                if cls._fail_count > 0:
                    cls._fail_count = 0
                # Auto-start SSE on first successful contact
                if not cls._sse_thread:
                    cls.start_sse(base_url)
                return cls._cache
        except Exception:
            cls._fail_count += 1
            if cls._fail_count >= 3:
                cls._cache = {}
            return cls._cache

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
        if cls._sse_connected:
            return True
        try:
            cls.get_status(base_url, cache_ttl=0)
            return True
        except Exception:
            return False
