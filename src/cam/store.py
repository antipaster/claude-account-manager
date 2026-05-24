from __future__ import annotations

import json
import os
import shutil
import time
from datetime import datetime
from pathlib import Path

from . import config
from .models import Account


class CamError(Exception):
    """User-facing error"""


# --- low level file IO ----------------------------------------------------------
def _read_json(path: Path) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _atomic_write(path: Path, text: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}")
    with open(tmp, "w", encoding="utf-8", newline="") as fh:
        fh.write(text)
    os.replace(tmp, path)  # atomic on Windows within a volume


def _write_config(obj: dict) -> None:  # preserve Claude Code's 2-space indent
    _atomic_write(config.CONFIG_PATH, json.dumps(obj, ensure_ascii=False, indent=2))


def _write_creds(obj: dict) -> None:  # preserve Claude Code's minified format
    _atomic_write(config.CREDS_PATH, json.dumps(obj, ensure_ascii=False, separators=(",", ":")))


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "unknown"


# --- live (active) account ------------------------------------------------------
def read_live() -> tuple[dict, dict]:
    cfg = _read_json(config.CONFIG_PATH) if config.CONFIG_PATH.exists() else {}
    creds = _read_json(config.CREDS_PATH) if config.CREDS_PATH.exists() else {}
    return cfg, creds


def current_account() -> Account | None:
    cfg, creds = read_live()
    identity = cfg.get("oauthAccount")
    claude_oauth = creds.get("claudeAiOauth")
    if not identity and not claude_oauth:
        return None
    identity = identity or {}
    acct_id = identity.get("accountUuid") or cfg.get("userID") or "current"
    return Account(
        id=acct_id,
        label=identity.get("displayName") or identity.get("emailAddress") or "current",
        email=identity.get("emailAddress", ""),
        identity=identity,
        user_id=cfg.get("userID"),
        claude_oauth=claude_oauth or {},
        added_at="",
    )


def live_access_token() -> str | None:
    _, creds = read_live()
    return (creds.get("claudeAiOauth") or {}).get("accessToken")


# --- the store ------------------------------------------------------------------
def list_accounts() -> list[Account]:
    if not config.ACCOUNTS_DIR.exists():
        return []
    out: list[Account] = []
    for p in sorted(config.ACCOUNTS_DIR.glob("*.json")):
        try:
            out.append(Account.from_dict(_read_json(p), p))
        except Exception:
            continue
    out.sort(key=lambda a: (a.last_used_at or "", a.label.lower()), reverse=True)
    return out


def get_account(acct_id: str) -> Account | None:
    p = config.ACCOUNTS_DIR / f"{_safe(acct_id)}.json"
    return Account.from_dict(_read_json(p), p) if p.exists() else None


def _write_record(rec: dict) -> Account:
    path = config.ACCOUNTS_DIR / f"{_safe(rec['id'])}.json"
    _atomic_write(path, json.dumps(rec, ensure_ascii=False, indent=2))
    return Account.from_dict(rec, path)


def save_current(label: str | None = None) -> Account:
    cfg, creds = read_live()
    identity = cfg.get("oauthAccount")
    claude_oauth = creds.get("claudeAiOauth")
    if not identity or not claude_oauth:
        raise CamError("No active Claude account found — is Claude Code logged in?")

    acct_id = identity.get("accountUuid") or cfg.get("userID") or "current"
    email = identity.get("emailAddress", "")
    path = config.ACCOUNTS_DIR / f"{_safe(acct_id)}.json"
    existing = _read_json(path) if path.exists() else {}
    now = _now_iso()
    return _write_record({
        "id": acct_id,
        "label": label or existing.get("label") or identity.get("displayName") or email or acct_id,
        "email": email,
        "identity": identity,
        "userID": cfg.get("userID"),
        "claudeAiOauth": claude_oauth,
        "added_at": existing.get("added_at") or now,
        "updated_at": now,
        "last_used_at": existing.get("last_used_at"),
    })


def switch_to(acct_id: str) -> Account:
    acct = get_account(acct_id)
    if acct is None:
        raise CamError(f"No saved account with id {acct_id!r}.")
    if not acct.claude_oauth or not acct.identity:
        raise CamError("That saved account is missing its tokens or identity.")

    backup_live("pre-switch")

    cfg, creds = read_live()
    creds["claudeAiOauth"] = acct.claude_oauth  # keep live mcpOAuth
    _write_creds(creds)

    cfg["oauthAccount"] = acct.identity
    if acct.user_id is not None:
        cfg["userID"] = acct.user_id
    _write_config(cfg)

    acct.last_used_at = _now_iso()
    _atomic_write(acct.path, json.dumps(acct.to_dict(), ensure_ascii=False, indent=2))
    return acct


