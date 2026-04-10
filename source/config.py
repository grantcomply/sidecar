import os
from pathlib import Path

from platformdirs import user_data_dir as _platform_user_data_dir

# source/ package directory and project root (one level up)
SOURCE_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(SOURCE_DIR)

_APP_NAME = "SeratoSidecar"


def user_data_dir() -> Path:
    """Return the platform-appropriate user data directory for this app.

    Creates the directory on first access. Paths:
        Windows: %APPDATA%\\SeratoSidecar
        macOS:   ~/Library/Application Support/SeratoSidecar
        Linux:   ~/.config/serato-sidecar  (XDG fallback)
    """
    # appauthor=False suppresses the extra vendor-name folder level on Windows.
    # roaming=True selects %APPDATA% (Roaming) over %LOCALAPPDATA% on Windows;
    # no-op on macOS / Linux.
    path = Path(_platform_user_data_dir(_APP_NAME, appauthor=False, roaming=True))
    path.mkdir(parents=True, exist_ok=True)
    return path


ENV_FILE = user_data_dir() / "settings.env"

FALLBACK_SUBCRATES_DIR = str(Path.home() / "Music" / "_Serato_" / "Subcrates")


def _migrate_legacy_env() -> None:
    """One-time migration of the old project-root .env to user data dir.

    Silent no-op if there's nothing to migrate or the destination already exists.
    """
    legacy = Path(PROJECT_ROOT) / ".env"
    if not legacy.is_file() or ENV_FILE.exists():
        return
    try:
        legacy.replace(ENV_FILE)
    except OSError:
        # Non-fatal: a stale legacy file shouldn't prevent startup.
        pass


_migrate_legacy_env()


def _load_env() -> dict[str, str]:
    """Read settings env file into a dict. Returns empty dict if file doesn't exist."""
    env = {}
    if ENV_FILE.is_file():
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return env


def _save_env(env: dict[str, str]):
    """Write a dict back to the settings env file."""
    with open(ENV_FILE, "w", encoding="utf-8") as f:
        for key, value in sorted(env.items()):
            f.write(f"{key}={value}\n")


def get_subcrates_dir() -> str:
    """Get the Serato subcrates dir from settings, falling back to the hardcoded default."""
    env = _load_env()
    return env.get("SERATO_SUBCRATES_DIR", FALLBACK_SUBCRATES_DIR)


def save_subcrates_dir(path: str):
    """Persist the Serato subcrates dir to settings."""
    env = _load_env()
    env["SERATO_SUBCRATES_DIR"] = path
    _save_env(env)

SUGGESTION_WEIGHTS = {
    "key": 0.45,
    "energy": 0.35,
    "bpm": 0.20,
}

BPM_MAX_DIFF = 20
ENERGY_SEVERE_PENALTY_THRESHOLD = 3
MAX_SUGGESTIONS = 30

# Standard Camelot wheel colors — maps each key to a distinct hue
CAMELOT_COLORS = {
    "1A": "#E8637A", "1B": "#FF7A8F",
    "2A": "#E87C4A", "2B": "#FFB07A",
    "3A": "#E8A83A", "3B": "#FFD06B",
    "4A": "#D4C84A", "4B": "#E8DC5E",
    "5A": "#8FD45A", "5B": "#A3E86E",
    "6A": "#5AD47A", "6B": "#6EE88E",
    "7A": "#4AC8A8", "7B": "#5EDCBC",
    "8A": "#4AB8D4", "8B": "#5ECCE8",
    "9A": "#5A8FD4", "9B": "#6EA3E8",
    "10A": "#7A5AD4", "10B": "#8E6EE8",
    "11A": "#A84AD4", "11B": "#BC5EE8",
    "12A": "#D44A8F", "12B": "#E85EA3",
}


def energy_color(level: int) -> str:
    """Return a color for the energy level (1-8 scale). Cool→hot."""
    return {
        1: "#4AB8D4", 2: "#5ECCE8", 3: "#6BDB6B", 4: "#8FD45A",
        5: "#C8E650", 6: "#FFB732", 7: "#FF8C42", 8: "#FF5C5C",
    }.get(level, "#ffffff")
