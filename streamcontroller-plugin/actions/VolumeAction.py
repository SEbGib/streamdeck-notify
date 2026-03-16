"""Volume control action for Stream Deck.

Uses wpctl (WirePlumber/PipeWire) via flatpak-spawn.
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.host import host_run

STEP = "5%"
ASSETS = Path(__file__).parent.parent / "assets"


class VolumeAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._direction: str = "up"
        self._volume_pct: int | None = None
        self._icon: Image.Image | None = None

        self.add_event_assigner(EventAssigner(
            id="volume-control",
            ui_label="Volume",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        settings = self.get_settings()
        self._direction = settings.get("direction", "up")
        icon_name = "volume_up" if self._direction == "up" else "volume_down"
        icon_path = ASSETS / f"{icon_name}.png"
        if icon_path.exists():
            self._icon = Image.open(icon_path).convert("RGBA").resize((72, 72), Image.LANCZOS)
        log.info(f"VolumeAction ready: direction={self._direction!r}")

    def on_tick(self):
        if self.page is not self.deck_controller.active_page:
            return
        try:
            self._poll_volume()
            self._update_display()
        except Warning:
            pass

    def _on_press(self, data=None):
        op = f"{STEP}+" if self._direction == "up" else f"{STEP}-"
        log.info(f"Volume: {op}")
        try:
            result = host_run(["wpctl", "set-volume", "-l", "1.0",
                                "@DEFAULT_AUDIO_SINK@", op])
            if result.returncode != 0:
                log.error(f"Volume set-volume failed: rc={result.returncode} stderr={result.stderr.strip()}")
        except Exception as e:
            log.error(f"Volume error: {e}")
        self._poll_volume()
        try:
            self._update_display()
        except Warning:
            pass

    def _poll_volume(self):
        try:
            result = host_run(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
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
        if self._icon:
            self.set_media(image=self._icon)
