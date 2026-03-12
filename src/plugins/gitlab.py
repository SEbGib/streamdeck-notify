"""GitLab plugin — shows MRs to review and pipeline status.

Uses `glab api` CLI to avoid token management issues (OAuth keyring).
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class GitLabPlugin(BasePlugin):
    """Show GitLab MRs and notifications on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._host: str = config.get("host", "gitlab.com")
        self._username: str | None = None

    async def setup(self) -> None:
        self._username = await self._glab_get_username()
        if self._username:
            logger.info("GitLab: logged in as %s", self._username)
        else:
            logger.warning("GitLab: could not get username via glab")

    async def poll(self) -> NotificationState:
        if not self._username:
            return NotificationState(label="GitLab", subtitle="No auth", color="#FC6D26")

        try:
            # Get MRs assigned for review
            mrs_data = await self._glab_api(
                f"/merge_requests?state=opened&reviewer_username={self._username}"
                "&scope=all&per_page=20"
            )
            mr_count = len(mrs_data) if isinstance(mrs_data, list) else 0

            # Get pending TODOs
            todos_data = await self._glab_api("/todos?state=pending&per_page=100")
            todo_count = len(todos_data) if isinstance(todos_data, list) else 0

        except Exception:
            logger.exception("GitLab poll failed")
            return NotificationState(label="GitLab", subtitle="Error", color="#FC6D26")

        total = mr_count + todo_count

        if mr_count:
            subtitle = f"{mr_count} MR{'s' if mr_count > 1 else ''}"
        elif todo_count:
            subtitle = f"{todo_count} todo{'s' if todo_count > 1 else ''}"
        else:
            subtitle = "OK"

        return NotificationState(
            count=total,
            label="GitLab",
            subtitle=subtitle,
            urgent=mr_count > 0,
            color="#FC6D26",
        )

    async def _glab_api(self, endpoint: str) -> list | dict:
        """Call GitLab API via glab CLI (handles OAuth token from keyring)."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["glab", "api", endpoint],
                capture_output=True,
                text=True,
                timeout=10,
            ),
        )
        if result.returncode != 0:
            logger.error("glab api error: %s", result.stderr.strip())
            return []
        return json.loads(result.stdout)

    async def _glab_get_username(self) -> str | None:
        """Get current GitLab username via glab."""
        try:
            data = await self._glab_api("/user")
            if isinstance(data, dict):
                return data.get("username", "")
        except Exception:
            logger.exception("Failed to get GitLab username")
        return None
