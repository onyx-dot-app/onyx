"""Chat input area with file attachment support."""

from __future__ import annotations

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Input, Static


class AttachedFilesBadge(Static):
    """Shows attached files as inline badges above the input."""

    DEFAULT_CSS = """
    AttachedFilesBadge {
        width: 100%;
        height: auto;
        padding: 0 1;
        display: none;
        color: #A0A0A0;
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


class ChatInput(Input):
    """Text input with slash command detection."""

    DEFAULT_CSS = """
    ChatInput {
        width: 1fr;
        dock: bottom;
    }
    """

    class MessageSubmitted(Message):
        """Fired when the user submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def __init__(self) -> None:
        super().__init__(
            placeholder="Type a message... (/help for commands)",
        )

    async def action_submit(self) -> None:
        """Handle Enter key press."""
        text = self.value.strip()
        if text:
            self.post_message(self.MessageSubmitted(text))
            self.value = ""


class InputArea(Horizontal):
    """Input area combining file badges and text input."""

    DEFAULT_CSS = """
    InputArea {
        width: 100%;
        height: auto;
        dock: bottom;
        padding: 0 0;
    }
    """

    def compose(self) -> ComposeResult:
        yield AttachedFilesBadge()
        yield ChatInput()

    @property
    def chat_input(self) -> ChatInput:
        return self.query_one(ChatInput)

    @property
    def file_badge(self) -> AttachedFilesBadge:
        return self.query_one(AttachedFilesBadge)
