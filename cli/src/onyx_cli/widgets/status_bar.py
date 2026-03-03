"""Minimal footer status bar widget."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class _StatusLeft(Static):
    """Left-aligned status text (assistant name)."""

    DEFAULT_CSS = """
    _StatusLeft {
        width: 1fr;
        height: 1;
        color: #555577;
        padding: 0 1;
    }
    """


class _StatusRight(Static):
    """Right-aligned status text (contextual hint)."""

    DEFAULT_CSS = """
    _StatusRight {
        width: auto;
        height: 1;
        color: #555577;
        padding: 0 1;
        text-align: right;
    }
    """


class StatusBar(Horizontal):
    """Minimal footer: assistant name on the left, contextual hint on the right."""

    DEFAULT_CSS = """
    StatusBar {
        width: 100%;
        height: 1;
        dock: bottom;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._persona_name: str = "Default"
        self._server_url: str = ""
        self._session_id: str = ""
        self._is_streaming: bool = False

    def compose(self) -> ComposeResult:
        yield _StatusLeft(self._persona_name)
        yield _StatusRight("Ctrl+D to quit")

    def set_persona(self, name: str) -> None:
        self._persona_name = name
        self._refresh_text()

    def set_server(self, url: str) -> None:
        self._server_url = url
        self._refresh_text()

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id[:8] if session_id else ""

    def set_streaming(self, is_streaming: bool) -> None:
        self._is_streaming = is_streaming
        self._refresh_text()

    def _refresh_text(self) -> None:
        try:
            left = self.query_one(_StatusLeft)
            right = self.query_one(_StatusRight)
        except Exception:
            return

        left_parts: list[str] = []
        if self._server_url:
            left_parts.append(self._server_url)
        left_parts.append(self._persona_name or "Default")
        left.update(" \u00b7 ".join(left_parts))
        right.update("Esc to cancel" if self._is_streaming else "Ctrl+D to quit")
