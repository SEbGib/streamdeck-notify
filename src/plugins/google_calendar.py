"""Google Calendar plugin — shows upcoming events.

Uses GNOME Online Accounts for authentication (no OAuth app needed).
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

CALENDAR_API = "https://www.googleapis.com/calendar/v3"


class GoogleCalendarPlugin(BasePlugin):
    """Show upcoming Google Calendar events on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._identity = config.get("identity")  # Optional email filter
        self._goa_path: str | None = None

    async def setup(self) -> None:
        from .goa import find_google_account
        self._goa_path = find_google_account(self._identity)
        if self._goa_path:
            logger.info("Calendar: using GOA account %s", self._goa_path)
        else:
            logger.warning("Calendar: no GOA Google account found")

    async def poll(self) -> NotificationState:
        if not self._goa_path:
            return NotificationState(label="Agenda", subtitle="No auth", color="#4285F4")

        loop = asyncio.get_event_loop()
        try:
            events = await loop.run_in_executor(None, self._fetch_events)
        except Exception:
            logger.exception("Calendar fetch failed")
            return NotificationState(label="Agenda", subtitle="Erreur", color="#4285F4")

        # Filter out all-day events (Domicile, Travail, etc.)
        timed = [e for e in events if "dateTime" in e.get("start", {})]

        if not timed:
            return NotificationState(
                count=0, label="Agenda", subtitle="Rien", color="#4285F4",
            )

        next_event = timed[0]
        start = next_event["start"]["dateTime"]
        summary = next_event.get("summary", "Sans titre")[:18]

        minutes_until = _minutes_until(start)
        if minutes_until is not None and minutes_until <= 5:
            subtitle = "MAINTENANT"
            urgent = True
        elif minutes_until is not None and minutes_until <= 15:
            subtitle = f"Dans {minutes_until}min"
            urgent = True
        elif minutes_until is not None:
            subtitle = f"Dans {minutes_until}min"
            urgent = False
        else:
            subtitle = summary
            urgent = False

        return NotificationState(
            count=len(timed),
            label=summary,
            subtitle=subtitle,
            urgent=urgent,
            color="#4285F4",
        )

    def _fetch_events(self) -> list[dict]:
        from .goa import get_access_token
        if not self._goa_path:
            return []
        token = get_access_token(self._goa_path)
        if not token:
            return []

        now = datetime.now(timezone.utc)
        lookahead = self.config.get("lookahead_minutes", 60)
        time_max = now + timedelta(minutes=lookahead)

        params = urllib.parse.urlencode({
            "timeMin": now.isoformat(),
            "timeMax": time_max.isoformat(),
            "maxResults": 5,
            "singleEvents": "true",
            "orderBy": "startTime",
        })
        url = f"{CALENDAR_API}/calendars/primary/events?{params}"

        req = urllib.request.Request(url)
        req.add_header("Authorization", f"Bearer {token}")
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())

        return data.get("items", [])


def _minutes_until(iso_str: str) -> int | None:
    """Parse ISO datetime and return minutes from now."""
    try:
        dt = datetime.fromisoformat(iso_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        delta = dt - datetime.now(timezone.utc)
        return max(0, int(delta.total_seconds() / 60))
    except (ValueError, TypeError):
        return None
