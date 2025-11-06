import os
from unittest.mock import MagicMock
from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

# Set environment variables to disable model server for testing
os.environ["MODEL_SERVER_HOST"] = "disabled"
os.environ["MODEL_SERVER_PORT"] = "9000"

from sqlalchemy.orm import Session

from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DEFAULT_PERSONA_ID
from onyx.configs.constants import MessageType
from onyx.configs.model_configs import GEN_AI_HISTORY_CUTOFF
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.models import DocumentSet
from onyx.db.models import LLMProvider
from onyx.db.models import Persona
from onyx.db.models import Persona__DocumentSet
from onyx.db.models import Persona__Tool
from onyx.db.models import SlackBot
from onyx.db.models import SlackChannelConfig
from onyx.db.models import User
from onyx.db.tools import get_builtin_tool
from onyx.llm.models import PreviousMessage
from onyx.onyxbot.slack.handlers.handle_regular_answer import handle_regular_answer
from onyx.onyxbot.slack.models import SlackMessageInfo
from onyx.tools.built_in_tools import SearchTool
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_persona(db_session: Session) -> Persona:
    """Helper to create a test persona for Slack bot"""
    unique_id = str(uuid4())[:8]
    document_set = DocumentSet(
        name=f"test_slack_docs_{unique_id}",
        description="Test document set for Slack thread context",
    )
    db_session.add(document_set)
    db_session.flush()

    persona = Persona(
        name=f"test_slack_persona_{unique_id}",
        description="Test persona for Slack thread context",
        chunks_above=0,
        chunks_below=0,
        llm_relevance_filter=True,
        llm_filter_extraction=True,
        recency_bias=RecencyBiasSetting.AUTO,
        system_prompt="You are a helpful assistant.",
        task_prompt="Answer the user's question based on the provided context.",
    )
    db_session.add(persona)
    db_session.flush()

    persona_doc_set = Persona__DocumentSet(
        persona_id=persona.id,
        document_set_id=document_set.id,
    )
    db_session.add(persona_doc_set)

    try:
        search_tool = get_builtin_tool(db_session=db_session, tool_type=SearchTool)
        if search_tool:
            persona_tool = Persona__Tool(persona_id=persona.id, tool_id=search_tool.id)
            db_session.add(persona_tool)
    except RuntimeError:
        # SearchTool not found, skip adding it
        pass

    db_session.commit()
    return persona


def _create_mock_slack_client() -> Mock:
    """Create a mock Slack client"""
    mock_client = Mock()
    mock_client.web_client = Mock()

    mock_post_message_response = {"ok": True, "message_ts": "1234567890.123456"}
    mock_client.web_client.chat_postMessage = Mock(
        return_value=mock_post_message_response
    )

    mock_users_info_response = Mock()
    mock_users_info_response.__getitem__ = Mock(
        side_effect=lambda key: {"ok": True}[key]
    )
    mock_users_info_response.data = {
        "user": {
            "id": "U9876543210",
            "name": "testuser",
            "real_name": "Test User",
            "profile": {
                "display_name": "Test User",
                "first_name": "Test",
                "last_name": "User",
                "email": "test@example.com",
            },
        }
    }
    mock_client.web_client.users_info = Mock(return_value=mock_users_info_response)

    mock_auth_test_response = {
        "ok": True,
        "user_id": "U1234567890",
        "bot_id": "B1234567890",
    }
    mock_client.web_client.auth_test = Mock(return_value=mock_auth_test_response)

    mock_client.web_client.reactions_add = Mock(return_value={"ok": True})
    mock_client.web_client.reactions_remove = Mock(return_value={"ok": True})

    return mock_client


def _setup_llm_provider(db_session: Session) -> None:
    """Create a default LLM provider in the database for testing with real API key"""
    # Delete any existing default LLM provider to ensure clean state
    existing_providers = db_session.query(LLMProvider).all()
    for provider in existing_providers:
        db_session.delete(provider)
    db_session.commit()

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise ValueError(
            "OPENAI_API_KEY environment variable not set - test requires real API key"
        )

    llm_provider = LLMProvider(
        name=f"test-llm-provider-{uuid4().hex[:8]}",
        provider="openai",
        api_key=api_key,
        default_model_name="gpt-4o",
        fast_default_model_name="gpt-4o-mini",
        is_default_provider=True,
        is_public=True,
    )
    db_session.add(llm_provider)
    db_session.commit()


