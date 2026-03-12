from enum import StrEnum


class Icons(StrEnum):
    MAIN = "main"
    SLACK = "slack"
    GITHUB = "github"
    GITLAB = "gitlab"
    GMAIL = "gmail"
    CALENDAR = "calendar"


class Colors(StrEnum):
    URGENT = "urgent"
    NORMAL = "normal"


# Source registry: id -> display name
SOURCES = {
    "slack": "Slack",
    "google_calendar": "Agenda",
    "gmail": "Gmail",
    "gitlab": "GitLab",
    "github": "GitHub",
}
