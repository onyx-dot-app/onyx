from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.configs.constants import FederatedConnectorSource
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.models import DocumentSet
from onyx.db.models import FederatedConnector
from onyx.db.models import Persona
from onyx.db.models import Persona__DocumentSet
from onyx.db.models import Persona__Prompt
from onyx.db.models import Persona__Tool
from onyx.db.models import Prompt
from onyx.db.models import SlackBot
from onyx.db.models import SlackChannelConfig
from onyx.onyxbot.slack.listener import process_message
from onyx.tools.built_in_tools import get_search_tool
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_persona_with_slack_config(db_session: Session) -> Persona:
    """Helper to create a test persona configured for Slack federated search"""
    unique_id = str(uuid4())[:8]
    document_set = DocumentSet(
        name=f"test_slack_docs_{unique_id}",
        description="Test document set for Slack federated search",
    )
    db_session.add(document_set)
    db_session.flush()

    persona = Persona(
        name=f"test_slack_persona_{unique_id}",
        description="Test persona for Slack federated search",
        chunks_above=0,
        chunks_below=0,
        llm_relevance_filter=True,
        llm_filter_extraction=True,
        recency_bias=RecencyBiasSetting.AUTO,
    )
    db_session.add(persona)
    db_session.flush()

    persona_doc_set = Persona__DocumentSet(
        persona_id=persona.id,
        document_set_id=document_set.id,
    )
    db_session.add(persona_doc_set)
    db_session.commit()

    prompt = Prompt(
        name="default_prompt",
        description="Default prompt for testing",
        system_prompt="You are a helpful assistant.",
        task_prompt="Answer the user's question based on the provided context.",
    )
    db_session.add(prompt)
    db_session.flush()

    persona_prompt = Persona__Prompt(persona_id=persona.id, prompt_id=prompt.id)
    db_session.add(persona_prompt)

    search_tool = get_search_tool(db_session)
    if search_tool:
        persona_tool = Persona__Tool(persona_id=persona.id, tool_id=search_tool.id)
        db_session.add(persona_tool)

    db_session.commit()

    persona_with_prompts = db_session.scalar(
        select(Persona)
        .options(joinedload(Persona.prompts))
        .where(Persona.id == persona.id)
    )

    return persona_with_prompts


def _create_mock_slack_request(text: str, channel_id: str = "C1234567890") -> Mock:
    """Create a mock Slack request"""
    mock_req = Mock()
    mock_req.type = "events_api"
    mock_req.envelope_id = "test_envelope_id"
    mock_req.payload = {
        "event": {
            "type": "app_mention",
            "text": f"<@U1234567890> {text}",
            "channel": channel_id,
            "user": "U9876543210",
            "ts": "1234567890.123456",
        }
    }
    mock_req.slack_bot_id = 12345
    return mock_req


