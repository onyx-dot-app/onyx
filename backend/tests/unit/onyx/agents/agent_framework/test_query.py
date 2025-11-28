from collections.abc import Callable
from typing import Any

from onyx.agents.agent_framework.models import RunItemStreamEvent
from onyx.agents.agent_framework.models import ToolCallOutputStreamItem
from onyx.agents.agent_framework.models import ToolCallStreamItem
from onyx.agents.agent_framework.query import query
from onyx.llm.message_types import ChatCompletionMessage
from onyx.llm.model_response import ModelResponseStream
from tests.unit.onyx.agents.agent_framework.conftest import FakeErrorTool
from tests.unit.onyx.agents.agent_framework.conftest import FakeTool
from tests.unit.onyx.agents.agent_framework.conftest import stream_chunk
from tests.unit.onyx.agents.agent_framework.conftest import tool_call_chunk


def test_query_emits_reasoning_and_tool_call_events(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
    fake_internal_search_tool: FakeTool,
) -> None:
    """Test that query emits ReasoningStart, ReasoningDone, ToolCall, and ToolCallOutputStreamItem events."""
    call_id = "toolu_01Xyj1F1fSG9BqjNJZi1JAnx"
    stream_id = "chatcmpl-ef21b1bf-4617-49a5-ba58-91ae67b88a68"

    responses = [
        # Reasoning chunks
        stream_chunk(
            id=stream_id,
            created="1762544618",
            reasoning_content="The user is asking",
            content="",
        ),
        stream_chunk(
            id=stream_id, created="1762544618", reasoning_content=" to", content=""
        ),
        # Tool call chunks
        stream_chunk(
            id=stream_id,
            created="1762544618",
            content="",
            tool_calls=[
                tool_call_chunk(id=call_id, name="internal_search", arguments="")
            ],
        ),
        stream_chunk(
            id=stream_id,
            created="1762544618",
            content="",
            tool_calls=[tool_call_chunk(arguments="")],
        ),
        # Streamed arguments
        *[
            stream_chunk(
                id=stream_id,
                created="1762544618",
                content="",
                tool_calls=[tool_call_chunk(arguments=arg)],
            )
            for arg in [
                '{"queries": ',
                '["new agent',
                " f",
                'ramework","',
                "agent fr",
                'amework"]}',
            ]
        ],
        stream_chunk(id=stream_id, created="1762544618", finish_reason="tool_calls"),
    ]

    llm = fake_llm(responses)
    messages: list[ChatCompletionMessage] = [
        {"role": "user", "content": "tell me about the new agent framework"}
    ]
    context: dict[str, bool] = {}

    result = query(
        llm,
        messages,
        tools=[fake_internal_search_tool],
        context=context,
        tool_choice=None,
    )
    events = list(result.stream)

    model_responses = [e for e in events if isinstance(e, ModelResponseStream)]
    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    assert len(model_responses) == 11
    assert len([e for e in run_item_events if e.type == "reasoning_start"]) == 1
    assert len([e for e in run_item_events if e.type == "reasoning_done"]) == 1

    # Verify that reasoning_done comes before tool_call events
    event_indices = {
        e.type: i
        for i, e in enumerate(events)
        if isinstance(e, RunItemStreamEvent)
        and e.type in ["reasoning_start", "reasoning_done", "tool_call"]
    }
    assert event_indices["reasoning_start"] < event_indices["reasoning_done"]
    assert event_indices["reasoning_done"] < event_indices["tool_call"]

    tool_call_events = [e for e in run_item_events if e.type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].details is not None
    assert isinstance(tool_call_events[0].details, ToolCallStreamItem)
    assert tool_call_events[0].details.call_id == call_id
    assert tool_call_events[0].details.name == "internal_search"
    assert (
        tool_call_events[0].details.arguments
        == '{"queries": ["new agent framework","agent framework"]}'
    )

    assert len(fake_internal_search_tool.calls) == 1
    assert fake_internal_search_tool.calls[0]["queries"] == [
        "new agent framework",
        "agent framework",
    ]
    assert context["internal_search_called"] is True

    tool_output_events = [e for e in run_item_events if e.type == "tool_call_output"]
    assert len(tool_output_events) == 1
    assert tool_output_events[0].details is not None
    assert isinstance(tool_output_events[0].details, ToolCallOutputStreamItem)
    assert tool_output_events[0].details.call_id == call_id
    assert (
        tool_output_events[0].details.output
        == "Internal Search results for: new agent framework, agent framework"
    )

    # Verify new_messages contains expected assistant and tool messages
    assert len(result.new_messages_stateful) == 2
    assert result.new_messages_stateful[0]["role"] == "assistant"
    assert result.new_messages_stateful[0]["content"] is None
    assert len(result.new_messages_stateful[0]["tool_calls"]) == 1
    assert result.new_messages_stateful[0]["tool_calls"][0]["id"] == call_id
    assert (
        result.new_messages_stateful[0]["tool_calls"][0]["function"]["name"]
        == "internal_search"
    )
    assert result.new_messages_stateful[1]["role"] == "tool"
    assert result.new_messages_stateful[1]["tool_call_id"] == call_id
    assert (
        result.new_messages_stateful[1]["content"]
        == "Internal Search results for: new agent framework, agent framework"
    )


