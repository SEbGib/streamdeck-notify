"""Tests for streamcontroller-plugin internal modules.

Covers:
  - internal.auto_brightness.get_brightness_for_time — time-based brightness with transitions
  - internal.host.host_run — flatpak-spawn wrapper argument construction
  - internal.page_switch._safe_on_ready — exception handling for all error types
"""

from __future__ import annotations

import subprocess
import sys
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Path setup — streamcontroller-plugin is not under src/, add it explicitly
# ---------------------------------------------------------------------------

_PLUGIN_ROOT = Path(__file__).parent.parent / "streamcontroller-plugin"
if str(_PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(_PLUGIN_ROOT))

from internal.auto_brightness import get_brightness_for_time  # noqa: E402
from internal.host import host_run  # noqa: E402
from internal.page_switch import _safe_on_ready  # noqa: E402


# ===========================================================================
# Helpers
# ===========================================================================

def _dt(hour: int, minute: int = 0) -> datetime:
    """Build a datetime for today at the given hour:minute."""
    return datetime(2024, 1, 15, hour, minute)


# ===========================================================================
# 1. auto_brightness.get_brightness_for_time
# ===========================================================================

class TestGetBrightnessForTime:
    # -----------------------------------------------------------------------
    # Stable zones — no transition
    # -----------------------------------------------------------------------

    def test_morning_8h_returns_80(self) -> None:
        assert get_brightness_for_time(_dt(8)) == 80

    def test_afternoon_15h_returns_80(self) -> None:
        assert get_brightness_for_time(_dt(15)) == 80

    def test_evening_20h_returns_50(self) -> None:
        assert get_brightness_for_time(_dt(20)) == 50

    def test_night_23h_returns_20(self) -> None:
        assert get_brightness_for_time(_dt(23)) == 20

    def test_deep_night_3h_returns_20(self) -> None:
        assert get_brightness_for_time(_dt(3)) == 20

    # -----------------------------------------------------------------------
    # Edge cases at exact knot boundaries
    # -----------------------------------------------------------------------

    def test_midnight_returns_20(self) -> None:
        assert get_brightness_for_time(_dt(0)) == 20

    def test_noon_returns_80(self) -> None:
        assert get_brightness_for_time(_dt(12)) == 80

    def test_7h_exactly_returns_20(self) -> None:
        # _time_to_float(7, 0) = 7.0 < 7.5 → shifted to 31.0
        # Knot (31.0, 20) is the start of the dawn ramp → brightness = 20
        assert get_brightness_for_time(_dt(7, 0)) == 20

    def test_19h_exactly_returns_80(self) -> None:
        # 19:00 is the start of the evening ramp → brightness = 80
        assert get_brightness_for_time(_dt(19, 0)) == 80

    # -----------------------------------------------------------------------
    # Transitions
    # -----------------------------------------------------------------------

    def test_transition_evening_ramp_19h15_between_50_and_80(self) -> None:
        # 19:15 is mid-ramp from 80 → 50 (ramp: 19:00–19:30)
        result = get_brightness_for_time(_dt(19, 15))
        assert 50 < result < 80

    def test_transition_evening_ramp_19h30_equals_50(self) -> None:
        # 19:30 is the end of the 80→50 ramp
        assert get_brightness_for_time(_dt(19, 30)) == 50

    def test_transition_night_ramp_22h15_between_20_and_50(self) -> None:
        # 22:15 is mid-ramp from 50 → 20 (ramp: 22:00–22:30)
        result = get_brightness_for_time(_dt(22, 15))
        assert 20 < result < 50

    def test_transition_night_ramp_22h30_equals_20(self) -> None:
        # 22:30 is the end of the 50→20 ramp
        assert get_brightness_for_time(_dt(22, 30)) == 20

    def test_transition_dawn_ramp_7h15_between_20_and_80(self) -> None:
        # 07:15 is mid-ramp from 20 → 80 (ramp: 07:00–07:30)
        # Note: 07:00 is already at 80, so ramp is 06:30(=31:00-0:30? no)
        # The dawn ramp is knot (31.0, 20) → (31.5, 80), i.e. 07:00–07:30
        result = get_brightness_for_time(_dt(7, 15))
        assert 20 < result < 80

    def test_transition_dawn_ramp_monotonically_increasing(self) -> None:
        # Each step during 07:00–07:30 should be >= previous
        times = [_dt(7, m) for m in range(0, 31, 5)]
        values = [get_brightness_for_time(t) for t in times]
        for a, b in zip(values, values[1:]):
            assert b >= a, f"Non-monotonic during dawn ramp: {values}"

    def test_transition_evening_ramp_monotonically_decreasing(self) -> None:
        # Each step during 19:00–19:30 should be <= previous
        times = [_dt(19, m) for m in range(0, 31, 5)]
        values = [get_brightness_for_time(t) for t in times]
        for a, b in zip(values, values[1:]):
            assert b <= a, f"Non-monotonic during evening ramp: {values}"

    def test_transition_night_ramp_monotonically_decreasing(self) -> None:
        # Each step during 22:00–22:30 should be <= previous
        times = [_dt(22, m) for m in range(0, 31, 5)]
        values = [get_brightness_for_time(t) for t in times]
        for a, b in zip(values, values[1:]):
            assert b <= a, f"Non-monotonic during night ramp: {values}"

    # -----------------------------------------------------------------------
    # Return type and range
    # -----------------------------------------------------------------------

    def test_return_type_is_int(self) -> None:
        assert isinstance(get_brightness_for_time(_dt(10)), int)

    def test_brightness_always_in_valid_range(self) -> None:
        # Check every hour of the day
        for hour in range(24):
            for minute in (0, 15, 30, 45):
                result = get_brightness_for_time(_dt(hour, minute))
                assert 0 <= result <= 100, f"Out of range at {hour:02d}:{minute:02d}: {result}"

    # -----------------------------------------------------------------------
    # No-argument form (uses current time) — just verify it returns an int
    # -----------------------------------------------------------------------

    def test_no_argument_returns_int(self) -> None:
        result = get_brightness_for_time()
        assert isinstance(result, int)
        assert 0 <= result <= 100


