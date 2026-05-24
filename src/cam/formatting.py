from __future__ import annotations

import time
from datetime import datetime, timezone

from rich.text import Text

_PLAN_NAMES = {
    "claude_max": "Max",
    "claude_pro": "Pro",
    "claude_team": "Team",
    "claude_enterprise": "Enterprise",
    "max": "Max",
    "pro": "Pro",
}


def esc(text: str | None) -> str:
    return (text or "").replace("[", r"\[")


def plan_label(identity: dict | None, claude_oauth: dict | None) -> str:
    identity = identity or {}
    claude_oauth = claude_oauth or {}
    base = (
        _PLAN_NAMES.get(identity.get("organizationType", ""))
        or _PLAN_NAMES.get(claude_oauth.get("subscriptionType", ""))
        or claude_oauth.get("subscriptionType", "")
        or "—"
    )
    tier = identity.get("organizationRateLimitTier") or ""
    if "20x" in tier:
        base += " 20×"
    elif "5x" in tier:
        base += " 5×"
    return base


def token_expiry_text(claude_oauth: dict | None) -> str:
    exp = (claude_oauth or {}).get("expiresAt")
    if not exp:
        return "no token"
    secs = int(exp / 1000 - time.time())
    if secs <= 0:
        return "token expired"
    if secs < 3600:
        return f"valid {secs // 60}m"
    if secs < 86400:
        return f"valid {secs // 3600}h {secs % 3600 // 60}m"
    return f"valid {secs // 86400}d"


def is_expired(claude_oauth: dict | None) -> bool:
    exp = (claude_oauth or {}).get("expiresAt")
    return bool(exp) and (exp / 1000 - time.time()) <= 0


def fmt_date(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).strftime("%b %Y")
    except Exception:
        return "—"


def until(iso: str | None) -> tuple[str, str]:
    """(countdown, local-time) for a reset timestamp."""
    if not iso:
        return ("—", "")
    try:
        target = datetime.fromisoformat(iso)
    except Exception:
        return ("—", "")
    secs = int((target - datetime.now(timezone.utc)).total_seconds())
    if secs <= 0:
        human = "now"
    elif secs < 3600:
        human = f"{secs // 60}m"
    elif secs < 86400:
        human = f"{secs // 3600}h {secs % 3600 // 60}m"
    else:
        human = f"{secs // 86400}d {secs % 86400 // 3600}h"
    return (human, target.astimezone().strftime("%a %H:%M"))


def bar(pct: float | None, pal: dict, width: int = 22) -> Text:
    if pct is None:
        return Text("—" * width, style=pal["muted"])
    pct = max(0.0, min(100.0, float(pct)))
    filled = round(pct / 100 * width)
    color = pal["ok"] if pct < 50 else (pal["warn"] if pct < 85 else pal["danger"])
    return Text("█" * filled + "░" * (width - filled), style=color)
