"""HTTP bridge daemon — polls notification sources, exposes JSON on localhost:9120.

This runs OUTSIDE Flatpak, with access to D-Bus, glab, gh, Google APIs.
StreamController plugin fetches /status to update buttons.
"""

from __future__ import annotations

import asyncio
import json
import logging
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml
from aiohttp import web

from .plugins import PLUGIN_REGISTRY
from .plugins.base import BasePlugin

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"
DEFAULT_PORT = 9120


class NotifyBridge:
    """HTTP bridge that polls sources and exposes their state via REST + SSE."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self._refresh_interval = self.config.get("deck", {}).get("refresh_interval", 30)
        self._port = self.config.get("bridge", {}).get("port", DEFAULT_PORT)
        self.plugins: dict[str, BasePlugin] = {}
        self._tasks: list[asyncio.Task] = []
        self._sse_clients: list[web.StreamResponse] = []
        self._last_states: dict[str, dict] = {}

    def _init_plugins(self) -> None:
        """Initialize plugins from config.

        Registers plugins referenced in buttons: section AND any plugin
        that has a configuration entry in plugins: section.
        """
        plugin_configs = self.config.get("plugins", {})

        # Plugins from button assignments
        for key_str, btn_config in self.config.get("buttons", {}).items():
            plugin_name = btn_config.get("plugin")
            if plugin_name not in PLUGIN_REGISTRY:
                logger.warning("Unknown plugin: %s", plugin_name)
                continue
            if plugin_name in self.plugins:
                continue
            merged_config = {**(plugin_configs.get(plugin_name) or {}), **btn_config}
            self.plugins[plugin_name] = PLUGIN_REGISTRY[plugin_name](merged_config)

        # Auto-register configured plugins not yet loaded (no button needed)
        for plugin_name, plugin_cfg in plugin_configs.items():
            if plugin_name in self.plugins:
                continue
            if plugin_name not in PLUGIN_REGISTRY:
                logger.warning("Unknown plugin in config: %s", plugin_name)
                continue
            self.plugins[plugin_name] = PLUGIN_REGISTRY[plugin_name](plugin_cfg or {})

    async def handle_status(self, request: web.Request) -> web.Response:
        """GET /status — return all plugin states as JSON."""
        data = {
            "plugins": {
                name: plugin.state.to_dict()
                for name, plugin in self.plugins.items()
            },
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return web.json_response(data)

    async def handle_action(self, request: web.Request) -> web.Response:
        """POST /action/{name} — trigger on_press for a plugin."""
        name = request.match_info["name"]
        plugin = self.plugins.get(name)
        if not plugin:
            return web.json_response({"error": f"Unknown plugin: {name}"}, status=404)
        await plugin.on_press()
        return web.json_response({"ok": True})

    async def handle_events(self, request: web.Request) -> web.StreamResponse:
        """GET /events — SSE stream of state changes."""
        resp = web.StreamResponse()
        resp.headers["Content-Type"] = "text/event-stream"
        resp.headers["Cache-Control"] = "no-cache"
        resp.headers["Connection"] = "keep-alive"
        await resp.prepare(request)

        # Send current state as initial event
        data = {
            name: plugin.state.to_dict()
            for name, plugin in self.plugins.items()
        }
        await resp.write(f"event: state\ndata: {json.dumps(data)}\n\n".encode())

        self._sse_clients.append(resp)
        try:
            # Keep connection alive until client disconnects
            while True:
                await asyncio.sleep(15)
                try:
                    await resp.write(b": keepalive\n\n")
                except (ConnectionResetError, ConnectionError):
                    break
        finally:
            self._sse_clients.remove(resp)

        return resp

    async def _broadcast_changes(self) -> None:
        """Check for state changes and push to SSE clients."""
        while True:
            await asyncio.sleep(1)
            if not self._sse_clients:
                continue

            changed = {}
            for name, plugin in self.plugins.items():
                current = plugin.state.to_dict()
                if current != self._last_states.get(name):
                    self._last_states[name] = current
                    changed[name] = current

            if changed:
                payload = f"event: state\ndata: {json.dumps(changed)}\n\n".encode()
                dead = []
                for client in self._sse_clients:
                    try:
                        await client.write(payload)
                    except (ConnectionResetError, ConnectionError):
                        dead.append(client)
                for client in dead:
                    self._sse_clients.remove(client)

    async def run(self) -> None:
        """Start polling loops and HTTP server."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )

        self._init_plugins()

        # Start polling loops
        for name, plugin in self.plugins.items():
            task = asyncio.create_task(
                plugin.run_loop(self._refresh_interval),
                name=f"poll-{name}",
            )
            self._tasks.append(task)

        # Start SSE broadcast task
        self._tasks.append(
            asyncio.create_task(self._broadcast_changes(), name="sse-broadcast")
        )

        # Setup HTTP server
        app = web.Application()
        app.router.add_get("/status", self.handle_status)
        app.router.add_get("/events", self.handle_events)
        app.router.add_post("/action/{name}", self.handle_action)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", self._port)
        await site.start()

        logger.info(
            "notify-bridge running on http://127.0.0.1:%d (%d plugins, refresh %ds)",
            self._port,
            len(self.plugins),
            self._refresh_interval,
        )

        # Handle shutdown
        stop_event = asyncio.Event()
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, stop_event.set)

        await stop_event.wait()

        logger.info("Shutting down...")
        for plugin in self.plugins.values():
            plugin.stop()
            await plugin.teardown()
        for task in self._tasks:
            task.cancel()
        await runner.cleanup()


def main():
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_PATH
    bridge = NotifyBridge(config_path)
    asyncio.run(bridge.run())


if __name__ == "__main__":
    main()
