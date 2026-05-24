"""Modal screens: confirm, text input, add menu, browser login, settings."""

from __future__ import annotations

import webbrowser

from textual import on, work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Select, Static, Switch

from . import oauth, store
from .formatting import esc
from .theme import THEME_LABELS, THEME_ORDER


class ConfirmScreen(ModalScreen[bool]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, ok_label: str = "Confirm", danger: bool = False) -> None:
        super().__init__()
        self.prompt, self.ok_label, self.danger = prompt, ok_label, danger

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.prompt, classes="prompt")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button(self.ok_label, variant="error" if self.danger else "primary", id="ok")

    @on(Button.Pressed)
    def _p(self, e: Button.Pressed) -> None:
        e.stop()
        self.dismiss(e.button.id == "ok")

    def action_cancel(self) -> None:
        self.dismiss(False)


class InputScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, value: str = "") -> None:
        super().__init__()
        self.prompt, self.value = prompt, value

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self.prompt, classes="prompt")
            yield Input(value=self.value, id="field")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("OK", variant="primary", id="ok")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    @on(Input.Submitted)
    def _s(self, e: Input.Submitted) -> None:
        e.stop()
        self.dismiss(self.query_one(Input).value)

    @on(Button.Pressed)
    def _p(self, e: Button.Pressed) -> None:
        e.stop()
        self.dismiss(self.query_one(Input).value if e.button.id == "ok" else None)

    def action_cancel(self) -> None:
        self.dismiss(None)


class AddMenuScreen(ModalScreen[str | None]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[b]Add an account[/]", classes="prompt")
            yield Static(
                "Capture the account you're logged into now, or log in to a different "
                "one in your browser without disturbing the current session.",
                classes="prompt dim-text",
            )
            yield Button("Capture current login", id="current", classes="menu")
            yield Button("Log in to a new account…", id="login", classes="menu")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")

    @on(Button.Pressed)
    def _p(self, e: Button.Pressed) -> None:
        e.stop()
        self.dismiss(None if e.button.id == "cancel" else e.button.id)

    def action_cancel(self) -> None:
        self.dismiss(None)


class LoginScreen(ModalScreen["store.Account | None"]):
    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self) -> None:
        super().__init__()
        self.url, self.verifier, self.state = oauth.start_login()

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[b]Add account — browser login[/]", classes="prompt")
            yield Static(
                "A browser opened to Claude. Log in as the account to add, approve access, "
                "then copy the code shown and paste it below.",
                classes="prompt dim-text",
            )
            yield Input(placeholder="Paste the authorization code here", id="field")
            yield Static("", id="login-status")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Open browser", id="open")
                yield Button("Add account", variant="primary", id="add")

    def on_mount(self) -> None:
        self._open()
        self.query_one(Input).focus()

    def _open(self) -> None:
        try:
            webbrowser.open(self.url)
        except Exception:
            pass

    def _status(self, msg: str, css: str = "dim-text") -> None:
        s = self.query_one("#login-status", Static)
        s.set_classes(css)
        s.update(esc(msg))

    @on(Input.Submitted)
    def _submit(self, e: Input.Submitted) -> None:
        e.stop()
        self._go()

    @on(Button.Pressed)
    def _p(self, e: Button.Pressed) -> None:
        e.stop()
        if e.button.id == "cancel":
            self.dismiss(None)
        elif e.button.id == "open":
            self._open()
        elif e.button.id == "add":
            self._go()

    def _go(self) -> None:
        code = self.query_one(Input).value.strip()
        if not code:
            self._status("Paste the code from the browser first.", "warn-text")
            return
        self._status("Validating with Anthropic…")
        self._exchange(code)

    @work(thread=True, exclusive=True)
    def _exchange(self, code: str) -> None:
        try:
            bundle = oauth.finish_login(code, self.verifier, self.state)
            acct = store.add_account_from_login(bundle)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            self.app.call_from_thread(self._status, f"Failed: {exc}", "error-text")
            return
        self.app.call_from_thread(self.dismiss, acct)

    def action_cancel(self) -> None:
        self.dismiss(None)


class SettingsScreen(ModalScreen[dict | None]):
    """Theme picker + behavior toggles. Theme previews live; Save persists."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, settings: dict) -> None:
        super().__init__()
        self.settings = dict(settings)
        self._orig_theme = settings.get("theme", "claude")

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static("[b]Settings[/]", classes="prompt")
            yield Label("Color theme")
            yield Select(
                [(THEME_LABELS[n], n) for n in THEME_ORDER],
                value=self.settings.get("theme", "claude"),
                allow_blank=False,
                id="theme",
            )
            with Horizontal(classes="setting-row"):
                yield Switch(value=self.settings.get("confirm_switch", True), id="confirm_switch")
                yield Label("Confirm before switching", classes="switch-label")
            with Horizontal(classes="setting-row"):
                yield Switch(value=self.settings.get("auto_usage", True), id="auto_usage")
                yield Label("Auto-load usage on select", classes="switch-label")
            with Horizontal(classes="buttons"):
                yield Button("Cancel", id="cancel")
                yield Button("Save", variant="primary", id="save")

    @on(Select.Changed)
    def _theme(self, e: Select.Changed) -> None:
        e.stop()
        if e.value is not Select.BLANK:
            self.settings["theme"] = e.value
            self.app.apply_theme(e.value)  # live preview

    @on(Switch.Changed)
    def _switch(self, e: Switch.Changed) -> None:
        e.stop()
        self.settings[e.switch.id] = e.value

    @on(Button.Pressed)
    def _btn(self, e: Button.Pressed) -> None:
        e.stop()
        if e.button.id == "save":
            self.dismiss(self.settings)
        else:
            self.app.apply_theme(self._orig_theme)
            self.dismiss(None)

    def action_cancel(self) -> None:
        self.app.apply_theme(self._orig_theme)
        self.dismiss(None)
