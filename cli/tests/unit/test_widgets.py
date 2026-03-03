"""UI tests for chat TUI widgets using Textual's async pilot."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from textual.app import App, ComposeResult

from onyx_cli.app import OnyxApp
from onyx_cli.config import OnyxCliConfig
from onyx_cli.widgets.chat_display import (
    AssistantMessage,
    ChatDisplay,
    ErrorMessage,
    StatusMessage,
    UserMessage,
)
from onyx_cli.widgets.input_area import (
    AttachedFilesBadge,
    ChatInput,
    InputArea,
)
from onyx_cli.widgets.status_bar import StatusBar


# ── Minimal test apps ────────────────────────────────────────────────


class FullLayoutApp(App):
    """Mimics the real OnyxApp layout without the API client."""

    CSS = """
    Screen {
        background: $surface;
    }
    """

    def compose(self) -> ComposeResult:
        yield ChatDisplay()
        yield InputArea()
        yield StatusBar()

    def on_mount(self) -> None:
        self.query_one(ChatInput).focus()


class InputOnlyApp(App):
    """App with just the InputArea for focused testing."""

    def compose(self) -> ComposeResult:
        yield InputArea()

    def on_mount(self) -> None:
        self.query_one(ChatInput).focus()


class ChatDisplayApp(App):
    """App with just the ChatDisplay for message testing."""

    def compose(self) -> ComposeResult:
        yield ChatDisplay()


# ── Input Focus & Typing Tests ───────────────────────────────────────


class TestInputFocus:
    """Tests that the input widget can receive focus and accept typed text."""

    @pytest.mark.asyncio
    async def test_chat_input_is_focusable(self) -> None:
        """ChatInput should be focusable after mount."""
        async with FullLayoutApp().run_test() as pilot:
            chat_input = pilot.app.query_one(ChatInput)
            assert chat_input.has_focus

    @pytest.mark.asyncio
    async def test_chat_input_focusable_in_isolation(self) -> None:
        """ChatInput should be focusable even when nested in InputArea alone."""
        async with InputOnlyApp().run_test() as pilot:
            chat_input = pilot.app.query_one(ChatInput)
            assert chat_input.has_focus

    @pytest.mark.asyncio
    async def test_can_type_into_input(self) -> None:
        """Typing characters should populate the ChatInput value."""
        async with FullLayoutApp().run_test() as pilot:
            for ch in "hello":
                await pilot.press(ch)
            chat_input = pilot.app.query_one(ChatInput)
            assert chat_input.value == "hello"

    @pytest.mark.asyncio
    async def test_can_type_slash_command(self) -> None:
        """Slash commands should be typeable."""
        async with FullLayoutApp().run_test() as pilot:
            for ch in "/help":
                await pilot.press(ch)
            chat_input = pilot.app.query_one(ChatInput)
            assert chat_input.value == "/help"

    @pytest.mark.asyncio
    async def test_submit_clears_input(self) -> None:
        """Pressing Enter should clear the input after submission."""
        messages: list[str] = []

        class CapturingApp(FullLayoutApp):
            def on_chat_input_message_submitted(
                self, event: ChatInput.MessageSubmitted
            ) -> None:
                messages.append(event.text)

        async with CapturingApp().run_test() as pilot:
            for ch in "test":
                await pilot.press(ch)
            await pilot.press("enter")
            chat_input = pilot.app.query_one(ChatInput)
            assert chat_input.value == ""
            assert messages == ["test"]

    @pytest.mark.asyncio
    async def test_empty_submit_does_nothing(self) -> None:
        """Pressing Enter with empty input should not fire a message."""
        messages: list[str] = []

        class CapturingApp(FullLayoutApp):
            def on_chat_input_message_submitted(
                self, event: ChatInput.MessageSubmitted
            ) -> None:
                messages.append(event.text)

        async with CapturingApp().run_test() as pilot:
            await pilot.press("enter")
            assert messages == []


# ── Chat Display Tests ───────────────────────────────────────────────


class TestChatDisplay:
    """Tests for the ChatDisplay widget's message rendering."""

    @pytest.mark.asyncio
    async def test_add_user_message(self) -> None:
        """Adding a user message should mount a UserMessage widget."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.add_user_message("Hello there")
            await pilot.pause()
            widgets = chat.query(UserMessage)
            assert len(widgets) == 1

    @pytest.mark.asyncio
    async def test_assistant_streaming(self) -> None:
        """Streaming tokens should accumulate in a single AssistantMessage."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.start_assistant_message()
            chat.append_token("Hello ")
            chat.append_token("world")
            await pilot.pause()

            widgets = chat.query(AssistantMessage)
            assert len(widgets) == 1
            assert widgets[0].buffer == "Hello world"

    @pytest.mark.asyncio
    async def test_assistant_finish(self) -> None:
        """Finishing an assistant message should commit it to history."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.start_assistant_message()
            chat.append_token("Response text")
            chat.finish_assistant_message()
            await pilot.pause()

            assert len(chat._history) == 1
            assert chat._history[0].content == "Response text"
            assert chat._current_assistant is None

    @pytest.mark.asyncio
    async def test_show_search_indicator(self) -> None:
        """Search indicators should mount StatusMessage widgets."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.show_search_indicator(queries=["Q4 roadmap"])
            await pilot.pause()
            widgets = chat.query(StatusMessage)
            assert len(widgets) == 1

    @pytest.mark.asyncio
    async def test_show_documents_found(self) -> None:
        """Document count should mount a StatusMessage."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.show_documents_found(5)
            await pilot.pause()
            widgets = chat.query(StatusMessage)
            assert len(widgets) == 1

    @pytest.mark.asyncio
    async def test_show_error(self) -> None:
        """Errors should mount an ErrorMessage widget."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.show_error("Something went wrong")
            await pilot.pause()
            widgets = chat.query(ErrorMessage)
            assert len(widgets) == 1

    @pytest.mark.asyncio
    async def test_show_info(self) -> None:
        """Info messages should mount a StatusMessage."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.show_info("Connected to server")
            await pilot.pause()
            widgets = chat.query(StatusMessage)
            assert len(widgets) == 1

    @pytest.mark.asyncio
    async def test_clear_all(self) -> None:
        """clear_all should remove all widgets and reset history."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.add_user_message("msg1")
            chat.show_info("info1")
            await pilot.pause()
            assert len(chat._history) > 0

            chat.clear_all()
            await pilot.pause()
            assert len(chat._history) == 0
            assert len(chat.query("*")) == 0

    @pytest.mark.asyncio
    async def test_multiple_messages_in_sequence(self) -> None:
        """Multiple user + assistant messages should each get their own widget."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)

            chat.add_user_message("First question")
            chat.start_assistant_message()
            chat.append_token("First answer")
            chat.finish_assistant_message()

            chat.add_user_message("Second question")
            chat.start_assistant_message()
            chat.append_token("Second answer")
            chat.finish_assistant_message()
            await pilot.pause()

            assert len(chat.query(UserMessage)) == 2
            assert len(chat.query(AssistantMessage)) == 2
            assert len(chat._history) == 4

    @pytest.mark.asyncio
    async def test_citations(self) -> None:
        """Citations should mount a StatusMessage and attach to history."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.start_assistant_message()
            chat.append_token("Here are results")
            chat.finish_assistant_message()
            chat.show_citations({1: "doc-abc", 2: "doc-def"})
            await pilot.pause()

            # Should have a status message for citations
            status_widgets = chat.query(StatusMessage)
            assert len(status_widgets) == 1

            # Should be attached to the assistant history entry
            assert chat._history[0].citations == {1: "doc-abc", 2: "doc-def"}

    @pytest.mark.asyncio
    async def test_reasoning_flow(self) -> None:
        """Reasoning start/append/finish should work without crashing."""
        async with ChatDisplayApp().run_test() as pilot:
            chat = pilot.app.query_one(ChatDisplay)
            chat.start_reasoning()
            chat.append_reasoning("Let me think...")
            chat.finish_reasoning()
            await pilot.pause()

            # Should have a "Thinking" status message
            assert len(chat.query(StatusMessage)) == 1


