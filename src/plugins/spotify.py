"""Media player plugin — shows now playing via D-Bus MPRIS2.

Uses gdbus subprocess to communicate with MPRIS2-compatible players
(Spotify, Chromium, Firefox, etc.).
Detects media source (Spotify, Deezer, YouTube, etc.) for dynamic icons.
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

# Source detection: bus name prefix → source key
_BUS_SOURCE_MAP = {
    "org.mpris.MediaPlayer2.spotify": "spotify",
    "org.mpris.MediaPlayer2.vlc": "vlc",
}

# Source detection: patterns in trackid/artUrl → source key
_TRACKID_PATTERNS = [
    ("deezer", "deezer"),
    ("youtube", "youtube"),
    ("soundcloud", "soundcloud"),
]

# Source → display color
_SOURCE_COLORS = {
    "spotify": "#1DB954",
    "deezer": "#A238FF",
    "youtube": "#FF0000",
    "vlc": "#FF8800",
    "soundcloud": "#FF5500",
    "unknown": "#FFFFFF",
}


class SpotifyPlugin(BasePlugin):
    """Show now playing track on Stream Deck via MPRIS2 D-Bus."""

    POLL_INTERVAL = 5

    def __init__(self, config: dict):
        super().__init__(config)
        self._player: str | None = config.get("player")
        self._active_player: str | None = None
        self._media_source: str = "unknown"

    async def run_loop(self, interval: int) -> None:
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
        self._active_player = await self._detect_player()

        if not self._active_player:
            return NotificationState(
                label="No player", subtitle="", color="#1DB954",
                extra={"media_source": "unknown"},
            )

        try:
            metadata = await self._fetch_metadata()
        except Exception:
            logger.exception("MPRIS poll failed")
            self._active_player = None
            return NotificationState(
                label="No player", subtitle="", color="#1DB954",
                extra={"media_source": "unknown"},
            )

        title = metadata.get("title", "")
        artist = metadata.get("artist", "")
        source = self._detect_source(metadata)
        self._media_source = source
        color = _SOURCE_COLORS.get(source, "#FFFFFF")

        if not title:
            return NotificationState(
                label="Paused", subtitle="", color=color,
                extra={"media_source": source},
            )

        label = title[:_MAX_LABEL_LEN] + ("…" if len(title) > _MAX_LABEL_LEN else "")
        subtitle = artist[:_MAX_LABEL_LEN] + ("…" if len(artist) > _MAX_LABEL_LEN else "")

        return NotificationState(
            count=0,
            label=label,
            subtitle=subtitle,
            urgent=False,
            color=color,
            extra={"media_source": source},
        )

    def _detect_source(self, metadata: dict[str, str]) -> str:
        """Detect the media source from bus name and metadata.

        Strategy:
        1. Native app bus names (spotify, vlc) → direct match
        2. Browser: check metadata fields for clues
           - Deezer: always provides xesam:album
           - YouTube: album is empty, title often has " - " artist separator
        3. Fallback: "browser"
        """
        player = self._active_player or ""

        # Direct match from bus name (native apps)
        for prefix, source in _BUS_SOURCE_MAP.items():
            if player == prefix or player.startswith(prefix + "."):
                return source

        # Browser-based detection
        if "chromium" not in player and "firefox" not in player:
            return "unknown"

        album = metadata.get("album", "")
        trackid = metadata.get("trackid", "").lower()
        art_url = metadata.get("art_url", "").lower()

        # Check explicit patterns in trackid/artUrl
        for pattern, source in _TRACKID_PATTERNS:
            if pattern in trackid or pattern in art_url:
                return source

        # Deezer heuristic: always provides album metadata
        if album:
            return "deezer"

        # YouTube heuristic: no album, browser-based
        return "youtube"

    async def on_press(self) -> None:
        if not self._active_player:
            return
        loop = asyncio.get_event_loop()
        try:
            await loop.run_in_executor(None, self._dbus_play_pause)
        except Exception:
            logger.exception("MPRIS PlayPause failed")

    async def _detect_player(self) -> str | None:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._detect_player_sync)

    def _detect_player_sync(self) -> str | None:
        """Blocking: find an active MPRIS2 player on the session bus."""
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

        mpris_names = re.findall(r"'(org\.mpris\.MediaPlayer2\.[^']+)'", result.stdout)
        if not mpris_names:
            return None

        prefixes = [self._player] if self._player else _DEFAULT_PLAYERS
        for prefix in prefixes:
            for name in mpris_names:
                if name == prefix or name.startswith(prefix + "."):
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
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._fetch_metadata_sync)

    def _fetch_metadata_sync(self) -> dict[str, str]:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", self._active_player,
                "--object-path", "/org/mpris/MediaPlayer2",
                "--method", "org.freedesktop.DBus.Properties.Get",
                "org.mpris.MediaPlayer2.Player", "Metadata",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.debug("gdbus metadata error: %s", result.stderr.strip())
            return {}

        return self._parse_metadata(result.stdout)

    def _dbus_play_pause(self) -> None:
        subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", self._active_player,
                "--object-path", "/org/mpris/MediaPlayer2",
                "--method", "org.mpris.MediaPlayer2.Player.PlayPause",
            ],
            capture_output=True, text=True, timeout=5,
        )

    @staticmethod
    def _parse_metadata(raw: str) -> dict[str, str]:
        """Extract title, artist, trackid, and artUrl from gdbus output."""
        metadata: dict[str, str] = {}

        title_match = re.search(r"'xesam:title':\s*<'([^']*)'", raw)
        if title_match:
            metadata["title"] = title_match.group(1)

        artist_match = re.search(r"'xesam:artist':\s*<\['([^']*)'", raw)
        if artist_match:
            metadata["artist"] = artist_match.group(1)

        album_match = re.search(r"'xesam:album':\s*<'([^']*)'", raw)
        if album_match:
            metadata["album"] = album_match.group(1)

        trackid_match = re.search(r"'mpris:trackid':\s*<objectpath\s+'([^']*)'", raw)
        if trackid_match:
            metadata["trackid"] = trackid_match.group(1)

        art_match = re.search(r"'mpris:artUrl':\s*<'([^']*)'", raw)
        if art_match:
            metadata["art_url"] = art_match.group(1)

        return metadata
