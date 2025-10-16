from datetime import datetime
from typing import Any
from unittest.mock import patch

from sqlalchemy.orm import Session

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.configs.constants import MessageType
from onyx.db.chat import create_chat_session
from onyx.db.chat import create_new_chat_message
from onyx.db.chat import get_or_create_root_message
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import ResearchAgentIteration
from onyx.db.models import ResearchAgentIterationSubStep
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.feature_flags.feature_flags_keys import SIMPLE_AGENT_FRAMEWORK
from onyx.feature_flags.interface import FeatureFlagProvider
from onyx.server.query_and_chat.streaming_models import FetchToolStart
from onyx.server.query_and_chat.streaming_models import SearchToolStart
from onyx.server.query_and_chat.streaming_utils import translate_db_message_to_packets
from tests.external_dependency_unit.conftest import create_test_user


class MockFeatureFlagProvider(FeatureFlagProvider):
    """Mock feature flag provider that returns a configurable value"""

    def __init__(self, enabled: bool = True):
        self.enabled = enabled

    def feature_enabled(
        self, flag_key: str, user_id: Any, user_properties: dict[str, Any] | None = None
    ) -> bool:
        if flag_key == SIMPLE_AGENT_FRAMEWORK:
            return self.enabled
        return False


def test_simple_agent_with_search_and_fetch_packets(
    db_session: Session,
    tenant_context: None,
) -> None:
    """
    Test that when feature flag is on and research_type is FAST,
    the translate_db_message_to_packets function returns packets with
    SearchToolStart followed by FetchToolStart for web fetch operations.
    """
    # Create a test user
    test_user: User = create_test_user(db_session, email_prefix="test_simple_agent")

    # Create a chat session
    chat_session: ChatSession = create_chat_session(
        db_session=db_session,
        description="Test simple agent packets",
        user_id=test_user.id,
        persona_id=0,
    )

    # Get root message for the chat session
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    # Create a chat message with FAST research type
    chat_message: ChatMessage = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=root_message,
        message="Test query",
        token_count=10,
        message_type=MessageType.USER,
        db_session=db_session,
        commit=True,
    )

    # Create assistant message with research type
    assistant_message: ChatMessage = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=chat_message,
        message="Test response",
        token_count=20,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
        commit=False,
    )
    assistant_message.research_type = ResearchType.FAST
    db_session.add(assistant_message)
    db_session.flush()

    # Create search tool entry in database
    search_tool = Tool(
        name="SearchTool",
        description="Search internal documents",
        in_code_tool_id="run_search",
        display_name="Internal Search",
    )
    db_session.add(search_tool)
    db_session.flush()

    # Create web search tool entry in database
    web_search_tool = Tool(
        name="WebSearchTool",
        description="Search the web",
        in_code_tool_id="run_web_search",
        display_name="Web Search",
    )
    db_session.add(web_search_tool)
    db_session.flush()

    # Create test document data
    test_doc_data = {
        "document_id": "test_doc_1",
        "chunk_ind": 0,
        "semantic_identifier": "Test Doc 1",
        "link": "https://test.com/doc1",
        "blurb": "Test document blurb",
        "source_type": "web",
        "boost": 1,
        "hidden": False,
        "metadata": {},
        "score": 0.9,
        "match_highlights": [],
        "updated_at": datetime.now().isoformat(),
        "primary_owners": [],
        "secondary_owners": [],
        "is_internet": False,
    }

    # Create first research iteration with search tool
    research_iteration_1 = ResearchAgentIteration(
        primary_question_id=assistant_message.id,
        iteration_nr=1,
        purpose="Search internal documents",
        reasoning="Need to search internal docs",
    )
    db_session.add(research_iteration_1)
    db_session.flush()

    # Create first sub-step with search tool (regular search)
    sub_step_1 = ResearchAgentIterationSubStep(
        primary_question_id=assistant_message.id,
        iteration_nr=1,
        iteration_sub_step_nr=1,
        sub_step_instructions="Search internal documents",
        sub_step_tool_id=search_tool.id,
        cited_doc_results=[test_doc_data],
        is_web_fetch=False,
    )
    db_session.add(sub_step_1)

    # Create second research iteration with web search tool
    research_iteration_2 = ResearchAgentIteration(
        primary_question_id=assistant_message.id,
        iteration_nr=2,
        purpose="Fetch web content",
        reasoning="Need to fetch from web",
    )
    db_session.add(research_iteration_2)
    db_session.flush()

    # Create second sub-step with web search tool and is_web_fetch=True
    sub_step_2 = ResearchAgentIterationSubStep(
        primary_question_id=assistant_message.id,
        iteration_nr=2,
        iteration_sub_step_nr=1,
        sub_step_instructions="Fetch web content",
        sub_step_tool_id=web_search_tool.id,
        cited_doc_results=[test_doc_data],
        is_web_fetch=True,
    )
    db_session.add(sub_step_2)
    db_session.commit()

    # Refresh to load relationships
    db_session.refresh(assistant_message)

    # Mock the feature flag provider to return True
    with patch(
        "onyx.server.query_and_chat.streaming_utils.get_default_feature_flag_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = MockFeatureFlagProvider(enabled=True)

        # Call translate_db_message_to_packets
        result = translate_db_message_to_packets(
            chat_message=assistant_message,
            db_session=db_session,
            remove_doc_content=False,
            start_step_nr=1,
        )

    # Verify packets were created
    assert len(result.packet_list) > 0

    # Find SearchToolStart and FetchToolStart packets
    search_packets = [
        p for p in result.packet_list if isinstance(p.obj, SearchToolStart)
    ]
    fetch_packets = [p for p in result.packet_list if isinstance(p.obj, FetchToolStart)]

    # Verify we have both types of packets
    assert (
        len(search_packets) > 0
    ), "Should have at least one SearchToolStart packet for regular search."
    assert (
        len(fetch_packets) > 0
    ), "Should have at least one FetchToolStart packet for web fetch"

    # Verify SearchToolStart comes before FetchToolStart (based on step number)
    search_indices = [result.packet_list.index(p) for p in search_packets]
    fetch_indices = [result.packet_list.index(p) for p in fetch_packets]

    assert min(search_indices) < min(
        fetch_indices
    ), "SearchToolStart should come before FetchToolStart"


def test_deep_research_ignores_simple_agent(
    db_session: Session,
    tenant_context: None,
) -> None:
    """
    Test that even with feature flag on, DEEP research type
    uses the old translation logic (no FetchToolStart packets).
    """
    # Create a test user
    test_user: User = create_test_user(db_session, email_prefix="test_deep_research")

    # Create a chat session
    chat_session: ChatSession = create_chat_session(
        db_session=db_session,
        description="Test deep research",
        user_id=test_user.id,
        persona_id=0,
    )

    # Get root message for the chat session
    root_message = get_or_create_root_message(
        chat_session_id=chat_session.id, db_session=db_session
    )

    # Create a chat message
    chat_message: ChatMessage = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=root_message,
        message="Test query",
        token_count=10,
        message_type=MessageType.USER,
        db_session=db_session,
        commit=True,
    )

    # Create assistant message with DEEP research type
    assistant_message: ChatMessage = create_new_chat_message(
        chat_session_id=chat_session.id,
        parent_message=chat_message,
        message="Test response",
        token_count=20,
        message_type=MessageType.ASSISTANT,
        db_session=db_session,
        commit=False,
    )
    assistant_message.research_type = ResearchType.DEEP
    db_session.add(assistant_message)
    db_session.flush()

    # Create research iteration
    research_iteration = ResearchAgentIteration(
        primary_question_id=assistant_message.id,
        iteration_nr=1,
        purpose="Test purpose",
        reasoning="Test reasoning",
    )
    db_session.add(research_iteration)
    db_session.flush()

    # Create web search tool entry in database
    web_search_tool = Tool(
        name="WebSearchTool",
        description="Search the web",
        in_code_tool_id="run_web_search",
        display_name="Web Search",
    )
    db_session.add(web_search_tool)
    db_session.flush()

    # Create test document data
    test_doc_data = {
        "document_id": "test_doc_1",
        "chunk_ind": 0,
        "semantic_identifier": "Test Doc 1",
        "link": "https://test.com/doc1",
        "blurb": "Test document blurb",
        "source_type": "web",
        "boost": 1,
        "hidden": False,
        "metadata": {},
        "score": 0.9,
        "match_highlights": [],
        "updated_at": datetime.now().isoformat(),
        "primary_owners": [],
        "secondary_owners": [],
        "is_internet": True,
    }

    # Create sub-step with web search tool and is_web_fetch=True
    # Even though is_web_fetch is True, DEEP research should ignore it
    sub_step = ResearchAgentIterationSubStep(
        primary_question_id=assistant_message.id,
        iteration_nr=1,
        iteration_sub_step_nr=1,
        sub_step_instructions="Fetch web content",
        sub_step_tool_id=web_search_tool.id,
        cited_doc_results=[test_doc_data],
        is_web_fetch=True,
    )
    db_session.add(sub_step)
    db_session.commit()

    # Mock the feature flag provider to return True
    with patch(
        "onyx.server.query_and_chat.streaming_utils.get_default_feature_flag_provider"
    ) as mock_get_provider:
        mock_get_provider.return_value = MockFeatureFlagProvider(enabled=True)

        # Call translate_db_message_to_packets
        result = translate_db_message_to_packets(
            chat_message=assistant_message,
            db_session=db_session,
            remove_doc_content=False,
            start_step_nr=1,
        )

    # Verify packets were created
    assert len(result.packet_list) > 0

    # Find FetchToolStart packets
    fetch_packets = [p for p in result.packet_list if isinstance(p.obj, FetchToolStart)]

    # Verify we have NO FetchToolStart packets (should use old logic for DEEP)
    assert (
        len(fetch_packets) == 0
    ), "DEEP research should not produce FetchToolStart packets even with feature flag on"

    # Verify we have SearchToolStart packets instead
    search_packets = [
        p for p in result.packet_list if isinstance(p.obj, SearchToolStart)
    ]
    assert (
        len(search_packets) > 0
    ), "DEEP research should use SearchToolStart (old behavior)"
