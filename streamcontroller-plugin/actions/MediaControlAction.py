"""Media control action — previous/next/play_pause track buttons.

Sends MPRIS2 commands via the bridge to the active media player.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image, ImageDraw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.bridge_client import BridgeClient

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
        icon_map = {
            "previous": "media_previous",
            "next": "media_next",
            "play_pause": "media_play_pause",
        }
        icon_name = icon_map.get(self._action, "media_previous")
        plugin_dir = Path(__file__).parent.parent
        for ext in (".png", ".svg"):
            path = plugin_dir / "assets" / f"{icon_name}{ext}"
            if path.exists():
                self._icon_path = path
                return

    def _set_icon(self):
        if self._icon_path and self._icon_path.exists():
            try:
                icon = Image.open(self._icon_path).convert("RGBA").resize((72, 72), Image.LANCZOS)
                self.set_media(image=icon)
                return
            except Exception as e:
                log.error(f"MediaControl icon error: {e}")

        # Fallback: render icon programmatically
        if self._action == "play_pause":
            self.set_media(image=_render_play_pause_icon())
        else:
            self.set_center_label(_ICON_LABELS.get(self._action, "?"))


def _render_play_pause_icon() -> Image.Image:
    """Render a play/pause icon."""
    size = 72
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # Play triangle
    draw.polygon(
        [(20, 18), (20, 54), (44, 36)],
        fill=(255, 255, 255, 220),
    )
    # Pause bars
    draw.rectangle([50, 18, 56, 54], fill=(255, 255, 255, 220))
    draw.rectangle([60, 18, 66, 54], fill=(255, 255, 255, 220))
    return img
