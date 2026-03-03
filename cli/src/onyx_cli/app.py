"""Main Textual App for Onyx CLI."""

from __future__ import annotations

import asyncio
import webbrowser
from pathlib import Path
from uuid import UUID

from onyx_cli.api_client import OnyxApiClient
from onyx_cli.api_client import OnyxApiError
from onyx_cli.config import load_config
from onyx_cli.config import OnyxCliConfig
from onyx_cli.config import save_config
from onyx_cli.models import CitationEvent
from onyx_cli.models import DeepResearchPlanDeltaEvent
from onyx_cli.models import ErrorEvent
from onyx_cli.models import FileDescriptorPayload
from onyx_cli.models import IntermediateReportDeltaEvent
from onyx_cli.models import MessageDeltaEvent
from onyx_cli.models import MessageIdEvent
from onyx_cli.models import MessageStartEvent
from onyx_cli.models import PersonaSummary
from onyx_cli.models import ReasoningDeltaEvent
from onyx_cli.models import ReasoningDoneEvent
from onyx_cli.models import ReasoningStartEvent
from onyx_cli.models import ResearchAgentStartEvent
from onyx_cli.models import SearchDocumentsEvent
from onyx_cli.models import SearchQueriesEvent
from onyx_cli.models import SearchStartEvent
from onyx_cli.models import SessionCreatedEvent
from onyx_cli.models import StopEvent
from onyx_cli.models import ToolStartEvent
from onyx_cli.widgets.chat_display import ChatDisplay
from onyx_cli.widgets.chat_display import SessionPicker
from onyx_cli.widgets.input_area import AttachedFilesBadge
from onyx_cli.widgets.input_area import ChatInput
from onyx_cli.widgets.input_area import InputArea
from onyx_cli.widgets.status_bar import StatusBar
from textual.app import App
from textual.app import ComposeResult
from textual.binding import Binding


HELP_TEXT = """\
[bold]Onyx CLI Commands[/bold]

  [bold cyan]/help[/bold cyan]              Show this help message
  [bold cyan]/new[/bold cyan]               Start a new chat session
  [bold cyan]/persona[/bold cyan]           List and switch assistants
  [bold cyan]/attach <path>[/bold cyan]     Attach a file to next message
  [bold cyan]/sessions[/bold cyan]          List recent chat sessions
  [bold cyan]/resume <id>[/bold cyan]       Resume a previous session
  [bold cyan]/configure[/bold cyan]         Re-run connection setup
  [bold cyan]/connectors[/bold cyan]        Open connectors page in browser
  [bold cyan]/settings[/bold cyan]          Open Onyx settings in browser
  [bold cyan]/quit[/bold cyan]              Exit Onyx CLI

[bold]Keyboard Shortcuts[/bold]

  [bold cyan]Enter[/bold cyan]              Send message
  [bold cyan]Escape[/bold cyan]             Cancel current generation
  [bold cyan]Ctrl+O[/bold cyan]             Toggle source citations
  [bold cyan]Ctrl+D[/bold cyan]             Quit (press twice)
"""


