from .base import BasePlugin, NotificationState
from .slack import SlackPlugin
from .google_calendar import GoogleCalendarPlugin
from .gmail import GmailPlugin
from .gitlab import GitLabPlugin
from .github import GitHubPlugin

PLUGIN_REGISTRY: dict[str, type[BasePlugin]] = {
    "slack": SlackPlugin,
    "google_calendar": GoogleCalendarPlugin,
    "gmail": GmailPlugin,
    "gitlab": GitLabPlugin,
    "github": GitHubPlugin,
}

__all__ = [
    "BasePlugin",
    "NotificationState",
    "PLUGIN_REGISTRY",
    "SlackPlugin",
    "GoogleCalendarPlugin",
    "GmailPlugin",
    "GitLabPlugin",
    "GitHubPlugin",
]
