from __future__ import annotations

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from . import formatting
from .models import Account


class AccountList(ListView):


    class SwitchRequested(Message):
        def __init__(self, item: ListItem) -> None:
            self.item = item
            super().__init__()

    def action_select_cursor(self) -> None:
        child = self.highlighted_child
        if child is not None:
            self.post_message(self.SwitchRequested(child))


class AccountRow(ListItem):
    
    def __init__(self, account: Account, is_active: bool, pal: dict) -> None:
        super().__init__()
        self.account = account
        self.is_active = is_active
        self.pal = pal

    def compose(self) -> ComposeResult:
        a, pal = self.account, self.pal
        dot, dot_color = ("●", pal["ok"]) if self.is_active else ("○", pal["muted"])
        title = Text()
        title.append(f"{dot} ", style=dot_color)
        title.append(a.label, style=f"bold {pal['text']}" if self.is_active else pal["text"])
        plan = a.plan
        if plan and plan != "—":
            title.append(f"  ({plan})", style=pal["accent"])
        yield Static(title)
        yield Static(Text(a.email or "—", style=pal["muted"]), classes="row-sub")


def _kv(pal: dict) -> Table:
    t = Table.grid(padding=(0, 3))
    t.add_column(style=pal["muted"], no_wrap=True)
    t.add_column(style=pal["text"])
    return t


def usage_block(pal: dict, usage: dict) -> Group:
    status = usage.get("status")
    if status == "loading":
        return Group(Text("  loading…", style=pal["muted"]))
    if status == "error":
        return Group(Text(f"  unavailable — {usage.get('err')}", style=pal["danger"]))
    if status != "ready" or not usage.get("data"):
        return Group(Text("  press u to load usage", style=pal["muted"]))

    data = usage["data"]
    rows: list = []

    def add(label: str, d: dict | None) -> None:
        if not d:
            return
        pct = d.get("utilization")
        line = Text()
        line.append(f"  {label:<15}", style=pal["muted"])
        line.append_text(formatting.bar(pct, pal))
        line.append(f"  {pct:.0f}%", style=pal["text"])
        rows.append(line)
        human, when = formatting.until(d.get("resets_at"))
        sub = Text(f"  {'':<15}resets in {human}", style=pal["muted"])
        if when:
            sub.append(f"  ({when})", style=pal["muted"])
        rows.append(sub)

    add("Session 5h", data.get("five_hour"))
    add("Week", data.get("seven_day"))
    add("Week · Opus", data.get("seven_day_opus"))
    add("Week · Sonnet", data.get("seven_day_sonnet"))

    eu = data.get("extra_usage") or {}
    if eu.get("is_enabled"):
        rows.append(Text(
            f"  Extra usage  {eu.get('used_credits')}/{eu.get('monthly_limit')} {eu.get('currency') or ''}",
            style=pal["muted"]))

    rows.append(Text(f"\n  updated {usage.get('age', 0)}s ago · press u to refresh", style=pal["muted"]))
    return Group(*rows)


def detail_group(acct: Account, pal: dict, is_active: bool, usage: dict) -> Group:
    identity = acct.identity or {}

    title = Text()
    title.append(acct.label, style=f"bold {pal['text']}")
    plan = acct.plan
    if plan and plan != "—":
        title.append(f"  ({plan})", style=pal["accent"])
    if is_active:
        title.append("    ● ACTIVE", style=f"bold {pal['ok']}")
    email = Text(acct.email or "—", style=pal["dim"])

    info = _kv(pal)
    info.add_row("Plan", plan)
    info.add_row("Organization", formatting.esc(acct.org_name) or "—")
    if acct.org_role:
        info.add_row("Role", acct.org_role)
    info.add_row("Member since", formatting.fmt_date(identity.get("accountCreatedAt")))
    if acct.added_at:
        info.add_row("Added", formatting.fmt_date(acct.added_at))
    info.add_row("Token", Text(acct.expiry_text, style=(pal["danger"] if acct.expired else pal["text"])))

    return Group(
        title, email, Text(""), info, Text(""),
        Text("USAGE", style=f"bold {pal['muted']}"),
        usage_block(pal, usage),
    )


def empty_detail(pal: dict, cur: Account | None) -> Group:
    head = Text()
    head.append("No accounts saved yet\n\n", style=f"bold {pal['text']}")
    if cur:
        head.append("You're currently logged in as\n", style=pal["muted"])
        head.append(f"{cur.label}  ", style=f"bold {pal['text']}")
        head.append(f"{cur.email}\n\n", style=pal["muted"])
    head.append("Press ", style=pal["muted"])
    head.append("a", style=f"bold {pal['accent']}")
    head.append(" or click ", style=pal["muted"])
    head.append("+ Add", style=f"bold {pal['accent']}")
    head.append(" to add your first account.", style=pal["muted"])
    return Group(head)
