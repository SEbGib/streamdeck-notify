"""Docker status plugin — shows running/stopped container counts.

Uses `docker ps` CLI subprocess.
"""

from __future__ import annotations

import asyncio
import json
import logging
import subprocess

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class DockerStatusPlugin(BasePlugin):
    """Show Docker container status on Stream Deck."""

    async def poll(self) -> NotificationState:
        try:
            running, stopped, unhealthy = await self._fetch_status()
        except Exception:
            logger.exception("Docker poll failed")
            return NotificationState(label="Docker", subtitle="Error", color="#FF3B30")

        total_up = len(running)
        total_down = len(stopped)
        has_unhealthy = len(unhealthy) > 0

        subtitle = f"{total_up} up"
        if total_down:
            subtitle += f" / {total_down} down"

        if total_down or has_unhealthy:
            color = "#FF3B30"
            urgent = True
        elif total_up == 0:
            color = "#8E8E93"
            urgent = False
            subtitle = "No containers"
        else:
            color = "#2DA160"
            urgent = False

        return NotificationState(
            count=total_down,
            label="Docker",
            subtitle=subtitle,
            urgent=urgent,
            color=color,
        )

    async def _fetch_status(self) -> tuple[list[dict], list[dict], list[dict]]:
        """Return (running, stopped, unhealthy) container lists."""
        loop = asyncio.get_event_loop()

        # Get all containers (running + stopped)
        all_result = await loop.run_in_executor(
            None,
            lambda: subprocess.run(
                ["docker", "ps", "-a", "--format", "{{json .}}"],
                capture_output=True,
                text=True,
                timeout=10,
            ),
        )
        if all_result.returncode != 0:
            logger.error("docker ps error: %s", all_result.stderr.strip())
            raise RuntimeError("docker ps failed")

        containers: list[dict] = []
        for line in all_result.stdout.strip().splitlines():
            if line.strip():
                try:
                    containers.append(json.loads(line))
                except json.JSONDecodeError:
                    continue

        running = [c for c in containers if c.get("State") == "running"]
        stopped = [c for c in containers if c.get("State") in ("exited", "dead")]
        unhealthy = [c for c in containers if "(unhealthy)" in c.get("Status", "")]

        return running, stopped, unhealthy