def _create_mock_slack_client(channel_id: str = "C1234567890") -> Mock:
    """Create a mock Slack client"""
    mock_client = Mock()
    mock_client.slack_bot_id = 12345
    mock_client.web_client = Mock()

    # Mock chat_postMessage to return proper response structure
    mock_post_message_response = {"ok": True, "message_ts": "1234567890.123456"}
    mock_client.web_client.chat_postMessage = Mock(
        return_value=mock_post_message_response
    )

    # Mock users_info to return proper response structure
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

    # Mock auth_test to return proper response structure
    mock_auth_test_response = {
        "ok": True,
        "user_id": "U1234567890",
        "bot_id": "B1234567890",
    }
    mock_client.web_client.auth_test = Mock(return_value=mock_auth_test_response)

    # Mock conversations_info to return proper response structure
    def mock_conversations_info_response(channel):
        channel_id = channel
        if channel_id == "C1234567890":  # general - public
            mock_response = Mock()
            mock_response.validate.return_value = None
            mock_response.data = {
                "channel": {
                    "id": "C1234567890",
                    "name": "general",
                    "is_channel": True,
                    "is_private": False,
                    "is_group": False,
                    "is_mpim": False,
                    "is_im": False,
                }
            }
            mock_response.__getitem__ = lambda self, key: mock_response.data[key]
            return mock_response
        elif channel_id == "C1111111111":  # support - public
            mock_response = Mock()
            mock_response.validate.return_value = None
            mock_response.data = {
                "channel": {
                    "id": "C1111111111",
                    "name": "support",
                    "is_channel": True,
                    "is_private": False,
                    "is_group": False,
                    "is_mpim": False,
                    "is_im": False,
                }
            }
            mock_response.__getitem__ = lambda self, key: mock_response.data[key]
            return mock_response
        elif channel_id == "C9999999999":  # dev-team - private
            mock_response = Mock()
            mock_response.validate.return_value = None
            mock_response.data = {
                "channel": {
                    "id": "C9999999999",
                    "name": "dev-team",
                    "is_channel": True,
                    "is_private": True,
                    "is_group": False,
                    "is_mpim": False,
                    "is_im": False,
                }
            }
            mock_response.__getitem__ = lambda self, key: mock_response.data[key]
            return mock_response
        elif channel_id == "D1234567890":  # DM
            mock_response = Mock()
            mock_response.validate.return_value = None
            mock_response.data = {
                "channel": {
                    "id": "D1234567890",
                    "name": "directmessage",
                    "is_channel": False,
                    "is_private": False,
                    "is_group": False,
                    "is_mpim": False,
                    "is_im": True,
                }
            }
            mock_response.__getitem__ = lambda self, key: mock_response.data[key]
            return mock_response
        else:
            mock_response = Mock()
            mock_response.validate.side_effect = Exception("channel_not_found")
            return mock_response

    mock_client.web_client.conversations_info = Mock(
        side_effect=mock_conversations_info_response
    )

    # Mock conversations_members
    mock_client.web_client.conversations_members = Mock(
        return_value={"ok": True, "members": ["U9876543210", "U1234567890"]}
    )

    # Mock conversations_replies
    mock_client.web_client.conversations_replies = Mock(
        return_value={"ok": True, "messages": []}
    )

    return mock_client


