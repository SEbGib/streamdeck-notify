"""Page switch action — navigate to a named page on the deck."""

from __future__ import annotations

from pathlib import Path
from loguru import logger as log
from PIL import Image

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner


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
        threading.Timer(0.05, self._do_switch).start()

    def _do_switch(self):
        try:
            import globals as gl
            import time
            import threading

            page_path = gl.page_manager.get_best_page_path_match_from_name(self._target_page)
            if page_path is None:
                log.warning(f"Page '{self._target_page}' not found")
                return
            page = gl.page_manager.get_page(page_path, self.deck_controller)
            dc = self.deck_controller

            # Synchronized clear — waits for current media player tick to finish
            dc.active_page = page
            dc.clear_media_player_tasks()

            # Load page content directly
            dc.load_background(page, update=False)
            dc.load_brightness(page)
            dc.load_all_inputs(page, update=False)

            # Only call on_ready for NEW actions (first load)
            # Returning pages already have state — just re-render
            threads = []
            for action in page.get_all_actions():
                if hasattr(action, "on_ready") and not action.on_ready_called:
                    action.load_event_overrides()
                    action.on_ready_called = True
                    t = threading.Thread(
                        target=self._safe_on_ready,
                        args=(action,),
                        daemon=True,
                    )
                    t.start()
                    threads.append(t)

            for t in threads:
                t.join(timeout=3.0)

            # Re-render all keys — uses stored action state
            dc.update_all_inputs()
            time.sleep(0.3)
            dc.update_all_inputs()

            log.info(f"PageSwitch: done switching to {self._target_page}")
        except Exception as e:
            log.error(f"PageSwitch error: {e}")

    @staticmethod
    def _safe_on_ready(action):
        """Call on_ready in a thread, catching all errors."""
        try:
            action.on_ready()
        except Exception as e:
            log.warning(f"on_ready failed for {action.__class__.__name__}: {e}")

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
