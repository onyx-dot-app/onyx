"""Unit tests for assign_citation_numbers handler."""

import json

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.chat.turn.context_handler import assign_citation_numbers
from onyx.chat.turn.models import ChatTurnContext


def test_citation_handler_assigns_sequential_numbers() -> None:
    """Test that citation handler assigns sequential numbers to documents."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}

    # Create tool response with LlmDoc objects
    llm_doc1 = {
        "document_id": "doc1",
        "content": "Content 1",
        "semantic_identifier": "Doc 1",
        "source_type": "web",
        "blurb": "Blurb 1",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": None,
    }
    llm_doc2 = {
        "document_id": "doc2",
        "content": "Content 2",
        "semantic_identifier": "Doc 2",
        "source_type": "web",
        "blurb": "Blurb 2",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": None,
    }

    agent_turn_messages = [
        {
            "role": "tool",
            "content": json.dumps({"search_results": [llm_doc1, llm_doc2]}),
            "tool_call_id": "call_1",
        }
    ]

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
    )

    # Execute
    result = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # Verify
    assert len(result) == 1
    assert result[0]["role"] == "tool"

    # Parse the updated content
    updated_content = json.loads(result[0]["content"])
    search_results = updated_content["search_results"]

    assert search_results[0]["document_citation_number"] == 1
    assert search_results[1]["document_citation_number"] == 2
    assert ctx.documents_cited_count == 2


def test_citation_handler_skips_already_numbered_documents() -> None:
    """Test that citation handler skips documents that already have citation numbers."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}

    llm_doc1 = {
        "document_id": "doc1",
        "content": "Content 1",
        "semantic_identifier": "Doc 1",
        "source_type": "web",
        "blurb": "Blurb 1",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": 5,  # Already numbered
    }
    llm_doc2 = {
        "document_id": "doc2",
        "content": "Content 2",
        "semantic_identifier": "Doc 2",
        "source_type": "web",
        "blurb": "Blurb 2",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": None,  # Needs numbering
    }

    agent_turn_messages = [
        {
            "role": "tool",
            "content": json.dumps([llm_doc1, llm_doc2]),
            "tool_call_id": "call_1",
        }
    ]

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=10,  # Start at 10
    )

    # Execute
    result = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # Verify
    updated_content = json.loads(result[0]["content"])

    assert updated_content[0]["document_citation_number"] == 5  # Unchanged
    assert updated_content[1]["document_citation_number"] == 11  # New number
    assert ctx.documents_cited_count == 11


def test_citation_handler_with_parallel_tool_calls() -> None:
    """Test citation handler with multiple tool responses (parallel calls)."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}

    llm_doc1 = {
        "document_id": "doc1",
        "content": "Content 1",
        "semantic_identifier": "Doc 1",
        "source_type": "web",
        "blurb": "Blurb 1",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": None,
    }
    llm_doc2 = {
        "document_id": "doc2",
        "content": "Content 2",
        "semantic_identifier": "Doc 2",
        "source_type": "web",
        "blurb": "Blurb 2",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": None,
    }

    agent_turn_messages = [
        {
            "role": "tool",
            "content": json.dumps([llm_doc1]),
            "tool_call_id": "call_1",
        },
        {
            "role": "tool",
            "content": json.dumps([llm_doc2]),
            "tool_call_id": "call_2",
        },
    ]

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
    )

    # Execute
    result = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # Verify
    assert len(result) == 2

    doc1_updated = json.loads(result[0]["content"])[0]
    doc2_updated = json.loads(result[1]["content"])[0]

    assert doc1_updated["document_citation_number"] == 1
    assert doc2_updated["document_citation_number"] == 2
    assert ctx.documents_cited_count == 2


def test_citation_handler_with_empty_agent_messages() -> None:
    """Test citation handler with empty agent_turn_messages."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}
    agent_turn_messages: list[dict] = []

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
    )

    # Execute
    result = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # Verify
    assert len(result) == 0
    assert ctx.documents_cited_count == 0


def test_citation_handler_with_non_tool_messages() -> None:
    """Test that citation handler ignores non-tool messages."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}

    agent_turn_messages = [
        {"role": "assistant", "content": "Regular assistant message"},
        {"role": "user", "content": "User message"},
    ]

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
    )

    # Execute
    result = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # Verify
    assert len(result) == 2
    assert result[0]["content"] == "Regular assistant message"
    assert result[1]["content"] == "User message"
    assert ctx.documents_cited_count == 0


def test_citation_handler_with_non_json_tool_content() -> None:
    """Test that citation handler handles non-JSON tool content gracefully."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}

    agent_turn_messages = [
        {
            "role": "tool",
            "content": "Plain text response, not JSON",
            "tool_call_id": "call_1",
        }
    ]

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
    )

    # Execute
    result = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # Verify - should return unchanged
    assert len(result) == 1
    assert result[0]["content"] == "Plain text response, not JSON"
    assert ctx.documents_cited_count == 0


def test_citation_handler_counter_increments_correctly() -> None:
    """Test that the citation counter increments correctly across multiple calls."""
    # Setup

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}

    ctx = ChatTurnContext(
        chat_session_id="test-session",
        message_id=1,
        research_type=ResearchType.FAST,
        run_dependencies={},
        aggregated_context=AggregatedDRContext(
            context="test",
            cited_documents=[],
            is_internet_marker_dict={},
            global_iteration_responses=[],
        ),
        documents_cited_count=0,
    )

    # First call with 2 documents
    llm_doc1 = {
        "document_id": "doc1",
        "content": "Content 1",
        "semantic_identifier": "Doc 1",
        "source_type": "web",
        "blurb": "Blurb 1",
        "metadata": {},
        "updated_at": None,
        "link": None,
        "source_links": None,
        "match_highlights": None,
        "document_citation_number": None,
    }

    agent_turn_messages1 = [
        {
            "role": "tool",
            "content": json.dumps([llm_doc1, llm_doc1.copy()]),
            "tool_call_id": "call_1",
        }
    ]

    assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages1, ctx
    )
    assert ctx.documents_cited_count == 2

    # Second call with 1 more document
    agent_turn_messages2 = [
        {
            "role": "tool",
            "content": json.dumps([llm_doc1.copy()]),
            "tool_call_id": "call_2",
        }
    ]

    result2 = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages2, ctx
    )

    # Verify counter continued from where it left off
    doc_from_second_call = json.loads(result2[0]["content"])[0]
    assert doc_from_second_call["document_citation_number"] == 3
    assert ctx.documents_cited_count == 3
