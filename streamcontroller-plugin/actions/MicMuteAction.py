"""Mic mute toggle action for Stream Deck.

Uses wpctl (WirePlumber/PipeWire) via flatpak-spawn to toggle microphone.
"""

from __future__ import annotations

import subprocess

from loguru import logger as log
from PIL import Image, ImageDraw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

COLOR_MUTED = (220, 50, 50)
COLOR_LIVE = (50, 180, 80)
COLOR_UNKNOWN = (120, 120, 120)


class MicMuteAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._muted: bool | None = None

        self.add_event_assigner(EventAssigner(
            id="mic-toggle",
            ui_label="Toggle Mic",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        log.info("MicMuteAction ready")

    def on_tick(self):
        if self.page is not self.deck_controller.active_page:
            return
        try:
            self._poll_state()
            self._update_display()
        except Warning:
            pass  # Action not yet ready

    def _on_press(self, data=None):
        log.info("MicMute: toggling")
        try:
            subprocess.run(
                ["flatpak-spawn", "--host",
                 "wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"],
                capture_output=True, timeout=3,
            )
        except Exception as e:
            log.error(f"MicMute toggle error: {e}")
        self._poll_state()
        try:
            self._update_display()
        except Warning:
            pass

    def _poll_state(self):
        try:
            result = subprocess.run(
                ["flatpak-spawn", "--host",
                 "wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode == 0:
                self._muted = "[MUTED]" in result.stdout
        except Exception:
            self._muted = None

    def _update_display(self):
        if self._muted is None:
            self.set_top_label("Mic")
            self.set_bottom_label("?", color=COLOR_UNKNOWN)
            self.set_media(image=_render_mic_icon(COLOR_UNKNOWN, False))
        elif self._muted:
            self.set_top_label("Muted")
            self.set_bottom_label("OFF", color=COLOR_MUTED)
            self.set_media(image=_render_mic_icon(COLOR_MUTED, True))
        else:
            self.set_top_label("Mic")
            self.set_bottom_label("ON", color=COLOR_LIVE)
            self.set_media(image=_render_mic_icon(COLOR_LIVE, False))


def _render_mic_icon(color: tuple, muted: bool) -> Image.Image:
    """Render a microphone icon with optional mute slash."""
    size = 72
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Mic body (rounded rectangle)
    draw.rounded_rectangle(
        [26, 10, 46, 42],
        radius=8,
        fill=(*color, 220),
    )

    # Mic stand (arc + line)
    draw.arc([18, 24, 54, 52], start=0, end=180, fill=(*color, 200), width=3)
    draw.line([36, 52, 36, 62], fill=(*color, 200), width=3)
    draw.line([26, 62, 46, 62], fill=(*color, 200), width=3)

    # Mute slash
    if muted:
        draw.line([14, 8, 58, 64], fill=(255, 60, 60, 240), width=4)

    return img
