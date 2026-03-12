"""System stats plugin — shows CPU and RAM usage.

Uses psutil if available, falls back to /proc/stat and /proc/meminfo on Linux.
"""

from __future__ import annotations

import asyncio
import logging
import time

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

# Thresholds
_WARN_THRESHOLD = 80
_CRITICAL_THRESHOLD = 90
_DANGER_THRESHOLD = 95


class SystemPlugin(BasePlugin):
    """Show CPU and RAM usage on Stream Deck."""

    def __init__(self, config: dict):
        super().__init__(config)
        self._prev_idle: float = 0
        self._prev_total: float = 0

    async def poll(self) -> NotificationState:
        try:
            cpu, ram = await self._fetch_stats()
        except Exception:
            logger.exception("System poll failed")
            return NotificationState(
                label="Système", subtitle="Error", color="#FF3B30"
            )

        subtitle = f"CPU {cpu:.0f}% RAM {ram:.0f}%"
        peak = max(cpu, ram)

        if peak >= _DANGER_THRESHOLD:
            color = "#FF3B30"
        elif peak >= _WARN_THRESHOLD:
            color = "#E5A000"
        else:
            color = "#2DA160"

        urgent = cpu >= _CRITICAL_THRESHOLD or ram >= _CRITICAL_THRESHOLD

        return NotificationState(
            count=0,
            label="Système",
            subtitle=subtitle,
            urgent=urgent,
            color=color,
        )

    async def _fetch_stats(self) -> tuple[float, float]:
        """Return (cpu_percent, ram_percent)."""
        loop = asyncio.get_event_loop()
        if _HAS_PSUTIL:
            return await loop.run_in_executor(None, self._stats_psutil)
        return await loop.run_in_executor(None, self._stats_proc)

    @staticmethod
    def _stats_psutil() -> tuple[float, float]:
        """Get stats via psutil."""
        cpu = psutil.cpu_percent(interval=0.5)
        ram = psutil.virtual_memory().percent
        return cpu, ram

    def _stats_proc(self) -> tuple[float, float]:
        """Get stats from /proc (Linux fallback)."""
        cpu = self._cpu_from_proc()
        ram = self._ram_from_proc()
        return cpu, ram

    def _cpu_from_proc(self) -> float:
        """Calculate CPU usage from /proc/stat delta."""
        try:
            with open("/proc/stat") as f:
                line = f.readline()
        except OSError:
            return 0.0

        parts = line.split()
        if len(parts) < 5:
            return 0.0

        values = [int(v) for v in parts[1:]]
        idle = values[3]
        total = sum(values)

        diff_idle = idle - self._prev_idle
        diff_total = total - self._prev_total

        self._prev_idle = idle
        self._prev_total = total

        if diff_total == 0:
            return 0.0
        return (1.0 - diff_idle / diff_total) * 100.0

    @staticmethod
    def _ram_from_proc() -> float:
        """Calculate RAM usage from /proc/meminfo."""
        meminfo: dict[str, int] = {}
        try:
            with open("/proc/meminfo") as f:
                for line in f:
                    parts = line.split()
                    if len(parts) >= 2:
                        key = parts[0].rstrip(":")
                        meminfo[key] = int(parts[1])
        except OSError:
            return 0.0

        total = meminfo.get("MemTotal", 0)
        available = meminfo.get("MemAvailable", 0)

        if total == 0:
            return 0.0
        return ((total - available) / total) * 100.0
