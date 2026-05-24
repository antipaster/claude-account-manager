from __future__ import annotations

from textual.theme import Theme

# role keys: accent, ok, warn, danger, text, dim, muted, bg, panel, panel2, border
PALETTES: dict[str, dict] = {
    "claude": {
        "accent": "#d97757", "ok": "#7fae6a", "warn": "#d9a35a", "danger": "#cf6b5a",
        "text": "#e8e6e3", "dim": "#b9b6b0", "muted": "#8a8784",
        "bg": "#16150f", "panel": "#1b1a13", "panel2": "#2a2519", "border": "#3a3834",
    },
    "midnight": {
        "accent": "#7aa2f7", "ok": "#9ece6a", "warn": "#e0af68", "danger": "#f7768e",
        "text": "#c0caf5", "dim": "#9aa5ce", "muted": "#565f89",
        "bg": "#11131a", "panel": "#161a26", "panel2": "#222a3d", "border": "#2c3147",
    },
    "forest": {
        "accent": "#5fb37a", "ok": "#8ec07c", "warn": "#d8a657", "danger": "#ea6962",
        "text": "#d6d6c2", "dim": "#a9b29a", "muted": "#7c8370",
        "bg": "#11140e", "panel": "#161b12", "panel2": "#222a1b", "border": "#33402c",
    },
    "grape": {
        "accent": "#c198eb", "ok": "#98c379", "warn": "#e5c07b", "danger": "#e06c75",
        "text": "#e6e0ec", "dim": "#bbb0c8", "muted": "#867c93",
        "bg": "#15121a", "panel": "#1a1623", "panel2": "#271f36", "border": "#382f47",
    },
    "mono": {
        "accent": "#cbb994", "ok": "#9aa886", "warn": "#cbb38a", "danger": "#c98b86",
        "text": "#e6e3dd", "dim": "#b0aca3", "muted": "#807c74",
        "bg": "#141412", "panel": "#1a1a17", "panel2": "#272420", "border": "#34322d",
    },
}

THEME_ORDER = ["claude", "midnight", "forest", "grape", "mono"]
THEME_LABELS = {
    "claude": "Claude — coral",
    "midnight": "Midnight — blue",
    "forest": "Forest — green",
    "grape": "Grape — purple",
    "mono": "Mono — warm gray",
}


def palette(name: str) -> dict:
    return PALETTES.get(name, PALETTES["claude"])


def textual_theme(name: str) -> Theme:
    p = palette(name)
    return Theme(
        name=name,
        primary=p["accent"],
        secondary=p["accent"],
        accent=p["accent"],
        foreground=p["text"],
        background=p["bg"],
        surface=p["panel"],
        panel=p["panel2"],
        success=p["ok"],
        warning=p["warn"],
        error=p["danger"],
        dark=True,
    )
