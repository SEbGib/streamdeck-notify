from enum import StrEnum


class Icons(StrEnum):
    MAIN = "main"
    SLACK = "slack"
    GITHUB = "github"
    GITLAB = "gitlab"
    GMAIL = "gmail"
    CALENDAR = "calendar"
    CICD = "cicd"
    DOCKER = "docker"
    WEATHER = "weather"
    SYSTEM = "system"
    SPOTIFY = "spotify"
    POMODORO = "pomodoro"


class Colors(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"


# Source registry: id -> (display name, default URL, icon key)
SOURCES = {
    "slack": ("Slack", "https://app.slack.com", Icons.SLACK),
    "google_calendar": ("Agenda", "https://calendar.google.com", Icons.CALENDAR),
    "gmail": ("Gmail", "https://mail.google.com", Icons.GMAIL),
    "gitlab": ("GitLab", "https://gitlab.com/dashboard/merge_requests", Icons.GITLAB),
    "github": ("GitHub", "https://github.com/notifications", Icons.GITHUB),
    "cicd": ("CI/CD", "https://gitlab.com/dashboard/pipelines", Icons.CICD),
    "docker": ("Docker", "", Icons.DOCKER),
    "weather": ("Météo", "", Icons.WEATHER),
    "system": ("Système", "", Icons.SYSTEM),
    "spotify": ("Spotify", "", Icons.SPOTIFY),
}

SOURCE_NAMES = {k: v[0] for k, v in SOURCES.items()}
SOURCE_URLS = {k: v[1] for k, v in SOURCES.items()}
SOURCE_ICONS = {k: v[2] for k, v in SOURCES.items()}
