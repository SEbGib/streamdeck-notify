"""Volume control action for Stream Deck.

Uses wpctl (WirePlumber/PipeWire) via flatpak-spawn.
"""

from __future__ import annotations

import subprocess

from loguru import logger as log
from PIL import Image, ImageDraw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

STEP = "5%"


class VolumeAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._direction: str = "up"  # "up" or "down"
        self._volume_pct: int | None = None

        self.add_event_assigner(EventAssigner(
            id="volume-control",
            ui_label="Volume",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        settings = self.get_settings()
        self._direction = settings.get("direction", "up")
        log.info(f"VolumeAction ready: direction={self._direction!r}")

    def on_tick(self):
        if self.page is not self.deck_controller.active_page:
            return
        try:
            self._poll_volume()
            self._update_display()
        except Warning:
            pass  # Action not yet ready

    def _on_press(self, data=None):
        op = f"{STEP}+" if self._direction == "up" else f"{STEP}-"
        log.info(f"Volume: {op}")
        try:
            subprocess.run(
                ["flatpak-spawn", "--host",
                 "wpctl", "set-volume", "-l", "1.0",
                 "@DEFAULT_AUDIO_SINK@", op],
                capture_output=True, timeout=3,
            )
        except Exception as e:
            log.error(f"Volume error: {e}")
        self._poll_volume()
        try:
            self._update_display()
        except Warning:
            pass

    def _poll_volume(self):
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host",
                 "wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                # Output: "Volume: 0.75" or "Volume: 0.75 [MUTED]"
                parts = result.stdout.strip().split()
                if len(parts) >= 2:
                    self._volume_pct = int(float(parts[1]) * 100)
        except Exception:
            self._volume_pct = None

    def _update_display(self):
        label = "Vol +" if self._direction == "up" else "Vol -"
        self.set_top_label(label)
        if self._volume_pct is not None:
            self.set_bottom_label(f"{self._volume_pct}%")
        else:
            self.set_bottom_label("?")
        self.set_media(image=_render_volume_icon(self._direction))


def _render_volume_icon(direction: str) -> Image.Image:
    """Render a speaker icon with up/down indicator."""
    size = 72
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    white = (255, 255, 255, 220)

    # Speaker body
    draw.rectangle([14, 26, 26, 46], fill=white)
    draw.polygon([(26, 26), (40, 14), (40, 58), (26, 46)], fill=white)

    # Sound waves
    draw.arc([38, 20, 54, 52], start=-40, end=40, fill=white, width=2)
    draw.arc([44, 14, 62, 58], start=-40, end=40, fill=white, width=2)

    # Direction arrow
    if direction == "up":
        draw.polygon([(54, 8), (48, 18), (60, 18)], fill=(100, 220, 100, 220))
    else:
        draw.polygon([(54, 64), (48, 54), (60, 54)], fill=(220, 150, 50, 220))

    return img
