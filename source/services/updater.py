"""
Auto-update check for Serato Sidecar.

Fetches a small JSON manifest from the project's GitHub releases page and
compares the advertised version against the currently running version. If a
newer version is available, returns an ``UpdateInfo`` with the platform-
specific download URL so the caller can open it in a browser.

Offline, DNS failures, timeouts, and malformed manifests are all treated as
"no update available" — not errors. DJs running this app at gigs are expected
to be on flaky / offline networks, so a failed update check must never
surface as a warning and must never block startup.

This module is intentionally network-blocking and is meant to be called from
a background daemon thread. See ``source/app.py`` for the caller. The thread
pattern mirrors ``source/services/crate_sync.py``.
"""
from __future__ import annotations

import json
import logging
import platform
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Optional

from packaging.version import InvalidVersion, Version

logger = logging.getLogger(__name__)

# Stable URL via the floating `latest` tag that the release workflow re-points
# on every release. Single source of truth — change here if the repo moves.
MANIFEST_URL = (
    "https://github.com/grantcomply/sidecar/releases/download/latest/latest.json"
)

REQUEST_TIMEOUT = 5  # seconds; keep tight so the UI never waits on a bad network.


def _detect_platform_key() -> str:
    """Map the current OS to the manifest's asset key.

    Uses ``platform.system()`` (which returns a plain ``str``) rather than
    ``sys.platform`` (typed as a ``Literal`` on each OS) so that all branches
    remain reachable to static type checkers regardless of the host OS.
    """
    system = platform.system()
    if system == "Windows":
        return "windows"
    if system == "Darwin":
        return "macos"
    return "linux"


PLATFORM_KEY = _detect_platform_key()


@dataclass(frozen=True)
class UpdateInfo:
    """Details about an available update returned from the manifest."""

    version: str
    notes: str
    url: str


def check_for_update(current_version: str) -> Optional[UpdateInfo]:
    """Fetch the release manifest and return an ``UpdateInfo`` if newer.

    Args:
        current_version: The version string of the running application
            (e.g. ``"0.1.0"``). Compared against the manifest's ``version``
            field using :class:`packaging.version.Version` so that
            ``0.1.10`` correctly sorts after ``0.1.2``.

    Returns:
        ``UpdateInfo`` if the manifest advertises a strictly newer version
        and an asset URL exists for the current platform. ``None`` in every
        other case — including offline, timeout, malformed manifest, missing
        keys, or the manifest simply being current or older. Never raises.
    """
    try:
        with urllib.request.urlopen(MANIFEST_URL, timeout=REQUEST_TIMEOUT) as resp:
            raw = resp.read()
    except urllib.error.URLError as e:
        logger.info("Update check: manifest unreachable (%s)", e.reason)
        return None
    except socket.timeout:
        logger.info("Update check: manifest request timed out after %ds", REQUEST_TIMEOUT)
        return None
    except OSError as e:
        logger.info("Update check: network error (%s)", e)
        return None

    try:
        manifest = json.loads(raw)
    except json.JSONDecodeError as e:
        logger.info("Update check: manifest is not valid JSON (%s)", e)
        return None

    try:
        manifest_version = manifest["version"]
        assets = manifest["assets"]
    except (KeyError, TypeError) as e:
        logger.info("Update check: manifest missing required fields (%s)", e)
        return None

    try:
        latest = Version(manifest_version)
        current = Version(current_version)
    except InvalidVersion as e:
        logger.info("Update check: invalid version string (%s)", e)
        return None

    if latest <= current:
        logger.info(
            "Update check: no update available (latest=%s, current=%s)",
            manifest_version,
            current_version,
        )
        return None

    if not isinstance(assets, dict) or PLATFORM_KEY not in assets:
        logger.info(
            "Update check: manifest has no asset for platform %r", PLATFORM_KEY,
        )
        return None

    notes = manifest.get("notes", "") if isinstance(manifest, dict) else ""
    update = UpdateInfo(
        version=str(manifest_version),
        notes=str(notes),
        url=str(assets[PLATFORM_KEY]),
    )
    logger.info(
        "Update check: new version %s available (current=%s)",
        update.version,
        current_version,
    )
    return update
