"""System stats plugin — shows CPU or RAM usage.

Supports a `metric` config ("cpu" or "ram") to show one metric per button.
Uses psutil if available, falls back to /proc/stat and /proc/meminfo on Linux.
"""

from __future__ import annotations

import asyncio
import logging

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)

try:
    import psutil

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

_WARN_THRESHOLD = 80
_CRITICAL_THRESHOLD = 90
_DANGER_THRESHOLD = 95


class SystemPlugin(BasePlugin):
    """Show CPU or RAM usage on Stream Deck."""

    POLL_INTERVAL = 5

    def __init__(self, config: dict):
        super().__init__(config)
        self._metric: str = config.get("metric", "cpu")
        self._warn: int = config.get("warn", _WARN_THRESHOLD)
        self._prev_idle: float = 0
        self._prev_total: float = 0

    async def run_loop(self, interval: int) -> None:
        self._running = True
        await self.setup()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in SystemPlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def poll(self) -> NotificationState:
        try:
            value = await self._fetch_metric()
        except Exception:
            logger.exception("System poll failed")
            return NotificationState(
                label=self._metric.upper(), subtitle="Error", color="#FF3B30"
            )

        label = self._metric.upper()
        subtitle = f"{value:.0f}%"

        if value >= _DANGER_THRESHOLD:
            color = "#FF3B30"
        elif value >= self._warn:
            color = "#E5A000"
        else:
            color = "#2DA160"

        urgent = value >= _CRITICAL_THRESHOLD

        return NotificationState(
            count=0,
            label=label,
            subtitle=subtitle,
            urgent=urgent,
            color=color,
        )

    async def _fetch_metric(self) -> float:
        loop = asyncio.get_event_loop()
        if self._metric == "ram":
            if _HAS_PSUTIL:
                return await loop.run_in_executor(None, lambda: psutil.virtual_memory().percent)
            return await loop.run_in_executor(None, self._ram_from_proc)
        else:
            if _HAS_PSUTIL:
                return await loop.run_in_executor(None, lambda: psutil.cpu_percent(interval=0.5))
            return await loop.run_in_executor(None, self._cpu_from_proc)

    def _cpu_from_proc(self) -> float:
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
