"""Generic notification action — one instance per source (Slack, GitHub, etc.)."""

from __future__ import annotations

import subprocess

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw

from loguru import logger as log

from src.backend.PluginManager.ActionCore import ActionCore

from ..globals import SOURCES
from ..internal.bridge_client import BridgeClient

# Source choices for the combo row
SOURCE_LIST = list(SOURCES.items())  # [("slack", "Slack"), ...]


class NotifyAction(ActionCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

        self._source: str = ""
        self._action_url: str = ""
        self._bridge_url: str = "http://127.0.0.1:9120"
        self._last_state: dict = {}
        self._bridge_down: bool = False

    def get_config_rows(self) -> list:
        """Build configuration UI rows."""
        rows = []
        settings = self.get_settings()

        # Source selector
        self._source_row = Adw.ComboRow(title="Source")
        string_list = self._source_row.get_model() or __import__("gi").repository.Gtk.StringList()
        model = __import__("gi").repository.Gtk.StringList()
        for source_id, source_name in SOURCE_LIST:
            model.append(source_name)
        self._source_row.set_model(model)

        # Set current selection
        current_source = settings.get("source", "")
        for i, (source_id, _) in enumerate(SOURCE_LIST):
            if source_id == current_source:
                self._source_row.set_selected(i)
                break

        self._source_row.connect("notify::selected", self._on_source_selected)
        rows.append(self._source_row)

        # URL entry
        self._url_row = Adw.EntryRow(title="URL (opened on click)")
        self._url_row.set_text(settings.get("action_url", ""))
        self._url_row.connect("changed", self._on_url_changed)
        rows.append(self._url_row)

        return rows

    def on_ready(self):
        settings = self.get_settings()
        self._source = settings.get("source", "")
        self._action_url = settings.get("action_url", "")
        self._update_display()
        log.info(f"NotifyAction ready: source={self._source}")

    def on_tick(self):
        """Called every second by StreamController."""
        if not self._source:
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
                log.error(f"NotifyAction tick error: {e}")

    def on_key_down(self):
        """Button pressed — reset count and open URL."""
        if self._source:
            BridgeClient.post_action(self._source, self._bridge_url)

        if self._action_url:
            try:
                subprocess.Popen(
                    ["xdg-open", self._action_url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                log.error(f"Failed to open URL: {e}")

    def _update_display(self):
        """Update button labels from bridge state."""
        if not self._last_state:
            self.set_top_label(SOURCES.get(self._source, "?"))
            self.set_bottom_label("...")
            return

        label = self._last_state.get("label", "")
        subtitle = self._last_state.get("subtitle", "")
        count = self._last_state.get("count", 0)

        self.set_top_label(label)

        if subtitle:
            self.set_bottom_label(subtitle)
        elif count > 0:
            self.set_bottom_label(str(count))
        else:
            self.set_bottom_label("")

    def _on_source_selected(self, combo_row, _param):
        idx = combo_row.get_selected()
        if 0 <= idx < len(SOURCE_LIST):
            source_id = SOURCE_LIST[idx][0]
            self._source = source_id
            settings = self.get_settings()
            settings["source"] = source_id
            self.set_settings(settings)
            self._last_state = {}
            self._update_display()
            log.info(f"NotifyAction: source changed to {source_id}")

    def _on_url_changed(self, entry_row):
        url = entry_row.get_text()
        self._action_url = url
        settings = self.get_settings()
        settings["action_url"] = url
        self.set_settings(settings)
