"""Utilities for running commands on the host from Flatpak sandbox."""

from __future__ import annotations

import subprocess


def host_run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a command on the host via flatpak-spawn.

    Adds --directory=/ to avoid CWD resolution failure
    (the Flatpak sandbox CWD doesn't exist on the host).
    """
    return subprocess.run(
        ["flatpak-spawn", "--host", "--directory=/"] + cmd,
        capture_output=True, text=True, timeout=3, **kwargs,
    )
