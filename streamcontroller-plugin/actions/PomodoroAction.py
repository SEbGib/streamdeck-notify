"""Pomodoro timer action for Stream Deck.

Cycles between 25 min focus and 5 min break.
- Short press: start / pause
- Long press: reset timer
- Display: countdown with color-coded state
"""

from __future__ import annotations

import time

from loguru import logger as log
from PIL import Image, ImageDraw

from src.backend.DeckManagement.InputIdentifier import Input
from src.backend.PluginManager.ActionCore import ActionCore
from src.backend.PluginManager.EventAssigner import EventAssigner

FOCUS_DURATION = 25 * 60  # 25 minutes in seconds
BREAK_DURATION = 5 * 60   # 5 minutes in seconds

COLOR_FOCUS = (200, 50, 50)    # Red
COLOR_BREAK = (50, 180, 80)    # Green
COLOR_PAUSED = (120, 120, 120) # Grey


class PomodoroAction(ActionCore):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._running: bool = False
        self._in_focus: bool = True
        self._remaining: int = FOCUS_DURATION
        self._last_tick: float = 0
        self._urgent_until: float = 0

        self.create_event_assigners()

    def create_event_assigners(self):
        self.add_event_assigner(EventAssigner(
            id="pomodoro-toggle",
            ui_label="Start/Pause",
            default_events=[Input.Key.Events.DOWN],
            callback=self._on_toggle,
        ))
        self.add_event_assigner(EventAssigner(
            id="pomodoro-reset",
            ui_label="Reset",
            default_events=[Input.Key.Events.HOLD_START],
            callback=self._on_reset,
        ))

    def on_ready(self):
        log.info("PomodoroAction ready")
        self._last_tick = time.time()
        self._update_display()

    def on_tick(self):
        """Called every second by StreamController."""
        now = time.time()

        if self._running:
            elapsed = now - self._last_tick
            if elapsed >= 1.0:
                seconds_passed = int(elapsed)
                self._remaining -= seconds_passed
                self._last_tick = now

                if self._remaining <= 0:
                    self._switch_phase()

                self._update_display()
        else:
            self._last_tick = now

        # Clear urgent flag after 3 seconds
        if self._urgent_until and now > self._urgent_until:
            self._urgent_until = 0
            self._update_display()

    def _on_toggle(self, data=None):
        """Short press — start or pause the timer."""
        self._running = not self._running
        self._last_tick = time.time()
        log.info(f"Pomodoro {'started' if self._running else 'paused'}")
        self._update_display()

    def _on_reset(self, data=None):
        """Long press — reset to focus mode."""
        self._running = False
        self._in_focus = True
        self._remaining = FOCUS_DURATION
        self._urgent_until = 0
        log.info("Pomodoro reset")
        self._update_display()

    def _switch_phase(self):
        """Auto-switch between focus and break."""
        self._in_focus = not self._in_focus
        self._remaining = FOCUS_DURATION if self._in_focus else BREAK_DURATION
        self._urgent_until = time.time() + 3  # Brief urgent indicator
        phase = "Focus" if self._in_focus else "Break"
        log.info(f"Pomodoro phase switch: {phase}")

    def _update_display(self):
        """Update button labels and icon."""
        minutes, seconds = divmod(max(self._remaining, 0), 60)
        countdown = f"{minutes:02d}:{seconds:02d}"

        if self._in_focus:
            phase_label = "Focus"
        else:
            phase_label = "Pause"  # "Pause" = break in French context

        if not self._running and self._remaining == (FOCUS_DURATION if self._in_focus else BREAK_DURATION):
            phase_label = "Pomo"  # Idle state

        self.set_top_label(phase_label)

        if self._urgent_until and time.time() < self._urgent_until:
            self.set_bottom_label(countdown, color=(255, 255, 0))
        elif not self._running:
            self.set_bottom_label(countdown, color=COLOR_PAUSED)
        elif self._in_focus:
            self.set_bottom_label(countdown, color=COLOR_FOCUS)
        else:
            self.set_bottom_label(countdown, color=COLOR_BREAK)

        # Render colored circle icon to indicate state
        self._render_icon()

    def _render_icon(self):
        """Render a simple colored icon showing timer state."""
        try:
            size = 72
            img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
            draw = ImageDraw.Draw(img)

            if self._in_focus:
                fill = COLOR_FOCUS if self._running else COLOR_PAUSED
            else:
                fill = COLOR_BREAK if self._running else COLOR_PAUSED

            if self._urgent_until and time.time() < self._urgent_until:
                fill = (255, 200, 0)  # Yellow flash on phase switch

            # Draw filled circle
            margin = 8
            draw.ellipse(
                [margin, margin, size - margin, size - margin],
                fill=(*fill, 220),
                outline=(255, 255, 255, 180),
                width=2,
            )

            # Draw play/pause indicator in center
            cx, cy = size // 2, size // 2
            if self._running:
                # Small "play" triangle (not needed, just a dot)
                draw.ellipse([cx - 4, cy - 4, cx + 4, cy + 4], fill=(255, 255, 255, 200))
            else:
                # Pause bars
                draw.rectangle([cx - 6, cy - 6, cx - 2, cy + 6], fill=(255, 255, 255, 200))
                draw.rectangle([cx + 2, cy - 6, cx + 6, cy + 6], fill=(255, 255, 255, 200))

            self.set_media(image=img)
        except Exception as e:
            log.error(f"Pomodoro icon render error: {e}")
