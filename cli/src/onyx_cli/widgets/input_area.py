"""Chat input area with clean prompt styling, file attachment support, and slash command menu."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input
from textual.widgets import OptionList
from textual.widgets import Static
from textual.widgets.option_list import Option


SLASH_COMMANDS: list[tuple[str, str]] = [
    ("/help", "Show help message"),
    ("/new", "Start a new chat session"),
    ("/persona", "List and switch assistants"),
    ("/attach", "Attach a file to next message"),
    ("/sessions", "List recent chat sessions"),
    ("/resume", "Resume a previous session"),
    ("/configure", "Re-run connection setup"),
    ("/connectors", "Open connectors in browser"),
    ("/settings", "Open settings in browser"),
    ("/quit", "Exit Onyx CLI"),
]


class AttachedFilesBadge(Static):
    """Shows attached files as inline badges above the input."""

    DEFAULT_CSS = """
    AttachedFilesBadge {
        width: 100%;
        height: auto;
        padding: 0 1 0 5;
        display: none;
        color: #666688;
    }

    AttachedFilesBadge.has-files {
        display: block;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._files: list[str] = []

    def add_file(self, name: str) -> None:
        self._files.append(name)
        self._refresh_display()

    def clear_files(self) -> None:
        self._files.clear()
        self._refresh_display()

    @property
    def file_count(self) -> int:
        return len(self._files)

    def _refresh_display(self) -> None:
        if self._files:
            badges = " ".join(f"[{f}]" for f in self._files)
            self.update(f"Attached: {badges}")
            self.add_class("has-files")
        else:
            self.update("")
            self.remove_class("has-files")


class _PromptPrefix(Static):
    """The \u276f prompt prefix."""

    DEFAULT_CSS = """
    _PromptPrefix {
        width: 3;
        height: 1;
        padding: 0 0 0 1;
        color: #6c8ebf;
    }
    """

    def __init__(self) -> None:
        super().__init__("\u276f ")


class SlashMenu(OptionList):
    """Dropdown menu for slash commands that appears above the input."""

    DEFAULT_CSS = """
    SlashMenu {
        width: 100%;
        height: auto;
        max-height: 12;
        display: none;
        background: $surface;
        border: tall $border-blurred;
        padding: 0 1;
    }

    SlashMenu.visible {
        display: block;
    }
    """

    class CommandSelected(Message):
        """Fired when a slash command is selected from the menu."""

        def __init__(self, command: str) -> None:
            super().__init__()
            self.command = command

    def __init__(self) -> None:
        super().__init__()
        self._all_commands = SLASH_COMMANDS
        self._filtered: list[tuple[str, str]] = list(SLASH_COMMANDS)

    def on_mount(self) -> None:
        self._rebuild_options(SLASH_COMMANDS)

    def filter(self, prefix: str) -> None:
        """Filter commands by prefix and refresh the option list."""
        if not prefix or prefix == "/":
            self._filtered = list(self._all_commands)
        else:
            needle = prefix.lower()
            self._filtered = [
                (cmd, desc)
                for cmd, desc in self._all_commands
                if cmd.startswith(needle)
            ]
        self._rebuild_options(self._filtered)

        if self._filtered:
            if not self.has_class("visible"):
                self.add_class("visible")
            self.highlighted = 0
        else:
            self.remove_class("visible")

    def _rebuild_options(self, commands: list[tuple[str, str]]) -> None:
        self.clear_options()
        for cmd, desc in commands:
            self.add_option(Option(f"{cmd}  [dim]{desc}[/dim]", id=cmd))

    def show(self) -> None:
        self.filter("/")
        self.add_class("visible")

    def hide(self) -> None:
        self.remove_class("visible")

    @property
    def is_visible(self) -> bool:
        return self.has_class("visible")

    def select_current(self) -> str | None:
        """Select the currently highlighted command and return it."""
        if self.highlighted is not None and self._filtered:
            idx = self.highlighted
            if 0 <= idx < len(self._filtered):
                cmd = self._filtered[idx][0]
                self.hide()
                return cmd
        return None


class ChatInput(Input):
    """Text input with slash command detection."""

    DEFAULT_CSS = """
    ChatInput {
        width: 1fr;
        height: 1;
        border: none;
        background: transparent;
        padding: 0;
    }

    ChatInput:focus {
        border: none;
    }
    """

    class MessageSubmitted(Message):
        """Fired when the user submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    class SlashTyped(Message):
        """Fired when the input value changes and starts with /."""

        def __init__(self, prefix: str) -> None:
            super().__init__()
            self.prefix = prefix

    class SlashCleared(Message):
        """Fired when the input no longer starts with /."""

    def __init__(self) -> None:
        super().__init__(
            placeholder="Send a message\u2026",
        )

    def watch_value(self, value: str) -> None:
        """React to input value changes to drive the slash menu."""
        stripped = value.strip()
        if stripped.startswith("/") and " " not in stripped:
            self.post_message(self.SlashTyped(stripped))
        else:
            self.post_message(self.SlashCleared())

    async def action_submit(self) -> None:
        """Handle Enter key press."""
        # Check if slash menu is open and should handle the enter
        try:
            menu = self.screen.query_one(SlashMenu)
            if menu.is_visible:
                cmd = menu.select_current()
                if cmd:
                    # If command takes args, fill it in with a trailing space
                    if cmd in ("/attach", "/persona", "/resume"):
                        self.value = cmd + " "
                        self.cursor_position = len(self.value)
                    else:
                        # Execute immediately
                        self.post_message(self.MessageSubmitted(cmd))
                        self.value = ""
                    return
        except Exception:
            pass

        text = self.value.strip()
        if text:
            self.post_message(self.MessageSubmitted(text))
            self.value = ""

    async def on_key(self, event: Input.Changed | object) -> None:
        """Intercept arrow keys for slash menu navigation."""
        # We need to import Key here to type-check
        from textual.events import Key

        if not isinstance(event, Key):
            return

        try:
            menu = self.screen.query_one(SlashMenu)
        except Exception:
            return

        if not menu.is_visible:
            return

        if event.key == "up":
            event.prevent_default()
            event.stop()
            if menu.highlighted is not None and menu.highlighted > 0:
                menu.highlighted = menu.highlighted - 1
        elif event.key == "down":
            event.prevent_default()
            event.stop()
            if menu.highlighted is not None:
                menu.highlighted = menu.highlighted + 1
        elif event.key == "escape":
            event.prevent_default()
            event.stop()
            menu.hide()
        elif event.key == "tab":
            event.prevent_default()
            event.stop()
            cmd = menu.select_current()
            if cmd:
                if cmd in ("/attach", "/persona", "/resume"):
                    self.value = cmd + " "
                    self.cursor_position = len(self.value)
                else:
                    self.value = cmd
                    self.cursor_position = len(self.value)


class _InputRow(Horizontal):
    """Row containing the prompt prefix and input field."""

    DEFAULT_CSS = """
    _InputRow {
        width: 100%;
        height: 1;
    }
    """

    def compose(self) -> ComposeResult:
        yield _PromptPrefix()
        yield ChatInput()


class _Separator(Static):
    """Thin horizontal rule above the input."""

    DEFAULT_CSS = """
    _Separator {
        width: 100%;
        height: 1;
        color: #333355;
    }
    """

    def __init__(self) -> None:
        super().__init__("\u2500" * 200)


class InputArea(Vertical):
    """Input area combining separator, file badges, slash menu, and prompt input."""

    DEFAULT_CSS = """
    InputArea {
        width: 100%;
        height: auto;
    }
    """

    def compose(self) -> ComposeResult:
        yield _Separator()
        yield AttachedFilesBadge()
        yield SlashMenu()
        yield _InputRow()
        yield _Separator()

    def on_chat_input_slash_typed(self, event: ChatInput.SlashTyped) -> None:
        """Show and filter the slash menu when / is typed."""
        self.query_one(SlashMenu).filter(event.prefix)

    def on_chat_input_slash_cleared(self, event: ChatInput.SlashCleared) -> None:
        """Hide the slash menu when input no longer starts with /."""
        self.query_one(SlashMenu).hide()

    @property
    def chat_input(self) -> ChatInput:
        return self.query_one(ChatInput)

    @property
    def file_badge(self) -> AttachedFilesBadge:
        return self.query_one(AttachedFilesBadge)
