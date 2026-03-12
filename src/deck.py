"""Stream Deck hardware interface."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from StreamDeck.DeviceManager import DeviceManager

if TYPE_CHECKING:
    from StreamDeck.Devices.StreamDeck import StreamDeck

logger = logging.getLogger(__name__)


class DeckManager:
    """Manage Stream Deck device connection and button updates."""

    def __init__(self, brightness: int = 70):
        self._deck: StreamDeck | None = None
        self._brightness = brightness
        self._key_callback = None

    def open(self) -> bool:
        """Find and open the first available Stream Deck."""
        decks = DeviceManager().enumerate()
        if not decks:
            logger.error("No Stream Deck found. Check USB connection and udev rules.")
            return False

        self._deck = decks[0]
        self._deck.open()
        self._deck.reset()
        self._deck.set_brightness(self._brightness)

        logger.info(
            "Opened %s (serial: %s, %d keys)",
            self._deck.deck_type(),
            self._deck.get_serial_number(),
            self._deck.key_count(),
        )

        if self._key_callback:
            self._deck.set_key_callback(self._key_callback)

        return True

    def set_key_callback(self, callback) -> None:
        """Set callback for key press events: callback(deck, key, state)."""
        self._key_callback = callback
        if self._deck:
            self._deck.set_key_callback(callback)

    def set_key_image(self, key: int, image_bytes: bytes) -> None:
        """Set the image on a specific key."""
        if not self._deck:
            return
        if key >= self._deck.key_count():
            logger.warning("Key %d out of range (max %d)", key, self._deck.key_count() - 1)
            return
        self._deck.set_key_image(key, image_bytes)

    @property
    def key_count(self) -> int:
        return self._deck.key_count() if self._deck else 0

    def close(self) -> None:
        """Reset and close the device."""
        if self._deck:
            self._deck.reset()
            self._deck.close()
            self._deck = None
