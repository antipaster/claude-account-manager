"""cam — Claude Code account manager.

Usage:
  cam                          launch the interactive TUI
  cam list                     list saved accounts (alias: ls); * marks the active one
  cam current                  show the active account
  cam save [label]             capture the current login into the manager
  cam use <name>               switch the active account (alias: switch)
  cam refresh <name>           force-refresh a saved account's token
  cam rm <name>                remove a saved account (alias: remove, delete)
  cam export [path]            export all saved accounts to a portable file
  cam import <path> [--force]  import accounts from an exported file

<name> matches an account id, label, or email (a unique substring is enough).

export/import move accounts between machines — e.g. Windows -> macOS. The export
file holds OAuth tokens: keep it private and delete it once imported.
"""
from __future__ import annotations

import sys
from pathlib import Path

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

    if cmd == "refresh":
        if not rest:
            sys.exit("usage: cam refresh <name>")
        a = _resolve(rest[0])
        store.refresh_account_token(a.id)
        print(f"Refreshed token for {a.label}.")
        return 0

    if cmd in ("rm", "remove", "delete"):
        if not rest:
            sys.exit("usage: cam rm <name>")
        a = _resolve(rest[0])
        store.delete_account(a.id)
        print(f"Removed {a.label}.")
        return 0

    if cmd == "export":
        dest = Path(rest[0]) if rest else Path.cwd() / "cam-accounts.json"
        n = store.export_accounts(dest)
        print(f"Exported {n} account{'' if n == 1 else 's'} to {dest}.")
        print("This file contains OAuth tokens — keep it private, "
              "and delete it once you've imported it on the other machine.")
        return 0

    if cmd == "import":
        force = any(a in ("--force", "-f") for a in rest)
        paths = [a for a in rest if not a.startswith("-")]
        if not paths:
            sys.exit("usage: cam import <path> [--force]")
        imported, skipped = store.import_accounts(Path(paths[0]), overwrite=force)
        msg = f"Imported {imported} account{'' if imported == 1 else 's'}."
        if skipped:
            msg += f" Skipped {skipped} already present (use --force to overwrite)."
        print(msg)
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
