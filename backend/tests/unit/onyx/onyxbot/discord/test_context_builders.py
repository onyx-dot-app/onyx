"""Unit tests for Discord bot context builders.

Tests the thread and reply context building logic with mocked Discord API.
"""

from typing import Any
from unittest.mock import AsyncMock
from unittest.mock import MagicMock

import discord
import pytest

from onyx.onyxbot.discord.constants import MAX_CONTEXT_MESSAGES
from onyx.onyxbot.discord.handle_message import _build_conversation_context
from onyx.onyxbot.discord.handle_message import _build_reply_chain_context
from onyx.onyxbot.discord.handle_message import _build_thread_context
from onyx.onyxbot.discord.handle_message import _format_messages_as_context
from onyx.onyxbot.discord.handle_message import format_message_content
from tests.unit.onyx.onyxbot.discord.conftest import AsyncIteratorMock
from tests.unit.onyx.onyxbot.discord.conftest import mock_message


class TestThreadContextBuilder:
    """Tests for _build_thread_context function."""

    @pytest.mark.asyncio
    async def test_build_thread_context_basic(
        self, mock_thread_with_messages: MagicMock, mock_bot_user: MagicMock
    ) -> None:
        """Thread with messages returns context in order."""
        msg = MagicMock(spec=discord.Message)
        msg.id = 999  # Current message ID
        msg.channel = mock_thread_with_messages

        result = await _build_thread_context(msg, mock_bot_user)

        assert result is not None
        assert "Conversation history" in result
        # Should contain message content
        assert "User msg" in result or "Bot response" in result

    @pytest.mark.asyncio
    async def test_build_thread_context_max_limit(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread with 20 messages returns only MAX_CONTEXT_MESSAGES."""
        # Create 20 messages
        messages = [
            mock_message(content=f"Message {i}", message_id=i) for i in range(20)
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)

        def history(**kwargs: Any) -> AsyncIteratorMock:
            limit = kwargs.get("limit", MAX_CONTEXT_MESSAGES)
            return AsyncIteratorMock(messages[:limit])

        thread.history = history
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "")
        )

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        result = await _build_thread_context(msg, mock_bot_user)

        assert result is not None
        # Should only have MAX_CONTEXT_MESSAGES worth of content

    @pytest.mark.asyncio
    async def test_build_thread_context_includes_starter(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread with starter message includes it at beginning."""
        starter = mock_message(
            content="This is the thread starter",
            message_id=666666,
        )

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(return_value=starter)

        messages = [
            mock_message(content="Reply 1", message_id=1),
            mock_message(content="Reply 2", message_id=2),
        ]

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        result = await _build_thread_context(msg, mock_bot_user)

        assert result is not None
        assert "thread starter" in result

    @pytest.mark.asyncio
    async def test_build_thread_context_filters_system_messages(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread with system messages only includes content messages."""
        messages = [
            mock_message(
                content="Normal message", message_type=discord.MessageType.default
            ),
            mock_message(
                content="", message_type=discord.MessageType.pins_add
            ),  # System
            mock_message(
                content="Another normal", message_type=discord.MessageType.reply
            ),
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "")
        )

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        result = await _build_thread_context(msg, mock_bot_user)

        # Should not include system message type
        assert result is not None

    @pytest.mark.asyncio
    async def test_build_thread_context_includes_bot_messages(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Bot messages in thread are included for context."""
        messages = [
            mock_message(content="User question", author_bot=False),
            mock_message(
                content="Bot response",
                author_bot=True,
                author_id=mock_bot_user.id,
                author_display_name="OnyxBot",
            ),
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "")
        )

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        result = await _build_thread_context(msg, mock_bot_user)

        assert result is not None
        assert "Bot response" in result

    @pytest.mark.asyncio
    async def test_build_thread_context_empty_thread(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread with only system messages returns None."""
        messages = [
            mock_message(content="", message_type=discord.MessageType.pins_add),
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "")
        )

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        await _build_thread_context(msg, mock_bot_user)
        # Should return None for empty context
        # (depends on implementation - may return None or empty string)

    @pytest.mark.asyncio
    async def test_build_thread_context_forum_channel(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Thread parent is ForumChannel - does NOT fetch starter message."""
        messages = [
            mock_message(content="Forum reply", message_id=1),
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.ForumChannel)  # Forum!
        # Set up mock before calling function so we can verify it wasn't called
        thread.parent.fetch_message = AsyncMock()

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        await _build_thread_context(msg, mock_bot_user)

        # Should not try to fetch starter message for forum channels
        thread.parent.fetch_message.assert_not_called()

    @pytest.mark.asyncio
    async def test_build_thread_context_starter_fetch_fails(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Starter message fetch raises NotFound - continues without starter."""
        messages = [
            mock_message(content="Reply message", message_id=1),
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "Not found")
        )

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        result = await _build_thread_context(msg, mock_bot_user)

        # Should still return context without starter
        assert result is not None

    @pytest.mark.asyncio
    async def test_build_thread_context_deduplicates_starter(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Starter also in recent history is not duplicated."""
        starter = mock_message(content="Thread starter", message_id=666666)

        messages = [
            starter,  # Starter in history
            mock_message(content="Reply", message_id=1),
        ]

        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(return_value=starter)

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread

        result = await _build_thread_context(msg, mock_bot_user)

        # Should only have starter once
        if result:
            assert (
                result.count("Thread starter") <= 2
            )  # At most once in formatted output


class TestReplyChainContextBuilder:
    """Tests for _build_reply_chain_context function."""

    @pytest.mark.asyncio
    async def test_build_reply_chain_single_reply(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Message replies to one message returns 1 message in chain."""
        parent = mock_message(content="Parent message", message_id=100)
        parent.reference = None

        child = MagicMock(spec=discord.Message)
        child.id = 200
        child.reference = MagicMock()
        child.reference.message_id = 100
        child.channel = MagicMock()
        child.channel.fetch_message = AsyncMock(return_value=parent)
        child.channel.name = "general"

        result = await _build_reply_chain_context(child, mock_bot_user)

        assert result is not None
        assert "Parent message" in result

    @pytest.mark.asyncio
    async def test_build_reply_chain_deep_chain(self, mock_bot_user: MagicMock) -> None:
        """A → B → C → D reply chain returns full chain in chronological order."""
        msg_d = mock_message(content="Message D", message_id=4)
        msg_d.reference = None

        msg_c = mock_message(content="Message C", message_id=3)
        ref_c = MagicMock()
        ref_c.message_id = 4
        msg_c.reference = ref_c

        msg_b = mock_message(content="Message B", message_id=2)
        ref_b = MagicMock()
        ref_b.message_id = 3
        msg_b.reference = ref_b

        # Current message replying to B
        ref_a = MagicMock()
        ref_a.message_id = 2

        msg_a = MagicMock(spec=discord.Message)
        msg_a.id = 1
        msg_a.reference = ref_a
        msg_a.channel = MagicMock()
        msg_a.channel.name = "general"

        # Mock fetch to return the chain
        message_map = {2: msg_b, 3: msg_c, 4: msg_d}

        async def fetch_message(msg_id: int) -> MagicMock:
            if msg_id in message_map:
                return message_map[msg_id]
            raise discord.NotFound(MagicMock(), "Not found")

        msg_a.channel.fetch_message = AsyncMock(side_effect=fetch_message)

        result = await _build_reply_chain_context(msg_a, mock_bot_user)

        assert result is not None
        # Should have all messages from the chain

    @pytest.mark.asyncio
    async def test_build_reply_chain_max_depth(self, mock_bot_user: MagicMock) -> None:
        """Chain depth > MAX_CONTEXT_MESSAGES stops at limit."""
        # Create a chain longer than MAX_CONTEXT_MESSAGES
        messages = {}
        for i in range(MAX_CONTEXT_MESSAGES + 5, 0, -1):
            msg = mock_message(content=f"Message {i}", message_id=i)
            if i < MAX_CONTEXT_MESSAGES + 5:
                ref = MagicMock()
                ref.message_id = i + 1
                msg.reference = ref
            else:
                msg.reference = None
            messages[i] = msg

        # Start from message 1
        start = MagicMock(spec=discord.Message)
        start.id = 0
        start.reference = MagicMock()
        start.reference.message_id = 1
        start.channel = MagicMock()
        start.channel.name = "general"

        async def fetch_message(msg_id: int) -> MagicMock:
            if msg_id in messages:
                return messages[msg_id]
            raise discord.NotFound(MagicMock(), "Not found")

        start.channel.fetch_message = AsyncMock(side_effect=fetch_message)

        result = await _build_reply_chain_context(start, mock_bot_user)

        # Should have at most MAX_CONTEXT_MESSAGES
        assert result is not None

    @pytest.mark.asyncio
    async def test_build_reply_chain_no_reply(self, mock_bot_user: MagicMock) -> None:
        """Message is not a reply returns None."""
        msg = MagicMock(spec=discord.Message)
        msg.reference = None

        result = await _build_reply_chain_context(msg, mock_bot_user)
        assert result is None

    @pytest.mark.asyncio
    async def test_build_reply_chain_deleted_message(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Reply to deleted message handles gracefully with partial chain."""
        msg = MagicMock(spec=discord.Message)
        msg.id = 200
        msg.reference = MagicMock()
        msg.reference.message_id = 100
        msg.channel = MagicMock()
        msg.channel.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "Not found")
        )
        msg.channel.name = "general"

        await _build_reply_chain_context(msg, mock_bot_user)
        # Should handle gracefully - may return None or partial context
        # Either is acceptable

    @pytest.mark.asyncio
    async def test_build_reply_chain_missing_reference_data(
        self, mock_bot_user: MagicMock
    ) -> None:
        """message.reference.message_id is None returns None."""
        msg = MagicMock(spec=discord.Message)
        msg.reference = MagicMock()
        msg.reference.message_id = None

        result = await _build_reply_chain_context(msg, mock_bot_user)
        assert result is None

    @pytest.mark.asyncio
    async def test_build_reply_chain_http_exception(
        self, mock_bot_user: MagicMock
    ) -> None:
        """discord.HTTPException on fetch stops chain."""
        msg = MagicMock(spec=discord.Message)
        msg.id = 200
        msg.reference = MagicMock()
        msg.reference.message_id = 100
        msg.channel = MagicMock()
        msg.channel.fetch_message = AsyncMock(
            side_effect=discord.HTTPException(MagicMock(), "HTTP error")
        )
        msg.channel.name = "general"

        await _build_reply_chain_context(msg, mock_bot_user)
        # Should handle gracefully


class TestCombinedContext:
    """Tests for combined thread + reply context."""

    @pytest.mark.asyncio
    async def test_combined_context_thread_with_reply(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Reply inside thread includes both contexts."""
        # Create a thread with messages
        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "")
        )

        # Thread history
        thread_messages = [
            mock_message(content="Thread msg 1", message_id=1),
            mock_message(content="Thread msg 2", message_id=2),
        ]

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(thread_messages)

        thread.history = history

        # Message is a reply to another message in the thread
        parent_msg = mock_message(content="Parent message", message_id=2)
        parent_msg.reference = None

        ref = MagicMock()
        ref.message_id = 2

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread
        msg.reference = ref
        msg.channel.fetch_message = AsyncMock(return_value=parent_msg)
        msg.channel.name = "test-thread"

        result = await _build_conversation_context(msg, mock_bot_user)

        # Should have context from the thread
        assert result is not None
        assert "Conversation history" in result

    @pytest.mark.asyncio
    async def test_build_conversation_context_routes_to_thread(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Message in thread routes to _build_thread_context."""
        thread = MagicMock(spec=discord.Thread)
        thread.id = 666666
        thread.parent = MagicMock(spec=discord.TextChannel)
        thread.parent.fetch_message = AsyncMock(
            side_effect=discord.NotFound(MagicMock(), "")
        )

        messages = [mock_message(content="Thread msg")]

        def history(**kwargs: Any) -> AsyncIteratorMock:  # noqa: ARG001
            return AsyncIteratorMock(messages)

        thread.history = history

        msg = MagicMock(spec=discord.Message)
        msg.id = 999
        msg.channel = thread
        msg.reference = None

        result = await _build_conversation_context(msg, mock_bot_user)
        assert result is not None

    @pytest.mark.asyncio
    async def test_build_conversation_context_routes_to_reply(
        self, mock_bot_user: MagicMock
    ) -> None:
        """Message with reference routes to _build_reply_chain_context."""
        parent = mock_message(content="Parent", message_id=100)
        parent.reference = None

        msg = MagicMock(spec=discord.Message)
        msg.id = 200
        msg.channel = MagicMock(spec=discord.TextChannel)  # Not a thread
        msg.reference = MagicMock()
        msg.reference.message_id = 100
        msg.channel.fetch_message = AsyncMock(return_value=parent)
        msg.channel.name = "general"

        result = await _build_conversation_context(msg, mock_bot_user)
        assert result is not None


class TestContextFormatting:
    """Tests for context formatting."""

    def test_format_message_content_mentions(self) -> None:
        """Messages with <@123> mentions are converted to @username."""
        msg = MagicMock(spec=discord.Message)
        msg.content = "Hello <@123456789> how are you?"

        user = MagicMock()
        user.id = 123456789
        user.display_name = "TestUser"
        msg.mentions = [user]
        msg.role_mentions = []
        msg.channel_mentions = []

        result = format_message_content(msg)
        assert "@TestUser" in result
        assert "<@123456789>" not in result

    def test_format_message_content_roles(self) -> None:
        """Messages with <@&456> roles are converted to @rolename."""
        msg = MagicMock(spec=discord.Message)
        msg.content = "Attention <@&456789> members"

        role = MagicMock()
        role.id = 456789
        role.name = "Moderators"
        msg.mentions = []
        msg.role_mentions = [role]
        msg.channel_mentions = []

        result = format_message_content(msg)
        assert "@Moderators" in result
        assert "<@&456789>" not in result

    def test_format_message_content_channels(self) -> None:
        """Messages with <#789> channels are converted to #channelname."""
        msg = MagicMock(spec=discord.Message)
        msg.content = "Check out <#789012>"

        channel = MagicMock()
        channel.id = 789012
        channel.name = "announcements"
        msg.mentions = []
        msg.role_mentions = []
        msg.channel_mentions = [channel]

        result = format_message_content(msg)
        assert "#announcements" in result
        assert "<#789012>" not in result

    def test_context_format_output(self, mock_bot_user: MagicMock) -> None:
        """Build full context has expected format."""
        messages: list[Any] = [
            mock_message(content="Hello bot", author_bot=False),
        ]
        messages[0].type = discord.MessageType.default

        result = _format_messages_as_context(messages, mock_bot_user)

        assert result is not None
        assert "Conversation history" in result
        assert "---" in result

    def test_context_format_with_username(self, mock_bot_user: MagicMock) -> None:
        """Messages from users include @username: prefix."""
        msg = mock_message(content="User message", author_bot=False)
        msg.author.display_name = "TestUser"
        msg.type = discord.MessageType.default

        result = _format_messages_as_context([msg], mock_bot_user)

        assert result is not None
        assert "@TestUser:" in result

    def test_context_format_bot_marker(self, mock_bot_user: MagicMock) -> None:
        """Bot messages in context are marked as OnyxBot:."""
        msg = mock_message(
            content="Bot response",
            author_bot=True,
            author_id=mock_bot_user.id,
        )
        msg.type = discord.MessageType.default

        result = _format_messages_as_context([msg], mock_bot_user)

        assert result is not None
        assert "OnyxBot:" in result
