"""Chat input area with clean prompt styling and file attachment support."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widgets import Input, Static


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
    """The ❯ prompt prefix."""

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

    def __init__(self) -> None:
        super().__init__(
            placeholder="Send a message\u2026",
        )

    async def action_submit(self) -> None:
        """Handle Enter key press."""
        text = self.value.strip()
        if text:
            self.post_message(self.MessageSubmitted(text))
            self.value = ""


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
    """Input area combining separator, file badges, and prompt input."""

    DEFAULT_CSS = """
    InputArea {
        width: 100%;
        height: auto;
        dock: bottom;
    }
    """

    def compose(self) -> ComposeResult:
        yield _Separator()
        yield AttachedFilesBadge()
        yield _InputRow()
        yield _Separator()

    @property
    def chat_input(self) -> ChatInput:
        return self.query_one(ChatInput)

    @property
    def file_badge(self) -> AttachedFilesBadge:
        return self.query_one(AttachedFilesBadge)
