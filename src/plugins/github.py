"""GitHub plugin — shows notifications and PRs to review."""

from __future__ import annotations

import asyncio
import logging
import subprocess

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class GitHubPlugin(BasePlugin):
    """Show GitHub notifications on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._token: str | None = None

    async def setup(self) -> None:
        self._token = await self._get_token()

    async def poll(self) -> NotificationState:
        if not self._token:
            return NotificationState(label="GitHub", subtitle="No auth", color="#FFFFFF")

        import aiohttp

        headers = {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

        try:
            async with aiohttp.ClientSession() as session:
                # Unread notifications
                async with session.get(
                    "https://api.github.com/notifications",
                    headers=headers,
                    params={"all": "false", "per_page": "50"},
                ) as resp:
                    if resp.status != 200:
                        logger.error("GitHub API %s", resp.status)
                        return NotificationState(
                            label="GitHub", subtitle="API error", color="#FFFFFF"
                        )
                    notifications = await resp.json()

                # Review requests
                async with session.get(
                    "https://api.github.com/search/issues",
                    headers=headers,
                    params={"q": "is:open is:pr review-requested:@me"},
                ) as resp:
                    pr_data = await resp.json()
                    pr_count = pr_data.get("total_count", 0)

        except Exception:
            logger.exception("GitHub poll failed")
            return NotificationState(label="GitHub", subtitle="Error", color="#FFFFFF")

        notif_count = len(notifications)
        total = notif_count + pr_count

        parts = []
        if pr_count:
            parts.append(f"{pr_count} PR{'s' if pr_count > 1 else ''}")
        if notif_count:
            parts.append(f"{notif_count} notif{'s' if notif_count > 1 else ''}")

        return NotificationState(
            count=total,
            label="GitHub",
            subtitle=" · ".join(parts) if parts else "OK",
            urgent=pr_count > 0,
            color="#FFFFFF",
        )

    async def _get_token(self) -> str | None:
        """Extract token from gh CLI."""
        loop = asyncio.get_event_loop()
        try:
            result = await loop.run_in_executor(
                None,
                lambda: subprocess.run(
                    ["gh", "auth", "token"],
                    capture_output=True,
                    text=True,
                ),
            )
            token = result.stdout.strip()
            if token:
                return token
        except Exception:
            logger.exception("Failed to get gh token")
        return None
