"""Slack notification plugin.

Supports two methods:
- "dbus": Monitor desktop notifications from Slack app (no API token needed)
- "api": Use Slack Web API (needs bot/user token with appropriate scopes)

D-Bus mode also tracks notification channels and provides message previews.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class SlackPlugin(BasePlugin):
    """Slack notifications via D-Bus monitoring or API."""

    # DND-active color (muted purple)
    COLOR_DEFAULT = "#4A154B"
    COLOR_DND = "#8B7A8E"

    def __init__(self, config: dict):
        super().__init__(config)
        self.method = config.get("method", "dbus")
        self._dbus_count = 0
        self._dbus_last_summary = ""
        self._dbus_last_channel = ""
        self._dbus_messages: deque[dict] = deque(maxlen=20)
        self._monitor_task: asyncio.Task | None = None
        self._last_activity: float = 0
        # Per-channel notification counts
        self._channels: dict[str, int] = {}
        # DND mode — when active, new notifications are ignored
        self._dnd_active: bool = False

    async def setup(self) -> None:
        if self.method == "dbus":
            self._monitor_task = asyncio.create_task(self._monitor_dbus())
            logger.info("Slack: D-Bus monitoring started")
        elif self.method == "api":
            token = self.config.get("token", "")
            if not token:
                logger.warning("Slack API token not configured, plugin disabled")

    async def teardown(self) -> None:
        if self._monitor_task:
            self._monitor_task.cancel()

    async def poll(self) -> NotificationState:
        if self.method == "dbus":
            return self._state_from_dbus()
        return await self._poll_api()

    # --- D-Bus method (no token needed) ---

    async def _monitor_dbus(self) -> None:
        """Listen for Slack desktop notifications via D-Bus."""
        try:
            from dbus_next.aio import MessageBus
            from dbus_next import MessageType, Message

            bus = await MessageBus().connect()

            reply = await bus.call(
                Message(
                    destination="org.freedesktop.DBus",
                    path="/org/freedesktop/DBus",
                    interface="org.freedesktop.DBus",
                    member="AddMatch",
                    signature="s",
                    body=[
                        "type='method_call',"
                        "interface='org.freedesktop.Notifications',"
                        "member='Notify',"
                        "eavesdrop='true'"
                    ],
                )
            )

            def on_message(msg: Message) -> None:
                if (
                    msg.message_type == MessageType.METHOD_CALL
                    and msg.member == "Notify"
                    and msg.body
                ):
                    app_name = str(msg.body[0]) if len(msg.body) > 0 else ""
                    summary = str(msg.body[3]) if len(msg.body) > 3 else ""
                    body = str(msg.body[4]) if len(msg.body) > 4 else ""
                    app_lower = app_name.lower()

                    # Match Slack app directly, or browser notifications about Slack
                    is_slack = (
                        "slack" in app_lower
                        or (
                            app_lower in ("google chrome", "chrome", "chromium", "firefox")
                            and "slack" in summary.lower()
                        )
                    )
                    if not is_slack:
                        return

                    # In DND mode, silently ignore new notifications
                    if self._dnd_active:
                        logger.debug("Slack DND active, ignoring: %s", summary[:30])
                        return

                    self._dbus_count += 1
                    # Strip HTML tags from browser notifications
                    summary = _strip_html(summary)
                    body = _strip_html(body)
                    # Extract actual message from Chrome body (format: "url\n\nmessage")
                    body = _extract_chrome_body(body)
                    self._dbus_last_summary = summary
                    # Channel: use summary (e.g. "Nouveau message de X")
                    channel = summary[:30].strip() if summary else "Slack"
                    self._dbus_last_channel = channel
                    if channel:
                        self._channels[channel] = self._channels.get(channel, 0) + 1
                    self._last_activity = time.time()
                    self._dbus_messages.append({
                        "summary": summary,
                        "body": body[:100],
                        "time": time.time(),
                        "channel": channel,
                    })
                    logger.info("Slack notification [%s]: %s - %s", app_name, summary, body[:50])

            bus.add_message_handler(on_message)
            await asyncio.get_event_loop().create_future()

        except ImportError:
            logger.error("dbus-next not installed, Slack D-Bus monitoring unavailable")
        except Exception:
            logger.exception("D-Bus monitoring failed")

    def _state_from_dbus(self) -> NotificationState:
        count = self._dbus_count

        # DND mode overrides everything
        if self._dnd_active:
            return NotificationState(
                count=count,
                label="Slack",
                subtitle="DND",
                urgent=False,
                color=self.COLOR_DND,
                extra={"dnd": True, "channels": dict(self._channels)},
            )

        # Build batched summary as label suffix
        num_channels = len(self._channels)
        if num_channels == 1:
            chan_name, chan_count = next(iter(self._channels.items()))
            label = f"{chan_name} ({chan_count})"
        elif num_channels > 1:
            label = f"{num_channels} canaux"
        else:
            label = "Slack"

        # Subtitle: latest message preview
        if self._dbus_last_summary:
            subtitle = self._dbus_last_summary[:25]
        else:
            subtitle = ""

        # Determine urgency: new messages in last 5 minutes
        recent = time.time() - self._last_activity < 300 if self._last_activity else False

        return NotificationState(
            count=count,
            label=label,
            subtitle=subtitle,
            urgent=count > 0 and recent,
            color=self.COLOR_DEFAULT,
            extra={
                "messages": list(self._dbus_messages),
                "last_channel": self._dbus_last_channel,
                "channels": dict(self._channels),
                "dnd": False,
            },
        )

    def reset_count(self) -> None:
        """Reset notification count and all channel tracking."""
        self._dbus_count = 0
        self._dbus_last_summary = ""
        self._dbus_last_channel = ""
        self._dbus_messages.clear()
        self._channels.clear()

    async def on_press(self) -> None:
        """Smart press: reset count > toggle DND on > toggle DND off."""
        if self._dbus_count > 0:
            # Has unread notifications — clear them
            self.reset_count()
        elif not self._dnd_active:
            # No notifications, DND off — enable DND
            self._dnd_active = True
            logger.info("Slack DND enabled")
        else:
            # DND active — disable it
            self._dnd_active = False
            logger.info("Slack DND disabled")

    # --- API method ---

    async def _poll_api(self) -> NotificationState:
        """Poll Slack API for unread messages."""
        import aiohttp

        token = self.config.get("token", "")
        if not token:
            return NotificationState(label="Slack", subtitle="No token", color="#4A154B")

        headers = {"Authorization": f"Bearer {token}"}
        total_unread = 0
        has_mention = False

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    "https://slack.com/api/conversations.list",
                    headers=headers,
                    params={"types": "public_channel,private_channel,im,mpim"},
                ) as resp:
                    data = await resp.json()
                    if not data.get("ok"):
                        logger.error("Slack API error: %s", data.get("error"))
                        return NotificationState(
                            label="Slack", subtitle="API error", color="#4A154B"
                        )

                    channels = self.config.get("channels")
                    for ch in data.get("channels", []):
                        if channels and ch.get("name") not in channels:
                            continue
                        unread = ch.get("unread_count_display", 0)
                        if unread:
                            total_unread += unread
                        if ch.get("mention_count", 0) > 0:
                            has_mention = True

        except Exception:
            logger.exception("Slack API poll failed")

        return NotificationState(
            count=total_unread,
            label="Slack",
            subtitle="@mention" if has_mention else "",
            urgent=has_mention,
            color="#4A154B",
        )


def _strip_html(text: str) -> str:
    """Remove HTML tags and decode entities from browser notification text."""
    if not text:
        return text
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&nbsp;", " ").replace("&#39;", "'").replace("&quot;", '"')
    return text.strip()


def _extract_chrome_body(body: str) -> str:
    """Extract actual message from Chrome notification body.

    Chrome sends: 'app.slack.com\\n\\nActual message here'
    """
    if not body:
        return body
    # Split on double newline, take the last non-empty part
    parts = body.split("\n\n")
    for part in reversed(parts):
        cleaned = part.strip()
        if cleaned and not cleaned.startswith(("http", "app.slack")):
            return cleaned
    return body.strip()
