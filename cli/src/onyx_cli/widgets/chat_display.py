"""Scrollable chat display widget with rich markdown rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from rich.markdown import Markdown
from rich.text import Text

from textual.widgets import RichLog


class _EntryKind(Enum):
    USER = "user"
    ASSISTANT = "assistant"
    INFO = "info"


@dataclass
class _HistoryEntry:
    kind: _EntryKind
    content: str
    citations: dict[int, str] = field(default_factory=dict)


class ChatDisplay(RichLog):
    """Scrollable message area with rich markdown rendering.

    Maintains a conversation history so that re-rendering the current
    streaming response doesn't lose previous messages.
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
        super().__init__(wrap=True, highlight=True, markup=True, auto_scroll=True)
        self._history: list[_HistoryEntry] = []
        self._current_assistant_text: str = ""
        self._is_streaming: bool = False
        self._reasoning_text: str = ""
        self._is_reasoning: bool = False

    def _replay_history(self) -> None:
        """Replay all committed history entries."""
        for entry in self._history:
            if entry.kind == _EntryKind.USER:
                self.write("")
                self.write(Text.from_markup("[bold cyan]You[/bold cyan]"))
                self.write(Text(entry.content))
            elif entry.kind == _EntryKind.ASSISTANT:
                self.write("")
                self.write(Text.from_markup("[bold green]Onyx[/bold green]"))
                self.write(Markdown(entry.content))
                if entry.citations:
                    self.write("")
                    self.write(Text.from_markup("[bold]Sources[/bold]"))
                    for num, doc_id in sorted(entry.citations.items()):
                        self.write(Text.from_markup(f"  [dim][{num}][/dim] {doc_id}"))
            elif entry.kind == _EntryKind.INFO:
                self.write(Text.from_markup(f"[dim]{entry.content}[/dim]"))

    def show_splash(self) -> None:
        """Show the Onyx ASCII art splash screen."""
        from onyx_cli.widgets.splash import SplashScreen

        self.mount(SplashScreen())

    def add_user_message(self, message: str) -> None:
        """Add a user message to the display."""
        self._history.append(_HistoryEntry(kind=_EntryKind.USER, content=message))
        self.write("")
        self.write(Text.from_markup("[bold cyan]You[/bold cyan]"))
        self.write(Text(message))

    def start_assistant_message(self) -> None:
        """Start a new assistant response section."""
        self._current_assistant_text = ""
        self._is_streaming = True
        self.write("")
        self.write(Text.from_markup("[bold green]Onyx[/bold green]"))

    def append_token(self, token: str) -> None:
        """Append a token to the current assistant response.

        To avoid the cost of re-rendering the full markdown on every single
        token, we take a pragmatic approach: clear the log, replay the
        committed history, then render the in-progress markdown once.
        """
        self._current_assistant_text += token
        if self._is_streaming:
            self.clear()
            self._replay_history()
            self.write("")
            self.write(Text.from_markup("[bold green]Onyx[/bold green]"))
            self.write(Markdown(self._current_assistant_text))

    def finish_assistant_message(self) -> None:
        """Finalize the assistant message and commit it to history."""
        self._is_streaming = False
        if self._current_assistant_text:
            self._history.append(
                _HistoryEntry(kind=_EntryKind.ASSISTANT, content=self._current_assistant_text)
            )
            # Final re-render for clean markdown
            self.clear()
            self._replay_history()

    def start_reasoning(self) -> None:
        """Start a reasoning block."""
        self._is_reasoning = True
        self._reasoning_text = ""
        self.write(Text.from_markup("\n[dim italic]Thinking...[/dim italic]"))

    def append_reasoning(self, text: str) -> None:
        """Append text to the reasoning block."""
        self._reasoning_text += text

    def finish_reasoning(self) -> None:
        """Close the reasoning block."""
        self._is_reasoning = False
        if self._reasoning_text:
            # Commit a short summary to history
            self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content="[Thought process omitted]"))
            self.write(Text.from_markup(f"[dim]{self._reasoning_text}[/dim]"))

    def show_search_indicator(self, queries: list[str] | None = None, is_internet: bool = False) -> None:
        """Show a search indicator."""
        prefix = "Web search" if is_internet else "Searching"
        if queries:
            query_text = ", ".join(f'"{q}"' for q in queries[:3])
            msg = f"{prefix}: {query_text}"
        else:
            msg = f"{prefix}..."
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.write(Text.from_markup(f"[dim]{msg}[/dim]"))

    def show_documents_found(self, count: int) -> None:
        """Show how many documents were found."""
        msg = f"Found {count} document{'s' if count != 1 else ''}"
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.write(Text.from_markup(f"[dim]{msg}[/dim]"))

    def show_citations(self, citations: dict[int, str]) -> None:
        """Show citation references at the end of a response.

        Also attaches them to the last assistant entry in history.
        """
        if not citations:
            return

        # Attach to last assistant history entry
        for entry in reversed(self._history):
            if entry.kind == _EntryKind.ASSISTANT:
                entry.citations = dict(citations)
                break

        self.write("")
        self.write(Text.from_markup("[bold]Sources[/bold]"))
        for num, doc_id in sorted(citations.items()):
            self.write(Text.from_markup(f"  [dim][{num}][/dim] {doc_id}"))

    def show_tool_start(self, tool_name: str) -> None:
        """Show that a tool is being used."""
        msg = f"Using {tool_name}..."
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.write(Text.from_markup(f"[dim]{msg}[/dim]"))

    def show_error(self, error: str) -> None:
        """Show an error message."""
        self.write("")
        self.write(Text.from_markup(f"[bold red]Error:[/bold red] {error}"))

    def show_info(self, message: str) -> None:
        """Show an informational message."""
        self.write(Text.from_markup(f"[dim]{message}[/dim]"))

    def show_research_task(self, task: str) -> None:
        """Show a deep research sub-task."""
        msg = f"Researching: {task}"
        self._history.append(_HistoryEntry(kind=_EntryKind.INFO, content=msg))
        self.write(Text.from_markup(f"[dim]{msg}[/dim]"))

    def clear(self) -> None:
        """Clear the display (but NOT the history)."""
        super().clear()

    def clear_all(self) -> None:
        """Clear both display and history (for /new command)."""
        self._history.clear()
        self._current_assistant_text = ""
        super().clear()
