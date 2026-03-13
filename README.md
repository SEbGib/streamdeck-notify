# streamdeck-notify

Stream Deck notification center for Linux — turns your Stream Deck into a live dashboard showing notifications from Slack, GitLab, GitHub, Gmail, and Google Calendar.

## Architecture

```
┌─────────────────────────┐     HTTP :9120     ┌──────────────────────┐
│   notify-bridge daemon  │ ◄────────────────► │  StreamController    │
│                         │   GET /status       │  (Flatpak)           │
│  Pollers:               │   POST /action/:id  │                      │
│  • Slack (D-Bus)        │                     │  Plugin:             │
│  • GitLab (glab CLI)    │                     │  • NotifyCenter      │
│  • GitHub (gh CLI)      │                     │  • Icons + badges    │
│  • Google Calendar      │                     │  • Click → open URL  │
│  • Gmail                │                     │                      │
└─────────────────────────┘                     └──────────────────────┘
```

The **bridge** runs outside Flatpak with full system access (D-Bus, CLI tools, GNOME Online Accounts).
The **StreamController plugin** fetches state via HTTP and updates button displays.

## Quick Start

```bash
# 1. Install dependencies
./setup.sh

# 2. Start the bridge
make bridge

# 3. Install the StreamController plugin
make install-plugin

# 4. (Re)start StreamController
# Add "Notification" actions to buttons and select sources
```

## Setup

### Prerequisites

- Stream Deck (tested with MK.2)
- [StreamController](https://flathub.org/apps/com.core447.StreamController) (Flatpak)
- Python 3.11+
- `glab` CLI (authenticated) for GitLab
- `gh` CLI (authenticated) for GitHub

### Slack

**No API token needed.** The bridge monitors desktop notifications via D-Bus.
Just have the Slack desktop app running and receiving notifications.

To use the Slack API instead (enterprise with API access):
```yaml
# config.yaml
plugins:
  slack:
    method: "api"
    token: "${SLACK_TOKEN}"
```

### Google Calendar & Gmail

**No OAuth app needed.** Uses [GNOME Online Accounts](https://wiki.gnome.org/Projects/GnomeOnlineAccounts) — just add your Google account in GNOME Settings with Calendar and Mail enabled.

The bridge extracts OAuth2 tokens via D-Bus (`org.gnome.OnlineAccounts.OAuth2Based`), so it works even on enterprise Google Workspace where creating custom OAuth apps is restricted.

- **Calendar**: uses Google Calendar REST API with GOA token
- **Gmail**: uses IMAP + XOAUTH2 with GOA token (Gmail REST API is not enabled in GNOME's OAuth project)

To filter a specific account (if you have multiple Google accounts in GNOME):
```yaml
# config.yaml
plugins:
  google_calendar:
    identity: "user@example.com"
  gmail:
    identity: "user@example.com"
```

<details>
<summary>Manual OAuth setup (alternative, if GOA is not available)</summary>

```bash
source .venv/bin/activate
python -m src.google_setup
```
Requires creating an OAuth app in Google Cloud Console.
</details>

### GitLab & GitHub

Uses existing CLI authentication — no extra config needed:
- `glab auth login` for GitLab
- `gh auth login` for GitHub

## Configuration

Edit `config.yaml` to customize button mapping, polling interval, and plugin settings.

## Systemd Service

```bash
# Enable auto-start at login
make enable

# Check status
make status

# View logs
make logs

# Disable
make disable
```

## Post-install: manual steps

These are **not automated** by `setup.sh` — reproduce manually after a fresh install.

### 1. GNOME Online Accounts (Calendar + Gmail)

Add your Google account in **GNOME Settings → Online Accounts** with Calendar and Mail enabled.
The bridge auto-detects the GOA account via D-Bus.

### 2. CLI authentication

```bash
glab auth login          # GitLab
gh auth login            # GitHub
```

### 3. Chrome PWAs (optional, for focus-existing-window on click)

Install as PWA from Chrome (⋮ → More tools → Create shortcut → Open as window):
- Slack: https://app.slack.com
- Gmail: https://mail.google.com
- Google Calendar: https://calendar.google.com

The plugin auto-detects PWAs from `~/.local/share/applications/chrome-*.desktop`.

### 4. StreamController pages

Page configs are backed up in `streamcontroller-pages/`. To restore:

```bash
cp streamcontroller-pages/*.json ~/.var/app/com.core447.StreamController/data/pages/
```

**Home page layout** (Stream Deck MK.2: 5 cols × 3 rows):

| | Col 0 | Col 1 | Col 2 | Col 3 | Col 4 |
|---|-------|-------|-------|-------|-------|
| **Row 0** | GitLab | Calendar | Gmail | Slack | GitHub |
| **Row 1** | CI/CD | Docker | Weather | CPU | RAM |
| **Row 2** | Spotify | — | — | Reset All | Pomodoro |

**Meeting page**: auto-switches when calendar shows "MAINTENANT", button at 4×2 returns to Home.

### 5. Slack workspace URL

Update the Slack URL in `Home.json` to match your workspace:
```json
"action_url": "https://app.slack.com/client/YOUR_WORKSPACE_ID"
```

## Development

```
streamdeck-notify/
├── src/
│   ├── bridge.py              # HTTP bridge daemon
│   ├── daemon.py              # Standalone mode (no StreamController)
│   ├── deck.py                # Stream Deck hardware interface
│   ├── renderer.py            # Pillow image renderer (standalone)
│   ├── google_setup.py        # Google OAuth setup helper
│   └── plugins/
│       ├── base.py            # Plugin interface
│       ├── slack.py           # Slack (D-Bus + API)
│       ├── gitlab.py          # GitLab (glab CLI)
│       ├── github.py          # GitHub (gh CLI)
│       ├── goa.py             # GNOME Online Accounts helper
│       ├── gmail.py           # Gmail (IMAP + GOA)
│       ├── google_calendar.py # Google Calendar (REST + GOA)
│       ├── docker_status.py   # Docker containers (docker ps)
│       ├── weather.py         # Weather (Open-Meteo, no API key)
│       ├── system.py          # System CPU/RAM
│       └── spotify.py         # Spotify/media (MPRIS2 D-Bus)
├── streamcontroller-plugin/   # StreamController plugin
│   ├── main.py
│   ├── manifest.json
│   ├── actions/NotifyAction.py
│   ├── internal/bridge_client.py
│   └── assets/                # Source icons
├── config.yaml
├── Makefile
└── systemd/
```

## License

MIT
