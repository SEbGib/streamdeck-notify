"""Media player plugin — shows now playing via D-Bus MPRIS2.

Uses gdbus subprocess to communicate with MPRIS2-compatible players
(Spotify, Chromium, Firefox, etc.).
"""

from __future__ import annotations

import asyncio
import logging
import re
import subprocess

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

_DEFAULT_PLAYERS = [
    "org.mpris.MediaPlayer2.spotify",
    "org.mpris.MediaPlayer2.chromium",
    "org.mpris.MediaPlayer2.firefox",
    "org.mpris.MediaPlayer2.vlc",
]

_MAX_LABEL_LEN = 18


class SpotifyPlugin(BasePlugin):
    """Show now playing track on Stream Deck via MPRIS2 D-Bus."""

    POLL_INTERVAL = 5  # Media updates need faster polling than notifications

    def __init__(self, config: dict):
        super().__init__(config)
        self._player: str | None = config.get("player")
        self._active_player: str | None = None

    async def run_loop(self, interval: int) -> None:
        """Override: use faster poll interval for media tracking."""
        self._running = True
        await self.setup()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in SpotifyPlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def setup(self) -> None:
        if self._player:
            self._active_player = self._player
            logger.info("MPRIS: using configured player %s", self._player)
        else:
            self._active_player = await self._detect_player()
            if self._active_player:
                logger.info("MPRIS: auto-detected %s", self._active_player)

    async def poll(self) -> NotificationState:
        # Always re-detect player (instance IDs change when tabs switch)
        self._active_player = await self._detect_player()

        if not self._active_player:
            return NotificationState(
                label="No player", subtitle="", color="#1DB954"
            )

        try:
            metadata = await self._fetch_metadata()
        except Exception:
            logger.exception("MPRIS poll failed")
            self._active_player = None
            return NotificationState(label="No player", subtitle="", color="#1DB954")

        title = metadata.get("title", "")
        artist = metadata.get("artist", "")

        if not title:
            return NotificationState(
                label="Paused", subtitle="", color="#1DB954"
            )

        label = title[:_MAX_LABEL_LEN] + ("…" if len(title) > _MAX_LABEL_LEN else "")
        subtitle = artist[:_MAX_LABEL_LEN] + ("…" if len(artist) > _MAX_LABEL_LEN else "")

        return NotificationState(
            count=0,
            label=label,
            subtitle=subtitle,
            urgent=False,
            color="#1DB954",
        )

    async def on_press(self) -> None:
        """Toggle play/pause on the active player."""
        if not self._active_player:
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._dbus_play_pause)
        except Exception:
            logger.exception("MPRIS PlayPause failed")

    async def _detect_player(self) -> str | None:
        """Try to find an active MPRIS2 player on the session bus."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._detect_player_sync)

    def _detect_player_sync(self) -> str | None:
        """Blocking: find an active MPRIS2 player on the session bus.

        Lists all bus names and matches by prefix (handles .instanceXXX suffixes
        like chromium.instance13744 for Deezer/YouTube in browser).
        """
        # Get all bus names
        try:
            result = subprocess.run(
                ["gdbus", "call", "--session",
                 "--dest", "org.freedesktop.DBus",
                 "--object-path", "/org/freedesktop/DBus",
                 "--method", "org.freedesktop.DBus.ListNames"],
                capture_output=True, text=True, timeout=3,
            )
            if result.returncode != 0:
                return None
        except (subprocess.TimeoutExpired, OSError):
            return None

        # Extract all MPRIS2 bus names
        mpris_names = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", result.stdout)
        if not mpris_names:
            return None

        # Try configured player first, then defaults — match by prefix
        prefixes = [self._player] if self._player else _DEFAULT_PLAYERS
        for prefix in prefixes:
            for name in mpris_names:
                if name == prefix or name.startswith(prefix + "."):
                    # Verify it responds
                    try:
                        check = subprocess.run(
                            ["gdbus", "call", "--session",
                             "--dest", name,
                             "--object-path", "/org/mpris/MediaPlayer2",
                             "--method", "org.freedesktop.DBus.Properties.Get",
                             "org.mpris.MediaPlayer2.Player", "PlaybackStatus"],
                            capture_output=True, text=True, timeout=3,
                        )
                        if check.returncode == 0:
                            return name
                    except (subprocess.TimeoutExpired, OSError):
                        continue

        # Fallback: try any MPRIS2 player found
        for name in mpris_names:
            try:
                check = subprocess.run(
                    ["gdbus", "call", "--session",
                     "--dest", name,
                     "--object-path", "/org/mpris/MediaPlayer2",
                     "--method", "org.freedesktop.DBus.Properties.Get",
                     "org.mpris.MediaPlayer2.Player", "PlaybackStatus"],
                    capture_output=True, text=True, timeout=3,
                )
                if check.returncode == 0:
                    return name
            except (subprocess.TimeoutExpired, OSError):
                continue

        return None

    async def _fetch_metadata(self) -> dict[str, str]:
        """Fetch track metadata from the active MPRIS2 player."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_metadata_sync)

    def _fetch_metadata_sync(self) -> dict[str, str]:
        """Blocking: get metadata via gdbus."""
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", self._active_player,
                "--object-path", "/org/mpris/MediaPlayer2",
                "--method", "org.freedesktop.DBus.Properties.Get",
                "org.mpris.MediaPlayer2.Player", "Metadata",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode != 0:
            logger.debug("gdbus metadata error: %s", result.stderr.strip())
            return {}

        return self._parse_metadata(result.stdout)

    def _dbus_play_pause(self) -> None:
        """Blocking: send PlayPause to the active player."""
        subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", self._active_player,
                "--object-path", "/org/mpris/MediaPlayer2",
                "--method", "org.mpris.MediaPlayer2.Player.PlayPause",
            ],
            capture_output=True,
            text=True,
            timeout=5,
        )

    @staticmethod
    def _parse_metadata(raw: str) -> dict[str, str]:
        """Extract title and artist from gdbus Metadata output.

        The output is a GVariant string — we extract known keys via regex.
        """
        metadata: dict[str, str] = {}

        # Title: 'xesam:title': <'Some Title'>
        title_match = re.search(r"'xesam:title':\s*<'([^']*)'", raw)
        if title_match:
            metadata["title"] = title_match.group(1)

        # Artist: 'xesam:artist': <['Artist Name']>
        artist_match = re.search(r"'xesam:artist':\s*<\['([^']*)'", raw)
        if artist_match:
            metadata["artist"] = artist_match.group(1)

        return metadata
