"""Scrollable chat display with individual message widgets.

Uses a VerticalScroll container with individual Static widgets per message.
During streaming, only the current message widget is updated — the rest of
the DOM is untouched.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import Enum

from rich.markdown import Markdown
from rich.text import Text
from textual.containers import Horizontal
from textual.containers import VerticalScroll
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets import Static
from textual.widgets.option_list import Option


class _EntryKind(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    INFO = "info"


@dataclass
class _HistoryEntry:
    kind: _EntryKind
    content: str
    citations: dict[int, str] = field(default_factory=dict)


class UserMessage(Static):
    """A user message with a dimmed prefix."""

    DEFAULT_CSS = """
    UserMessage {
        width: 100%;
        padding: 0 1 0 3;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, content: str) -> None:
        label = Text()
        label.append("\u276f ", style="dim")
        label.append(content)
        super().__init__(label)


class _AssistantPrefix(Static):
    """The colored dot prefix for assistant messages."""

    DEFAULT_CSS = """
    _AssistantPrefix {
        width: 2;
        height: 1;
        padding: 0;
    }
    """

    def __init__(self) -> None:
        super().__init__(Text.from_markup("[bold #6c8ebf]\u25c9[/bold #6c8ebf]"))


class _AssistantContent(Static):
    """The text content of an assistant message."""

    DEFAULT_CSS = """
    _AssistantContent {
        width: 1fr;
        height: auto;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._buffer: str = ""

    def append(self, token: str) -> None:
        """Append a token and re-render as plain text (fast)."""
        self._buffer += token
        self.update(Text(self._buffer))

    def finish(self) -> None:
        """Final render with full Markdown formatting."""
        if self._buffer:
            self.update(Markdown(self._buffer))

    @property
    def buffer(self) -> str:
        return self._buffer


class AssistantMessage(Horizontal):
    """An assistant message with a colored dot prefix inline with content.

    Uses a Horizontal layout: dot on the left, content on the right.
    During streaming, content is rendered as plain Rich Text for speed.
    On finish, it re-renders once with Rich Markdown for proper formatting.
    """

    DEFAULT_CSS = """
    AssistantMessage {
        width: 100%;
        padding: 0 1 0 1;
        margin: 1 0 0 0;
        height: auto;
    }
    """

    def compose(self) -> None:
        yield _AssistantPrefix()
        yield _AssistantContent()

    def append(self, token: str) -> None:
        """Append a token to the content area."""
        self.query_one(_AssistantContent).append(token)

    def finish(self) -> None:
        """Final render with Markdown formatting."""
        self.query_one(_AssistantContent).finish()

    @property
    def buffer(self) -> str:
        return self.query_one(_AssistantContent).buffer


class CitationBlock(Static):
    """Citation references, hidden by default. Toggle with Ctrl+O."""

    DEFAULT_CSS = """
    CitationBlock {
        width: 100%;
        padding: 0 1 0 3;
        color: #666688;
        display: none;
    }

    CitationBlock.visible {
        display: block;
    }
    """


class StatusMessage(Static):
    """Compact status line for search indicators, tool usage, etc."""

    DEFAULT_CSS = """
    StatusMessage {
        width: 100%;
        padding: 0 1 0 3;
        color: #666688;
    }
    """

    def __init__(self, content: str) -> None:
        label = Text.from_markup(f"[dim]\u25cf {content}[/dim]")
        super().__init__(label)


class ErrorMessage(Static):
    """Red-styled error message."""

    DEFAULT_CSS = """
    ErrorMessage {
        width: 100%;
        padding: 0 1 0 3;
        margin: 1 0 0 0;
    }
    """

    def __init__(self, content: str) -> None:
        label = Text.from_markup(f"[bold red]Error:[/bold red] {content}")
        super().__init__(label)


class SessionPicker(OptionList):
    """Interactive session picker with arrow key navigation."""

    DEFAULT_CSS = """
    SessionPicker {
        width: 100%;
        height: auto;
        max-height: 16;
        margin: 0 0 0 3;
        background: $surface;
        border: tall $border-blurred;
        padding: 0 1;
    }

    SessionPicker:focus {
        border: tall $border;
    }
    """

    class SessionSelected(Message):
        """Fired when a session is selected."""

        def __init__(self, session_id: str) -> None:
            super().__init__()
            self.session_id = session_id

    def __init__(self, sessions: list[tuple[str, str]]) -> None:
        """sessions: list of (session_id, display_label) tuples."""
        super().__init__()
        self._sessions = sessions

    def on_mount(self) -> None:
        for sid, label in self._sessions:
            self.add_option(Option(label, id=sid))
        if self._sessions:
            self.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """When an option is selected, post our custom message and remove ourselves."""
        if event.option.id:
            self.post_message(self.SessionSelected(event.option.id))
        self.remove()

    def on_key(self, event: object) -> None:
        """Handle Escape to dismiss the picker."""
        from textual.events import Key

        if isinstance(event, Key) and event.key == "escape":
            event.prevent_default()
            event.stop()
            self.remove()


class ChatDisplay(VerticalScroll):
    """Scrollable message area with individual message widgets.

    Maintains a conversation history and mounts discrete widgets for each
    message. Streaming updates only touch the active AssistantMessage widget.
    """

    DEFAULT_CSS = """
    ChatDisplay {
        width: 100%;
        height: 1fr;
        padding: 0 1;
        scrollbar-size: 1 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._history: list[_HistoryEntry] = []
        self._current_assistant: AssistantMessage | None = None
        self._current_assistant_text: str = ""
        self._is_streaming: bool = False
        self._reasoning_text: str = ""
        self._is_reasoning: bool = False
        self._sources_visible: bool = False

    def show_splash(self) -> None:
        """Show the Onyx ASCII art splash screen."""
        from onyx_cli.widgets.splash import SplashScreen

        self.mount(SplashScreen())

    def add_user_message(self, message: str) -> None:
        """Add a user message to the display."""
        self._history.append(_HistoryEntry(kind=_EntryKind.USER, content=message))
        self.mount(UserMessage(message))
        self._scroll_to_end()

    def start_assistant_message(self) -> None:
        """Start a new assistant response section."""
        self._current_assistant_text = ""
        self._is_streaming = True
        widget = AssistantMessage()
        self._current_assistant = widget
        self.mount(widget)
        self._scroll_to_end()

    def append_token(self, token: str) -> None:
        """Append a token to the current assistant response."""
        self._current_assistant_text += token
        if self._is_streaming and self._current_assistant is not None:
            self._current_assistant.append(token)
            self._scroll_to_end()

    def finish_assistant_message(self) -> None:
        """Finalize the assistant message and commit it to history."""
        self._is_streaming = False
        if self._current_assistant_text:
            self._history.append(
                _HistoryEntry(
                    kind=_EntryKind.ASSISTANT, content=self._current_assistant_text
                )
            )
        if self._current_assistant is not None:
            self._current_assistant.finish()
            self._scroll_to_end()
        self._current_assistant = None

    def start_reasoning(self) -> None:
        """Start a reasoning block."""
        self._is_reasoning = True
        self._reasoning_text = ""
        self.mount(StatusMessage("Thinking\u2026"))
        self._scroll_to_end()

    def append_reasoning(self, text: str) -> None:
        """Append text to the reasoning block."""
        self._reasoning_text += text

    def finish_reasoning(self) -> None:
        """Close the reasoning block."""
        self._is_reasoning = False
        if self._reasoning_text:
            self._history.append(
                _HistoryEntry(kind=_EntryKind.INFO, content="[Thought process omitted]")
            )

    def show_search_indicator(
        self, queries: list[str] | None = None, is_internet: bool = False
    ) -> None:
        """Show a search indicator."""
        prefix = "Web search" if is_internet else "Searching"
        if queries:
            query_text = ", ".join(f'"{q}"' for q in queries[:3])
            msg = f"{prefix}: {query_text}"
        else:
            msg = f"{prefix}\u2026"
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.mount(StatusMessage(msg))
        self._scroll_to_end()

    def show_documents_found(self, count: int) -> None:
        """Show how many documents were found."""
        msg = f"Found {count} document{'s' if count != 1 else ''}"
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.mount(StatusMessage(msg))
        self._scroll_to_end()

    def show_citations(self, citations: dict[int, str]) -> None:
        """Show citation references (hidden by default, toggle with Ctrl+O)."""
        if not citations:
            return

        # Attach to last assistant history entry
        for entry in reversed(self._history):
            if entry.kind == _EntryKind.ASSISTANT:
                entry.citations = dict(citations)
                break

        parts = [
            f"[dim][{num}][/dim] {doc_id}" for num, doc_id in sorted(citations.items())
        ]
        citation_text = f"Sources ({len(citations)}): " + "  ".join(parts)
        block = CitationBlock(Text.from_markup(f"[dim]\u25cf {citation_text}[/dim]"))
        if self._sources_visible:
            block.add_class("visible")
        self.mount(block)
        self._scroll_to_end()

    def toggle_sources(self) -> None:
        """Toggle visibility of all citation blocks."""
        self._sources_visible = not self._sources_visible
        for block in self.query(CitationBlock):
            if self._sources_visible:
                block.add_class("visible")
            else:
                block.remove_class("visible")
        if self._sources_visible:
            self._scroll_to_end()

    def show_tool_start(self, tool_name: str) -> None:
        """Show that a tool is being used."""
        msg = f"Using {tool_name}\u2026"
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.mount(StatusMessage(msg))
        self._scroll_to_end()

    def show_error(self, error: str) -> None:
        """Show an error message."""
        self.mount(ErrorMessage(error))
        self._scroll_to_end()

    def show_info(self, message: str) -> None:
        """Show an informational message."""
        self.mount(StatusMessage(message))
        self._scroll_to_end()

    def show_research_task(self, task: str) -> None:
        """Show a deep research sub-task."""
        msg = f"Researching: {task}"
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.mount(StatusMessage(msg))
        self._scroll_to_end()

    def write(self, content: str) -> None:
        """Write raw markup content (for help text, persona lists, etc.)."""
        widget = Static(Text.from_markup(content) if content else Text(""))
        widget.styles.padding = (0, 1, 0, 3)
        self.mount(widget)
        self._scroll_to_end()

    def clear(self) -> None:
        """Clear the display (but NOT the history)."""
        self.query("*").remove()

    def clear_all(self) -> None:
        """Clear both display and history (for /new command)."""
        self._history.clear()
        self._current_assistant_text = ""
        self._current_assistant = None
        self.query("*").remove()

    def _scroll_to_end(self) -> None:
        """Scroll to the bottom of the chat."""
        self.scroll_end(animate=False)
