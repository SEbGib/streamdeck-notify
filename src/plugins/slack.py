"""Slack notification plugin.

Supports two methods:
- "dbus": Monitor desktop notifications from Slack app (no API token needed)
- "api": Use Slack Web API (needs bot/user token with appropriate scopes)
"""

from __future__ import annotations

import asyncio
import logging
import re

from .base import BasePlugin, NotificationState

logger = logging.getLogger(__name__)


class SlackPlugin(BasePlugin):
    """Slack notifications via D-Bus monitoring or API."""

    def __init__(self, config: dict):
        super().__init__(config)
        self.method = config.get("method", "dbus")
        self._dbus_count = 0
        self._dbus_last_summary = ""
        self._monitor_task: asyncio.Task | None = None

    async def setup(self) -> None:
        if self.method == "dbus":
            self._monitor_task = asyncio.create_task(self._monitor_dbus())
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

            # Subscribe to org.freedesktop.Notifications
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
                    app_name = msg.body[0] if len(msg.body) > 0 else ""
                    if "slack" in app_name.lower():
                        summary = msg.body[3] if len(msg.body) > 3 else ""
                        self._dbus_count += 1
                        self._dbus_last_summary = str(summary)
                        logger.debug("Slack notification: %s", summary)

            bus.add_message_handler(on_message)
            # Keep listening
            await asyncio.get_event_loop().create_future()

        except ImportError:
            logger.error("dbus-next not installed, Slack D-Bus monitoring unavailable")
        except Exception:
            logger.exception("D-Bus monitoring failed")

    def _state_from_dbus(self) -> NotificationState:
        count = self._dbus_count
        return NotificationState(
            count=count,
            label="Slack",
            subtitle=self._dbus_last_summary[:20] if self._dbus_last_summary else "",
            urgent=count > 0,
            color="#4A154B",
        )

    def reset_count(self) -> None:
        """Reset notification count (e.g., after pressing the button)."""
        self._dbus_count = 0
        self._dbus_last_summary = ""

    async def on_press(self) -> None:
        self.reset_count()

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
                # Get conversations with unread
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
            subtitle=f"{'@mention' if has_mention else ''}",
            urgent=has_mention,
            color="#4A154B",
        )
