"""Page switch action — navigate to a named page on the deck."""

from __future__ import annotations

from pathlib import Path
from loguru import logger as log
from PIL import Image

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.page_switch import switch_to_page


class PageSwitchAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True
        self._target_page: str = ""
        self._icon_path: Path | None = None

        self.add_event_assigner(EventAssigner(
            id="page-switch",
            ui_label="Switch Page",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    def on_ready(self):
        settings = self.get_settings()
        self._target_page = settings.get("target_page", "")
        log.info(f"PageSwitchAction ready: target={self._target_page!r}")
        self._resolve_icon()
        self._update_display()

    def on_tick(self):
        pass

    def _on_press(self, data=None):
        if not self._target_page:
            return
        log.info(f"PageSwitch: navigating to {self._target_page!r}")
        import threading
        threading.Timer(0.05, switch_to_page, args=[self._target_page, self.deck_controller]).start()

    def _resolve_icon(self):
        icon_name = self.get_settings().get("icon", "page_next")
        plugin_dir = Path(__file__).parent.parent
        for ext in (".png", ".svg"):
            path = plugin_dir / "assets" / f"{icon_name}{ext}"
            if path.exists():
                self._icon_path = path
                return

    def _update_display(self):
        if self._icon_path and self._icon_path.exists():
            try:
                icon = Image.open(self._icon_path).convert("RGBA").resize((72, 72), Image.LANCZOS)
                self.set_media(image=icon)
            except Exception as e:
                log.error(f"PageSwitch icon error: {e}")

        label = self.get_settings().get("label", self._target_page or "Page")
        self.set_bottom_label(label)