# ── Status Bar Tests ─────────────────────────────────────────────────


class StatusBarApp(App):
    def compose(self) -> ComposeResult:
        yield StatusBar()


class TestStatusBar:
    """Tests for the StatusBar widget."""

    @pytest.mark.asyncio
    async def test_default_persona_shown(self) -> None:
        """Status bar should show 'Default' persona on mount."""
        async with StatusBarApp().run_test() as pilot:
            status = pilot.app.query_one(StatusBar)
            assert status._persona_name == "Default"

    @pytest.mark.asyncio
    async def test_set_persona(self) -> None:
        """set_persona should update the displayed name."""
        async with StatusBarApp().run_test() as pilot:
            status = pilot.app.query_one(StatusBar)
            status.set_persona("Research Assistant")
            await pilot.pause()
            assert status._persona_name == "Research Assistant"

    @pytest.mark.asyncio
    async def test_streaming_hint(self) -> None:
        """While streaming, hint should show 'Esc to cancel'."""
        async with StatusBarApp().run_test() as pilot:
            status = pilot.app.query_one(StatusBar)
            status.set_streaming(True)
            await pilot.pause()
            assert status._is_streaming is True

    @pytest.mark.asyncio
    async def test_not_streaming_hint(self) -> None:
        """When not streaming, hint should show 'Ctrl+D to quit'."""
        async with StatusBarApp().run_test() as pilot:
            status = pilot.app.query_one(StatusBar)
            status.set_streaming(False)
            await pilot.pause()
            assert status._is_streaming is False