# ===========================================================================
# 2. host.host_run
# ===========================================================================

class TestHostRun:
    def _run_and_capture(self, cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
        """Call host_run with a mocked subprocess.run and return the captured call args."""
        with patch("internal.host.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="", stderr=""
            )
            host_run(cmd, **kwargs)
            return mock_run

    def test_flatpak_spawn_is_first_arg(self) -> None:
        mock_run = self._run_and_capture(["echo", "hello"])
        actual_cmd = mock_run.call_args[0][0]
        assert actual_cmd[0] == "flatpak-spawn"

    def test_host_flag_is_present(self) -> None:
        mock_run = self._run_and_capture(["echo", "hello"])
        actual_cmd = mock_run.call_args[0][0]
        assert "--host" in actual_cmd

    def test_directory_flag_is_present(self) -> None:
        mock_run = self._run_and_capture(["echo", "hello"])
        actual_cmd = mock_run.call_args[0][0]
        assert "--directory=/" in actual_cmd

    def test_user_command_appended_after_prefix(self) -> None:
        mock_run = self._run_and_capture(["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"])
        actual_cmd = mock_run.call_args[0][0]
        # Prefix is 3 items: flatpak-spawn, --host, --directory=/
        assert actual_cmd[3:] == ["wpctl", "get-volume", "@DEFAULT_AUDIO_SINK@"]

    def test_full_prefix_order(self) -> None:
        mock_run = self._run_and_capture(["ls"])
        actual_cmd = mock_run.call_args[0][0]
        assert actual_cmd[:3] == ["flatpak-spawn", "--host", "--directory=/"]

    def test_default_timeout_is_3(self) -> None:
        mock_run = self._run_and_capture(["ls"])
        kwargs = mock_run.call_args[1]
        assert kwargs.get("timeout") == 3

    def test_capture_output_is_true(self) -> None:
        mock_run = self._run_and_capture(["ls"])
        kwargs = mock_run.call_args[1]
        assert kwargs.get("capture_output") is True

    def test_text_mode_is_true(self) -> None:
        mock_run = self._run_and_capture(["ls"])
        kwargs = mock_run.call_args[1]
        assert kwargs.get("text") is True

    def test_extra_kwargs_forwarded(self) -> None:
        mock_run = self._run_and_capture(["ls"], env={"MY_VAR": "1"})
        kwargs = mock_run.call_args[1]
        assert kwargs.get("env") == {"MY_VAR": "1"}

    def test_returns_completed_process(self) -> None:
        with patch("internal.host.subprocess.run") as mock_run:
            mock_run.return_value = subprocess.CompletedProcess(
                args=[], returncode=0, stdout="ok", stderr=""
            )
            result = host_run(["ls"])
        assert isinstance(result, subprocess.CompletedProcess)


# ===========================================================================
# 3. page_switch._safe_on_ready
# ===========================================================================

class TestSafeOnReady:
    def _make_action(self, name: str = "FakeAction", source: str = "test") -> MagicMock:
        action = MagicMock()
        action.__class__.__name__ = name
        action._source = source
        return action

    # -----------------------------------------------------------------------
    # Success path
    # -----------------------------------------------------------------------

    def test_success_calls_on_ready(self) -> None:
        action = self._make_action()
        _safe_on_ready(action)
        action.on_ready.assert_called_once()

    def test_success_logs_ok(self) -> None:
        action = self._make_action()
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        mock_log.info.assert_called_once()
        call_args = mock_log.info.call_args[0][0]
        assert "OK" in call_args

    # -----------------------------------------------------------------------
    # Exception branch
    # -----------------------------------------------------------------------

    def test_exception_is_caught(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = RuntimeError("something broke")
        # Must not propagate
        _safe_on_ready(action)

    def test_exception_logs_warning(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = ValueError("bad value")
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args[0][0]
        assert "FAIL" in call_args

    def test_exception_message_included_in_log(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = RuntimeError("specific-error-msg")
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        log_msg = mock_log.warning.call_args[0][0]
        assert "specific-error-msg" in log_msg

    # -----------------------------------------------------------------------
    # Warning branch (Warning is a subclass of Exception, caught first)
    # -----------------------------------------------------------------------

    def test_warning_is_caught(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = Warning("not ready yet")
        # Must not propagate
        _safe_on_ready(action)

    def test_warning_logs_warning_level(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = Warning("not ready yet")
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        mock_log.warning.assert_called_once()
        call_args = mock_log.warning.call_args[0][0]
        assert "WARNING" in call_args

    def test_warning_message_included_in_log(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = Warning("deck-not-initialized")
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        log_msg = mock_log.warning.call_args[0][0]
        assert "deck-not-initialized" in log_msg

    # -----------------------------------------------------------------------
    # BaseException branch (e.g. KeyboardInterrupt, SystemExit)
    # -----------------------------------------------------------------------

    def test_keyboard_interrupt_is_caught(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = KeyboardInterrupt()
        # Must not propagate
        _safe_on_ready(action)

    def test_system_exit_is_caught(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = SystemExit(1)
        # Must not propagate
        _safe_on_ready(action)

    def test_base_exception_logs_error(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = KeyboardInterrupt()
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        mock_log.error.assert_called_once()
        call_args = mock_log.error.call_args[0][0]
        assert "CRASH" in call_args

    def test_base_exception_includes_type_name_in_log(self) -> None:
        action = self._make_action()
        action.on_ready.side_effect = KeyboardInterrupt()
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        log_msg = mock_log.error.call_args[0][0]
        assert "KeyboardInterrupt" in log_msg

    # -----------------------------------------------------------------------
    # Action class name and source appear in log messages
    # -----------------------------------------------------------------------

    def test_action_name_in_success_log(self) -> None:
        action = self._make_action(name="MyAction", source="page1")
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        log_msg = mock_log.info.call_args[0][0]
        assert "MyAction" in log_msg

    def test_action_source_in_success_log(self) -> None:
        action = self._make_action(name="MyAction", source="my-source")
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        log_msg = mock_log.info.call_args[0][0]
        assert "my-source" in log_msg

    def test_action_without_source_attribute_uses_fallback(self) -> None:
        action = MagicMock()
        action.__class__.__name__ = "NoSourceAction"
        # No _source attribute — getattr fallback should return '?'
        del action._source
        with patch("internal.page_switch.log") as mock_log:
            _safe_on_ready(action)
        log_msg = mock_log.info.call_args[0][0]
        assert "?" in log_msg
