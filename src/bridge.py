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
    """HTTP bridge that polls sources and exposes their state."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self._refresh_interval = self.config.get("deck", {}).get("refresh_interval", 30)
        self._port = self.config.get("bridge", {}).get("port", DEFAULT_PORT)
        self.plugins: dict[str, BasePlugin] = {}
        self._tasks: list[asyncio.Task] = []

    def _init_plugins(self) -> None:
        """Initialize plugins from config."""
        plugin_configs = self.config.get("plugins", {})
        for key_str, btn_config in self.config.get("buttons", {}).items():
            plugin_name = btn_config.get("plugin")
            if plugin_name not in PLUGIN_REGISTRY:
                logger.warning("Unknown plugin: %s", plugin_name)
                continue
            if plugin_name in self.plugins:
                continue  # Already registered

            merged_config = {**(plugin_configs.get(plugin_name) or {}), **btn_config}
            self.plugins[plugin_name] = PLUGIN_REGISTRY[plugin_name](merged_config)

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

        # Setup HTTP server
        app = web.Application()
        app.router.add_get("/status", self.handle_status)
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
