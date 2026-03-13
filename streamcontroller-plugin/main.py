"""Notify Center — StreamController plugin for notification monitoring."""

from loguru import logger as log

from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.DeckManagement.InputIdentifier import Input

from .actions.NotifyAction import NotifyAction
from .actions.PomodoroAction import PomodoroAction
from .actions.ResetAllAction import ResetAllAction
from .actions.MediaControlAction import MediaControlAction
from .actions.PageSwitchAction import PageSwitchAction
from .globals import Icons


class NotifyCenter(PluginBase):
    def __init__(self):
        log.info("NotifyCenter: __init__ starting")
        super().__init__()

        try:
            self._init_icons()
        except Exception as e:
            log.error(f"NotifyCenter: icon init failed: {e}")

        try:
            notify_action = ActionHolder(
                plugin_base=self,
                action_core=NotifyAction,
                action_id_suffix="NotifyAction",
                action_name="Notification",
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.UNTESTED,
                },
            )
            self.add_action_holder(notify_action)
            log.info("NotifyCenter: action holder added")
        except Exception as e:
            log.error(f"NotifyCenter: action holder failed: {e}")

        try:
            pomodoro_action = ActionHolder(
                plugin_base=self,
                action_core=PomodoroAction,
                action_id_suffix="PomodoroAction",
                action_name="Pomodoro Timer",
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.UNTESTED,
                },
            )
            self.add_action_holder(pomodoro_action)
            log.info("NotifyCenter: pomodoro action holder added")
        except Exception as e:
            log.error(f"NotifyCenter: pomodoro action holder failed: {e}")

        try:
            reset_all_action = ActionHolder(
                plugin_base=self,
                action_core=ResetAllAction,
                action_id_suffix="ResetAllAction",
                action_name="Reset All",
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.UNTESTED,
                },
            )
            self.add_action_holder(reset_all_action)
            log.info("NotifyCenter: reset-all action holder added")
        except Exception as e:
            log.error(f"NotifyCenter: reset-all action holder failed: {e}")

        try:
            media_control_action = ActionHolder(
                plugin_base=self,
                action_core=MediaControlAction,
                action_id_suffix="MediaControlAction",
                action_name="Media Control",
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.UNTESTED,
                },
            )
            self.add_action_holder(media_control_action)
            log.info("NotifyCenter: media-control action holder added")
        except Exception as e:
            log.error(f"NotifyCenter: media-control action holder failed: {e}")

        try:
            page_switch_action = ActionHolder(
                plugin_base=self,
                action_core=PageSwitchAction,
                action_id_suffix="PageSwitchAction",
                action_name="Page Switch",
                action_support={
                    Input.Key: ActionInputSupport.SUPPORTED,
                    Input.Dial: ActionInputSupport.UNSUPPORTED,
                    Input.Touchscreen: ActionInputSupport.UNTESTED,
                },
            )
            self.add_action_holder(page_switch_action)
            log.info("NotifyCenter: page-switch action holder added")
        except Exception as e:
            log.error(f"NotifyCenter: page-switch action holder failed: {e}")

        self.register()
        log.info("NotifyCenter: register() done")

    def _init_icons(self):
        for icon_key in Icons:
            path = self.get_asset_path(f"{icon_key.value}.png")
            self.add_icon(icon_key, path)
