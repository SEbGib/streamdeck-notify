"""Notify Center — StreamController plugin for notification monitoring."""

from loguru import logger as log

from src.backend.PluginManager.ActionHolder import ActionHolder
from src.backend.PluginManager.ActionInputSupport import ActionInputSupport
from src.backend.PluginManager.PluginBase import PluginBase
from src.backend.DeckManagement.InputIdentifier import Input

from .actions.NotifyAction import NotifyAction
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

        self.register()
        log.info("NotifyCenter: register() done")

    def _init_icons(self):
        for icon_key in Icons:
            path = self.get_asset_path(f"{icon_key.value}.png")
            self.add_icon(icon_key, path)
