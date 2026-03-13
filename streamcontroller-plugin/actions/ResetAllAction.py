"""Reset All action — single button to mark all notification sources as read."""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image, ImageDraw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.bridge_client import BridgeClient

COLOR_IDLE = (80, 80, 80)
COLOR_HAS_NOTIFS = (255, 59, 48)
COLOR_CLEARED = (50, 180, 80)


class ResetAllAction(ActionCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._bridge_url: str = "http://127.0.0.1:9120"
        self._total_count: int = 0
        self._flash_ticks: int = 0

        self.create_event_assigners()

    def create_event_assigners(self):
        self.add_event_assigner(EventAssigner(
            id="reset-all",
            ui_label="Reset All",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        log.info("ResetAllAction ready")
        self._update_display()

    def on_tick(self):
        if self._flash_ticks > 0:
            self._flash_ticks -= 1
            if self._flash_ticks == 0:
                self._update_display()
            return

        try:
            data = BridgeClient.get_status(self._bridge_url)
            plugins = data.get("plugins", {})
            total = sum(p.get("count", 0) for p in plugins.values())
            if total != self._total_count:
                self._total_count = total
                self._update_display()
        except Exception:
            pass

    def _on_press(self, data=None):
        log.info("ResetAllAction: resetting all sources")
        try:
            status = BridgeClient.get_status(self._bridge_url)
            plugins = status.get("plugins", {})
            for name, state in plugins.items():
                if state.get("count", 0) > 0:
                    BridgeClient.post_action(name, self._bridge_url)
        except Exception as e:
            log.error(f"ResetAll error: {e}")

        self._total_count = 0
        self._flash_ticks = 3
        self.set_top_label("Reset!")
        self.set_bottom_label("")
        self._render_icon(COLOR_CLEARED)

    def _update_display(self):
        if self._total_count > 0:
            self.set_top_label("Clear All")
            self.set_bottom_label(str(self._total_count), color=COLOR_HAS_NOTIFS)
            self._render_icon(COLOR_HAS_NOTIFS)
        else:
            self.set_top_label("Clear All")
            self.set_bottom_label("")
            self._render_icon(COLOR_IDLE)

    def _render_icon(self, color: tuple):
        try:
            size = 72
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            # Checkmark circle
            margin = 10
            draw.ellipse(
                [margin, margin, size - margin, size - margin],
                fill=(*color, 200),
                outline=(255, 255, 255, 150),
                width=2,
            )

            # Checkmark
            cx, cy = size // 2, size // 2
            draw.line(
                [(cx - 12, cy), (cx - 3, cy + 10), (cx + 14, cy - 10)],
                fill=(255, 255, 255, 230),
                width=4,
            )

            self.set_media(image=img)
        except Exception as e:
            log.error(f"ResetAll icon error: {e}")