def test_query_emits_message_start_and_done_for_content(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
) -> None:
    """Test that query emits MessageStart and MessageDone events for regular message content."""
    stream_id = "chatcmpl-2b136068-c6fb-4af1-97d5-d2c9d84cd52b"

    responses = [
        stream_chunk(id=stream_id, created="1762544448", content="What"),
        stream_chunk(id=stream_id, created="1762544448", content=" would"),
        stream_chunk(id=stream_id, created="1762544448", finish_reason="stop"),
        # Extra empty message that can occur after finish_reason
        stream_chunk(id=stream_id, created="1762544448"),
    ]

    llm = fake_llm(responses)
    messages: list[ChatCompletionMessage] = [{"role": "user", "content": "hello"}]
    result = query(
        llm,
        messages,
        tools=[],
        context={},
        tool_choice=None,
    )
    events = list(result.stream)

    model_responses = [e for e in events if isinstance(e, ModelResponseStream)]
    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    assert len(model_responses) == 4
    assert len([e for e in run_item_events if e.type == "message_start"]) == 1
    assert len([e for e in run_item_events if e.type == "message_done"]) == 1

    # Verify new_messages contains the assistant's message
    assert len(result.new_messages_stateful) == 1
    assert result.new_messages_stateful[0]["role"] == "assistant"
    assert result.new_messages_stateful[0]["content"] == "What would"


def test_query_handles_parallel_tool_calls(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
    fake_internal_search_tool: FakeTool,
    fake_web_search_tool: FakeTool,
) -> None:
    """Test that query handles parallel tool calls correctly (Claude-style interleaved)."""
    stream_id = "chatcmpl-32110864-73fa-4ea3-8762-cf431f7959e7"
    call_id_1 = "toolu_017uoJFHavhpdC2boEuBj4X1"
    call_id_2 = "toolu_01Gd7XLQ4EpXHjr9cbTxqtQ4"

    responses = [
        # First tool call
        stream_chunk(
            id=stream_id,
            created="1762819828",
            content="",
            tool_calls=[
                tool_call_chunk(
                    id=call_id_1, name="internal_search", arguments="", index=0
                )
            ],
        ),
        stream_chunk(
            id=stream_id,
            created="1762819828",
            content="",
            tool_calls=[tool_call_chunk(arguments="", index=0)],
        ),
        *[
            stream_chunk(
                id=stream_id,
                created="1762819828",
                content="",
                tool_calls=[tool_call_chunk(arguments=arg, index=0)],
            )
            for arg in ['{"queries":', ' ["ne', "w a", "gen", "t fr", "am", 'ework"]}']
        ],
        # Second tool call
        stream_chunk(
            id=stream_id,
            created="1762819828",
            content="",
            tool_calls=[
                tool_call_chunk(id=call_id_2, name="web_search", arguments="", index=1)
            ],
        ),
        stream_chunk(
            id=stream_id,
            created="1762819828",
            content="",
            tool_calls=[tool_call_chunk(arguments="", index=1)],
        ),
        *[
            stream_chunk(
                id=stream_id,
                created="1762819828",
                content="",
                tool_calls=[tool_call_chunk(arguments=arg, index=1)],
            )
            for arg in ['{"querie', 's": ', '["chees', 'e"]}']
        ],
        stream_chunk(id=stream_id, created="1762819828", finish_reason="tool_calls"),
    ]

    llm = fake_llm(responses)
    context: dict[str, bool] = {}
    messages: list[ChatCompletionMessage] = [
        {"role": "user", "content": "search for stuff"}
    ]
    result = query(
        llm,
        messages,
        tools=[fake_internal_search_tool, fake_web_search_tool],
        context=context,
        tool_choice=None,
    )
    events = list(result.stream)

    model_responses = [e for e in events if isinstance(e, ModelResponseStream)]
    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    assert len(model_responses) == 16

    tool_call_events = [e for e in run_item_events if e.type == "tool_call"]
    assert len(tool_call_events) == 2
    assert tool_call_events[0].details is not None
    assert isinstance(tool_call_events[0].details, ToolCallStreamItem)
    assert tool_call_events[0].details.call_id == call_id_1
    assert tool_call_events[0].details.name == "internal_search"
    assert (
        tool_call_events[0].details.arguments == '{"queries": ["new agent framework"]}'
    )
    assert tool_call_events[1].details is not None
    assert isinstance(tool_call_events[1].details, ToolCallStreamItem)
    assert tool_call_events[1].details.call_id == call_id_2
    assert tool_call_events[1].details.name == "web_search"
    assert tool_call_events[1].details.arguments == '{"queries": ["cheese"]}'

    assert len(fake_internal_search_tool.calls) == 1
    assert fake_internal_search_tool.calls[0]["queries"] == ["new agent framework"]
    assert len(fake_web_search_tool.calls) == 1
    assert fake_web_search_tool.calls[0]["queries"] == ["cheese"]
    assert context["internal_search_called"] is True
    assert context["web_search_called"] is True

    tool_output_events = [e for e in run_item_events if e.type == "tool_call_output"]
    assert len(tool_output_events) == 2
    assert tool_output_events[0].details is not None
    assert isinstance(tool_output_events[0].details, ToolCallOutputStreamItem)
    assert tool_output_events[0].details.call_id == call_id_1
    assert (
        tool_output_events[0].details.output
        == "Internal Search results for: new agent framework"
    )
    assert tool_output_events[1].details is not None
    assert isinstance(tool_output_events[1].details, ToolCallOutputStreamItem)
    assert tool_output_events[1].details.call_id == call_id_2
    assert tool_output_events[1].details.output == "Web Search results for: cheese"


