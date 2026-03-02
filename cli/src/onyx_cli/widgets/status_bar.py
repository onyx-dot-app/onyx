"""Footer status bar widget."""

from __future__ import annotations

from textual.widgets import Static


class StatusBar(Static):
    """Footer bar showing session info and keyboard shortcuts."""

    DEFAULT_CSS = """
    StatusBar {
        width: 100%;
        height: 1;
        dock: bottom;
        background: #1a1a2e;
        color: #666688;
        padding: 0 1;
        text-align: center;
    }
    """

    def __init__(self) -> None:
        super().__init__("")
        self._persona_name: str = "Default"
        self._session_id: str = ""
        self._is_streaming: bool = False
        self._refresh_text()

    def set_persona(self, name: str) -> None:
        self._persona_name = name
        self._refresh_text()

    def set_session(self, session_id: str) -> None:
        self._session_id = session_id[:8] if session_id else ""
        self._refresh_text()

    def set_streaming(self, is_streaming: bool) -> None:
        self._is_streaming = is_streaming
        self._refresh_text()

    def _refresh_text(self) -> None:
        parts: list[str] = []

        if self._is_streaming:
            parts.append("Esc cancel")
        parts.append("Ctrl+D quit")
        parts.append("/help commands")

        if self._persona_name:
            parts.append(f"Assistant: {self._persona_name}")

        if self._session_id:
            parts.append(f"Session: #{self._session_id}")

        self.update(" | ".join(parts))
