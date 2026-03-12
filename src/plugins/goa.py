"""GNOME Online Accounts helper — extracts OAuth2 tokens via D-Bus.

Works with any Google account configured in GNOME Settings.
No need to create your own OAuth app — uses GNOME's built-in credentials.
"""

from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

GOA_BUS = "org.gnome.OnlineAccounts"
GOA_PATH = "/org/gnome/OnlineAccounts"


def find_google_account(identity: str | None = None) -> str | None:
    """Find the GOA object path for a Google account.

    Args:
        identity: Optional email to match. If None, returns the first Google account.

    Returns:
        D-Bus object path like /org/gnome/OnlineAccounts/Accounts/account_XXX, or None.
    """
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", GOA_BUS,
                "--object-path", GOA_PATH,
                "--method", "org.freedesktop.DBus.ObjectManager.GetManagedObjects",
            ],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            logger.error("GOA GetManagedObjects failed: %s", result.stderr)
            return None

        output = result.stdout

        accounts = re.findall(
            r"'(/org/gnome/OnlineAccounts/Accounts/[^']+)'", output
        )

        for path in accounts:
            # Check if this path's section contains google provider
            idx = output.find(path)
            # Get a chunk after the path
            chunk = output[idx:idx + 2000]
            if "'google'" not in chunk:
                continue
            if identity and identity not in chunk:
                continue
            return path

        logger.warning("No Google account found in GNOME Online Accounts")
        return None

    except Exception:
        logger.exception("Failed to query GNOME Online Accounts")
        return None


def get_access_token(account_path: str) -> str | None:
    """Get an OAuth2 access token from GOA.

    GOA handles refresh automatically — we just call GetAccessToken.

    Returns:
        Access token string, or None on failure.
    """
    try:
        result = subprocess.run(
            [
                "gdbus", "call", "--session",
                "--dest", GOA_BUS,
                "--object-path", account_path,
                "--method", "org.gnome.OnlineAccounts.OAuth2Based.GetAccessToken",
            ],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode != 0:
            logger.error("GOA GetAccessToken failed: %s", result.stderr)
            return None

        # Output format: ('ya29.xxxxx', 3599)
        token = result.stdout.strip()
        token = token.lstrip("('").split("',")[0]
        return token

    except Exception:
        logger.exception("Failed to get GOA access token")
        return None


def get_google_token(identity: str | None = None) -> str | None:
    """Convenience: find Google account and get its access token."""
    path = find_google_account(identity)
    if not path:
        return None
    return get_access_token(path)