def rename_account(acct_id: str, label: str) -> Account:
    acct = get_account(acct_id)
    if acct is None:
        raise CamError(f"No saved account with id {acct_id!r}.")
    acct.label = label.strip() or acct.label
    _atomic_write(acct.path, json.dumps(acct.to_dict(), ensure_ascii=False, indent=2))
    return acct


def delete_account(acct_id: str) -> None:
    p = config.ACCOUNTS_DIR / f"{_safe(acct_id)}.json"
    if p.exists():
        p.unlink()


# --- tokens & login -------------------------------------------------------------
def valid_access_token(acct: Account) -> str:
    """Usable access token for a *saved* account; refreshes + saves back if stale.
    Never call for the active account — use live_access_token() instead."""
    from . import oauth

    co = acct.claude_oauth or {}
    exp = co.get("expiresAt") or 0
    if co.get("accessToken") and (exp / 1000 - time.time()) > 60:
        return co["accessToken"]

    rt = co.get("refreshToken")
    if not rt:
        if co.get("accessToken"):
            return co["accessToken"]
        raise CamError("No usable token stored for this account.")

    bundle = oauth.refresh_token(rt)
    merged = dict(co)
    for key, val in bundle.items():
        if val is not None:
            merged[key] = val
    acct.claude_oauth = merged
    if acct.path:
        _atomic_write(acct.path, json.dumps(acct.to_dict(), ensure_ascii=False, indent=2))
    return acct.claude_oauth["accessToken"]


def build_identity_from_profile(profile: dict) -> dict:
    acct = profile.get("account", {}) or {}
    org = profile.get("organization", {}) or {}
    return {
        "accountUuid": acct.get("uuid"),
        "emailAddress": acct.get("email"),
        "organizationUuid": org.get("uuid"),
        "displayName": acct.get("display_name") or acct.get("full_name"),
        "organizationName": org.get("name"),
        "organizationType": org.get("organization_type"),
        "billingType": org.get("billing_type"),
        "organizationRole": None,
        "workspaceRole": None,
        "organizationRateLimitTier": org.get("rate_limit_tier"),
        "userRateLimitTier": None,
        "seatTier": org.get("seat_tier"),
        "hasExtraUsageEnabled": org.get("has_extra_usage_enabled"),
        "accountCreatedAt": acct.get("created_at"),
        "subscriptionCreatedAt": org.get("subscription_created_at"),
    }


def add_account_from_login(bundle: dict, label: str | None = None) -> Account:
    """Save a brand-new account from a fresh login. Does NOT touch live files."""
    from . import oauth

    profile = oauth.get_profile(bundle["accessToken"])
    identity = build_identity_from_profile(profile)
    acct_obj = profile.get("account", {}) or {}
    org = profile.get("organization", {}) or {}

    bundle = dict(bundle)
    bundle.setdefault(
        "subscriptionType",
        "max" if acct_obj.get("has_claude_max") else ("pro" if acct_obj.get("has_claude_pro") else None),
    )
    bundle.setdefault("rateLimitTier", org.get("rate_limit_tier"))

    acct_id = identity.get("accountUuid") or "unknown"
    email = identity.get("emailAddress", "")
    path = config.ACCOUNTS_DIR / f"{_safe(acct_id)}.json"
    existing = _read_json(path) if path.exists() else {}
    now = _now_iso()
    return _write_record({
        "id": acct_id,
        "label": label or existing.get("label") or identity.get("displayName") or email or acct_id,
        "email": email,
        "identity": identity,
        "userID": existing.get("userID"),
        "claudeAiOauth": bundle,
        "added_at": existing.get("added_at") or now,
        "updated_at": now,
        "last_used_at": existing.get("last_used_at"),
    })


# --- backups --------------------------------------------------------------------
def backup_live(tag: str = "backup") -> Path:
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    d = config.BACKUPS_DIR / f"{ts}-{tag}"
    d.mkdir(parents=True, exist_ok=True)
    if config.CREDS_PATH.exists():
        shutil.copy2(config.CREDS_PATH, d / "credentials.json")
    if config.CONFIG_PATH.exists():
        cfg = _read_json(config.CONFIG_PATH)
        slim = {"oauthAccount": cfg.get("oauthAccount"), "userID": cfg.get("userID")}
        _atomic_write(d / "identity.json", json.dumps(slim, ensure_ascii=False, indent=2))
    _prune_backups()
    return d


def _prune_backups() -> None:
    if not config.BACKUPS_DIR.exists():
        return
    keep = config.load_settings().get("backups_to_keep", 30)
    dirs = sorted([p for p in config.BACKUPS_DIR.iterdir() if p.is_dir()])
    for old in dirs[:-keep] if keep > 0 else []:
        shutil.rmtree(old, ignore_errors=True)
