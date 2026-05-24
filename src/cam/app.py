from __future__ import annotations

import time
from pathlib import Path

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, ListView, Static

from . import config, oauth, store, theme
from .models import Account
from .screens import AddMenuScreen, ConfirmScreen, InputScreen, LoginScreen, SettingsScreen
from .widgets import AccountList, AccountRow, detail_group, empty_detail

SPARK = "✻"
DOT = "·"
USAGE_TTL = 90


class CamApp(App[None]):
    CSS_PATH = Path(__file__).parent / "styles.tcss"
    TITLE = "Claude Code Account Manager"

    BINDINGS = [
        Binding("s", "switch", "Switch"),
        Binding("a", "add", "Add"),
        Binding("r", "rename", "Rename"),
        Binding("d", "delete", "Delete"),
        Binding("u", "refresh_usage", "Usage"),
        Binding("comma", "settings", "Settings"),
        Binding("g,f5", "reload", "Reload"),
        Binding("q", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.settings = config.load_settings()
        self.pal = theme.palette(self.settings["theme"])
        self.live_id: str | None = None
        self._usage: dict[str, tuple[float, dict]] = {}
        self._usage_err: dict[str, str] = {}
        self._loading: set[str] = set()
        self._detail_id: str | None = None

    def compose(self) -> ComposeResult:
        yield Static(id="topbar")
        with Horizontal(id="main"):
            with Vertical(id="sidebar"):
                yield Static("ACCOUNTS", classes="section")
                yield AccountList(id="list")
                with Horizontal(id="sidebar-actions"):
                    yield Button("+ Add", id="btn-add", variant="primary")
                    yield Button("Settings", id="btn-settings", classes="flat")
            with Vertical(id="detail"):
                yield Static(id="detail-body")
                with Horizontal(id="detail-actions"):
                    yield Button("Switch", id="btn-switch", variant="primary")
                    yield Button("Rename", id="btn-rename", classes="flat")
                    yield Button("Delete", id="btn-delete", variant="error")
                    yield Button("Refresh usage", id="btn-usage", classes="flat")

    def on_mount(self) -> None:
        for name in theme.THEME_ORDER:
            try:
                self.register_theme(theme.textual_theme(name))
            except Exception:
                pass
        try:
            self.theme = self.settings["theme"]
        except Exception:
            pass
        self.reload()

    # ---- chrome -----------------------------------------------------------
    def _set_topbar(self, n: int) -> None:
        t = Text()
        t.append(f"{SPARK} ", style=f"bold {self.pal['accent']}")
        t.append("Claude Code ", style=f"bold {self.pal['text']}")
        t.append(f"{DOT} Account Manager", style=self.pal["muted"])
        t.append(f"     {n} account{'s' if n != 1 else ''}", style=self.pal["muted"])
        self.query_one("#topbar", Static).update(t)

    def apply_theme(self, name: str) -> None:
        self.settings["theme"] = name
        self.pal = theme.palette(name)
        try:
            self.theme = name
        except Exception:
            pass
        sel = self._selected()
        self.reload(focus_id=sel.id if sel else None)

    # ---- data refresh -----------------------------------------------------
    def reload(self, focus_id: str | None = None) -> None:
        cur = store.current_account()
        self.live_id = cur.id if cur else None
        accounts = store.list_accounts()
        self._set_topbar(len(accounts))

        lv = self.query_one("#list", ListView)
        focus_id = focus_id or (self._selected().id if self._selected() else None)
        lv.clear()
        self.query_one("#detail-actions").disabled = not accounts

        if not accounts:
            self._detail_id = None
            self.query_one("#detail-body", Static).update(empty_detail(self.pal, cur))
            return

        target = 0
        for i, acct in enumerate(accounts):
            lv.append(AccountRow(acct, acct.id == self.live_id, self.pal))
            if focus_id and acct.id == focus_id:
                target = i
        lv.index = target
        lv.focus()
        self._show_detail(accounts[target])

    # ---- detail pane ------------------------------------------------------
    def _selected(self) -> Account | None:
        try:
            item = self.query_one("#list", ListView).highlighted_child
        except Exception:
            return None
        return getattr(item, "account", None)

    @on(ListView.Highlighted)
    def _highlighted(self, e: ListView.Highlighted) -> None:
        acct = getattr(e.item, "account", None)
        if acct:
            self._show_detail(acct)

    def _usage_state(self, acct_id: str) -> dict:
        if acct_id in self._loading and acct_id not in self._usage:
            return {"status": "loading"}
        if acct_id in self._usage_err and acct_id not in self._usage:
            return {"status": "error", "err": self._usage_err[acct_id]}
        cached = self._usage.get(acct_id)
        if not cached:
            return {"status": "none"}
        return {"status": "ready", "data": cached[1], "age": int(time.time() - cached[0])}

    def _render_detail(self, acct: Account) -> None:
        grp = detail_group(acct, self.pal, acct.id == self.live_id, self._usage_state(acct.id))
        self.query_one("#detail-body", Static).update(grp)

    def _show_detail(self, acct: Account, force_usage: bool = False) -> None:
        self._detail_id = acct.id
        self._render_detail(acct)
        cached = self._usage.get(acct.id)
        fresh = cached and (time.time() - cached[0] < USAGE_TTL)
        if force_usage:
            self._usage.pop(acct.id, None)
            self._fetch_usage(acct)
        elif self.settings.get("auto_usage", True) and not fresh:
            self._fetch_usage(acct)

    @work(thread=True, exclusive=True, group="usage")
    def _fetch_usage(self, acct: Account) -> None:
        self._loading.add(acct.id)
        self.app.call_from_thread(self._rerender_if_current, acct.id)
        try:
            token = store.live_access_token() if acct.id == self.live_id else store.valid_access_token(acct)
            if not token:
                raise store.CamError("no token")
            data = oauth.get_usage(token)
            self._usage[acct.id] = (time.time(), data)
            self._usage_err.pop(acct.id, None)
        except Exception as exc:  # noqa: BLE001
            self._usage_err[acct.id] = str(exc).splitlines()[0][:80]
        finally:
            self._loading.discard(acct.id)
        self.app.call_from_thread(self._rerender_if_current, acct.id)

    def _rerender_if_current(self, acct_id: str) -> None:
        if acct_id == self._detail_id:
            acct = store.get_account(acct_id) or self._selected()
            if acct:
                self._render_detail(acct)

    # ---- buttons ----------------------------------------------------------
    @on(Button.Pressed)
    def _buttons(self, e: Button.Pressed) -> None:
        dispatch = {
            "btn-add": self.action_add,
            "btn-settings": self.action_settings,
            "btn-switch": self.action_switch,
            "btn-rename": self.action_rename,
            "btn-delete": self.action_delete,
            "btn-usage": self.action_refresh_usage,
        }
        fn = dispatch.get(e.button.id)
        if fn:
            fn()

    @on(AccountList.SwitchRequested)
    def _on_switch_requested(self) -> None:
        self.action_switch()

    # ---- actions ----------------------------------------------------------
    def action_switch(self) -> None:
        acct = self._selected()
        if acct is None:
            return
        if acct.id == self.live_id:
            self.notify(f"{acct.label} is already active.")
            return

        def go(ok: bool = True) -> None:
            if not ok:
                return
            try:
                store.switch_to(acct.id)
            except store.CamError as exc:
                self.notify(str(exc), severity="error", title="Switch failed")
                return
            self.reload(focus_id=acct.id)
            self.notify(f"Now active: {acct.label}. Start a new `claude` session to use it.",
                        title="Switched")

        if self.settings.get("confirm_switch", True):
            self.push_screen(
                ConfirmScreen(
                    f"Switch the active Claude account to\n\n  [b]{_e(acct.label)}[/]\n"
                    f"  [dim]{_e(acct.email)}[/]\n\n[dim]Your current account is backed up first.[/]",
                    ok_label="Switch",
                ),
                go,
            )
        else:
            go(True)

    def action_add(self) -> None:
        def chosen(kind: str | None) -> None:
            if kind == "current":
                self._add_current()
            elif kind == "login":
                self.push_screen(LoginScreen(), self._after_login)

        self.push_screen(AddMenuScreen(), chosen)

    def _add_current(self) -> None:
        cur = store.current_account()
        if cur is None:
            self.notify("No active Claude account to capture.", severity="error")
            return

        def save(label: str | None) -> None:
            if label is None:
                return
            try:
                acct = store.save_current(label.strip() or None)
            except store.CamError as exc:
                self.notify(str(exc), severity="error", title="Save failed")
                return
            self.reload(focus_id=acct.id)
            self.notify(f"Captured {acct.label}.", title="Saved")

        self.push_screen(InputScreen("Label for the current account:", value=cur.label), save)

    def _after_login(self, acct: "Account | None") -> None:
        if acct is None:
            return
        self.reload(focus_id=acct.id)
        self.notify(f"Added {acct.label} ({acct.email}).", title="Account added")

    def action_rename(self) -> None:
        acct = self._selected()
        if acct is None:
            return

        def do(label: str | None) -> None:
            if not label:
                return
            store.rename_account(acct.id, label)
            self.reload(focus_id=acct.id)

        self.push_screen(InputScreen("New label:", value=acct.label), do)

    def action_delete(self) -> None:
        acct = self._selected()
        if acct is None:
            return

        def do(ok: bool) -> None:
            if not ok:
                return
            store.delete_account(acct.id)
            self.notify(f"Removed {acct.label}.", title="Deleted")
            self.reload()

        self.push_screen(
            ConfirmScreen(
                f"Remove [b]{_e(acct.label)}[/] from the manager?\n\n"
                f"[dim]This deletes only the saved profile here; it does not log the "
                f"account out of Claude.[/]",
                ok_label="Delete",
                danger=True,
            ),
            do,
        )

    def action_refresh_usage(self) -> None:
        acct = self._selected()
        if acct:
            self._show_detail(acct, force_usage=True)

    def action_settings(self) -> None:
        def done(result: dict | None) -> None:
            if result is None:
                return
            self.settings.update(result)
            config.save_settings(self.settings)
            self.apply_theme(self.settings["theme"])
            self.notify("Settings saved.")

        self.push_screen(SettingsScreen(self.settings), done)

    def action_reload(self) -> None:
        self.reload()


def _e(text: str | None) -> str:
    return (text or "").replace("[", r"\[")


def main() -> None:
    CamApp().run()


if __name__ == "__main__":
    main()
