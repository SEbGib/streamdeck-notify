"""Media control action — previous/next/play_pause track buttons.

Sends MPRIS2 commands via the bridge to the active media player.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.bridge_client import BridgeClient

ASSETS = Path(__file__).parent.parent / "assets"

_ICON_LABELS = {
    "previous": "⏮",
    "next": "⏭",
    "play_pause": "⏯",
}


class MediaControlAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._action: str = ""
        self._bridge_url: str = "http://127.0.0.1:9120"

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
        self._set_icon()

    def on_tick(self):
        pass

    def _on_press(self, data=None):
        log.info(f"MediaControl: {self._action}")
        BridgeClient.post_action("spotify", self._bridge_url, action=self._action)

    def _set_icon(self):
        icon_map = {
            "previous": "media_previous",
            "next": "media_next",
            "play_pause": "media_play_pause",
        }
        icon_name = icon_map.get(self._action, "media_previous")
        icon_path = ASSETS / f"{icon_name}.png"
        if icon_path.exists():
            try:
                icon = Image.open(icon_path).convert("RGBA").resize((72, 72), Image.LANCZOS)
                self.set_media(image=icon)
                return
            except Exception as e:
                log.error(f"MediaControl icon error: {e}")
        self.set_center_label(_ICON_LABELS.get(self._action, "?"))
