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

The **bridge** runs outside Flatpak with full system access (D-Bus, CLI tools, Google APIs).
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

```bash
# Interactive setup — opens browser for OAuth
source .venv/bin/activate
python -m src.google_setup
```

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
│       ├── gmail.py           # Gmail API
│       └── google_calendar.py # Google Calendar API
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
