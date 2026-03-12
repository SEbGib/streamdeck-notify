"""Interactive Google OAuth setup.

Run this once to authorize Calendar and Gmail access:
    python -m src.google_setup

It will open a browser for Google OAuth consent, then save the token.
"""

import sys
from pathlib import Path

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]

CONFIG_DIR = Path("~/.config/streamdeck-notify").expanduser()
CREDS_FILE = CONFIG_DIR / "google_credentials.json"
TOKEN_FILE = CONFIG_DIR / "google_token.json"


def setup():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    if not CREDS_FILE.exists():
        print(f"""
Google OAuth Setup
==================

1. Go to https://console.cloud.google.com/apis/credentials
2. Create a project (or select existing)
3. Enable these APIs:
   - Google Calendar API
   - Gmail API
4. Create OAuth 2.0 credentials → "Desktop application"
5. Download the JSON file and save it as:
   {CREDS_FILE}

Then run this script again.
""")
        sys.exit(1)

    try:
        from google.oauth2.credentials import Credentials
        from google_auth_oauthlib.flow import InstalledAppFlow
        from google.auth.transport.requests import Request
    except ImportError:
        print("Missing dependencies. Run: pip install google-api-python-client google-auth-oauthlib")
        sys.exit(1)

    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("Refreshing expired token...")
            creds.refresh(Request())
        else:
            print("Opening browser for Google authorization...")
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_FILE.write_text(creds.to_json())
        print(f"Token saved to {TOKEN_FILE}")

    # Verify
    from googleapiclient.discovery import build

    cal = build("calendar", "v3", credentials=creds)
    events = cal.events().list(calendarId="primary", maxResults=1).execute()
    print(f"Calendar OK: {len(events.get('items', []))} upcoming event(s)")

    gmail = build("gmail", "v1", credentials=creds)
    labels = gmail.users().labels().get(userId="me", id="INBOX").execute()
    print(f"Gmail OK: {labels.get('messagesUnread', 0)} unread message(s)")

    print("\nSetup complete! Calendar and Gmail plugins are ready.")


if __name__ == "__main__":
    setup()
