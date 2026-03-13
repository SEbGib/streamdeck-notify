"""Generic notification action — one instance per source (Slack, GitHub, etc.).

Features:
- Icon per source with notification badge
- Urgent visual indicator (red label color)
- Auto-populated default URL per source
- Button press opens URL and resets count
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk

from loguru import logger as log
from PIL import Image, ImageDraw, ImageFont

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

from ..globals import SOURCES, SOURCE_NAMES, SOURCE_URLS, SOURCE_ICONS
from ..internal.bridge_client import BridgeClient

SOURCE_LIST = list(SOURCES.items())  # [("slack", ("Slack", url, icon)), ...]

BADGE_RED = "#FF3B30"
BADGE_BG_URGENT = (80, 0, 0, 200)
TEXT_WHITE = "#FFFFFF"


class NotifyAction(ActionCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.has_configuration = True

        self._source: str = ""
        self._action_url: str = ""
        self._bridge_url: str = "http://127.0.0.1:9120"
        self._last_state: dict = {}
        self._bridge_down: bool = False
        self._icon_path: Path | None = None

        self.create_event_assigners()

    def create_event_assigners(self):
        self.add_event_assigner(EventAssigner(
            id="open-notification",
            ui_label="Open",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_press,
        ))
        self.add_event_assigner(EventAssigner(
            id="reset-notification",
            ui_label="Reset",
            default_events=[Input.Key.Events.HOLD_START],
            callback=self._on_reset,
        ))

    def get_config_rows(self) -> list:
        """Build configuration UI rows."""
        rows = []
        settings = self.get_settings()

        # Source selector
        self._source_row = Adw.ComboRow(title="Source")
        model = Gtk.StringList()
        for source_id, (source_name, _, _) in SOURCE_LIST:
            model.append(source_name)
        self._source_row.set_model(model)

        current_source = settings.get("source", "")
        for i, (source_id, _) in enumerate(SOURCE_LIST):
            if source_id == current_source:
                self._source_row.set_selected(i)
                break

        self._source_row.connect("notify::selected", self._on_source_selected)
        rows.append(self._source_row)

        # URL entry (pre-filled with default for source)
        self._url_row = Adw.EntryRow(title="URL (opened on click)")
        url = settings.get("action_url", "")
        if not url and current_source:
            url = SOURCE_URLS.get(current_source, "")
        self._url_row.set_text(url)
        self._url_row.connect("changed", self._on_url_changed)
        rows.append(self._url_row)

        return rows

    def on_ready(self):
        settings = self.get_settings()
        self._source = settings.get("source", "")
        self._action_url = settings.get("action_url", "")
        if not self._action_url and self._source:
            self._action_url = SOURCE_URLS.get(self._source, "")
        log.info(f"NotifyAction ready: source={self._source!r}, url={self._action_url!r}")
        self._resolve_icon()
        self._update_display()

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

    def _on_reset(self, data=None):
        """Long press — reset count without opening URL."""
        log.info(f"NotifyAction reset: source={self._source!r}")
        if self._source:
            BridgeClient.post_action(self._source, self._bridge_url)
        self.set_bottom_label("Reset!")
        # Next tick will clear/update the label automatically

    def _on_press(self, data=None):
        """Button pressed — reset count and open URL."""
        log.info(f"NotifyAction press: source={self._source!r}")
        if self._source:
            BridgeClient.post_action(self._source, self._bridge_url)

        url = self._action_url
        if not url and self._source:
            url = SOURCE_URLS.get(self._source, "")
        if url:
            log.info(f"NotifyAction opening: {url}")
            try:
                subprocess.Popen(
                    ["xdg-open", url],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception as e:
                log.error(f"Failed to open URL: {e}")

    def _update_display(self):
        """Update button image with icon, labels, and badge."""
        if not self._last_state:
            self.set_top_label(SOURCE_NAMES.get(self._source, "?"))
            self.set_bottom_label("...")
            self._set_source_icon()
            return

        label = self._last_state.get("label", "")
        subtitle = self._last_state.get("subtitle", "")
        count = self._last_state.get("count", 0)
        urgent = self._last_state.get("urgent", False)

        self.set_top_label(label)

        if subtitle:
            color = (255, 59, 48) if urgent else None
            self.set_bottom_label(subtitle, color=color)
        elif count > 0:
            self.set_bottom_label(str(count), color=(255, 59, 48))
        else:
            self.set_bottom_label("")

        # Dynamic icon for media sources
        extra = self._last_state.get("extra", {})
        media_source = extra.get("media_source")
        if media_source and self._source == "spotify":
            self._resolve_dynamic_icon(media_source)

        self._set_source_icon(badge_count=count, urgent=urgent)

    def _resolve_icon(self):
        """Find the icon file for the current source."""
        if not self._source:
            return
        icon_key = SOURCE_ICONS.get(self._source, "")
        if icon_key:
            self._icon_path = self._find_icon(icon_key)

    def _resolve_dynamic_icon(self, media_source: str):
        """Switch icon based on detected media source."""
        # Try media-specific icon first, fall back to default spotify icon
        path = self._find_icon(media_source)
        if path:
            self._icon_path = path
        else:
            icon_key = SOURCE_ICONS.get(self._source, "")
            if icon_key:
                self._icon_path = self._find_icon(icon_key)

    def _find_icon(self, name: str) -> Path | None:
        """Find an icon file by name in assets."""
        plugin_dir = Path(__file__).parent.parent
        for ext in (".png", ".svg"):
            path = plugin_dir / "assets" / f"{name}{ext}"
            if path.exists():
                return path
        return None

    def _set_source_icon(self, badge_count: int = 0, urgent: bool = False):
        """Set button icon, optionally with a notification badge overlay."""
        if not self._icon_path or not self._icon_path.exists():
            return

        try:
            icon = Image.open(self._icon_path).convert("RGBA")
            icon = icon.resize((72, 72), Image.LANCZOS)

            if badge_count > 0:
                icon = self._add_badge(icon, badge_count)

            if urgent:
                overlay = Image.new("RGBA", icon.size, BADGE_BG_URGENT)
                icon = Image.alpha_composite(icon, overlay)

            self.set_media(image=icon)
        except Exception as e:
            log.error(f"Icon render error: {e}")

    @staticmethod
    def _add_badge(img: Image.Image, count: int) -> Image.Image:
        """Draw a red notification badge on the top-right of an image."""
        draw = ImageDraw.Draw(img)
        text = str(count) if count < 100 else "99+"
        font = _get_font(14)

        bbox = draw.textbbox((0, 0), text, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]

        padding = 4
        badge_w = max(text_w + padding * 2, text_h + padding * 2)
        badge_h = text_h + padding * 2

        x = img.width - badge_w - 2
        y = 2

        draw.rounded_rectangle(
            [x, y, x + badge_w, y + badge_h],
            radius=badge_h // 2,
            fill=BADGE_RED,
        )
        draw.text(
            (x + (badge_w - text_w) // 2, y + padding - 1),
            text,
            fill=TEXT_WHITE,
            font=font,
        )
        return img

    def _on_source_selected(self, combo_row, _param):
        idx = combo_row.get_selected()
        if 0 <= idx < len(SOURCE_LIST):
            source_id = SOURCE_LIST[idx][0]
            self._source = source_id
            settings = self.get_settings()
            settings["source"] = source_id
            default_url = SOURCE_URLS.get(source_id, "")
            if not settings.get("action_url"):
                settings["action_url"] = default_url
                self._action_url = default_url
                if hasattr(self, "_url_row"):
                    self._url_row.set_text(default_url)
            self.set_settings(settings)
            self._resolve_icon()
            self._last_state = {}
            self._update_display()

    def _on_url_changed(self, entry_row):
        url = entry_row.get_text()
        self._action_url = url
        settings = self.get_settings()
        settings["action_url"] = url
        self.set_settings(settings)


def _get_font(size: int):
    """Get a font, falling back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/app/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()
