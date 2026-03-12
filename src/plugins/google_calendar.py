"""Google Calendar plugin — shows upcoming events."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class GoogleCalendarPlugin(BasePlugin):
    """Show upcoming Google Calendar events on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._service = None

    async def setup(self) -> None:
        self._service = _build_service(self.config)

    async def poll(self) -> NotificationState:
        if not self._service:
            return NotificationState(label="Agenda", subtitle="No auth", color="#4285F4")

        import asyncio

        loop = asyncio.get_event_loop()
        events = await loop.run_in_executor(None, self._fetch_events)

        if not events:
            return NotificationState(
                count=0,
                label="Agenda",
                subtitle="Rien",
                color="#4285F4",
            )

        next_event = events[0]
        start = next_event["start"].get("dateTime", next_event["start"].get("date", ""))
        summary = next_event.get("summary", "Sans titre")[:18]

        minutes_until = _minutes_until(start)
        if minutes_until is not None and minutes_until <= 5:
            subtitle = f"MAINTENANT"
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
            count=len(events),
            label=summary,
            subtitle=subtitle,
            urgent=urgent,
            color="#4285F4",
        )

    def _fetch_events(self) -> list[dict]:
        now = datetime.now(timezone.utc)
        lookahead = self.config.get("lookahead_minutes", 60)
        time_max = now + timedelta(minutes=lookahead)

        result = (
            self._service.events()
            .list(
                calendarId="primary",
                timeMin=now.isoformat(),
                timeMax=time_max.isoformat(),
                maxResults=5,
                singleEvents=True,
                orderBy="startTime",
            )
            .execute()
        )
        return result.get("items", [])


def _build_service(config: dict):
    """Build Google Calendar API service with OAuth."""
    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
        from googleapiclient.discovery import build
    except ImportError:
        logger.error("Google API dependencies not installed")
        return None

    creds_file = Path(config.get("credentials_file", "")).expanduser()
    token_file = Path(config.get("token_file", "")).expanduser()
    scopes = [
        "https://www.googleapis.com/auth/calendar.readonly",
        "https://www.googleapis.com/auth/gmail.readonly",
    ]

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        elif creds_file.exists():
            flow = InstalledAppFlow.from_client_secrets_file(str(creds_file), scopes)
            creds = flow.run_local_server(port=0)
        else:
            logger.warning("No Google credentials file at %s", creds_file)
            return None

        token_file.parent.mkdir(parents=True, exist_ok=True)
        token_file.write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


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