def test_query_handles_parallel_tool_calls_in_one_event(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
    fake_internal_search_tool: FakeTool,
    fake_web_search_tool: FakeTool,
) -> None:
    """Test that query handles Gemini-style parallel tool calls where both tools come in one chunk."""
    stream_id = "Yn4SaajROLXEnvgP5JTN-AQ"
    call_id_1 = "call_130bec4755e544ea95f4b1bafd81"
    call_id_2 = "call_42273e8ee5ac4c0a97237d6d25a6"

    # Gemini-style: both tool calls with complete arguments in a single event
    responses = [
        stream_chunk(
            id=stream_id,
            created="1762819684",
            tool_calls=[
                tool_call_chunk(
                    id=call_id_1,
                    name="internal_search",
                    arguments='{"queries": ["new agent framework"]}',
                    index=0,
                ),
                tool_call_chunk(
                    id=call_id_2,
                    name="web_search",
                    arguments='{"queries": ["cheese"]}',
                    index=1,
                ),
            ],
        ),
        stream_chunk(id=stream_id, created="1762819684", finish_reason="tool_calls"),
    ]

    llm = fake_llm(responses)
    context: dict[str, bool] = {}
    messages: list[ChatCompletionMessage] = [{"role": "user", "content": "search"}]
    result = query(
        llm,
        messages,
        tools=[fake_internal_search_tool, fake_web_search_tool],
        context=context,
        tool_choice=None,
    )
    events = list(result.stream)

    model_responses = [e for e in events if isinstance(e, ModelResponseStream)]
    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    assert len(model_responses) == 2

    tool_call_events = [e for e in run_item_events if e.type == "tool_call"]
    assert len(tool_call_events) == 2
    assert tool_call_events[0].details is not None
    assert isinstance(tool_call_events[0].details, ToolCallStreamItem)
    assert tool_call_events[0].details.call_id == call_id_1
    assert tool_call_events[0].details.name == "internal_search"
    assert (
        tool_call_events[0].details.arguments == '{"queries": ["new agent framework"]}'
    )
    assert tool_call_events[1].details is not None
    assert isinstance(tool_call_events[1].details, ToolCallStreamItem)
    assert tool_call_events[1].details.call_id == call_id_2
    assert tool_call_events[1].details.name == "web_search"
    assert tool_call_events[1].details.arguments == '{"queries": ["cheese"]}'

    assert len(fake_internal_search_tool.calls) == 1
    assert fake_internal_search_tool.calls[0]["queries"] == ["new agent framework"]
    assert len(fake_web_search_tool.calls) == 1
    assert fake_web_search_tool.calls[0]["queries"] == ["cheese"]
    assert context["internal_search_called"] is True
    assert context["web_search_called"] is True

    tool_output_events = [e for e in run_item_events if e.type == "tool_call_output"]
    assert len(tool_output_events) == 2
    assert tool_output_events[0].details is not None
    assert isinstance(tool_output_events[0].details, ToolCallOutputStreamItem)
    assert tool_output_events[0].details.call_id == call_id_1
    assert (
        tool_output_events[0].details.output
        == "Internal Search results for: new agent framework"
    )
    assert tool_output_events[1].details is not None
    assert isinstance(tool_output_events[1].details, ToolCallOutputStreamItem)
    assert tool_output_events[1].details.call_id == call_id_2
    assert tool_output_events[1].details.output == "Web Search results for: cheese"

    # Verify new_messages contains expected assistant and tool messages
    assert len(result.new_messages_stateful) == 3  # 1 assistant + 2 tool responses
    assert result.new_messages_stateful[0]["role"] == "assistant"
    assert result.new_messages_stateful[0]["content"] is None
    assert len(result.new_messages_stateful[0]["tool_calls"]) == 2
    assert result.new_messages_stateful[1]["role"] == "tool"
    assert result.new_messages_stateful[1]["tool_call_id"] == call_id_1
    assert result.new_messages_stateful[2]["role"] == "tool"
    assert result.new_messages_stateful[2]["tool_call_id"] == call_id_2


