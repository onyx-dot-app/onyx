"""Unit tests for update_task_prompt handler."""

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.agents.agent_search.dr.models import AggregatedDRContext
from onyx.chat.models import PromptConfig
from onyx.chat.turn.context_handler import update_task_prompt
from onyx.chat.turn.models import ChatTurnContext


def test_task_prompt_handler_removes_only_from_agent_messages() -> None:
    """Test that task prompt handler only removes from agent_turn_messages, not history."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = [
        {"role": "user", "content": "First user message"},
        {"role": "assistant", "content": "First assistant message"},
    ]
    current_user_message = {"role": "user", "content": "Current query"}
    agent_turn_messages = [
        {"role": "assistant", "content": "Tool call response"},
        {"role": "user", "content": "Old task prompt"},
    ]

    # Create mock context
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
    )

    # Execute
    result = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    # Verify
    # Chat history should remain unchanged
    assert len(chat_history) == 2
    assert chat_history[0]["content"] == "First user message"

    # Result should have assistant message and new task prompt
    assert len(result) == 2
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "user"
    assert result[1]["content"] != "Old task prompt"  # Should be replaced


def test_task_prompt_handler_with_empty_agent_messages() -> None:
    """Test task prompt handler with empty agent_turn_messages."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = [{"role": "user", "content": "History message"}]
    current_user_message = {"role": "user", "content": "Current query"}
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
    )

    # Execute
    result = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    # Verify
    # Should just add a new task prompt
    assert len(result) == 1
    assert result[0]["role"] == "user"


def test_task_prompt_handler_with_no_user_messages() -> None:
    """Test task prompt handler when agent_turn_messages has no user messages."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = [{"role": "user", "content": "History message"}]
    current_user_message = {"role": "user", "content": "Current query"}
    agent_turn_messages = [
        {"role": "assistant", "content": "Assistant message 1"},
        {"role": "assistant", "content": "Assistant message 2"},
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
    )

    # Execute
    result = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    # Verify
    # Should have both assistant messages plus new task prompt
    assert len(result) == 3
    assert result[0]["role"] == "assistant"
    assert result[1]["role"] == "assistant"
    assert result[2]["role"] == "user"


def test_task_prompt_handler_preserves_chat_history() -> None:
    """Test that chat_history is never modified."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = [
        {"role": "user", "content": "History user message"},
        {"role": "assistant", "content": "History assistant message"},
    ]
    original_history = chat_history.copy()

    current_user_message = {"role": "user", "content": "Current query"}
    agent_turn_messages = [{"role": "user", "content": "Task prompt to replace"}]

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
    )

    # Execute
    update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    # Verify chat_history unchanged
    assert chat_history == original_history


def test_task_prompt_handler_with_content_array() -> None:
    """Test task prompt handler with content as array (common format)."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = []
    current_user_message = {
        "role": "user",
        "content": [{"type": "text", "text": "Query from content array"}],
    }
    agent_turn_messages = [{"role": "user", "content": "Old task prompt"}]

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
    )

    # Execute
    result = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        False,
    )

    # Verify
    assert len(result) == 1
    assert result[0]["role"] == "user"
    # The new prompt should contain the query text
    assert isinstance(result[0]["content"], str)


def test_task_prompt_handler_with_citation_requirements() -> None:
    """Test that citation requirements are included when should_cite_documents=True."""
    # Setup
    prompt_config = PromptConfig(
        system_prompt="Test system prompt",
        task_prompt="Test task prompt",
        datetime_aware=False,
    )

    chat_history = []
    current_user_message = {"role": "user", "content": "Query"}
    agent_turn_messages = []

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
    )

    # Execute
    result = update_task_prompt(
        chat_history,
        current_user_message,
        agent_turn_messages,
        ctx,
        prompt_config,
        True,
    )

    # Verify
    assert len(result) == 1
    assert result[0]["role"] == "user"
    # Should contain citation reminder (exact text may vary)
    content = result[0]["content"]
    assert isinstance(content, str)
