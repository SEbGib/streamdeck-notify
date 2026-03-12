"""Base plugin interface for Stream Deck notification sources."""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field

logger = logging.getLogger(__name__)


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

    @abstractmethod
    async def poll(self) -> NotificationState:
        """Fetch current notification state. Called every refresh cycle."""
        ...

    async def on_press(self) -> None:
        """Called when the button is pressed. Override for custom behavior."""

    async def setup(self) -> None:
        """One-time setup (auth, connections). Override if needed."""

    async def teardown(self) -> None:
        """Cleanup on shutdown. Override if needed."""

    async def run_loop(self, interval: int) -> None:
        """Main polling loop."""
        self._running = True
        await self.setup()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in %s", self.__class__.__name__)
            await asyncio.sleep(interval)

    def stop(self) -> None:
        self._running = False
