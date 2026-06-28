from __future__ import annotations

import json
import os
import shutil
import subprocess
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


# --- live credentials (file on Linux/Windows, Keychain on macOS) ----------------
def _keychain_read() -> dict | None:
    """Read the Claude Code OAuth blob from the macOS Keychain. None if missing."""
    try:
        res = subprocess.run(
            ["security", "find-generic-password",
             "-a", config.KEYCHAIN_ACCOUNT, "-s", config.KEYCHAIN_SERVICE, "-w"],
            capture_output=True, text=True, timeout=15,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if res.returncode != 0:
        return None
    text = res.stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _keychain_write(text: str) -> None:
    try:
        subprocess.run(
            ["security", "add-generic-password", "-U",
             "-a", config.KEYCHAIN_ACCOUNT, "-s", config.KEYCHAIN_SERVICE, "-w", text],
            check=True, capture_output=True, text=True, timeout=15,
        )
    except FileNotFoundError as exc:
        raise CamError("`security` not found — required for macOS Keychain access.") from exc
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or "").strip() or str(exc)
        raise CamError(f"Failed to write credentials to macOS Keychain: {msg}") from exc


def _read_creds() -> dict:
    """Live OAuth blob. On macOS, falls back from the file to the Keychain so we
    match Claude Code's precedence rule (an on-disk credentials file overrides)."""
    if config.CREDS_PATH.exists():
        try:
            return _read_json(config.CREDS_PATH)
        except Exception:
            pass
    if config.IS_MACOS:
        data = _keychain_read()
        if data is not None:
            return data
    return {}


def _write_creds(obj: dict) -> None:
    """Persist the live OAuth blob in Claude Code's minified shape, to whichever
    backing store Claude Code is reading from on this platform."""
    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"))
    # If the file exists Claude Code reads it first, on every platform — keep it
    # in sync. Otherwise on macOS write to the Keychain.
    if config.CREDS_PATH.exists() or not config.IS_MACOS:
        _atomic_write(config.CREDS_PATH, text)
        return
    _keychain_write(text)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name) or "unknown"


# --- live (active) account ------------------------------------------------------
def read_live() -> tuple[dict, dict]:
    cfg = _read_json(config.CONFIG_PATH) if config.CONFIG_PATH.exists() else {}
    return cfg, _read_creds()


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


# --- portable export / import ---------------------------------------------------
# Saved account records are platform-independent: they hold the OAuth tokens and
# identity verbatim, with no reference to where Claude Code keeps the live creds
# (file vs. Keychain). That makes them safe to carry between Windows, macOS and
# Linux — export bundles them into one file, import writes them back.
EXPORT_VERSION = 1


def _restrict_permissions(path: Path) -> None:
    """Best-effort owner-only lock-down — the file carries live OAuth tokens.
    No-op where the platform/filesystem ignores POSIX modes (e.g. most of Windows)."""
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def export_accounts(dest: Path) -> int:
    """Write every saved account to a single portable JSON bundle at `dest`.

    The bundle can be copied to another machine and read back with
    `import_accounts`, regardless of OS. Returns the number of accounts written.
    The file contains live OAuth tokens — treat it as a secret."""
    accounts = [a.to_dict() for a in list_accounts()]
    bundle = {
        "cam_export_version": EXPORT_VERSION,
        "exported_at": _now_iso(),
        "accounts": accounts,
    }
    dest = Path(dest).expanduser()
    _atomic_write(dest, json.dumps(bundle, ensure_ascii=False, indent=2))
    _restrict_permissions(dest)
    return len(accounts)


def _extract_records(data) -> list[dict]:
    """Pull account records out of an exported bundle, a bare list, or a single
    account record — so imports are forgiving about exactly what they're handed."""
    if isinstance(data, dict) and isinstance(data.get("accounts"), list):
        return [r for r in data["accounts"] if isinstance(r, dict)]
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict) and (data.get("id") or data.get("claudeAiOauth")):
        return [data]
    return []


def import_accounts(src: Path, overwrite: bool = False) -> tuple[int, int]:
    """Import accounts from a file written by `export_accounts` (also accepts a
    bare list of records or a single record). Existing accounts are kept unless
    `overwrite` is set. Returns (imported, skipped)."""
    src = Path(src).expanduser()
    if not src.exists():
        raise CamError(f"No such file: {src}")
    try:
        data = _read_json(src)
    except Exception as exc:
        raise CamError(f"Could not read {src}: {exc}") from exc

    records = _extract_records(data)
    if not records:
        raise CamError(f"No accounts found in {src.name}.")

    imported = skipped = 0
    for rec in records:
        acct_id = rec.get("id") or (rec.get("identity") or {}).get("accountUuid")
        if not acct_id or not rec.get("claudeAiOauth"):
            skipped += 1
            continue
        path = config.ACCOUNTS_DIR / f"{_safe(acct_id)}.json"
        if path.exists() and not overwrite:
            skipped += 1
            continue
        rec = dict(rec, id=acct_id)
        _write_record(rec)
        imported += 1
    return imported, skipped


# --- tokens & login -------------------------------------------------------------
def valid_access_token(acct: Account) -> str:
    """Usable access token for a *saved* account; refreshes + saves back if stale.
    Never call for the active account — use live_access_token() instead."""
    co = acct.claude_oauth or {}
    exp = co.get("expiresAt") or 0
    if co.get("accessToken") and (exp / 1000 - time.time()) > 60:
        return co["accessToken"]
    if not co.get("refreshToken"):
        if co.get("accessToken"):
            return co["accessToken"]
        raise CamError("No usable token stored for this account.")
    return _refresh_and_persist(acct)["accessToken"]


def _refresh_and_persist(acct: Account) -> dict:
    """Force a token refresh and write the merged bundle back to the saved record.
    If this account is the live one, also rewrites ~/.claude/.credentials.json."""
    from . import oauth

    co = acct.claude_oauth or {}
    rt = co.get("refreshToken")
    if not rt:
        raise CamError("No refresh token stored for this account.")

    try:
        bundle = oauth.refresh_token(rt)
    except oauth.ApiError as exc:
        msg = str(exc)
        if "invalid_grant" in msg or "HTTP 400" in msg or "HTTP 401" in msg:
            raise CamError(
                "This account's refresh token is no longer valid. Claude rotates refresh "
                "tokens on every use, so an account stays usable on only one machine at a "
                "time — using it elsewhere (or refreshing) revokes this copy. Log in to "
                "this account again with `claude` (/login), then run `cam save` to "
                "re-capture it here."
            ) from exc
        raise CamError(f"Token refresh failed: {msg}") from exc
    merged = dict(co)
    for key, val in bundle.items():
        if val is not None:
            merged[key] = val
    acct.claude_oauth = merged
    if acct.path:
        _atomic_write(acct.path, json.dumps(acct.to_dict(), ensure_ascii=False, indent=2))

    cur = current_account()
    if cur and cur.id == acct.id:
        _, creds = read_live()
        creds["claudeAiOauth"] = merged
        _write_creds(creds)
    return merged


def refresh_account_token(acct_id: str) -> Account:
    """User-triggered refresh: force a new access token via the stored refresh token."""
    acct = get_account(acct_id)
    if acct is None:
        raise CamError(f"No saved account with id {acct_id!r}.")
    _refresh_and_persist(acct)
    return acct


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
    creds = _read_creds()
    if creds:
        _atomic_write(
            d / "credentials.json",
            json.dumps(creds, ensure_ascii=False, separators=(",", ":")),
        )
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
