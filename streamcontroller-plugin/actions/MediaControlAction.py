"""Media control action — previous/next track buttons.

Sends MPRIS2 commands via the bridge to the active media player.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.bridge_client import BridgeClient


class MediaControlAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._action: str = ""  # "previous" or "next"
        self._bridge_url: str = "http://127.0.0.1:9120"
        self._icon_path: Path | None = None

        self.add_event_assigner(EventAssigner(
            id="media-control",
            ui_label="Media Control",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        settings = self.get_settings()
        self._action = settings.get("action", "previous")
        log.info(f"MediaControlAction ready: action={self._action!r}")
        self._resolve_icon()
        self._set_icon()

    def on_tick(self):
        pass

    def _on_press(self, data=None):
        log.info(f"MediaControl: {self._action}")
        BridgeClient.post_action("spotify", self._bridge_url, action=self._action)

    def _resolve_icon(self):
        icon_name = "media_previous" if self._action == "previous" else "media_next"
        plugin_dir = Path(__file__).parent.parent
        for ext in (".png", ".svg"):
            path = plugin_dir / "assets" / f"{icon_name}{ext}"
            if path.exists():
                self._icon_path = path
                return

    def _set_icon(self):
        if not self._icon_path or not self._icon_path.exists():
            label = "⏮" if self._action == "previous" else "⏭"
            self.set_center_label(label)
            return

        try:
            from PIL import Image
            icon = Image.open(self._icon_path).convert("RGBA").resize((72, 72), Image.LANCZOS)
            self.set_media(image=icon)
        except Exception as e:
            log.error(f"MediaControl icon error: {e}")