class TestSlackThreadContext:
    """Test Slack bot thread context handling for query rephrasing"""

    def _setup_test_environment(
        self, db_session: Session
    ) -> tuple[User, Persona, SlackBot, SlackChannelConfig]:
        """Setup test environment with user, persona, and Slack channel config"""
        user = create_test_user(db_session, "slack_thread_test")
        persona = _create_test_persona(db_session)

        unique_id = str(uuid4())[:8]
        slack_bot = SlackBot(
            name=f"Test Slack Bot {unique_id}",
            bot_token=f"xoxb-test-token-{unique_id}",
            app_token=f"xapp-test-token-{unique_id}",
            user_token=f"xoxp-test-user-token-{unique_id}",
            enabled=True,
        )
        db_session.add(slack_bot)
        db_session.flush()

        slack_channel_config = SlackChannelConfig(
            slack_bot_id=slack_bot.id,
            persona_id=persona.id,
            channel_config={"channel_name": "general", "disabled": False},
            enable_auto_filters=True,
            is_default=True,
        )
        db_session.add(slack_channel_config)
        db_session.commit()

        return user, persona, slack_bot, slack_channel_config

    @patch("onyx.utils.gpu_utils.fast_gpu_status_request", return_value=False)
    @patch(
        "onyx.document_index.vespa.index.VespaIndex.hybrid_retrieval", return_value=[]
    )
    @patch("onyx.chat.process_message.stream_chat_message_objects")
    def test_thread_messages_converted_to_previous_messages(
        self,
        mock_stream_chat: Mock,
        mock_vespa: Mock,
        mock_gpu_status: Mock,
        db_session: Session,
    ) -> None:
        """Test that Slack thread messages are properly converted to PreviousMessage format"""
        _setup_llm_provider(db_session)
        user, persona, slack_bot, slack_channel_config = self._setup_test_environment(
            db_session
        )

        # Create thread with multiple messages
        thread_messages = [
            ThreadMessage(
                message="What is the project deadline?",
                sender="user1",
                role=MessageType.USER,
            ),
            ThreadMessage(
                message="The project deadline is March 15th, 2025.",
                sender=None,
                role=MessageType.ASSISTANT,
            ),
            ThreadMessage(
                message="What about the budget?",
                sender="user1",
                role=MessageType.USER,
            ),
        ]

        message_info = SlackMessageInfo(
            thread_messages=thread_messages,
            msg_to_respond="1234567890.123456",
            channel_to_respond="C1234567890",
            sender_id="U9876543210",
            bypass_filters=False,
            is_bot_dm=False,
            is_bot_member_channel=True,
            is_bot_msg=False,
            is_slash_command=False,
            email="test@example.com",
            slack_context=None,
        )

        # Mock stream_chat_message_objects to capture the call arguments
        mock_stream_chat.return_value = iter([])  # Empty iterator

        mock_client = _create_mock_slack_client()

        # Call the handler
        with patch("onyx.onyxbot.slack.handlers.handle_regular_answer.gather_stream"):
            handle_regular_answer(
                message_info=message_info,
                slack_channel_config=slack_channel_config,
                receiver_ids=None,
                client=mock_client,
                channel="C1234567890",
                logger=MagicMock(),
                feedback_reminder_id=None,
            )

        # Verify stream_chat_message_objects was called
        assert mock_stream_chat.called, "stream_chat_message_objects should be called"

        # Get the call arguments
        call_kwargs = mock_stream_chat.call_args[1]

        # Verify thread_message_history parameter exists
        assert (
            "thread_message_history" in call_kwargs
        ), "thread_message_history should be passed"

        thread_message_history = call_kwargs["thread_message_history"]

        # Should have converted history messages (not including the current message)
        assert (
            thread_message_history is not None
        ), "thread_message_history should not be None"
        assert len(thread_message_history) == 2, "Should have 2 history messages"

        # Verify the messages are PreviousMessage objects
        for msg in thread_message_history:
            assert isinstance(
                msg, PreviousMessage
            ), "Messages should be PreviousMessage instances"

        # Verify message content and roles
        assert thread_message_history[0].message == "What is the project deadline?"
        assert thread_message_history[0].message_type == MessageType.USER
        assert (
            thread_message_history[1].message
            == "The project deadline is March 15th, 2025."
        )
        assert thread_message_history[1].message_type == MessageType.ASSISTANT

    @patch("onyx.utils.gpu_utils.fast_gpu_status_request", return_value=False)
    @patch(
        "onyx.document_index.vespa.index.VespaIndex.hybrid_retrieval", return_value=[]
    )
    @patch("onyx.chat.process_message.stream_chat_message_objects")
    def test_thread_messages_respect_token_limit(
        self,
        mock_stream_chat: Mock,
        mock_vespa: Mock,
        mock_gpu_status: Mock,
        db_session: Session,
    ) -> None:
        """Test that thread message history respects GEN_AI_HISTORY_CUTOFF token limit"""
        _setup_llm_provider(db_session)
        user, persona, slack_bot, slack_channel_config = self._setup_test_environment(
            db_session
        )

        # Create thread with many long messages to exceed token limit
        # Each message is approximately 50 tokens (rough estimate)
        long_message = "This is a very long message " * 20  # ~100 tokens per message
        thread_messages = []

        # Add enough messages to likely exceed GEN_AI_HISTORY_CUTOFF
        for i in range(20):
            thread_messages.append(
                ThreadMessage(
                    message=f"{long_message} Message {i}",
                    sender=f"user{i % 2}",
                    role=MessageType.USER if i % 2 == 0 else MessageType.ASSISTANT,
                )
            )

        # Add the current message
        thread_messages.append(
            ThreadMessage(
                message="What is the summary?",
                sender="user1",
                role=MessageType.USER,
            )
        )

        message_info = SlackMessageInfo(
            thread_messages=thread_messages,
            msg_to_respond="1234567890.123456",
            channel_to_respond="C1234567890",
            sender_id="U9876543210",
            bypass_filters=False,
            is_bot_dm=False,
            is_bot_member_channel=True,
            is_bot_msg=False,
            is_slash_command=False,
            email="test@example.com",
            slack_context=None,
        )

        mock_stream_chat.return_value = iter([])
        mock_client = _create_mock_slack_client()

        with patch("onyx.onyxbot.slack.handlers.handle_regular_answer.gather_stream"):
            handle_regular_answer(
                message_info=message_info,
                slack_channel_config=slack_channel_config,
                receiver_ids=None,
                client=mock_client,
                channel="C1234567890",
                logger=MagicMock(),
                feedback_reminder_id=None,
            )

        call_kwargs = mock_stream_chat.call_args[1]
        thread_message_history = call_kwargs["thread_message_history"]

        # Verify that token limit was enforced
        assert thread_message_history is not None
        # Should have fewer messages than the full history
        assert len(thread_message_history) < 20, (
            "Should have truncated messages to fit within token limit"
        )

        # Verify total token count doesn't exceed limit
        total_tokens = sum(msg.token_count for msg in thread_message_history)
        assert total_tokens <= GEN_AI_HISTORY_CUTOFF, (
            f"Total tokens {total_tokens} should not exceed {GEN_AI_HISTORY_CUTOFF}"
        )

        # Verify messages are in chronological order (oldest to newest)
        # The most recent messages should be included
        if len(thread_message_history) > 0:
            # Should be working backwards from most recent, so messages should be recent
            assert "Message" in thread_message_history[-1].message

    @patch("onyx.utils.gpu_utils.fast_gpu_status_request", return_value=False)
    @patch(
        "onyx.document_index.vespa.index.VespaIndex.hybrid_retrieval", return_value=[]
    )
    @patch("onyx.chat.process_message.stream_chat_message_objects")
    def test_empty_thread_history(
        self,
        mock_stream_chat: Mock,
        mock_vespa: Mock,
        mock_gpu_status: Mock,
        db_session: Session,
    ) -> None:
        """Test that empty thread history (single message) works correctly"""
        _setup_llm_provider(db_session)
        user, persona, slack_bot, slack_channel_config = self._setup_test_environment(
            db_session
        )

        # Single message with no history
        thread_messages = [
            ThreadMessage(
                message="What is the weather today?",
                sender="user1",
                role=MessageType.USER,
            ),
        ]

        message_info = SlackMessageInfo(
            thread_messages=thread_messages,
            msg_to_respond="1234567890.123456",
            channel_to_respond="C1234567890",
            sender_id="U9876543210",
            bypass_filters=False,
            is_bot_dm=False,
            is_bot_member_channel=True,
            is_bot_msg=False,
            is_slash_command=False,
            email="test@example.com",
            slack_context=None,
        )

        mock_stream_chat.return_value = iter([])
        mock_client = _create_mock_slack_client()

        with patch("onyx.onyxbot.slack.handlers.handle_regular_answer.gather_stream"):
            handle_regular_answer(
                message_info=message_info,
                slack_channel_config=slack_channel_config,
                receiver_ids=None,
                client=mock_client,
                channel="C1234567890",
                logger=MagicMock(),
                feedback_reminder_id=None,
            )

        call_kwargs = mock_stream_chat.call_args[1]
        thread_message_history = call_kwargs["thread_message_history"]

        # With only one message (the current one), history should be None
        assert (
            thread_message_history is None
        ), "thread_message_history should be None for single message"

    @patch("onyx.utils.gpu_utils.fast_gpu_status_request", return_value=False)
    @patch(
        "onyx.document_index.vespa.index.VespaIndex.hybrid_retrieval", return_value=[]
    )
    @patch("onyx.chat.process_message.stream_chat_message_objects")
    def test_single_message_history_still_passed(
        self,
        mock_stream_chat: Mock,
        mock_vespa: Mock,
        mock_gpu_status: Mock,
        db_session: Session,
    ) -> None:
        """Test that single_message_history is still passed alongside thread_message_history"""
        _setup_llm_provider(db_session)
        user, persona, slack_bot, slack_channel_config = self._setup_test_environment(
            db_session
        )

        thread_messages = [
            ThreadMessage(
                message="First question",
                sender="user1",
                role=MessageType.USER,
            ),
            ThreadMessage(
                message="First answer",
                sender=None,
                role=MessageType.ASSISTANT,
            ),
            ThreadMessage(
                message="Follow up question",
                sender="user1",
                role=MessageType.USER,
            ),
        ]

        message_info = SlackMessageInfo(
            thread_messages=thread_messages,
            msg_to_respond="1234567890.123456",
            channel_to_respond="C1234567890",
            sender_id="U9876543210",
            bypass_filters=False,
            is_bot_dm=False,
            is_bot_member_channel=True,
            is_bot_msg=False,
            is_slash_command=False,
            email="test@example.com",
            slack_context=None,
        )

        mock_stream_chat.return_value = iter([])
        mock_client = _create_mock_slack_client()

        with patch("onyx.onyxbot.slack.handlers.handle_regular_answer.gather_stream"):
            handle_regular_answer(
                message_info=message_info,
                slack_channel_config=slack_channel_config,
                receiver_ids=None,
                client=mock_client,
                channel="C1234567890",
                logger=MagicMock(),
                feedback_reminder_id=None,
            )

        call_kwargs = mock_stream_chat.call_args[1]

        # Both should be passed
        assert (
            "single_message_history" in call_kwargs
        ), "single_message_history should be passed"
        assert (
            "thread_message_history" in call_kwargs
        ), "thread_message_history should be passed"

        single_message_history = call_kwargs["single_message_history"]
        thread_message_history = call_kwargs["thread_message_history"]

        # single_message_history should be a formatted string
        assert isinstance(
            single_message_history, str
        ), "single_message_history should be a string"
        assert len(single_message_history) > 0, "single_message_history should not be empty"
        assert (
            "First question" in single_message_history
        ), "single_message_history should contain thread content"

        # thread_message_history should be a list of PreviousMessage
        assert isinstance(
            thread_message_history, list
        ), "thread_message_history should be a list"
        assert len(thread_message_history) == 2, "Should have 2 history messages"

