"""Unit tests for combined context handlers."""

import json

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler import assign_citation_numbers
from onyx.chat.turn.context_handler import update_task_prompt
from onyx.chat.turn.models import ChatTurnContext


def test_both_handlers_work_together() -> None:
    """Test that both handlers can be applied in sequence."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = [
        {"role": "user", "content": "Previous user message"},
        {"role": "assistant", "content": "Previous assistant message"},
    ]
    current_user_message = {"role": "user", "content": "Current query"}

    # Create agent messages with tool response and task prompt
    llm_doc = {
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

    agent_turn_messages = [
        {"role": "tool", "content": json.dumps([llm_doc]), "tool_call_id": "call_1"},
        {"role": "assistant", "content": "Tool response processed"},
        {"role": "user", "content": "Old task prompt"},
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

    # Execute handlers in order
    # 1. Citation handler
    after_citation = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )

    # 2. Task prompt handler
    final_result = update_task_prompt(
        chat_history, current_user_message, after_citation, ctx, prompt_config, False
    )

    # Verify
    # Should have tool message, assistant message, and new task prompt
    assert len(final_result) == 3
    assert final_result[0]["role"] == "tool"
    assert final_result[1]["role"] == "assistant"
    assert final_result[2]["role"] == "user"

    # Verify citation was assigned
    tool_content = json.loads(final_result[0]["content"])
    assert tool_content[0]["document_citation_number"] == 1
    assert ctx.documents_cited_count == 1

    # Verify task prompt was replaced
    assert final_result[2]["content"] != "Old task prompt"


def test_citations_assigned_before_task_prompt_update() -> None:
    """Test that citations are assigned before task prompt is updated."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

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
            "content": json.dumps([llm_doc1, llm_doc2]),
            "tool_call_id": "call_1",
        },
        {"role": "user", "content": "Old task prompt"},
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

    # Execute in order
    after_citation = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )
    final_result = update_task_prompt(
        chat_history, current_user_message, after_citation, ctx, prompt_config, True
    )

    # Verify citations are present
    tool_content = json.loads(final_result[0]["content"])
    assert tool_content[0]["document_citation_number"] == 1
    assert tool_content[1]["document_citation_number"] == 2


def test_chat_history_remains_unchanged_through_both_handlers() -> None:
    """Test that chat_history is never modified by either handler."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = [
        {"role": "user", "content": "History message 1"},
        {"role": "assistant", "content": "History message 2"},
    ]
    original_history = [msg.copy() for msg in chat_history]

    current_user_message = {"role": "user", "content": "Current query"}

    llm_doc = {
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

    agent_turn_messages = [
        {"role": "tool", "content": json.dumps([llm_doc]), "tool_call_id": "call_1"},
        {"role": "user", "content": "Old task prompt"},
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

    # Execute both handlers
    after_citation = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )
    update_task_prompt(
        chat_history, current_user_message, after_citation, ctx, prompt_config, False
    )

    # Verify chat_history unchanged
    assert chat_history == original_history


def test_multiple_iterations_with_both_handlers() -> None:
    """Test simulating multiple agent loop iterations with both handlers."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

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

    # Iteration 1
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

    agent_turn_messages = [
        {"role": "tool", "content": json.dumps([llm_doc1]), "tool_call_id": "call_1"},
        {"role": "user", "content": "Task prompt 1"},
    ]

    agent_turn_messages = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )
    agent_turn_messages = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    assert ctx.documents_cited_count == 1

    # Iteration 2 - simulate more tool calls
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

    # In a real scenario, agent_turn_messages would accumulate
    agent_turn_messages = agent_turn_messages + [
        {"role": "assistant", "content": "Processing..."},
        {"role": "tool", "content": json.dumps([llm_doc2]), "tool_call_id": "call_2"},
        {"role": "user", "content": "Task prompt 2"},
    ]

    agent_turn_messages = assign_citation_numbers(
        chat_history, current_user_message, agent_turn_messages, ctx
    )
    agent_turn_messages = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    # Verify citation counter continued from previous iteration
    assert ctx.documents_cited_count == 2

    # Verify all docs are numbered
    # Find tool messages and verify their citation numbers
    tool_messages = [msg for msg in agent_turn_messages if msg.get("role") == "tool"]
    assert len(tool_messages) == 2

    tool1_content = json.loads(tool_messages[0]["content"])
    tool2_content = json.loads(tool_messages[1]["content"])

    assert tool1_content[0]["document_citation_number"] == 1
    assert tool2_content[0]["document_citation_number"] == 2
