from .base import BasePlugin, NotificationState
from .slack import SlackPlugin
from .google_calendar import GoogleCalendarPlugin
from .gmail import GmailPlugin
from .gitlab import GitLabPlugin
from .github import GitHubPlugin
from .cicd import CICDPlugin
from .docker_status import DockerStatusPlugin
from .weather import WeatherPlugin
from .system import SystemPlugin
from .spotify import SpotifyPlugin
from .system_detail import DiskPlugin, LoadAvgPlugin, UptimePlugin, NetTXPlugin, NetRXPlugin

PLUGIN_REGISTRY: dict[str, type[BasePlugin]] = {
    "slack": SlackPlugin,
    "google_calendar": GoogleCalendarPlugin,
    "gmail": GmailPlugin,
    "gitlab": GitLabPlugin,
    "github": GitHubPlugin,
    "cicd": CICDPlugin,
    "docker": DockerStatusPlugin,
    "weather": WeatherPlugin,
    "system": SystemPlugin,
    "system_cpu": SystemPlugin,
    "system_ram": SystemPlugin,
    "spotify": SpotifyPlugin,
    "disk": DiskPlugin,
    "load_avg": LoadAvgPlugin,
    "uptime": UptimePlugin,
    "net_tx": NetTXPlugin,
    "net_rx": NetRXPlugin,
}

__all__ = [
    "BasePlugin",
    "NotificationState",
    "PLUGIN_REGISTRY",
]
