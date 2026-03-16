"""System detail plugins — disk, network, load average, uptime.

Stdlib-only (no psutil). One plugin class per metric, each registered
under its own key in PLUGIN_REGISTRY.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Disk usage
# ---------------------------------------------------------------------------

class DiskPlugin(BasePlugin):
    """Show disk usage for / partition."""

    POLL_INTERVAL = 30

    def __init__(self, config: dict):
        super().__init__(config)
        self._path: str = config.get("path", "/")
        self._warn: int = config.get("warn", 80)

    async def run_loop(self, interval: int) -> None:
        self._running = True
        await self.setup()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in DiskPlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def poll(self) -> NotificationState:
        try:
            usage = shutil.disk_usage(self._path)
            pct = usage.used / usage.total * 100
            free_gb = usage.free / (1024 ** 3)
        except Exception:
            logger.exception("Disk poll failed")
            return NotificationState(label="Disk", subtitle="Error", color="#FF3B30")

        if pct >= 95:
            color = "#FF3B30"
            urgent = True
        elif pct >= self._warn:
            color = "#E5A000"
            urgent = False
        else:
            color = "#2DA160"
            urgent = False

        return NotificationState(
            count=0,
            label="Disk",
            subtitle=f"{pct:.0f}% ({free_gb:.0f}G)",
            urgent=urgent,
            color=color,
        )


# ---------------------------------------------------------------------------
# Load average
# ---------------------------------------------------------------------------

class LoadAvgPlugin(BasePlugin):
    """Show 1-minute load average."""

    POLL_INTERVAL = 10

    def __init__(self, config: dict):
        super().__init__(config)
        self._warn: float = config.get("warn", 4.0)

    async def run_loop(self, interval: int) -> None:
        self._running = True
        await self.setup()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in LoadAvgPlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def poll(self) -> NotificationState:
        try:
            load1, load5, load15 = os.getloadavg()
        except OSError:
            logger.exception("Load avg poll failed")
            return NotificationState(label="Load", subtitle="Error", color="#FF3B30")

        if load1 >= self._warn * 1.5:
            color = "#FF3B30"
            urgent = True
        elif load1 >= self._warn:
            color = "#E5A000"
            urgent = False
        else:
            color = "#2DA160"
            urgent = False

        return NotificationState(
            count=0,
            label="Load",
            subtitle=f"{load1:.1f} / {load5:.1f}",
            urgent=urgent,
            color=color,
        )


# ---------------------------------------------------------------------------
# Uptime
# ---------------------------------------------------------------------------

class UptimePlugin(BasePlugin):
    """Show system uptime from /proc/uptime."""

    POLL_INTERVAL = 60

    async def run_loop(self, interval: int) -> None:
        self._running = True
        await self.setup()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in UptimePlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def poll(self) -> NotificationState:
        try:
            with open("/proc/uptime") as f:
                seconds = float(f.read().split()[0])
        except OSError:
            logger.exception("Uptime poll failed")
            return NotificationState(label="Uptime", subtitle="Error", color="#FF3B30")

        days = int(seconds // 86400)
        hours = int((seconds % 86400) // 3600)
        mins = int((seconds % 3600) // 60)

        if days > 0:
            subtitle = f"{days}d {hours}h"
        else:
            subtitle = f"{hours}h {mins}m"

        return NotificationState(
            count=0,
            label="Uptime",
            subtitle=subtitle,
            urgent=False,
            color="#2DA160",
        )


# ---------------------------------------------------------------------------
# Network stats (bytes sent / received delta)
# ---------------------------------------------------------------------------

def _read_net_stats() -> dict[str, tuple[int, int]]:
    """Read /proc/net/dev and return {iface: (rx_bytes, tx_bytes)}."""
    stats: dict[str, tuple[int, int]] = {}
    try:
        with open("/proc/net/dev") as f:
            for line in f:
                line = line.strip()
                if ":" not in line:
                    continue
                iface, rest = line.split(":", 1)
                iface = iface.strip()
                if iface in ("lo",):
                    continue
                fields = rest.split()
                if len(fields) < 9:
                    continue
                rx = int(fields[0])
                tx = int(fields[8])
                stats[iface] = (rx, tx)
    except OSError:
        pass
    return stats


class NetTXPlugin(BasePlugin):
    """Show network transmit rate (bytes sent/s) across all non-loopback interfaces."""

    POLL_INTERVAL = 5

    def __init__(self, config: dict):
        super().__init__(config)
        self._prev_tx: int = 0
        self._prev_ts: float = 0.0

    async def run_loop(self, interval: int) -> None:
        self._running = True
        await self.setup()
        # Initialise baseline without publishing
        stats = _read_net_stats()
        self._prev_tx = sum(tx for _, tx in stats.values())
        self._prev_ts = time.monotonic()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in NetTXPlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def poll(self) -> NotificationState:
        try:
            stats = _read_net_stats()
            now = time.monotonic()
            total_tx = sum(tx for _, tx in stats.values())
            elapsed = now - self._prev_ts if self._prev_ts else 1.0
            rate = (total_tx - self._prev_tx) / elapsed if elapsed > 0 else 0.0
            self._prev_tx = total_tx
            self._prev_ts = now
        except Exception:
            logger.exception("Net TX poll failed")
            return NotificationState(label="Net TX", subtitle="Error", color="#FF3B30")

        subtitle = _format_rate(rate)
        color = "#2DA160" if rate < 1_000_000 else "#E5A000"

        return NotificationState(
            count=0,
            label="Net TX",
            subtitle=subtitle,
            urgent=False,
            color=color,
        )


class NetRXPlugin(BasePlugin):
    """Show network receive rate (bytes received/s) across all non-loopback interfaces."""

    POLL_INTERVAL = 5

    def __init__(self, config: dict):
        super().__init__(config)
        self._prev_rx: int = 0
        self._prev_ts: float = 0.0

    async def run_loop(self, interval: int) -> None:
        self._running = True
        await self.setup()
        # Initialise baseline without publishing
        stats = _read_net_stats()
        self._prev_rx = sum(rx for rx, _ in stats.values())
        self._prev_ts = time.monotonic()
        while self._running:
            try:
                self.state = await self.poll()
            except Exception:
                logger.exception("Poll error in NetRXPlugin")
            await asyncio.sleep(self.POLL_INTERVAL)

    async def poll(self) -> NotificationState:
        try:
            stats = _read_net_stats()
            now = time.monotonic()
            total_rx = sum(rx for rx, _ in stats.values())
            elapsed = now - self._prev_ts if self._prev_ts else 1.0
            rate = (total_rx - self._prev_rx) / elapsed if elapsed > 0 else 0.0
            self._prev_rx = total_rx
            self._prev_ts = now
        except Exception:
            logger.exception("Net RX poll failed")
            return NotificationState(label="Net RX", subtitle="Error", color="#FF3B30")

        subtitle = _format_rate(rate)
        color = "#2DA160" if rate < 1_000_000 else "#E5A000"

        return NotificationState(
            count=0,
            label="Net RX",
            subtitle=subtitle,
            urgent=False,
            color=color,
        )


def _format_rate(bps: float) -> str:
    """Format bytes/s as human-readable rate."""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} MB/s"
    elif bps >= 1_000:
        return f"{bps / 1_000:.0f} kB/s"
    else:
        return f"{bps:.0f} B/s"
