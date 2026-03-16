"""Gmail plugin — shows unread email count.

Uses GNOME Online Accounts for authentication via IMAP + XOAUTH2.
The Gmail REST API requires explicit project activation, but IMAP works
with any GOA token out of the box.
"""

from __future__ import annotations

import asyncio
import imaplib
import logging

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class GmailPlugin(BasePlugin):
    """Show unread Gmail count on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._identity = config.get("identity")
        self._goa_path: str | None = None
        self._email: str | None = None

    async def setup(self) -> None:
        from .goa import find_google_account
        self._goa_path = find_google_account(self._identity)
        if self._goa_path:
            logger.info("Gmail: using GOA account %s", self._goa_path)
            # Resolve email for IMAP auth
            self._email = self._identity or self._resolve_email()
        else:
            logger.warning("Gmail: no GOA Google account found")

    def _resolve_email(self) -> str | None:
        """Extract email from GOA account properties."""
        import subprocess
        if not self._goa_path:
            return None
        try:
            result = subprocess.run(
                [
                    "gdbus", "call", "--session",
                    "--dest", "org.gnome.OnlineAccounts",
                    "--object-path", self._goa_path,
                    "--method", "org.freedesktop.DBus.Properties.Get",
                    "org.gnome.OnlineAccounts.Account", "Identity",
                ],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                # Output: (<'email@example.com'>,)
                email = result.stdout.strip().split("'")[1]
                return email
        except Exception:
            logger.exception("Failed to resolve GOA email")
        return None

    async def poll(self) -> NotificationState:
        if not self._goa_path or not self._email:
            return NotificationState(label="Gmail", subtitle="No auth", color="#EA4335")

        loop = asyncio.get_event_loop()
        try:
            unread = await loop.run_in_executor(None, self._fetch_unread_imap)
        except Exception:
            logger.exception("Gmail fetch failed")
            return NotificationState(label="Gmail", subtitle="Erreur", color="#EA4335")

        return NotificationState(
            count=unread,
            label="Gmail",
            subtitle=f"{unread} non lu{'s' if unread > 1 else ''}" if unread else "Inbox zero",
            urgent=unread > 5,
            color="#EA4335",
        )

    def _fetch_unread_imap(self) -> int:
        """Get unread message count via IMAP with XOAUTH2."""
        from .goa import get_access_token
        if not self._goa_path or not self._email:
            return 0
        token = get_access_token(self._goa_path)
        if not token:
            return 0

        auth_string = f"user={self._email}\x01auth=Bearer {token}\x01\x01"

        imap = imaplib.IMAP4_SSL("imap.gmail.com")
        try:
            imap.authenticate("XOAUTH2", lambda _: auth_string.encode())
            imap.select("INBOX", readonly=True)
            typ, data = imap.search(None, "UNSEEN")
            return len(data[0].split()) if data[0] else 0
        finally:
            try:
                imap.logout()
            except Exception:
                pass
