from __future__ import annotations

import getpass
import json
import os
import sys
from pathlib import Path

HOME = Path.home()

IS_MACOS = sys.platform == "darwin"

# On macOS, Claude Code stores the live OAuth credentials in the system Keychain
# instead of an on-disk file. If `~/.claude/.credentials.json` exists, Claude Code
# reads it in preference to the Keychain — we honor the same precedence.
KEYCHAIN_SERVICE = "Claude Code-credentials"
try:
    KEYCHAIN_ACCOUNT = getpass.getuser()
except Exception:
    KEYCHAIN_ACCOUNT = os.environ.get("USER") or os.environ.get("USERNAME") or ""

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