class TestSlackBotFederatedSearch:
    """Test Slack bot federated search functionality"""

    def _setup_test_environment(self, db_session: Session):
        """Setup test environment with user, persona, and federated connector"""
        user = create_test_user(db_session, "slack_bot_test")

        persona = _create_test_persona_with_slack_config(db_session)

        federated_connector = FederatedConnector(
            source=FederatedConnectorSource.FEDERATED_SLACK,
            credentials={"workspace_url": "https://test.slack.com"},
        )
        db_session.add(federated_connector)
        db_session.flush()

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

        return user, persona, federated_connector, slack_bot, slack_channel_config

    def _setup_slack_mocks(self, channel_name: str):
        """Setup only Slack API mocks - everything else runs live"""
        patches = [
            patch("slack_sdk.WebClient.search_messages"),
            patch("onyx.context.search.federated.slack_search.query_slack"),
            patch("onyx.onyxbot.slack.listener.get_channel_type_from_id"),
        ]

        started_patches = [p.start() for p in patches]

        self._setup_slack_api_mocks(started_patches[0], None)

        # Setup query_slack mock to test filtering logic
        self._setup_query_slack_mock(started_patches[1], channel_name)

        # Setup channel type mock
        self._setup_channel_type_mock(started_patches[2], channel_name)

        return patches, started_patches

    def _setup_slack_api_mocks(self, mock_search_messages, mock_conversations_info):
        """Setup Slack API mocks to return controlled data for testing filtering"""
        # Mock search_messages to return messages from different channel types
        mock_search_response = Mock()
        mock_search_response.validate.return_value = None
        mock_search_response.get.return_value = {
            "matches": [
                {
                    "text": "Performance issue in API",
                    "permalink": "https://test.slack.com/archives/C1234567890/p1234567890",
                    "ts": "1234567890.123456",
                    "channel": {"id": "C1234567890", "name": "general"},
                    "username": "user1",
                    "score": 0.9,
                },
                {
                    "text": "Performance issue in dashboard",
                    "permalink": "https://test.slack.com/archives/C1111111111/p1234567891",
                    "ts": "1234567891.123456",
                    "channel": {"id": "C1111111111", "name": "support"},
                    "username": "user2",
                    "score": 0.8,
                },
                {
                    "text": "Performance issue in private channel",
                    "permalink": "https://test.slack.com/archives/C9999999999/p1234567892",
                    "ts": "1234567892.123456",
                    "channel": {"id": "C9999999999", "name": "dev-team"},
                    "username": "user3",
                    "score": 0.7,
                },
                {
                    "text": "Performance issue in DM",
                    "permalink": "https://test.slack.com/archives/D1234567890/p1234567893",
                    "ts": "1234567893.123456",
                    "channel": {"id": "D1234567890", "name": "directmessage"},
                    "username": "user4",
                    "score": 0.6,
                },
            ]
        }
        mock_search_messages.return_value = mock_search_response

    def _setup_query_slack_mock(self, mock_query_slack, channel_name: str):
        """Setup query_slack mock to capture filtering parameters"""

        def mock_query_slack_capture_params(
            query_string: str,
            original_query,
            access_token: str,
            limit: int | None = None,
            allowed_private_channel: str | None = None,
            bot_token: str | None = None,
            include_dm: bool = False,
        ):
            # Store the filtering parameters for verification
            self._captured_filtering_params = {
                "allowed_private_channel": allowed_private_channel,
                "include_dm": include_dm,
                "channel_name": channel_name,
            }

            # Return empty list - we're just testing the parameters, not the filtering logic
            return []

        mock_query_slack.side_effect = mock_query_slack_capture_params

    def _setup_channel_type_mock(
        self, mock_get_channel_type_from_id, channel_name: str
    ):
        """Setup get_channel_type_from_id mock to return correct channel types"""

        def mock_channel_type_response(web_client, channel_id: str):
            if channel_id == "C1234567890":  # general - public
                return "public_channel"
            elif channel_id == "C1111111111":  # support - public
                return "public_channel"
            elif channel_id == "C9999999999":  # dev-team - private
                return "private_channel"
            elif channel_id == "D1234567890":  # DM
                return "im"
            else:
                return "public_channel"  # default

        mock_get_channel_type_from_id.side_effect = mock_channel_type_response

    def _teardown_common_mocks(self, patches):
        """Stop all patches"""
        for p in patches:
            p.stop()

    def test_slack_bot_public_channel_filtering(self, db_session: Session) -> None:
        """Test that slack bot in public channel sees only public channel messages"""
        # Setup test environment
        user, persona, slack_connector, slack_bot, slack_channel_config = (
            self._setup_test_environment(db_session)
        )

        channel_id = "C1234567890"  # #general (public)
        channel_name = "general"

        # Setup only Slack API mocks - everything else runs live
        patches, started_patches = self._setup_slack_mocks(channel_name)

        try:
            # Call process_message - this will run through the real flow with live services
            # Only Slack API calls are mocked, everything else (Postgres, Vespa, LLM) runs live

            # Create mock Slack request and client
            mock_req = _create_mock_slack_request(
                "search for performance issues", channel_id
            )
            mock_client = _create_mock_slack_client(channel_id)

            # Call process_message to trigger the search
            process_message(mock_req, mock_client)

            # The real slack_retrieval function will be called and handle the filtering
            # We just verify that the bot successfully processed the request

            # Verify the response was sent to the correct channel
            mock_client.web_client.chat_postMessage.assert_called()
            post_message_calls = mock_client.web_client.chat_postMessage.call_args_list
            last_call = post_message_calls[-1]
            assert (
                last_call[1]["channel"] == channel_id
            ), f"Response should be sent to {channel_id}"

            # Verify the response contains content
            response_text = last_call[1].get("text", "")
            assert len(response_text) > 0, "Bot should have sent a non-empty response"

            # Verify that the bot response contains only messages from expected channels
            # The real slack_retrieval function should filter messages based on channel context
            response_text = last_call[1].get("text", "")

            # Test that the bot successfully processed the request
            assert len(response_text) > 0, "Bot should have sent a response"

            # Test the actual filtering logic by verifying the parameters passed to query_slack
            assert hasattr(
                self, "_captured_filtering_params"
            ), "query_slack should have been called"
            params = self._captured_filtering_params

            # For public channels, should have no private channel access and no DM access
            assert (
                params["allowed_private_channel"] is None
            ), "Public channels should not have private channel access"
            assert (
                params["include_dm"] is False
            ), "Public channels should not include DMs"
            assert (
                params["channel_name"] == "general"
            ), "Should be testing general channel"

        finally:
            self._teardown_common_mocks(patches)

    def test_slack_bot_private_channel_filtering(self, db_session: Session) -> None:
        """Test that slack bot in private channel sees private + public channel messages"""
        self._setup_test_environment(db_session)

        channel_id = "C9999999999"  # #dev-team (private)
        channel_name = "dev-team"

        patches, started_patches = self._setup_slack_mocks(channel_name)

        try:
            mock_req = _create_mock_slack_request(
                "search for performance issues", channel_id
            )
            mock_client = _create_mock_slack_client(channel_id)

            process_message(mock_req, mock_client)

            mock_client.web_client.chat_postMessage.assert_called()
            post_message_calls = mock_client.web_client.chat_postMessage.call_args_list
            last_call = post_message_calls[-1]
            assert (
                last_call[1]["channel"] == channel_id
            ), f"Response should be sent to {channel_id}"

            # Verify the response contains content
            response_text = last_call[1].get("text", "")
            assert len(response_text) > 0, "Bot should have sent a non-empty response"

            response_text = last_call[1].get("text", "")

            assert hasattr(
                self, "_captured_filtering_params"
            ), "query_slack should have been called"
            params = self._captured_filtering_params

            assert (
                params["allowed_private_channel"] == "C9999999999"
            ), "Private channels should have access to their specific private channel"
            assert (
                params["include_dm"] is False
            ), "Private channels should not include DMs"
            assert (
                params["channel_name"] == "dev-team"
            ), "Should be testing dev-team channel"

        finally:
            self._teardown_common_mocks(patches)

    def test_slack_bot_dm_filtering(self, db_session: Session) -> None:
        """Test that slack bot in DM sees all messages (no filtering)"""
        self._setup_test_environment(db_session)

        channel_id = "D1234567890"  # DM
        channel_name = "directmessage"

        patches, started_patches = self._setup_slack_mocks(channel_name)

        try:
            mock_req = _create_mock_slack_request(
                "search for performance issues", channel_id
            )
            mock_client = _create_mock_slack_client(channel_id)

            process_message(mock_req, mock_client)

            mock_client.web_client.chat_postMessage.assert_called()
            post_message_calls = mock_client.web_client.chat_postMessage.call_args_list
            last_call = post_message_calls[-1]
            assert (
                last_call[1]["channel"] == channel_id
            ), f"Response should be sent to {channel_id}"

            response_text = last_call[1].get("text", "")
            assert len(response_text) > 0, "Bot should have sent a non-empty response"

            response_text = last_call[1].get("text", "")

            assert len(response_text) > 0, "Bot should have sent a response"

            assert hasattr(
                self, "_captured_filtering_params"
            ), "query_slack should have been called"
            params = self._captured_filtering_params

            assert (
                params["allowed_private_channel"] is None
            ), "DMs should not have private channel access"
            assert params["include_dm"] is True, "DMs should include DM messages"
            assert (
                params["channel_name"] == "directmessage"
            ), "Should be testing directmessage channel"

        finally:
            self._teardown_common_mocks(patches)
