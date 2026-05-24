from __future__ import annotations

import sys

from . import store
from .models import Account


def _resolve(name: str) -> Account:
    name_l = name.lower()
    accounts = store.list_accounts()
    for a in accounts:
        if a.id == name:
            return a
    for a in accounts:
        if a.label.lower() == name_l or a.email.lower() == name_l:
            return a
    matches = [a for a in accounts if name_l in a.label.lower() or name_l in a.email.lower()]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        sys.exit(f"No saved account matches {name!r}.")
    sys.exit(f"{name!r} is ambiguous: {', '.join(a.label for a in matches)}")


def _fmt(a: Account, active_id: str | None) -> str:
    mark = "* " if a.id == active_id else "  "
    return f"{mark}{a.label:<22} {a.email:<32} {a.plan:<10} {a.expiry_text}"


def _run(argv: list[str]) -> int:
    cmd, rest = argv[0], argv[1:]
    cur = store.current_account()
    active_id = cur.id if cur else None

    if cmd in ("list", "ls"):
        accounts = store.list_accounts()
        if not accounts:
            print("No saved accounts. Run `cam save` to capture the current one.")
            return 0
        for a in accounts:
            print(_fmt(a, active_id))
        return 0

    if cmd == "current":
        print("Not logged in." if cur is None else _fmt(cur, active_id).strip())
        return 0

    if cmd == "save":
        a = store.save_current(rest[0] if rest else None)
        print(f"Saved {a.label} ({a.email}).")
        return 0

    if cmd in ("use", "switch"):
        if not rest:
            sys.exit("usage: cam use <name>")
        a = _resolve(rest[0])
        store.switch_to(a.id)
        print(f"Switched to {a.label}. Start a new `claude` session to use it.")
        return 0

    if cmd in ("rm", "remove", "delete"):
        if not rest:
            sys.exit("usage: cam rm <name>")
        a = _resolve(rest[0])
        store.delete_account(a.id)
        print(f"Removed {a.label}.")
        return 0

    print(__doc__)
    return 0 if cmd in ("-h", "--help", "help") else 2


def main() -> int:
    try:  # windows console defaults to cp1252; our output has unicoded
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    if len(sys.argv) > 1:
        try:
            return _run(sys.argv[1:])
        except store.CamError as exc:
            sys.exit(str(exc))
    from .app import CamApp

    CamApp().run()
    return 0
