"""Main daemon — orchestrates plugins, rendering, and the Stream Deck."""

from __future__ import annotations

import asyncio
import logging
import signal
import subprocess
import sys
from pathlib import Path

import yaml

from .deck import DeckManager
from .plugins import PLUGIN_REGISTRY
from .plugins.base import BasePlugin
from .renderer import render_button, render_empty

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent.parent / "config.yaml"


class StreamDeckNotifyDaemon:
    """Main daemon that ties everything together."""

    def __init__(self, config_path: Path = CONFIG_PATH):
        with open(config_path) as f:
            self.config = yaml.safe_load(f)

        self.deck = DeckManager(brightness=self.config.get("deck", {}).get("brightness", 70))
        self.buttons: dict[int, ButtonBinding] = {}
        self._refresh_interval = self.config.get("deck", {}).get("refresh_interval", 30)

    def _init_plugins(self) -> None:
        """Initialize plugins from config."""
        plugin_configs = self.config.get("plugins", {})
        for key_str, btn_config in self.config.get("buttons", {}).items():
            key = int(key_str)
            plugin_name = btn_config.get("plugin")
            if plugin_name not in PLUGIN_REGISTRY:
                logger.warning("Unknown plugin: %s (key %d)", plugin_name, key)
                continue

            merged_config = {**(plugin_configs.get(plugin_name) or {}), **btn_config}
            plugin = PLUGIN_REGISTRY[plugin_name](merged_config)

            self.buttons[key] = ButtonBinding(
                key=key,
                plugin=plugin,
                icon=btn_config.get("icon"),
                label=btn_config.get("label", ""),
                action=btn_config.get("action"),
            )

    async def run(self) -> None:
        """Start the daemon."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        )

        if not self.deck.open():
            logger.error("Cannot open Stream Deck. Exiting.")
            sys.exit(1)

        self._init_plugins()
        self.deck.set_key_callback(self._on_key)

        # Clear all buttons
        for i in range(self.deck.key_count):
            self.deck.set_key_image(i, render_empty())

        # Start plugin loops and rendering
        tasks = []
        for binding in self.buttons.values():
            tasks.append(
                asyncio.create_task(
                    binding.plugin.run_loop(self._refresh_interval)
                )
            )
        tasks.append(asyncio.create_task(self._render_loop()))

        # Handle shutdown
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: asyncio.create_task(self._shutdown(tasks)))

        logger.info(
            "Stream Deck Notify running (%d buttons configured, refresh %ds)",
            len(self.buttons),
            self._refresh_interval,
        )

        await asyncio.gather(*tasks, return_exceptions=True)

    async def _render_loop(self) -> None:
        """Periodically re-render all buttons."""
        while True:
            for key, binding in self.buttons.items():
                try:
                    image = render_button(
                        binding.plugin.state,
                        icon_name=binding.icon,
                        label=binding.label,
                    )
                    self.deck.set_key_image(key, image)
                except Exception:
                    logger.exception("Render error for key %d", key)
            await asyncio.sleep(2)  # Render refresh faster than poll

    def _on_key(self, _deck, key: int, state: bool) -> None:
        """Handle key press."""
        if not state:  # Only on key-down
            return

        binding = self.buttons.get(key)
        if not binding:
            return

        logger.info("Key %d pressed (%s)", key, binding.label)

        # Run plugin on_press callback
        asyncio.get_event_loop().create_task(binding.plugin.on_press())

        # Execute configured action (open URL, run command)
        if binding.action:
            try:
                subprocess.Popen(
                    binding.action,
                    shell=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                logger.exception("Action failed for key %d", key)

    async def _shutdown(self, tasks: list[asyncio.Task]) -> None:
        """Graceful shutdown."""
        logger.info("Shutting down...")
        for binding in self.buttons.values():
            binding.plugin.stop()
            await binding.plugin.teardown()
        for task in tasks:
            task.cancel()
        self.deck.close()


class ButtonBinding:
    """Maps a key to a plugin instance and its display config."""

    def __init__(
        self,
        key: int,
        plugin: BasePlugin,
        icon: str | None,
        label: str,
        action: str | None,
    ):
        self.key = key
        self.plugin = plugin
        self.icon = icon
        self.label = label
        self.action = action


def main():
    """Entry point."""
    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else CONFIG_PATH
    daemon = StreamDeckNotifyDaemon(config_path)
    asyncio.run(daemon.run())


if __name__ == "__main__":
    main()