# ── Attached Files Badge Tests ───────────────────────────────────────


class TestAttachedFilesBadge:
    """Tests for the file attachment badge."""

    @pytest.mark.asyncio
    async def test_initially_hidden(self) -> None:
        """Badge should be hidden when no files are attached."""
        async with FullLayoutApp().run_test() as pilot:
            badge = pilot.app.query_one(AttachedFilesBadge)
            assert badge.file_count == 0
            assert not badge.has_class("has-files")

    @pytest.mark.asyncio
    async def test_add_file_shows_badge(self) -> None:
        """Adding a file should show the badge."""
        async with FullLayoutApp().run_test() as pilot:
            badge = pilot.app.query_one(AttachedFilesBadge)
            badge.add_file("report.pdf")
            await pilot.pause()
            assert badge.file_count == 1
            assert badge.has_class("has-files")

    @pytest.mark.asyncio
    async def test_clear_files_hides_badge(self) -> None:
        """Clearing files should hide the badge."""
        async with FullLayoutApp().run_test() as pilot:
            badge = pilot.app.query_one(AttachedFilesBadge)
            badge.add_file("report.pdf")
            badge.clear_files()
            await pilot.pause()
            assert badge.file_count == 0
            assert not badge.has_class("has-files")


# ── OnyxApp Integration Tests (with mocked API) ─────────────────────


def _make_test_config() -> OnyxCliConfig:
    """Create a config that won't try to read from disk."""
    return OnyxCliConfig(
        server_url="https://test.example.com",
        api_key="test-key",
    )


class TestOnyxAppFocus:
    """Tests that the real OnyxApp gives focus to ChatInput immediately."""

    @pytest.mark.asyncio
    async def test_input_focused_on_mount(self) -> None:
        """ChatInput should have focus immediately after mount, even if API is slow."""
        config = _make_test_config()
        app = OnyxApp(config=config)

        # Mock the API client so it doesn't make real HTTP calls
        with patch.object(app._client, "list_personas", new_callable=AsyncMock) as mock:
            mock.return_value = []
            async with app.run_test() as pilot:
                await pilot.pause()
                chat_input = pilot.app.query_one(ChatInput)
                assert chat_input.has_focus

    @pytest.mark.asyncio
    async def test_input_focused_even_when_api_fails(self) -> None:
        """ChatInput should have focus even if the API call fails."""
        config = _make_test_config()
        app = OnyxApp(config=config)

        with patch.object(app._client, "list_personas", new_callable=AsyncMock) as mock:
            mock.side_effect = Exception("Connection refused")
            async with app.run_test() as pilot:
                await pilot.pause()
                chat_input = pilot.app.query_one(ChatInput)
                assert chat_input.has_focus

    @pytest.mark.asyncio
    async def test_can_type_in_real_app(self) -> None:
        """User should be able to type in the real OnyxApp."""
        config = _make_test_config()
        app = OnyxApp(config=config)

        with patch.object(app._client, "list_personas", new_callable=AsyncMock) as mock:
            mock.return_value = []
            async with app.run_test() as pilot:
                await pilot.pause()
                for ch in "hello":
                    await pilot.press(ch)
                chat_input = pilot.app.query_one(ChatInput)
                assert chat_input.value == "hello"

    @pytest.mark.asyncio
    async def test_status_bar_shows_server_after_init(self) -> None:
        """Status bar should show the server URL after initialization."""
        config = _make_test_config()
        app = OnyxApp(config=config)

        with patch.object(app._client, "list_personas", new_callable=AsyncMock) as mock:
            mock.return_value = []
            async with app.run_test() as pilot:
                # Wait for the background worker to complete
                await pilot.pause()
                await pilot.pause()
                status = pilot.app.query_one(StatusBar)
                assert status._server_url == "https://test.example.com"
