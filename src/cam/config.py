from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path.home()


CONFIG_PATH = HOME / ".claude.json"
CREDS_PATH = HOME / ".claude" / ".credentials.json"


STORE = Path(os.environ.get("CAM_HOME") or (HOME / ".claude-account-manager"))
ACCOUNTS_DIR = STORE / "accounts"
BACKUPS_DIR = STORE / "backups"
SETTINGS_PATH = STORE / "settings.json"

DEFAULT_SETTINGS: dict = {
    "theme": "claude",
    "confirm_switch": True,
    "auto_usage": True,
    "backups_to_keep": 30,
}


def load_settings() -> dict:
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
    except Exception:
        data = {}
    settings = dict(DEFAULT_SETTINGS)
    settings.update({k: v for k, v in data.items() if k in DEFAULT_SETTINGS})
    return settings


def save_settings(settings: dict) -> None:
    STORE.mkdir(parents=True, exist_ok=True)
    clean = {k: settings.get(k, v) for k, v in DEFAULT_SETTINGS.items()}
    SETTINGS_PATH.write_text(json.dumps(clean, indent=2), encoding="utf-8")
