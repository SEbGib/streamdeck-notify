"""Tests for the NotifyBridge HTTP endpoints and plugin state format.

Coverage targets:
  - GET /status — JSON shape, all plugin states present
  - POST /action/{name} — known plugin, unknown plugin, optional action param
  - GET /events — SSE initial event shape
  - NotificationState.to_dict — required keys and types
  - Individual plugin state production (Slack, GitLab, System, Spotify, Weather)
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
import yaml
from aiohttp.test_utils import TestClient

from src.bridge import NotifyBridge
from src.plugins.base import NotificationState
from src.plugins.slack import SlackPlugin, _strip_html, _extract_chrome_body
from src.plugins.gitlab import GitLabPlugin
from src.plugins.system import SystemPlugin
from src.plugins.spotify import SpotifyPlugin
from src.plugins.weather import WeatherPlugin

from tests.conftest import StubPlugin


# ===========================================================================
# 1. GET /status
# ===========================================================================

class TestStatusEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_client: TestClient) -> None:
        resp = await test_client.get("/status")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_content_type_is_json(self, test_client: TestClient) -> None:
        resp = await test_client.get("/status")
        assert "application/json" in resp.content_type

    @pytest.mark.asyncio
    async def test_top_level_keys(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/status")).json()
        assert "plugins" in data
        assert "timestamp" in data

    @pytest.mark.asyncio
    async def test_all_plugins_present(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/status")).json()
        assert set(data["plugins"].keys()) == {"slack", "gitlab"}

    @pytest.mark.asyncio
    async def test_slack_state_in_status(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/status")).json()
        slack = data["plugins"]["slack"]
        assert slack["count"] == 3
        assert slack["label"] == "Slack"
        assert slack["urgent"] is True

    @pytest.mark.asyncio
    async def test_gitlab_state_in_status(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/status")).json()
        gitlab = data["plugins"]["gitlab"]
        assert gitlab["count"] == 2
        assert gitlab["label"] == "GitLab"
        assert gitlab["urgent"] is True

    @pytest.mark.asyncio
    async def test_timestamp_is_iso8601(self, test_client: TestClient) -> None:
        from datetime import datetime
        data = await (await test_client.get("/status")).json()
        # Must not raise
        dt = datetime.fromisoformat(data["timestamp"])
        assert dt.tzinfo is not None  # timezone-aware

    @pytest.mark.asyncio
    async def test_plugin_state_has_required_keys(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/status")).json()
        required = {"count", "label", "subtitle", "urgent", "color", "badge_color", "extra"}
        for name, state in data["plugins"].items():
            missing = required - set(state.keys())
            assert not missing, f"Plugin '{name}' state missing keys: {missing}"


# ===========================================================================
# 2. POST /action/{name}
# ===========================================================================

class TestActionEndpoint:
    @pytest.mark.asyncio
    async def test_known_plugin_returns_200(self, test_client: TestClient) -> None:
        resp = await test_client.post("/action/slack")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_known_plugin_response_body(self, test_client: TestClient) -> None:
        data = await (await test_client.post("/action/slack")).json()
        assert data == {"ok": True}

    @pytest.mark.asyncio
    async def test_unknown_plugin_returns_404(self, test_client: TestClient) -> None:
        resp = await test_client.post("/action/nonexistent")
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_unknown_plugin_error_message(self, test_client: TestClient) -> None:
        data = await (await test_client.post("/action/nonexistent")).json()
        assert "error" in data
        assert "nonexistent" in data["error"]

    @pytest.mark.asyncio
    async def test_on_press_called(self, test_client: TestClient, bridge_with_stubs) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["slack"]
        await test_client.post("/action/slack")
        assert stub.press_called == 1

    @pytest.mark.asyncio
    async def test_action_param_forwarded(self, test_client: TestClient, bridge_with_stubs) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["gitlab"]
        await test_client.post("/action/gitlab?action=refresh")
        assert stub.press_called == 1
        assert stub.last_press_action == "refresh"

    @pytest.mark.asyncio
    async def test_no_action_param_calls_on_press_empty(
        self, test_client: TestClient, bridge_with_stubs
    ) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["slack"]
        await test_client.post("/action/slack")
        # on_press called without action kwarg — default empty string
        assert stub.last_press_action == ""

    @pytest.mark.asyncio
    async def test_multiple_presses_accumulate(
        self, test_client: TestClient, bridge_with_stubs
    ) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["slack"]
        await test_client.post("/action/slack")
        await test_client.post("/action/slack")
        assert stub.press_called == 2


# ===========================================================================
# 3. GET /events (SSE)
# ===========================================================================

class TestEventsEndpoint:
    @pytest.mark.asyncio
    async def test_sse_content_type(self, test_client: TestClient) -> None:
        # Open the SSE stream and read just enough to get the first event
        async with test_client.session.get(
            test_client.make_url("/events")
        ) as resp:
            assert resp.status == 200
            assert "text/event-stream" in resp.content_type

    @pytest.mark.asyncio
    async def test_sse_initial_event_present(self, test_client: TestClient) -> None:
        async with test_client.session.get(
            test_client.make_url("/events")
        ) as resp:
            # Read chunks until we find the initial "event: state" line
            raw = b""
            async for chunk in resp.content:
                raw += chunk
                if b"event: state" in raw:
                    break

        text = raw.decode()
        assert "event: state" in text

    @pytest.mark.asyncio
    async def test_sse_initial_data_is_valid_json(self, test_client: TestClient) -> None:
        async with test_client.session.get(
            test_client.make_url("/events")
        ) as resp:
            raw = b""
            async for chunk in resp.content:
                raw += chunk
                if b"\n\n" in raw:
                    break

        text = raw.decode()
        # Extract the data: line
        data_line = next(
            line for line in text.splitlines() if line.startswith("data:")
        )
        payload = json.loads(data_line[len("data:"):].strip())
        assert isinstance(payload, dict)

    @pytest.mark.asyncio
    async def test_sse_initial_event_contains_all_plugins(
        self, test_client: TestClient
    ) -> None:
        async with test_client.session.get(
            test_client.make_url("/events")
        ) as resp:
            raw = b""
            async for chunk in resp.content:
                raw += chunk
                if b"\n\n" in raw:
                    break

        text = raw.decode()
        data_line = next(line for line in text.splitlines() if line.startswith("data:"))
        payload = json.loads(data_line[len("data:"):].strip())
        assert "slack" in payload
        assert "gitlab" in payload

    @pytest.mark.asyncio
    async def test_sse_cache_control_header(self, test_client: TestClient) -> None:
        async with test_client.session.get(
            test_client.make_url("/events")
        ) as resp:
            assert resp.headers.get("Cache-Control") == "no-cache"


# ===========================================================================
# 4. NotificationState — to_dict contract
# ===========================================================================

class TestNotificationState:
    def test_default_state_has_all_keys(self) -> None:
        state = NotificationState()
        d = state.to_dict()
        assert set(d.keys()) == {"count", "label", "subtitle", "urgent", "color", "badge_color", "extra"}

    def test_default_values(self) -> None:
        d = NotificationState().to_dict()
        assert d["count"] == 0
        assert d["label"] == ""
        assert d["subtitle"] == ""
        assert d["urgent"] is False
        assert d["color"] == "#FFFFFF"
        assert d["badge_color"] == "#FF3B30"
        assert d["extra"] == {}

    def test_custom_values_round_trip(self) -> None:
        state = NotificationState(
            count=5, label="Test", subtitle="sub", urgent=True,
            color="#000000", badge_color="#AABBCC", extra={"k": "v"},
        )
        d = state.to_dict()
        assert d["count"] == 5
        assert d["label"] == "Test"
        assert d["subtitle"] == "sub"
        assert d["urgent"] is True
        assert d["color"] == "#000000"
        assert d["badge_color"] == "#AABBCC"
        assert d["extra"] == {"k": "v"}

    def test_extra_is_dict(self) -> None:
        d = NotificationState(extra={"foo": [1, 2]}).to_dict()
        assert isinstance(d["extra"], dict)

    def test_to_dict_returns_new_copy(self) -> None:
        state = NotificationState(extra={"a": 1})
        d1 = state.to_dict()
        d2 = state.to_dict()
        assert d1 is not d2


# ===========================================================================
# 5. SlackPlugin state production (unit, no D-Bus)
# ===========================================================================

class TestSlackPlugin:
    def _make_plugin(self, config: dict | None = None) -> SlackPlugin:
        return SlackPlugin(config or {"method": "dbus"})

    def test_initial_state_idle(self) -> None:
        plugin = self._make_plugin()
        state = plugin._state_from_dbus()
        assert state.count == 0
        assert state.label == "Slack"
        assert state.urgent is False

    def test_single_channel_label(self) -> None:
        plugin = self._make_plugin()
        plugin._dbus_count = 2
        plugin._channels = {"#general": 2}
        plugin._dbus_last_summary = "Hello"
        import time
        plugin._last_activity = time.time()
        state = plugin._state_from_dbus()
        assert "#general" in state.label
        assert "2" in state.label
        assert state.urgent is True

    def test_multi_channel_label(self) -> None:
        plugin = self._make_plugin()
        plugin._dbus_count = 5
        plugin._channels = {"#general": 3, "#random": 2}
        import time
        plugin._last_activity = time.time()
        state = plugin._state_from_dbus()
        assert "canaux" in state.label
        assert state.count == 5

    def test_dnd_mode_state(self) -> None:
        plugin = self._make_plugin()
        plugin._dnd_active = True
        state = plugin._state_from_dbus()
        assert state.subtitle == "DND"
        assert state.urgent is False
        assert state.extra["dnd"] is True

    def test_reset_clears_state(self) -> None:
        plugin = self._make_plugin()
        plugin._dbus_count = 3
        plugin._channels = {"#general": 3}
        plugin._dbus_last_summary = "Hi"
        plugin.reset_count()
        assert plugin._dbus_count == 0
        assert plugin._channels == {}
        assert plugin._dbus_last_summary == ""

    @pytest.mark.asyncio
    async def test_on_press_clears_unread(self) -> None:
        plugin = self._make_plugin()
        plugin._dbus_count = 4
        plugin._channels = {"#general": 4}
        with patch.object(plugin, "notify_state_changed"):
            await plugin.on_press()
        assert plugin._dbus_count == 0

    @pytest.mark.asyncio
    async def test_on_press_enables_dnd_when_no_unread(self) -> None:
        plugin = self._make_plugin()
        plugin._dbus_count = 0
        plugin._dnd_active = False
        with patch.object(plugin, "notify_state_changed"):
            await plugin.on_press()
        assert plugin._dnd_active is True

    @pytest.mark.asyncio
    async def test_on_press_disables_dnd(self) -> None:
        plugin = self._make_plugin()
        plugin._dnd_active = True
        with patch.object(plugin, "notify_state_changed"):
            await plugin.on_press()
        assert plugin._dnd_active is False

    @pytest.mark.asyncio
    async def test_api_poll_no_token_returns_no_token_state(self) -> None:
        plugin = SlackPlugin({"method": "api"})
        state = await plugin._poll_api()
        assert state.label == "Slack"
        assert "No token" in state.subtitle

    def test_extra_contains_channels_key(self) -> None:
        plugin = self._make_plugin()
        plugin._channels = {"#dev": 1}
        state = plugin._state_from_dbus()
        assert "channels" in state.extra

    def test_state_color_default(self) -> None:
        plugin = self._make_plugin()
        state = plugin._state_from_dbus()
        assert state.color == SlackPlugin.COLOR_DEFAULT

    def test_state_color_dnd(self) -> None:
        plugin = self._make_plugin()
        plugin._dnd_active = True
        state = plugin._state_from_dbus()
        assert state.color == SlackPlugin.COLOR_DND


# ===========================================================================
# 5b. Slack helper functions
# ===========================================================================

class TestSlackHelpers:
    def test_strip_html_removes_tags(self) -> None:
        assert _strip_html("<b>Hello</b>") == "Hello"

    def test_strip_html_decodes_entities(self) -> None:
        assert _strip_html("a &amp; b") == "a & b"
        assert _strip_html("&lt;tag&gt;") == "<tag>"
        assert _strip_html("it&#39;s") == "it's"

    def test_strip_html_empty_string(self) -> None:
        assert _strip_html("") == ""

    def test_extract_chrome_body_strips_url_prefix(self) -> None:
        body = "app.slack.com\n\nHello from channel"
        assert _extract_chrome_body(body) == "Hello from channel"

    def test_extract_chrome_body_plain_text(self) -> None:
        assert _extract_chrome_body("Just a message") == "Just a message"

    def test_extract_chrome_body_empty(self) -> None:
        assert _extract_chrome_body("") == ""


# ===========================================================================
# 6. GitLabPlugin state production (mocked subprocess)
# ===========================================================================

class TestGitLabPlugin:
    def _make_plugin(self) -> GitLabPlugin:
        return GitLabPlugin({"host": "gitlab.com"})

    @pytest.mark.asyncio
    async def test_poll_no_username_returns_no_auth_state(self) -> None:
        plugin = self._make_plugin()
        # _username is None by default (setup() not called)
        state = await plugin.poll()
        assert state.label == "GitLab"
        assert state.subtitle == "No auth"

    @pytest.mark.asyncio
    async def test_poll_with_mrs_returns_urgent(self) -> None:
        plugin = self._make_plugin()
        plugin._username = "testuser"

        async def mock_glab_api(endpoint: str):
            if "merge_requests" in endpoint:
                return [{"id": 1, "title": "Fix bug"}, {"id": 2, "title": "Add feature"}]
            if "todos" in endpoint:
                return []
            return []

        with patch.object(plugin, "_glab_api", side_effect=mock_glab_api):
            state = await plugin.poll()

        assert state.count == 2
        assert "MR" in state.subtitle
        assert state.urgent is True
        assert state.color == "#FC6D26"

    @pytest.mark.asyncio
    async def test_poll_with_todos_only(self) -> None:
        plugin = self._make_plugin()
        plugin._username = "testuser"

        async def mock_glab_api(endpoint: str):
            if "merge_requests" in endpoint:
                return []
            if "todos" in endpoint:
                return [{"id": 1}, {"id": 2}, {"id": 3}]
            return []

        with patch.object(plugin, "_glab_api", side_effect=mock_glab_api):
            state = await plugin.poll()

        assert state.count == 3
        assert "todo" in state.subtitle
        assert state.urgent is False

    @pytest.mark.asyncio
    async def test_poll_all_clear(self) -> None:
        plugin = self._make_plugin()
        plugin._username = "testuser"

        async def mock_glab_api(endpoint: str):
            return []

        with patch.object(plugin, "_glab_api", side_effect=mock_glab_api):
            state = await plugin.poll()

        assert state.count == 0
        assert state.subtitle == "OK"
        assert state.urgent is False

    @pytest.mark.asyncio
    async def test_poll_exception_returns_error_state(self) -> None:
        plugin = self._make_plugin()
        plugin._username = "testuser"

        async def mock_glab_api(endpoint: str):
            raise RuntimeError("network error")

        with patch.object(plugin, "_glab_api", side_effect=mock_glab_api):
            state = await plugin.poll()

        assert state.subtitle == "Error"


# ===========================================================================
# 7. SystemPlugin state production (mocked psutil / proc)
# ===========================================================================

class TestSystemPlugin:
    @pytest.mark.asyncio
    async def test_cpu_low_usage_green(self) -> None:
        plugin = SystemPlugin({"metric": "cpu"})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(return_value=30.0)):
            state = await plugin.poll()
        assert state.label == "CPU"
        assert "30" in state.subtitle
        assert state.color == "#2DA160"
        assert state.urgent is False

    @pytest.mark.asyncio
    async def test_cpu_warn_threshold_orange(self) -> None:
        plugin = SystemPlugin({"metric": "cpu"})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(return_value=85.0)):
            state = await plugin.poll()
        assert state.color == "#E5A000"
        assert state.urgent is False

    @pytest.mark.asyncio
    async def test_cpu_critical_threshold_urgent(self) -> None:
        plugin = SystemPlugin({"metric": "cpu"})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(return_value=92.0)):
            state = await plugin.poll()
        assert state.urgent is True

    @pytest.mark.asyncio
    async def test_cpu_danger_threshold_red(self) -> None:
        plugin = SystemPlugin({"metric": "cpu"})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(return_value=96.0)):
            state = await plugin.poll()
        assert state.color == "#FF3B30"

    @pytest.mark.asyncio
    async def test_ram_metric_label(self) -> None:
        plugin = SystemPlugin({"metric": "ram"})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(return_value=55.0)):
            state = await plugin.poll()
        assert state.label == "RAM"
        assert "55" in state.subtitle

    @pytest.mark.asyncio
    async def test_custom_warn_threshold(self) -> None:
        plugin = SystemPlugin({"metric": "cpu", "warn": 50})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(return_value=60.0)):
            state = await plugin.poll()
        assert state.color == "#E5A000"

    @pytest.mark.asyncio
    async def test_exception_returns_error_state(self) -> None:
        plugin = SystemPlugin({"metric": "cpu"})
        with patch.object(plugin, "_fetch_metric", new=AsyncMock(side_effect=OSError("proc"))):
            state = await plugin.poll()
        assert state.subtitle == "Error"
        assert state.color == "#FF3B30"


# ===========================================================================
# 8. SpotifyPlugin state production (mocked gdbus subprocess)
# ===========================================================================

class TestSpotifyPlugin:
    def _make_plugin(self) -> SpotifyPlugin:
        return SpotifyPlugin({})

    @pytest.mark.asyncio
    async def test_no_player_detected(self) -> None:
        plugin = self._make_plugin()
        with patch.object(plugin, "_detect_player", new=AsyncMock(return_value=None)):
            state = await plugin.poll()
        assert state.label == "No player"
        assert state.extra["media_source"] == "unknown"

    @pytest.mark.asyncio
    async def test_playing_track_builds_state(self) -> None:
        plugin = self._make_plugin()
        plugin._active_player = "org.mpris.MediaPlayer2.spotify"
        metadata = {"title": "Bohemian Rhapsody", "artist": "Queen", "trackid": "/track/1"}

        with (
            patch.object(plugin, "_detect_player", new=AsyncMock(return_value="org.mpris.MediaPlayer2.spotify")),
            patch.object(plugin, "_fetch_metadata", new=AsyncMock(return_value=metadata)),
        ):
            state = await plugin.poll()

        assert "Bohemian" in state.label
        assert state.subtitle == "Queen"
        assert state.color == "#1DB954"
        assert state.extra["media_source"] == "spotify"

    @pytest.mark.asyncio
    async def test_long_title_truncated(self) -> None:
        plugin = self._make_plugin()
        long_title = "A" * 30
        metadata = {"title": long_title, "artist": "Artist"}

        with (
            patch.object(plugin, "_detect_player", new=AsyncMock(return_value="org.mpris.MediaPlayer2.spotify")),
            patch.object(plugin, "_fetch_metadata", new=AsyncMock(return_value=metadata)),
        ):
            state = await plugin.poll()

        assert len(state.label) <= 19  # 18 chars + ellipsis
        assert state.label.endswith("…")

    @pytest.mark.asyncio
    async def test_paused_no_title(self) -> None:
        plugin = self._make_plugin()
        metadata = {"artist": "Queen"}  # no title key

        with (
            patch.object(plugin, "_detect_player", new=AsyncMock(return_value="org.mpris.MediaPlayer2.spotify")),
            patch.object(plugin, "_fetch_metadata", new=AsyncMock(return_value=metadata)),
        ):
            state = await plugin.poll()

        assert state.label == "Paused"

    def test_detect_source_spotify_native(self) -> None:
        plugin = self._make_plugin()
        plugin._active_player = "org.mpris.MediaPlayer2.spotify"
        source = plugin._detect_source({})
        assert source == "spotify"

    def test_detect_source_vlc(self) -> None:
        plugin = self._make_plugin()
        plugin._active_player = "org.mpris.MediaPlayer2.vlc"
        source = plugin._detect_source({})
        assert source == "vlc"

    def test_detect_source_deezer_via_album(self) -> None:
        plugin = self._make_plugin()
        plugin._active_player = "org.mpris.MediaPlayer2.chromium"
        source = plugin._detect_source({"album": "Some Album"})
        assert source == "deezer"

    def test_detect_source_youtube_no_album(self) -> None:
        plugin = self._make_plugin()
        plugin._active_player = "org.mpris.MediaPlayer2.chromium"
        source = plugin._detect_source({"title": "Some Video"})
        assert source == "youtube"

    def test_parse_metadata_extracts_fields(self) -> None:
        raw = (
            "({'mpris:trackid': <objectpath '/com/spotify/track/1ABCdef'>, "
            "'xesam:title': <'Bohemian Rhapsody'>, "
            "'xesam:artist': <['Queen']>, "
            "'xesam:album': <'A Night at the Opera'>, "
            "'mpris:artUrl': <'https://i.scdn.co/image/abc'>},)"
        )
        meta = SpotifyPlugin._parse_metadata(raw)
        assert meta["title"] == "Bohemian Rhapsody"
        assert meta["artist"] == "Queen"
        assert meta["album"] == "A Night at the Opera"
        assert "1ABCdef" in meta["trackid"]


# ===========================================================================
# 9. WeatherPlugin state production (mocked urllib)
# ===========================================================================

class TestWeatherPlugin:
    def _make_plugin(self) -> WeatherPlugin:
        return WeatherPlugin({"latitude": 48.85, "longitude": 2.35, "location": "Paris"})

    @pytest.mark.asyncio
    async def test_sunny_weather(self) -> None:
        plugin = self._make_plugin()
        api_response = {"current": {"temperature_2m": 22.5, "weather_code": 0}}

        with patch.object(plugin, "_fetch_weather", new=AsyncMock(return_value=api_response)):
            state = await plugin.poll()

        assert state.label == "22°C"
        assert "dégagé" in state.subtitle.lower()
        assert state.color == "#4A90D9"
        assert state.urgent is False
        assert state.extra["weather_icon"] == "weather_sun"

    @pytest.mark.asyncio
    async def test_rainy_weather(self) -> None:
        plugin = self._make_plugin()
        api_response = {"current": {"temperature_2m": 10.0, "weather_code": 63}}

        with patch.object(plugin, "_fetch_weather", new=AsyncMock(return_value=api_response)):
            state = await plugin.poll()

        assert state.label == "10°C"
        assert state.extra["weather_icon"] == "weather_rain"

    @pytest.mark.asyncio
    async def test_unknown_weather_code_falls_back(self) -> None:
        plugin = self._make_plugin()
        api_response = {"current": {"temperature_2m": 15.0, "weather_code": 999}}

        with patch.object(plugin, "_fetch_weather", new=AsyncMock(return_value=api_response)):
            state = await plugin.poll()

        assert state.label == "15°C"
        # Subtitle falls back to location when description is empty
        assert state.subtitle == "Paris"

    @pytest.mark.asyncio
    async def test_fetch_exception_returns_error_state(self) -> None:
        plugin = self._make_plugin()
        with patch.object(plugin, "_fetch_weather", new=AsyncMock(side_effect=OSError("timeout"))):
            state = await plugin.poll()

        assert state.subtitle == "Erreur"
        assert state.label == "Météo"

    @pytest.mark.asyncio
    async def test_missing_temperature_shows_na(self) -> None:
        plugin = self._make_plugin()
        api_response = {"current": {"weather_code": 0}}  # no temperature_2m

        with patch.object(plugin, "_fetch_weather", new=AsyncMock(return_value=api_response)):
            state = await plugin.poll()

        assert state.label == "N/A"


# ===========================================================================
# 10. GET /health
# ===========================================================================

class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_client: TestClient) -> None:
        resp = await test_client.get("/health")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_content_type_is_json(self, test_client: TestClient) -> None:
        resp = await test_client.get("/health")
        assert "application/json" in resp.content_type

    @pytest.mark.asyncio
    async def test_status_ok(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/health")).json()
        assert data["status"] == "ok"

    @pytest.mark.asyncio
    async def test_uptime_seconds_is_non_negative_int(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/health")).json()
        assert isinstance(data["uptime_seconds"], int)
        assert data["uptime_seconds"] >= 0

    @pytest.mark.asyncio
    async def test_plugins_key_present(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/health")).json()
        assert "plugins" in data
        assert set(data["plugins"].keys()) == {"slack", "gitlab"}

    @pytest.mark.asyncio
    async def test_plugin_entry_has_required_keys(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/health")).json()
        required = {"last_poll", "poll_count", "error_count"}
        for name, entry in data["plugins"].items():
            missing = required - set(entry.keys())
            assert not missing, f"Plugin '{name}' health entry missing keys: {missing}"

    @pytest.mark.asyncio
    async def test_initial_last_poll_is_null(self, test_client: TestClient) -> None:
        """Plugins that have never been polled via run_loop report last_poll as null."""
        data = await (await test_client.get("/health")).json()
        for name, entry in data["plugins"].items():
            assert entry["last_poll"] is None, f"Plugin '{name}' should start with null last_poll"

    @pytest.mark.asyncio
    async def test_initial_poll_count_is_zero(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/health")).json()
        for name, entry in data["plugins"].items():
            assert entry["poll_count"] == 0

    @pytest.mark.asyncio
    async def test_initial_error_count_is_zero(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/health")).json()
        for name, entry in data["plugins"].items():
            assert entry["error_count"] == 0

    @pytest.mark.asyncio
    async def test_poll_count_increments_after_run_loop_poll(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        """Simulate run_loop updating poll_count directly on the stub plugin."""
        from datetime import datetime, timezone
        stub: StubPlugin = bridge_with_stubs.plugins["slack"]
        stub.poll_count = 5
        stub.last_poll = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        data = await (await test_client.get("/health")).json()
        assert data["plugins"]["slack"]["poll_count"] == 5
        assert data["plugins"]["slack"]["last_poll"] == "2025-01-01T12:00:00+00:00"

    @pytest.mark.asyncio
    async def test_error_count_reflected(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["gitlab"]
        stub.error_count = 3

        data = await (await test_client.get("/health")).json()
        assert data["plugins"]["gitlab"]["error_count"] == 3


# ===========================================================================
# 10. Bridge _init_plugins (unit — no file I/O beyond config)
# ===========================================================================

class TestBridgeInitPlugins:
    def test_plugins_loaded_from_buttons(self, config_file: Path) -> None:
        from src.bridge import NotifyBridge
        bridge = NotifyBridge(config_file)
        bridge._init_plugins()
        assert "slack" in bridge.plugins
        assert "gitlab" in bridge.plugins

    def test_unknown_plugin_skipped_gracefully(self, tmp_path: Path) -> None:
        """_init_plugins logs a warning but does not raise for unknown plugin names."""
        from src.bridge import NotifyBridge

        cfg = {
            "deck": {"refresh_interval": 30},
            "buttons": {0: {"plugin": "no_such_plugin"}},
            "plugins": {},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(cfg))
        bridge = NotifyBridge(path)
        bridge._init_plugins()
        assert "no_such_plugin" not in bridge.plugins

    def test_plugin_config_merged_with_button_config(self, tmp_path: Path) -> None:
        """Plugin-level config and button-level config are merged."""
        from src.bridge import NotifyBridge

        cfg = {
            "deck": {"refresh_interval": 30},
            "buttons": {0: {"plugin": "slack", "label": "S"}},
            "plugins": {"slack": {"method": "api", "token": "xoxb-test"}},
        }
        path = tmp_path / "config.yaml"
        path.write_text(yaml.dump(cfg))
        bridge = NotifyBridge(path)
        bridge._init_plugins()
        slack: SlackPlugin = bridge.plugins["slack"]  # type: ignore[assignment]
        assert slack.method == "api"
        assert slack.config.get("token") == "xoxb-test"


# ===========================================================================
# 11. GET /history
# ===========================================================================

class TestHistoryEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_client: TestClient) -> None:
        resp = await test_client.get("/history")
        assert resp.status == 200

    @pytest.mark.asyncio
    async def test_content_type_is_json(self, test_client: TestClient) -> None:
        resp = await test_client.get("/history")
        assert "application/json" in resp.content_type

    @pytest.mark.asyncio
    async def test_top_level_key_is_events(self, test_client: TestClient) -> None:
        data = await (await test_client.get("/history")).json()
        assert "events" in data
        assert isinstance(data["events"], list)

    @pytest.mark.asyncio
    async def test_empty_when_no_history(self, test_client: TestClient) -> None:
        """No run_loop called — plugins have no history entries."""
        data = await (await test_client.get("/history")).json()
        assert data["events"] == []

    @pytest.mark.asyncio
    async def test_events_contain_required_keys(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["slack"]
        stub._history = [
            {
                "timestamp": "2025-01-01T10:00:00+00:00",
                "source": "StubPlugin",
                "label": "Slack",
                "subtitle": "hi",
                "count": 1,
                "urgent": False,
            }
        ]
        data = await (await test_client.get("/history")).json()
        event = data["events"][0]
        required = {"timestamp", "source", "label", "subtitle", "count", "urgent", "plugin"}
        assert required <= set(event.keys())

    @pytest.mark.asyncio
    async def test_events_sorted_newest_first(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["slack"]
        stub._history = [
            {"timestamp": "2025-01-01T08:00:00+00:00", "source": "S", "label": "A", "subtitle": "", "count": 0, "urgent": False},
            {"timestamp": "2025-01-01T10:00:00+00:00", "source": "S", "label": "B", "subtitle": "", "count": 1, "urgent": False},
            {"timestamp": "2025-01-01T09:00:00+00:00", "source": "S", "label": "C", "subtitle": "", "count": 2, "urgent": False},
        ]
        data = await (await test_client.get("/history")).json()
        timestamps = [e["timestamp"] for e in data["events"]]
        assert timestamps == sorted(timestamps, reverse=True)

    @pytest.mark.asyncio
    async def test_events_include_plugin_key(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        stub: StubPlugin = bridge_with_stubs.plugins["gitlab"]
        stub._history = [
            {"timestamp": "2025-01-01T12:00:00+00:00", "source": "StubPlugin", "label": "GitLab", "subtitle": "", "count": 2, "urgent": True},
        ]
        data = await (await test_client.get("/history")).json()
        gitlab_events = [e for e in data["events"] if e.get("plugin") == "gitlab"]
        assert len(gitlab_events) == 1

    @pytest.mark.asyncio
    async def test_source_filter_by_plugin_key(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        bridge_with_stubs.plugins["slack"]._history = [
            {"timestamp": "2025-01-01T10:00:00+00:00", "source": "StubPlugin", "label": "Slack", "subtitle": "", "count": 1, "urgent": False},
        ]
        bridge_with_stubs.plugins["gitlab"]._history = [
            {"timestamp": "2025-01-01T11:00:00+00:00", "source": "StubPlugin", "label": "GitLab", "subtitle": "", "count": 2, "urgent": True},
        ]
        data = await (await test_client.get("/history?source=slack")).json()
        assert all(e["plugin"] == "slack" for e in data["events"])
        assert len(data["events"]) == 1

    @pytest.mark.asyncio
    async def test_source_filter_returns_empty_for_unknown(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        bridge_with_stubs.plugins["slack"]._history = [
            {"timestamp": "2025-01-01T10:00:00+00:00", "source": "StubPlugin", "label": "Slack", "subtitle": "", "count": 1, "urgent": False},
        ]
        data = await (await test_client.get("/history?source=nonexistent")).json()
        assert data["events"] == []

    @pytest.mark.asyncio
    async def test_merges_history_from_multiple_plugins(
        self, test_client: TestClient, bridge_with_stubs: NotifyBridge
    ) -> None:
        bridge_with_stubs.plugins["slack"]._history = [
            {"timestamp": "2025-01-01T10:00:00+00:00", "source": "S", "label": "Slack", "subtitle": "", "count": 1, "urgent": False},
        ]
        bridge_with_stubs.plugins["gitlab"]._history = [
            {"timestamp": "2025-01-01T11:00:00+00:00", "source": "G", "label": "GitLab", "subtitle": "", "count": 2, "urgent": True},
        ]
        data = await (await test_client.get("/history")).json()
        assert len(data["events"]) == 2
        # Newest first: gitlab then slack
        assert data["events"][0]["plugin"] == "gitlab"
        assert data["events"][1]["plugin"] == "slack"


# ===========================================================================
# 12. BasePlugin._record_history (unit)
# ===========================================================================

class TestBasePluginHistory:
    def _make_stub(self) -> "StubPlugin":
        from tests.conftest import StubPlugin
        return StubPlugin({})

    def test_record_history_appends_entry(self) -> None:
        stub = self._make_stub()
        from src.plugins.base import NotificationState
        state = NotificationState(count=2, label="X", subtitle="y", urgent=True)
        stub._record_history(state)
        assert len(stub._history) == 1
        entry = stub._history[0]
        assert entry["count"] == 2
        assert entry["label"] == "X"
        assert entry["subtitle"] == "y"
        assert entry["urgent"] is True
        assert "timestamp" in entry
        assert "source" in entry

    def test_record_history_caps_at_50(self) -> None:
        from src.plugins.base import NotificationState, HISTORY_MAX
        stub = self._make_stub()
        for i in range(60):
            stub._record_history(NotificationState(count=i, label=str(i)))
        assert len(stub._history) == HISTORY_MAX
        # Most recent (last 50) are kept
        assert stub._history[-1]["count"] == 59

    def test_record_history_timestamp_is_iso8601(self) -> None:
        from src.plugins.base import NotificationState
        from datetime import datetime
        stub = self._make_stub()
        stub._record_history(NotificationState())
        dt = datetime.fromisoformat(stub._history[0]["timestamp"])
        assert dt.tzinfo is not None

    @pytest.mark.asyncio
    async def test_run_loop_records_on_state_change(self) -> None:
        """run_loop records a history entry when the state actually changes."""
        from src.plugins.base import NotificationState
        from tests.conftest import StubPlugin

        initial = NotificationState(count=0, label="A")
        stub = StubPlugin({}, initial)

        changed = NotificationState(count=1, label="B")
        call_count = 0

        async def changing_poll() -> NotificationState:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return initial
            stub._running = False  # stop after second poll
            return changed

        stub.poll = changing_poll  # type: ignore[method-assign]

        import asyncio
        await asyncio.wait_for(stub.run_loop(0), timeout=2)

        # Second poll returned a different state → one history entry
        assert len(stub._history) == 1
        assert stub._history[0]["count"] == 1