class OnyxApp(App):
    """Onyx CLI - Terminal chat interface for Onyx."""

    TITLE = "Onyx CLI"

    CSS = """
    Screen {
        background: $surface;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel_stream", "Cancel", show=False),
        Binding("ctrl+d", "quit_app", "Quit", show=False),
        Binding("ctrl+o", "toggle_sources", "Sources", show=False),
    ]

    def __init__(self, config: OnyxCliConfig | None = None) -> None:
        super().__init__()
        self._config = config or load_config()
        self._client = OnyxApiClient(self._config)
        self._chat_session_id: UUID | None = None
        self._persona_id: int = self._config.default_persona_id
        self._persona_name: str = "Default"
        self._personas: list[PersonaSummary] = []
        self._is_streaming: bool = False
        self._stream_task: asyncio.Task | None = None  # type: ignore[type-arg]
        self._attached_files: list[FileDescriptorPayload] = []
        self._citations: dict[int, str] = {}
        self._quit_pending: bool = False
        self._assistant_started: bool = False
        self._parent_message_id: int | None = -1
        self._needs_rename: bool = False

    def compose(self) -> ComposeResult:
        yield ChatDisplay()
        yield InputArea()
        yield StatusBar()

    def on_mount(self) -> None:
        # Focus the input immediately so the user can type right away,
        # before any async initialization that might block.
        self.query_one(ChatInput).focus()
        # Run API initialization in the background so it doesn't block the UI.
        self.run_worker(self._initialize_chat(), exclusive=False)

    async def _initialize_chat(self) -> None:
        """Initialize the chat interface after configuration."""
        chat = self.query_one(ChatDisplay)
        status = self.query_one(StatusBar)

        # Load personas in background
        try:
            self._personas = await self._client.list_personas()
            # Find default persona name
            for p in self._personas:
                if p.id == self._persona_id:
                    self._persona_name = p.name
                    break
        except Exception:
            chat.show_info("Could not load assistants. Using default.")

        status.set_server(self._config.server_url)
        status.set_persona(self._persona_name)

    # ── Message Handling ─────────────────────────────────────────────

    async def on_chat_input_message_submitted(
        self, event: ChatInput.MessageSubmitted
    ) -> None:
        """Handle submitted text from the chat input."""
        text = event.text

        # Handle slash commands
        if text.startswith("/"):
            await self._handle_slash_command(text)
            return

        # Send as chat message
        await self._send_message(text)

    async def _send_message(self, message: str) -> None:
        """Send a message and stream the response."""
        if self._is_streaming:
            return

        chat = self.query_one(ChatDisplay)
        status = self.query_one(StatusBar)

        # Show user message
        chat.add_user_message(message)

        # Prepare file descriptors
        file_descriptors = list(self._attached_files)
        self._attached_files.clear()
        self.query_one(AttachedFilesBadge).clear_files()

        # Start streaming
        self._is_streaming = True
        self._citations = {}
        self._assistant_started = False
        status.set_streaming(True)

        self._stream_task = asyncio.create_task(
            self._stream_response(message, file_descriptors)
        )

    async def _stream_response(
        self,
        message: str,
        file_descriptors: list[FileDescriptorPayload],
    ) -> None:
        """Stream the assistant response."""
        chat = self.query_one(ChatDisplay)
        status = self.query_one(StatusBar)

        try:
            async for event in self._client.send_message_stream(
                message=message,
                chat_session_id=self._chat_session_id,
                persona_id=self._persona_id,
                parent_message_id=self._parent_message_id,
                file_descriptors=file_descriptors if file_descriptors else None,
            ):
                match event:
                    case SessionCreatedEvent():
                        self._chat_session_id = event.chat_session_id
                        self._needs_rename = True
                        status.set_session(str(event.chat_session_id))

                    case MessageIdEvent():
                        self._parent_message_id = event.reserved_assistant_message_id

                    case MessageStartEvent():
                        if not self._assistant_started:
                            chat.start_assistant_message()
                            self._assistant_started = True

                    case MessageDeltaEvent():
                        if not self._assistant_started:
                            chat.start_assistant_message()
                            self._assistant_started = True
                        chat.append_token(event.content)

                    case SearchStartEvent():
                        chat.show_search_indicator(is_internet=event.is_internet_search)

                    case SearchQueriesEvent():
                        chat.show_search_indicator(queries=event.queries)

                    case SearchDocumentsEvent():
                        chat.show_documents_found(len(event.documents))

                    case ReasoningStartEvent():
                        chat.start_reasoning()

                    case ReasoningDeltaEvent():
                        chat.append_reasoning(event.reasoning)

                    case ReasoningDoneEvent():
                        chat.finish_reasoning()

                    case CitationEvent():
                        self._citations[event.citation_number] = event.document_id

                    case ToolStartEvent():
                        chat.show_tool_start(event.tool_name)

                    case ResearchAgentStartEvent():
                        chat.show_research_task(event.research_task)

                    case DeepResearchPlanDeltaEvent():
                        chat.append_token(event.content)

                    case IntermediateReportDeltaEvent():
                        chat.append_token(event.content)

                    case StopEvent():
                        break

                    case ErrorEvent():
                        chat.show_error(event.error)
                        break

        except OnyxApiError as e:
            chat.show_error(f"API error: {e.detail}")
        except asyncio.CancelledError:
            chat.show_info("Generation cancelled.")
        except Exception as e:
            chat.show_error(str(e))
        finally:
            if self._assistant_started:
                chat.finish_assistant_message()
                if self._citations:
                    chat.show_citations(self._citations)
            self._is_streaming = False
            status.set_streaming(False)
            self._stream_task = None

            # Auto-name new sessions after the first response
            if self._needs_rename and self._chat_session_id:
                self._needs_rename = False
                asyncio.create_task(self._auto_rename_session())

    async def _auto_rename_session(self) -> None:
        """Ask the backend to auto-generate a session name via LLM."""
        if not self._chat_session_id:
            return
        try:
            await self._client.rename_chat_session(self._chat_session_id)
        except Exception:
            pass  # Best-effort; don't disrupt the user

    # ── Slash Commands ───────────────────────────────────────────────

    async def _handle_slash_command(self, text: str) -> None:
        """Dispatch slash commands."""
        parts = text.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        chat = self.query_one(ChatDisplay)

        match command:
            case "/help":
                chat.write(HELP_TEXT)

            case "/new":
                await self._new_session()

            case "/persona" | "/assistant":
                if arg:
                    await self._select_persona(arg)
                else:
                    await self._show_personas()

            case "/attach":
                await self._attach_file(arg)

            case "/sessions":
                await self._show_sessions()

            case "/resume":
                await self._resume_session(arg)

            case "/configure":
                chat.show_info(
                    "Run 'onyx-cli configure' to change connection settings."
                )

            case "/connectors":
                url = f"{self._config.server_url}/admin/connectors"
                webbrowser.open(url)
                chat.show_info(f"Opened {url} in browser")

            case "/settings":
                url = f"{self._config.server_url}/admin/settings"
                webbrowser.open(url)
                chat.show_info(f"Opened {url} in browser")

            case "/quit":
                self.exit()

            case _:
                chat.show_info(
                    f"Unknown command: {command}. Type /help for available commands."
                )

    async def _new_session(self) -> None:
        """Start a new chat session."""
        chat = self.query_one(ChatDisplay)
        status = self.query_one(StatusBar)

        self._chat_session_id = None
        self._parent_message_id = -1
        self._needs_rename = False
        self._citations = {}
        chat.clear_all()
        status.set_session("")
        chat.show_info("New conversation started. Type a message to begin.")

    async def _show_personas(self) -> None:
        """Show available personas and let user pick one."""
        chat = self.query_one(ChatDisplay)

        try:
            self._personas = await self._client.list_personas()
        except Exception as e:
            chat.show_error(f"Could not load assistants: {e}")
            return

        if not self._personas:
            chat.show_info("No assistants available.")
            return

        chat.write("")
        chat.write("[bold]Available Assistants[/bold]")
        for p in self._personas:
            marker = " [bold green]*[/bold green]" if p.id == self._persona_id else ""
            desc = (
                f" - {p.description[:60]}..."
                if p.description and len(p.description) > 60
                else f" - {p.description}" if p.description else ""
            )
            chat.write(f"  [bold]{p.id}[/bold]: {p.name}{desc}{marker}")
        chat.write("")
        chat.show_info("Use /persona <id> to switch. Example: /persona 1")

        # Check if user passed an ID
        # This is handled in the slash command dispatch since we split the command

    async def _select_persona(self, persona_id_str: str) -> None:
        """Switch to a specific persona by ID."""
        chat = self.query_one(ChatDisplay)
        status = self.query_one(StatusBar)

        try:
            pid = int(persona_id_str)
        except ValueError:
            chat.show_info("Invalid persona ID. Use a number.")
            return

        # Find persona
        target = None
        for p in self._personas:
            if p.id == pid:
                target = p
                break

        if target is None:
            chat.show_info(
                f"Persona {pid} not found. Use /persona to see available assistants."
            )
            return

        self._persona_id = target.id
        self._persona_name = target.name
        status.set_persona(target.name)
        chat.show_info(f"Switched to assistant: {target.name}")

        # Save preference
        self._config.default_persona_id = target.id
        save_config(self._config)

    async def _attach_file(self, path_str: str) -> None:
        """Attach a file for the next message."""
        chat = self.query_one(ChatDisplay)
        badge = self.query_one(AttachedFilesBadge)

        if not path_str:
            chat.show_info("Usage: /attach <file_path>")
            return

        file_path = Path(path_str).expanduser().resolve()
        if not file_path.exists():
            chat.show_error(f"File not found: {file_path}")
            return

        chat.show_info(f"Uploading {file_path.name}...")

        try:
            descriptor = await self._client.upload_file(file_path)
            self._attached_files.append(descriptor)
            badge.add_file(file_path.name)
            chat.show_info(f"Attached: {file_path.name}")
        except Exception as e:
            chat.show_error(f"Upload failed: {e}")

    async def _show_sessions(self) -> None:
        """Show recent chat sessions as an interactive picker."""
        chat = self.query_one(ChatDisplay)

        try:
            sessions = await self._client.list_chat_sessions()
        except Exception as e:
            chat.show_error(f"Could not load sessions: {e}")
            return

        if not sessions:
            chat.show_info("No previous sessions found.")
            return

        chat.show_info("Select a session to resume (Enter to select, Esc to cancel):")

        # Build options: (full_session_id, display_label)
        options: list[tuple[str, str]] = []
        for s in sessions[:15]:
            name = s.name or "Untitled"
            sid = str(s.id)[:8]
            label = f"{sid}  {name}  [dim]({s.time_created})[/dim]"
            options.append((str(s.id), label))

        picker = SessionPicker(options)
        chat.mount(picker)
        chat._scroll_to_end()
        picker.focus()

    async def on_session_picker_session_selected(
        self, event: SessionPicker.SessionSelected
    ) -> None:
        """Handle session selection from the interactive picker."""
        await self._resume_session(event.session_id)
        # Return focus to the chat input
        self.query_one(ChatInput).focus()

    async def _resume_session(self, session_id_str: str) -> None:
        """Resume a previous chat session."""
        chat = self.query_one(ChatDisplay)
        status = self.query_one(StatusBar)

        if not session_id_str:
            chat.show_info("Usage: /resume <session_id>")
            return

        # Try to find session by prefix match
        try:
            sessions = await self._client.list_chat_sessions()
        except Exception as e:
            chat.show_error(f"Could not load sessions: {e}")
            return

        target = None
        for s in sessions:
            if str(s.id).startswith(session_id_str):
                target = s
                break

        if target is None:
            # Try as full UUID
            try:
                target_uuid = UUID(session_id_str)
                self._chat_session_id = target_uuid
            except ValueError:
                chat.show_error(f"Session not found: {session_id_str}")
                return
        else:
            self._chat_session_id = target.id

        # Load session messages
        try:
            detail = await self._client.get_chat_session(self._chat_session_id)
            chat.clear()
            status.set_session(str(self._chat_session_id))

            if detail.persona_name:
                self._persona_name = detail.persona_name
                status.set_persona(detail.persona_name)
            if detail.persona_id is not None:
                self._persona_id = detail.persona_id

            # Replay messages
            for msg in detail.messages:
                if msg.message_type == "user":
                    chat.add_user_message(msg.message)
                elif msg.message_type == "assistant":
                    chat.start_assistant_message()
                    chat.append_token(msg.message)
                    chat.finish_assistant_message()

            # Set parent to last message
            if detail.messages:
                self._parent_message_id = detail.messages[-1].message_id

            chat.show_info(f"Resumed session: {detail.description or 'Untitled'}")
        except Exception as e:
            chat.show_error(f"Could not load session: {e}")

    # ── Keybindings ──────────────────────────────────────────────────

    def action_cancel_stream(self) -> None:
        """Cancel the current streaming response."""
        if self._is_streaming and self._stream_task:
            self._stream_task.cancel()
            if self._chat_session_id:
                asyncio.create_task(
                    self._client.stop_chat_session(self._chat_session_id)
                )

    def action_toggle_sources(self) -> None:
        """Toggle visibility of citation sources."""
        chat = self.query_one(ChatDisplay)
        chat.toggle_sources()

    def action_quit_app(self) -> None:
        """Quit with double Ctrl+D confirmation."""
        if self._quit_pending:
            self.exit()
        else:
            self._quit_pending = True
            chat = self.query_one(ChatDisplay)
            chat.show_info("Press Ctrl+D again to quit.")
            # Reset after 2 seconds
            self.set_timer(2.0, self._reset_quit)

    def _reset_quit(self) -> None:
        self._quit_pending = False

    async def on_unmount(self) -> None:
        """Clean up on exit."""
        await self._client.close()