def test_query_emits_reasoning_done_before_message_start(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
) -> None:
    """Test that query emits reasoning_done before message_start when transitioning from reasoning to message."""
    stream_id = "chatcmpl-3a248070-d1fb-4ea1-87d5-e3c9d84cd52b"

    responses = [
        # Reasoning chunks
        stream_chunk(
            id=stream_id,
            created="1762544618",
            reasoning_content="Let me think about this.",
            content="",
        ),
        stream_chunk(
            id=stream_id,
            created="1762544618",
            reasoning_content=" I should respond.",
            content="",
        ),
        # Transition to message content
        stream_chunk(id=stream_id, created="1762544618", content="Based"),
        stream_chunk(id=stream_id, created="1762544618", content=" on"),
        stream_chunk(id=stream_id, created="1762544618", content=" my"),
        stream_chunk(id=stream_id, created="1762544618", content=" analysis"),
        stream_chunk(id=stream_id, created="1762544618", finish_reason="stop"),
    ]

    llm = fake_llm(responses)
    messages: list[ChatCompletionMessage] = [{"role": "user", "content": "hello"}]
    result = query(
        llm,
        messages,
        tools=[],
        context={},
        tool_choice=None,
    )
    events = list(result.stream)

    model_responses = [e for e in events if isinstance(e, ModelResponseStream)]
    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    assert len(model_responses) == 7

    # Check that we have the expected events
    assert len([e for e in run_item_events if e.type == "reasoning_start"]) == 1
    assert len([e for e in run_item_events if e.type == "reasoning_done"]) == 1
    assert len([e for e in run_item_events if e.type == "message_start"]) == 1
    assert len([e for e in run_item_events if e.type == "message_done"]) == 1

    # Find the indices of the events
    event_indices = {
        e.type: i for i, e in enumerate(events) if isinstance(e, RunItemStreamEvent)
    }

    # Verify the correct order: reasoning_start < reasoning_done < message_start < message_done
    assert event_indices["reasoning_start"] < event_indices["reasoning_done"]
    assert event_indices["reasoning_done"] < event_indices["message_start"]
    assert event_indices["message_start"] < event_indices["message_done"]

    # Verify new_messages contains the assistant's message
    assert len(result.new_messages_stateful) == 1
    assert result.new_messages_stateful[0]["role"] == "assistant"
    assert result.new_messages_stateful[0]["content"] == "Based on my analysis"


