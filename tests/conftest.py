"""Shared fixtures for streamdeck-notify tests."""

from __future__ import annotations

from pathlib import Path
from typing import AsyncGenerator

import pytest
import pytest_asyncio
import yaml
from aiohttp import web
from aiohttp.test_utils import TestClient, TestServer

from src.bridge import NotifyBridge
from src.plugins.base import BasePlugin, NotificationState


# ---------------------------------------------------------------------------
# Minimal config written to a temp file so NotifyBridge.__init__ can parse it
# ---------------------------------------------------------------------------

MINIMAL_CONFIG: dict = {
    "deck": {"refresh_interval": 30},
    "bridge": {"port": 9120},
    "buttons": {
        0: {"plugin": "slack", "label": "Slack"},
        1: {"plugin": "gitlab", "label": "GitLab"},
    },
    "plugins": {
        "slack": {"method": "dbus"},
        "gitlab": {"host": "gitlab.com"},
    },
}


@pytest.fixture()
def config_file(tmp_path: Path) -> Path:
    """Write a minimal config.yaml and return its path."""
    path = tmp_path / "config.yaml"
    path.write_text(yaml.dump(MINIMAL_CONFIG))
    return path


# ---------------------------------------------------------------------------
# Stub plugin — no external I/O
# ---------------------------------------------------------------------------

class StubPlugin(BasePlugin):
    """A minimal plugin that returns a fixed state, no external calls."""

    def __init__(self, config: dict, state: NotificationState | None = None):
        super().__init__(config)
        if state is not None:
            self.state = state
        self.poll_called = 0
        self.press_called = 0
        self.last_press_action: str | None = None

    async def poll(self) -> NotificationState:
        self.poll_called += 1
        return self.state

    async def on_press(self, action: str = "") -> None:
        self.press_called += 1
        self.last_press_action = action


# ---------------------------------------------------------------------------
# NotifyBridge pre-wired with stub plugins (no _init_plugins called)
# ---------------------------------------------------------------------------

@pytest.fixture()
def stub_slack_state() -> NotificationState:
    return NotificationState(
        count=3,
        label="Slack",
        subtitle="general (3)",
        urgent=True,
        color="#4A154B",
        badge_color="#FF3B30",
        extra={"dnd": False, "channels": {"general": 3}, "last_channel": "general", "messages": []},
    )


@pytest.fixture()
def stub_gitlab_state() -> NotificationState:
    return NotificationState(
        count=2,
        label="GitLab",
        subtitle="2 MRs",
        urgent=True,
        color="#FC6D26",
        badge_color="#FF3B30",
        extra={},
    )


@pytest.fixture()
def bridge_with_stubs(
    config_file: Path,
    stub_slack_state: NotificationState,
    stub_gitlab_state: NotificationState,
) -> NotifyBridge:
    """NotifyBridge whose plugins are replaced by StubPlugins before any HTTP call."""
    bridge = NotifyBridge(config_file)
    bridge.plugins = {
        "slack": StubPlugin({}, stub_slack_state),
        "gitlab": StubPlugin({}, stub_gitlab_state),
    }
    return bridge


# ---------------------------------------------------------------------------
# aiohttp test app (routes wired, no polling tasks started)
# ---------------------------------------------------------------------------

def _make_app(bridge: NotifyBridge) -> web.Application:
    app = web.Application()
    app.router.add_get("/status", bridge.handle_status)
    app.router.add_get("/events", bridge.handle_events)
    app.router.add_post("/action/{name}", bridge.handle_action)
    return app


@pytest_asyncio.fixture()
async def test_client(bridge_with_stubs: NotifyBridge) -> AsyncGenerator[TestClient, None]:
    """aiohttp TestClient with the bridge routes, no background tasks."""
    app = _make_app(bridge_with_stubs)
    async with TestClient(TestServer(app)) as client:
        yield client
