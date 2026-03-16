"""SystemDetailAction — displays a single system metric from the bridge.

Simpler than NotifyAction: no badge, no URL, no page-switch on hold.
Just polls the bridge and shows label + subtitle.

Sources: disk, load_avg, uptime, net_tx, net_rx
"""

from __future__ import annotations

from pathlib import Path

from loguru import logger as log
from PIL import Image

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..internal.bridge_client import BridgeClient

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

# Metric options available in this action
_METRICS = [
    ("disk",     "Disk"),
    ("load_avg", "Load Avg"),
    ("uptime",   "Uptime"),
    ("net_tx",   "Net TX"),
    ("net_rx",   "Net RX"),
    ("system_cpu", "CPU"),
    ("system_ram", "RAM"),
]


class SystemDetailAction(ActionCore):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

        self._source: str = ""
        self._bridge_url: str = "http://127.0.0.1:9120"
        self._last_state: dict = {}
        self._bridge_down: bool = False
        self._icon_path: Path | None = None

        self.add_event_assigner(EventAssigner(
            id="system-detail-refresh",
            ui_label="Refresh",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))

    # ------------------------------------------------------------------
    # Configuration UI
    # ------------------------------------------------------------------

    def get_config_rows(self) -> list:
        rows = []
        settings = self.get_settings()
        current = settings.get("source", "")

        self._metric_row = Adw.ComboRow(title="Metric")
        model = Gtk.StringList()
        for _, label in _METRICS:
            model.append(label)
        self._metric_row.set_model(model)

        for i, (mid, _) in enumerate(_METRICS):
            if mid == current:
                self._metric_row.set_selected(i)
                break

        self._metric_row.connect("notify::selected", self._on_metric_selected)
        rows.append(self._metric_row)
        return rows

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def on_ready(self):
        settings = self.get_settings()
        self._source = settings.get("source", "")
        log.info(f"SystemDetailAction ready: source={self._source!r}")
        self._resolve_icon()
        self._update_display()

    def on_tick(self):
        if not self._source:
            return
        if self.page is not self.deck_controller.active_page:
            return

        try:
            state = BridgeClient.get_plugin_state(self._source, self._bridge_url)
            if not state and not self._last_state:
                if not self._bridge_down:
                    self._bridge_down = True
                    self.set_bottom_label("Bridge?")
                return

            self._bridge_down = False
            if state != self._last_state:
                self._last_state = state
                self._update_display()

        except Exception as e:
            if not self._bridge_down:
                self._bridge_down = True
                self.set_bottom_label("Bridge?")
                log.error(f"SystemDetailAction tick error: {e}")

    # ------------------------------------------------------------------
    # Display
    # ------------------------------------------------------------------

    def _update_display(self):
        if not self._last_state:
            display_name = dict(_METRICS).get(self._source, self._source)
            self.set_top_label(display_name)
            self.set_bottom_label("...")
            self._set_icon()
            return

        label = self._last_state.get("label", "")
        subtitle = self._last_state.get("subtitle", "")
        urgent = self._last_state.get("urgent", False)

        self.set_top_label(label)
        if subtitle:
            color = (255, 59, 48) if urgent else None
            self.set_bottom_label(subtitle, color=color)
        else:
            self.set_bottom_label("")

        self._set_icon()

    def _resolve_icon(self):
        """Use a source-specific icon if available, fall back to 'system'."""
        plugin_dir = Path(__file__).parent.parent
        for name in (self._source, "system"):
            for ext in (".png", ".svg"):
                path = plugin_dir / "assets" / f"{name}{ext}"
                if path.exists():
                    self._icon_path = path
                    return

    def _set_icon(self):
        if not self._icon_path or not self._icon_path.exists():
            return
        try:
            icon = Image.open(self._icon_path).convert("RGBA").resize((72, 72), Image.LANCZOS)
            self.set_media(image=icon)
        except Exception as e:
            log.error(f"SystemDetailAction icon error: {e}")

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    def _on_press(self, data=None):
        """Force immediate state refresh on button press."""
        self._last_state = {}
        self._update_display()

    def _on_metric_selected(self, combo_row, _param):
        idx = combo_row.get_selected()
        if 0 <= idx < len(_METRICS):
            source_id = _METRICS[idx][0]
            self._source = source_id
            settings = self.get_settings()
            settings["source"] = source_id
            self.set_settings(settings)
            self._resolve_icon()
            self._last_state = {}
            self._update_display()
