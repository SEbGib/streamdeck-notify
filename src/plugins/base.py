"""Base plugin interface for Stream Deck notification sources."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

HISTORY_MAX = 50


@dataclass
class NotificationState:
    """State of a notification source, rendered on a button."""

    count: int = 0
    label: str = ""
    subtitle: str = ""
    urgent: bool = False
    color: str = "#FFFFFF"
    badge_color: str = "#FF3B30"
    extra: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class BasePlugin(ABC):
    """Base class for all notification plugins."""

    def __init__(self, config: dict):
        self.config = config
        self.state = NotificationState()
        self._running = False
        self.poll_count: int = 0
        self.error_count: int = 0
        self.last_poll: datetime | None = None
        self._history: list[dict] = []

    @abstractmethod
    async def poll(self) -> NotificationState:
        """Fetch current notification state. Called every refresh cycle."""
        ...

    async def on_press(self, action: str = "") -> None:
        """Called when the button is pressed. Override for custom behavior."""

    async def setup(self) -> None:
        """One-time setup (auth, connections). Override if needed."""

    async def teardown(self) -> None:
        """Cleanup on shutdown. Override if needed."""

    def notify_state_changed(self) -> None:
        """Update state immediately and wake the poll loop.

        Call from event-driven handlers (D-Bus, etc.) to push changes
        without waiting for the next poll cycle.
        """
        try:
            # Synchronous state refresh — poll() must handle being called
            # outside the normal loop for event-driven plugins
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                loop.create_task(self._refresh_state())
        except Exception:
            pass

    def _record_history(self, state: NotificationState) -> None:
        """Append a history entry for a state transition (capped at HISTORY_MAX)."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": self.__class__.__name__,
            "label": state.label,
            "subtitle": state.subtitle,
            "count": state.count,
            "urgent": state.urgent,
        }
        self._history.append(entry)
        if len(self._history) > HISTORY_MAX:
            self._history = self._history[-HISTORY_MAX:]

    async def _refresh_state(self) -> None:
        """Immediate state refresh triggered by notify_state_changed."""
        try:
            new_state = await self.poll()
            if new_state.to_dict() != self.state.to_dict():
                self._record_history(new_state)
            self.state = new_state
        except Exception:
            logger.exception("Immediate refresh error in %s", self.__class__.__name__)

    async def run_loop(self, interval: int) -> None:
        """Main polling loop."""
        self._running = True
        await self.setup()
        while self._running:
            try:
                new_state = await self.poll()
                if new_state.to_dict() != self.state.to_dict():
                    self._record_history(new_state)
                self.state = new_state
                self.poll_count += 1
                self.last_poll = datetime.now(timezone.utc)
            except Exception:
                self.error_count += 1
                logger.exception("Poll error in %s", self.__class__.__name__)
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
