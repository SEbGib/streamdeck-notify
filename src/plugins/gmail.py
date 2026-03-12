"""Gmail plugin — shows unread email count."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class GmailPlugin(BasePlugin):
    """Show unread Gmail count on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._service = None

    async def setup(self) -> None:
        self._service = _build_gmail_service(self.config)

    async def poll(self) -> NotificationState:
        if not self._service:
            return NotificationState(label="Gmail", subtitle="No auth", color="#EA4335")

        loop = asyncio.get_event_loop()
        unread = await loop.run_in_executor(None, self._fetch_unread)

        return NotificationState(
            count=unread,
            label="Gmail",
            subtitle=f"{unread} non lu{'s' if unread > 1 else ''}" if unread else "Inbox zero",
            urgent=unread > 5,
            color="#EA4335",
        )

    def _fetch_unread(self) -> int:
        """Get unread message count from Gmail."""
        try:
            labels = self.config.get("labels", ["INBOX"])
            total = 0
            for label_name in labels:
                result = (
                    self._service.users()
                    .labels()
                    .get(userId="me", id=label_name)
                    .execute()
                )
                total += result.get("messagesUnread", 0)
            return total
        except Exception:
            logger.exception("Gmail fetch failed")
            return 0


def _build_gmail_service(config: dict):
    """Build Gmail API service, reusing Calendar OAuth token."""
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

    return build("gmail", "v1", credentials=creds)
