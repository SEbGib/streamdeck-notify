"""Mic mute toggle action for Stream Deck.

Uses wpctl (WirePlumber/PipeWire) via flatpak-spawn to toggle microphone.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.host import host_run

ASSETS = Path(__file__).parent.parent / "assets"


def _load_icon(name: str) -> Image.Image | None:
    path = ASSETS / f"{name}.png"
    if path.exists():
        return Image.open(path).convert("RGBA").resize((72, 72), Image.LANCZOS)
    return None


class MicMuteAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._muted: bool | None = None
        self._icon_live: Image.Image | None = None
        self._icon_muted: Image.Image | None = None

        self.add_event_assigner(EventAssigner(
            id="mic-toggle",
            ui_label="Toggle Mic",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        self._icon_live = _load_icon("mic")
        self._icon_muted = _load_icon("mic_muted")
        log.info("MicMuteAction ready")

    def on_tick(self):
        if self.page is not self.deck_controller.active_page:
            return
        try:
            self._poll_state()
            self._update_display()
        except Warning:
            pass

    def _on_press(self, data=None):
        log.info("MicMute: toggling")
        try:
            result = host_run(["wpctl", "set-mute", "@DEFAULT_AUDIO_SOURCE@", "toggle"])
            if result.returncode != 0:
                log.error(f"MicMute set-mute failed: rc={result.returncode} stderr={result.stderr.strip()}")
        except Exception as e:
            log.error(f"MicMute toggle error: {e}")
        self._poll_state()
        try:
            self._update_display()
        except Warning:
            pass

    def _poll_state(self):
        try:
            result = host_run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"])
            if result.returncode == 0:
                self._muted = "[MUTED]" in result.stdout
        except Exception:
            self._muted = None

    def _update_display(self):
        if self._muted is None:
            self.set_top_label("Mic")
            self.set_bottom_label("?")
        elif self._muted:
            self.set_top_label("Muted")
            self.set_bottom_label("OFF", color=(220, 50, 50))
            if self._icon_muted:
                self.set_media(image=self._icon_muted)
        else:
            self.set_top_label("Mic")
            self.set_bottom_label("ON", color=(50, 180, 80))
            if self._icon_live:
                self.set_media(image=self._icon_live)
