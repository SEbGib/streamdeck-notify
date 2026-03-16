"""GitLab CI/CD plugin — shows pipeline status across projects.

Uses `glab api` CLI to avoid token management issues (OAuth keyring).
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

# Pipeline status → category mapping
_FAILED_STATUSES = {"failed", "canceled"}
_RUNNING_STATUSES = {"running", "pending", "waiting_for_resource", "preparing"}
_SUCCESS_STATUSES = {"success", "manual", "skipped"}


class CICDPlugin(BasePlugin):
    """Show GitLab CI/CD pipeline status on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._host: str = config.get("host", "gitlab.com")

    async def poll(self) -> NotificationState:
        try:
            pipelines = await self._fetch_pipelines()
        except Exception:
            logger.exception("CI/CD poll failed")
            return NotificationState(label="CI/CD", subtitle="Error", color="#FC6D26")

        failed = [p for p in pipelines if p.get("status") in _FAILED_STATUSES]
        running = [p for p in pipelines if p.get("status") in _RUNNING_STATUSES]

        failed_count = len(failed)
        running_count = len(running)

        if failed_count:
            subtitle = f"{failed_count} failed"
            color = "#FC6D26"
            urgent = True
        elif running_count:
            subtitle = f"{running_count} running"
            color = "#E5A000"
            urgent = False
        else:
            subtitle = "All green"
            color = "#2DA160"
            urgent = False

        return NotificationState(
            count=failed_count,
            label="CI/CD",
            subtitle=subtitle,
            urgent=urgent,
            color=color,
        )

    async def on_press(self) -> None:
        self.state = NotificationState(label="CI/CD", subtitle="...", color="#FFFFFF")

    async def _fetch_pipelines(self) -> list[dict]:
        """Get recent pipelines from all membership projects."""
        projects = await self._glab_api(
            "/projects?membership=true&per_page=20&order_by=last_activity_at"
        )
        if not isinstance(projects, list):
            return []

        # Fetch latest pipeline per project in parallel
        tasks = []
        for proj in projects:
            pid = proj.get("id")
            if pid is None:
                continue
            tasks.append(
                self._glab_api(
                    f"/projects/{pid}/pipelines?per_page=1&order_by=updated_at"
                )
            )

        results = await asyncio.gather(*tasks, return_exceptions=True)
        pipelines: list[dict] = []
        for result in results:
            if isinstance(result, Exception):
                continue
            if isinstance(result, list):
                pipelines.extend(result)
        return pipelines

    async def _glab_api(self, endpoint: str) -> list | dict:
        """Call GitLab API via glab CLI."""
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["glab", "api", endpoint],
                capture_output=True,
                text=True,
                timeout=15,
            ),
        )
        if result.returncode != 0:
            logger.error("glab api error: %s", result.stderr.strip())
            return []
        return json.loads(result.stdout)