def test_query_treats_tool_like_message_as_tool_call(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
    fake_internal_search_tool: FakeTool,
) -> None:
    """Test that query treats JSON message content as a tool call when structured_response_format is empty."""
    stream_id = "chatcmpl-tool-like-message"

    responses = [
        stream_chunk(
            id=stream_id,
            created="1762545000",
            content='{"name": "internal_search", ',
        ),
        stream_chunk(
            id=stream_id,
            created="1762545000",
            content='"arguments": {"queries": ["new agent", "framework"]}',
        ),
        stream_chunk(id=stream_id, created="1762545000", content="}"),
        stream_chunk(id=stream_id, created="1762545000", finish_reason="stop"),
    ]

    llm = fake_llm(responses)
    context: dict[str, bool] = {}
    messages: list[ChatCompletionMessage] = [
        {"role": "user", "content": "tell me about agents"}
    ]

    result = query(
        llm,
        messages,
        tools=[fake_internal_search_tool],
        context=context,
        tool_choice=None,
        structured_response_format={},
    )

    events = list(result.stream)
    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    tool_call_events = [e for e in run_item_events if e.type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].details is not None
    assert isinstance(tool_call_events[0].details, ToolCallStreamItem)
    assert tool_call_events[0].details.name == "internal_search"
    assert (
        tool_call_events[0].details.arguments
        == '{"queries": ["new agent", "framework"]}'
    )

    assert len(fake_internal_search_tool.calls) == 1
    assert fake_internal_search_tool.calls[0]["queries"] == ["new agent", "framework"]
    assert context["internal_search_called"] is True

    tool_output_events = [e for e in run_item_events if e.type == "tool_call_output"]
    assert len(tool_output_events) == 1
    assert tool_output_events[0].details is not None
    assert isinstance(tool_output_events[0].details, ToolCallOutputStreamItem)
    assert (
        tool_output_events[0].details.output
        == "Internal Search results for: new agent, framework"
    )

    assert len(result.new_messages_stateful) == 2
    assert result.new_messages_stateful[0]["role"] == "assistant"
    assert result.new_messages_stateful[0]["content"] is None
    assert len(result.new_messages_stateful[0]["tool_calls"]) == 1
    assert (
        result.new_messages_stateful[0]["tool_calls"][0]["function"]["name"]
        == "internal_search"
    )
    assert result.new_messages_stateful[1]["role"] == "tool"
    assert (
        result.new_messages_stateful[1]["tool_call_id"]
        == tool_call_events[0].details.call_id
    )
    assert result.new_messages_stateful[1]["content"] == (
        "Internal Search results for: new agent, framework"
    )


def test_query_handles_tool_error_gracefully(
    fake_llm: Callable[[list[ModelResponseStream]], Any],
    fake_error_tool: FakeErrorTool,
) -> None:
    """Test that query handles tool errors gracefully and treats the error as the tool call response."""
    call_id = "toolu_01ErrorToolCall123"
    stream_id = "chatcmpl-error-test-12345"

    responses = [
        stream_chunk(
            id=stream_id,
            created="1762545000",
            content="",
            tool_calls=[tool_call_chunk(id=call_id, name="error_tool", arguments="")],
        ),
        stream_chunk(
            id=stream_id,
            created="1762545000",
            content="",
            tool_calls=[tool_call_chunk(arguments="")],
        ),
        *[
            stream_chunk(
                id=stream_id,
                created="1762545000",
                content="",
                tool_calls=[tool_call_chunk(arguments=arg)],
            )
            for arg in ['{"queries": ', '["test"]}']
        ],
        stream_chunk(id=stream_id, created="1762545000", finish_reason="tool_calls"),
    ]

    llm = fake_llm(responses)
    context: dict[str, bool] = {}
    messages: list[ChatCompletionMessage] = [
        {"role": "user", "content": "call the error tool"}
    ]

    result = query(
        llm,
        messages,
        tools=[fake_error_tool],
        context=context,
        tool_choice=None,
    )
    events = list(result.stream)

    run_item_events = [e for e in events if isinstance(e, RunItemStreamEvent)]

    # Verify tool_call event was emitted
    tool_call_events = [e for e in run_item_events if e.type == "tool_call"]
    assert len(tool_call_events) == 1
    assert tool_call_events[0].details is not None
    assert isinstance(tool_call_events[0].details, ToolCallStreamItem)
    assert tool_call_events[0].details.call_id == call_id
    assert tool_call_events[0].details.name == "error_tool"

    # Verify tool_call_output event was emitted with the error message
    tool_output_events = [e for e in run_item_events if e.type == "tool_call_output"]
    assert len(tool_output_events) == 1
    assert tool_output_events[0].details is not None
    assert isinstance(tool_output_events[0].details, ToolCallOutputStreamItem)
    assert tool_output_events[0].details.call_id == call_id
    assert tool_output_events[0].details.output == "Error: Error running tool"

    # Verify new_messages contains expected assistant and tool messages
    assert len(result.new_messages_stateful) == 2
    assert result.new_messages_stateful[0]["role"] == "assistant"
    assert result.new_messages_stateful[0]["content"] is None
    assert len(result.new_messages_stateful[0]["tool_calls"]) == 1
    assert result.new_messages_stateful[0]["tool_calls"][0]["id"] == call_id
    assert (
        result.new_messages_stateful[0]["tool_calls"][0]["function"]["name"]
        == "error_tool"
    )
    assert result.new_messages_stateful[1]["role"] == "tool"
    assert result.new_messages_stateful[1]["tool_call_id"] == call_id
    assert result.new_messages_stateful[1]["content"] == "Error: Error running tool"
