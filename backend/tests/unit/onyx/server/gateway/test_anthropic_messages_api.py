from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    ChatCompletionMessageToolCall,
    Choice,
    Delta,
    FunctionCall,
    Message,
    ModelResponse,
    ModelResponseStream,
    StreamingChoice,
    Usage,
)
from onyx.llm.models import (
    AssistantMessage,
    NamedToolChoice,
    ReasoningEffort,
    RedactedThinkingBlock,
    SystemMessage,
    ThinkingBlock,
    ToolChoice,
    ToolChoiceOptions,
    ToolMessage,
    UserMessage,
)
from onyx.llm.multi_llm import LLMRateLimitError, LLMTimeoutError
from onyx.server.gateway import api as gateway_api
from onyx.server.gateway import stream_bridge
from onyx.server.gateway.api import _MESSAGES_ADAPTER
from onyx.server.gateway.models import (
    AnthropicCountTokensRequest,
    AnthropicMessageResponse,
    AnthropicMessagesRequest,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.server.gateway.test_llm_gateway_api import (
    _ChunkStreamLLM,
    _InvokeLLM,
    _model,
    _provider,
    _RaisingInvokeLLM,
    _StreamingLLM,
)


def test_anthropic_messages_to_raw_messages_converts_full_turn() -> None:
    system = [
        {
            "type": "text",
            "text": "You are Claude Code.",
            "cache_control": {"type": "ephemeral"},
        }
    ]
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "sure"},
                {
                    "type": "tool_use",
                    "id": "call_1",
                    "name": "Bash",
                    "input": {"cmd": "ls"},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": [
                        {"type": "text", "text": "part1"},
                        {"type": "text", "text": "part2"},
                    ],
                }
            ],
        },
    ]

    raw = gateway_api._anthropic_messages_to_raw_messages(messages, system)

    assert raw[0] == {"role": "system", "content": "You are Claude Code."}
    tool_message = next(m for m in raw if m["role"] == "tool")
    assert isinstance(tool_message["content"], str)
    assistant_message = next(m for m in raw if m["role"] == "assistant")
    assert assistant_message["tool_calls"][0]["function"]["name"] == "Bash"
    parsed_args = json.loads(
        assistant_message["tool_calls"][0]["function"]["arguments"]
    )
    assert parsed_args == {"cmd": "ls"}

    validated = _MESSAGES_ADAPTER.validate_python(raw)
    assert [type(m) for m in validated] == [
        SystemMessage,
        UserMessage,
        AssistantMessage,
        ToolMessage,
    ]


def test_anthropic_system_string_becomes_system_message() -> None:
    raw = gateway_api._anthropic_messages_to_raw_messages(
        [{"role": "user", "content": "hi"}], "You are terse."
    )
    assert raw[0] == {"role": "system", "content": "You are terse."}


def test_anthropic_messages_reject_multimodal_tool_results() -> None:
    messages = [
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "call_1",
                    "content": [
                        {"type": "text", "text": "screenshot"},
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": "abc",
                            },
                        },
                    ],
                }
            ],
        }
    ]

    with pytest.raises(OnyxError) as exc_info:
        gateway_api._anthropic_messages_to_raw_messages(messages, None)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


@pytest.mark.parametrize("system", [None, "", "   ", []])
def test_anthropic_blank_system_produces_no_system_message(
    system: str | list[dict[str, Any]] | None,
) -> None:
    raw = gateway_api._anthropic_messages_to_raw_messages(
        [{"role": "user", "content": "hi"}], system
    )
    assert all(m["role"] != "system" for m in raw)


def test_anthropic_tools_converts_custom_tool() -> None:
    request = AnthropicMessagesRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        tools=[
            {
                "name": "Bash",
                "description": "run",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )

    tools = gateway_api._anthropic_tools(request.tools)

    assert tools == [
        {
            "type": "function",
            "function": {
                "name": "Bash",
                "parameters": {"type": "object", "properties": {}},
                "description": "run",
            },
        }
    ]


def test_anthropic_tools_rejects_hosted_tool_without_input_schema() -> None:
    request = AnthropicMessagesRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
    )

    with pytest.raises(OnyxError) as exc_info:
        gateway_api._anthropic_tools(request.tools)

    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_anthropic_tools_none_when_absent() -> None:
    request = AnthropicMessagesRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )
    assert gateway_api._anthropic_tools(request.tools) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, None),
        ({"type": "auto"}, ToolChoiceOptions.AUTO),
        ({"type": "any"}, ToolChoiceOptions.REQUIRED),
        ({"type": "none"}, ToolChoiceOptions.NONE),
    ],
)
def test_anthropic_tool_choice(
    raw: dict[str, Any] | None, expected: ToolChoiceOptions | None
) -> None:
    assert gateway_api._anthropic_tool_choice(raw) is expected


def test_anthropic_tool_choice_maps_named_tool() -> None:
    assert gateway_api._anthropic_tool_choice(
        {"type": "tool", "name": "Bash"}
    ) == NamedToolChoice(name="Bash")


@pytest.mark.parametrize(
    "raw",
    [{"type": "tool"}, {"type": "tool", "name": ""}, {"type": "bogus"}],
)
def test_anthropic_tool_choice_refuses_unsupported(raw: dict[str, Any]) -> None:
    with pytest.raises(OnyxError) as exc_info:
        gateway_api._anthropic_tool_choice(raw)
    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_anthropic_reasoning_effort_defaults_to_auto_when_absent() -> None:
    assert gateway_api._anthropic_reasoning_effort(None, None) is ReasoningEffort.AUTO


def test_anthropic_reasoning_effort_disabled_maps_to_off() -> None:
    assert (
        gateway_api._anthropic_reasoning_effort({"type": "disabled"}, None)
        is ReasoningEffort.OFF
    )


def test_anthropic_reasoning_effort_disabled_wins_over_output_config() -> None:
    assert (
        gateway_api._anthropic_reasoning_effort(
            {"type": "disabled"}, {"effort": "high"}
        )
        is ReasoningEffort.OFF
    )


def test_anthropic_reasoning_effort_enabled_maps_to_a_real_effort() -> None:
    effort = gateway_api._anthropic_reasoning_effort(
        {"type": "enabled", "budget_tokens": 8000}, None
    )
    assert effort in (ReasoningEffort.LOW, ReasoningEffort.MEDIUM, ReasoningEffort.HIGH)


@pytest.mark.parametrize(
    ("effort_raw", "expected"),
    [
        ("low", ReasoningEffort.LOW),
        ("medium", ReasoningEffort.MEDIUM),
        ("high", ReasoningEffort.HIGH),
        ("xhigh", ReasoningEffort.XHIGH),
    ],
)
def test_anthropic_reasoning_effort_adaptive_honors_output_config_effort(
    effort_raw: str, expected: ReasoningEffort
) -> None:
    effort = gateway_api._anthropic_reasoning_effort(
        {"type": "adaptive"}, {"effort": effort_raw}
    )
    assert effort is expected


def test_anthropic_reasoning_effort_adaptive_without_effort_stays_auto() -> None:
    assert (
        gateway_api._anthropic_reasoning_effort({"type": "adaptive"}, None)
        is ReasoningEffort.AUTO
    )


def test_anthropic_reasoning_effort_output_config_alone_is_honored() -> None:
    assert (
        gateway_api._anthropic_reasoning_effort(None, {"effort": "high"})
        is ReasoningEffort.HIGH
    )


@pytest.mark.parametrize(
    ("finish_reason", "has_tool_use", "expected"),
    [
        ("stop", False, "end_turn"),
        ("length", False, "max_tokens"),
        ("length", True, "max_tokens"),
        ("tool_calls", True, "tool_use"),
        ("stop", True, "tool_use"),
        ("content_filter", False, "refusal"),
        (None, False, "end_turn"),
    ],
)
def test_anthropic_stop_reason(
    finish_reason: str | None, has_tool_use: bool, expected: str
) -> None:
    assert gateway_api._anthropic_stop_reason(finish_reason, has_tool_use) == expected


def _tool_call(
    arguments: str, *, name: str | None = "Bash"
) -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id="call_1", function=FunctionCall(name=name, arguments=arguments)
    )


def test_anthropic_tool_use_blocks_parses_valid_json() -> None:
    blocks = gateway_api._anthropic_tool_use_blocks([_tool_call('{"cmd":"ls"}')])
    assert blocks[0].input == {"cmd": "ls"}


def test_anthropic_tool_use_blocks_empty_arguments_become_empty_dict() -> None:
    blocks = gateway_api._anthropic_tool_use_blocks([_tool_call("")])
    assert blocks[0].input == {}


@pytest.mark.parametrize("arguments", ["{not json", "[1]"])
def test_anthropic_tool_use_blocks_rejects_invalid_input(arguments: str) -> None:
    with pytest.raises(ValueError):
        gateway_api._anthropic_tool_use_blocks([_tool_call(arguments)])


def test_anthropic_tool_use_blocks_skips_nameless_call() -> None:
    blocks = gateway_api._anthropic_tool_use_blocks([_tool_call("{}", name=None)])
    assert blocks == []


def test_anthropic_messages_request_tolerates_unknown_top_level_fields() -> None:
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "1/test",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "anthropic_version": "2023-06-01",
            "extra_thing": 1,
        }
    )
    assert request.model == "1/test"


def _handle_anthropic_call(
    request: AnthropicMessagesRequest,
) -> StreamingResponse | AnthropicMessageResponse:
    provider = _provider(1, "openai", [_model("test")])
    return gateway_api.handle_anthropic_messages(
        request=request,
        provider=provider,
        model_config=provider.model_configurations[0],
        flow=LLMFlow.CRAFT_LLM_GENERATION,
    )


def _anthropic_request(**overrides: Any) -> AnthropicMessagesRequest:
    defaults: dict[str, Any] = {
        "model": "1/test",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    }
    defaults.update(overrides)
    return AnthropicMessagesRequest(**defaults)


class _RecordingInvokeLLM(_InvokeLLM):
    def __init__(self, response: ModelResponse) -> None:
        super().__init__(response)
        self.received_tool_choice: ToolChoice | None = None

    def invoke(self, *args: object, **kwargs: object) -> ModelResponse:
        self.received_tool_choice = cast("ToolChoice | None", kwargs.get("tool_choice"))
        return super().invoke(*args, **kwargs)


def test_handle_anthropic_messages_forwards_named_tool_choice() -> None:
    response = ModelResponse(
        id="msg-1",
        created="1784577999",
        choice=Choice(finish_reason="stop", message=Message(content="ok")),
    )
    fake_llm = _RecordingInvokeLLM(response)
    request = _anthropic_request(
        tools=[
            {
                "name": "get_weather",
                "description": "Get the current weather",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
        tool_choice={"type": "tool", "name": "get_weather"},
    )

    with patch.object(gateway_api, "llm_from_provider", return_value=fake_llm):
        _handle_anthropic_call(request)

    assert fake_llm.received_tool_choice == NamedToolChoice(name="get_weather")


def test_handle_anthropic_messages_happy_path_serializes_response() -> None:
    response = ModelResponse(
        id="msg-1",
        created="1784577999",
        choice=Choice(
            finish_reason="tool_calls",
            message=Message(
                content="Sure thing",
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        function=FunctionCall(name="Bash", arguments='{"cmd":"ls"}'),
                    )
                ],
            ),
        ),
        usage=Usage(
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            cache_creation_input_tokens=20,
            cache_read_input_tokens=30,
        ),
    )

    with patch.object(
        gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
    ):
        result = _handle_anthropic_call(_anthropic_request())

    assert isinstance(result, AnthropicMessageResponse)
    payload = result.to_wire()
    assert payload["type"] == "message"
    assert payload["role"] == "assistant"
    assert payload["content"] == [
        {"type": "text", "text": "Sure thing"},
        {"type": "tool_use", "id": "call_1", "name": "Bash", "input": {"cmd": "ls"}},
    ]
    assert payload["stop_reason"] == "tool_use"
    assert "stop_sequence" in payload
    assert payload["stop_sequence"] is None
    assert payload["usage"] == {
        "input_tokens": 50,
        "output_tokens": 10,
        "cache_creation_input_tokens": 20,
        "cache_read_input_tokens": 30,
    }


def test_handle_anthropic_messages_rejects_invalid_upstream_tool_arguments() -> None:
    response = ModelResponse(
        id="msg-1",
        created="1784577999",
        choice=Choice(
            finish_reason="tool_calls",
            message=Message(
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        function=FunctionCall(name="Bash", arguments="{not json"),
                    )
                ]
            ),
        ),
    )

    with (
        patch.object(
            gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        _handle_anthropic_call(_anthropic_request())

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (LLMRateLimitError("slow down"), OnyxErrorCode.RATE_LIMITED),
        (LLMTimeoutError("too slow"), OnyxErrorCode.BAD_GATEWAY),
    ],
)
def test_handle_anthropic_messages_maps_provider_errors_to_onyx_codes(
    exc: Exception, expected_code: OnyxErrorCode
) -> None:
    with (
        patch.object(
            gateway_api, "llm_from_provider", return_value=_RaisingInvokeLLM(exc)
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        _handle_anthropic_call(_anthropic_request())

    assert exc_info.value.error_code == expected_code


def test_handle_anthropic_messages_sanitizes_generic_invoke_failure() -> None:
    with (
        patch.object(
            gateway_api,
            "llm_from_provider",
            return_value=_RaisingInvokeLLM(ValueError("secret-url?key=abc")),
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        _handle_anthropic_call(_anthropic_request())

    assert exc_info.value.error_code == OnyxErrorCode.BAD_GATEWAY
    assert "secret" not in str(exc_info.value.detail)
    assert "abc" not in str(exc_info.value.detail)


def _anthropic_stream_events(
    llm: LLM,
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str = "1/test",
    message_id: str = "msg_1",
) -> list[dict[str, Any]]:
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        frames = list(
            stream_bridge._run_bridged_stream(
                gateway_api._anthropic_stream_worker,
                {
                    "llm": llm,
                    "flow": LLMFlow.CRAFT_LLM_GENERATION,
                    "messages": [UserMessage(content="hi")],
                    "tools": tools,
                    "tool_choice": None,
                    "max_tokens": 1024,
                    "reasoning_effort": ReasoningEffort.AUTO,
                    "model": model,
                    "message_id": message_id,
                },
            )
        )

    events: list[dict[str, Any]] = []
    for frame in frames:
        assert frame.endswith("\n\n")
        event_line, data_line = frame[:-2].split("\n", 1)
        assert event_line.startswith("event: ")
        assert data_line.startswith("data: ")
        data = json.loads(data_line.removeprefix("data: "))
        assert data["type"] == event_line.removeprefix("event: ")
        events.append(data)
    return events


_TEXT_AND_TOOL_CALL_CHUNKS = [
    ModelResponseStream(
        id="a1", created="0", choice=StreamingChoice(delta=Delta(content="Hi"))
    ),
    ModelResponseStream(
        id="a1", created="0", choice=StreamingChoice(delta=Delta(content=" there"))
    ),
    ModelResponseStream(
        id="a1",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="call_1",
                        index=0,
                        function=FunctionCall(name="Bash", arguments=""),
                    )
                ]
            )
        ),
    ),
    ModelResponseStream(
        id="a1",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        index=0,
                        function=FunctionCall(arguments='{"cmd":"ls"}'),
                    )
                ]
            )
        ),
    ),
    ModelResponseStream(
        id="a1",
        created="0",
        choice=StreamingChoice(finish_reason="tool_calls", delta=Delta()),
        usage=Usage(
            prompt_tokens=100,
            completion_tokens=10,
            total_tokens=110,
            cache_creation_input_tokens=20,
            cache_read_input_tokens=30,
        ),
    ),
]


def test_anthropic_stream_emits_text_then_tool_use_then_stop_in_order() -> None:
    events = _anthropic_stream_events(_ChunkStreamLLM(_TEXT_AND_TOOL_CALL_CHUNKS))
    event_types = [e["type"] for e in events]

    assert event_types == [
        "message_start",
        "ping",
        "content_block_start",
        "content_block_delta",
        "content_block_delta",
        "content_block_stop",
        "content_block_start",
        "content_block_delta",
        "content_block_stop",
        "message_delta",
        "message_stop",
    ]

    message_start = events[0]
    assert message_start["message"]["content"] == []
    assert message_start["message"]["usage"] == {
        "input_tokens": 0,
        "output_tokens": 0,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
    }

    text_block_start = events[2]
    assert text_block_start["index"] == 0
    assert text_block_start["content_block"] == {"type": "text", "text": ""}
    assert [e["delta"]["text"] for e in events[3:5]] == ["Hi", " there"]
    assert events[5]["index"] == 0

    tool_block_start = events[6]
    assert tool_block_start["index"] == 1
    assert tool_block_start["content_block"]["type"] == "tool_use"
    assert tool_block_start["content_block"]["id"] == "call_1"
    assert tool_block_start["content_block"]["name"] == "Bash"
    assert tool_block_start["content_block"]["input"] == {}

    tool_delta = events[7]
    assert tool_delta["index"] == 1
    assert tool_delta["delta"]["type"] == "input_json_delta"
    assert tool_delta["delta"]["partial_json"] == '{"cmd":"ls"}'
    assert events[8]["index"] == 1

    message_delta = events[9]
    assert message_delta["delta"]["stop_reason"] == "tool_use"
    assert message_delta["usage"] == {
        "input_tokens": 50,
        "output_tokens": 10,
        "cache_creation_input_tokens": 20,
        "cache_read_input_tokens": 30,
    }


_TEXT_ONLY_CHUNKS = [
    ModelResponseStream(
        id="a2", created="0", choice=StreamingChoice(delta=Delta(content="Hi"))
    ),
    ModelResponseStream(
        id="a2",
        created="0",
        choice=StreamingChoice(finish_reason="stop", delta=Delta()),
    ),
]


def test_anthropic_stream_text_only_ends_with_end_turn() -> None:
    events = _anthropic_stream_events(_ChunkStreamLLM(_TEXT_ONLY_CHUNKS))

    message_delta = next(e for e in events if e["type"] == "message_delta")
    assert message_delta["delta"]["stop_reason"] == "end_turn"
    assert not any(
        e["type"] == "content_block_start" and e["content_block"]["type"] == "tool_use"
        for e in events
    )


@pytest.mark.parametrize(
    ("exc", "expected_error_type"),
    [
        (RuntimeError("secret-provider-response"), "api_error"),
        (LLMRateLimitError("slow down"), "rate_limit_error"),
    ],
)
def test_anthropic_stream_upstream_failure_emits_single_error_frame(
    exc: Exception, expected_error_type: str
) -> None:
    events = _anthropic_stream_events(
        _StreamingLLM(threading.Event(), fail=True, exc=exc)
    )

    assert events[-1]["type"] == "error"
    assert events[-1]["error"]["type"] == expected_error_type
    assert "secret-provider-response" not in json.dumps(events)
    assert not any(e["type"] == "message_stop" for e in events)
    assert sum(1 for e in events if e["type"] == "error") == 1


def test_anthropic_messages_endpoint_rejects_non_gateway_credentials() -> None:
    request = _anthropic_request()
    with (
        patch.object(gateway_api, "gateway_request_flow", MagicMock(return_value=None)),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_anthropic_messages(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(spec=Session),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_anthropic_messages_endpoint_enforces_token_rate_limits() -> None:
    request = _anthropic_request()
    user = MagicMock()
    rate_limited = OnyxError(OnyxErrorCode.RATE_LIMITED, "over budget")

    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(
            gateway_api, "check_token_rate_limits", side_effect=rate_limited
        ) as rate_check,
        patch.object(gateway_api, "resolve_gateway_model") as resolve_model,
        patch.object(gateway_api, "handle_anthropic_messages") as handle,
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_anthropic_messages(
            request=request,
            http_request=MagicMock(spec=Request),
            user=user,
            db_session=MagicMock(spec=Session),
        )

    assert exc_info.value.error_code is OnyxErrorCode.RATE_LIMITED
    rate_check.assert_called_once_with(user)
    resolve_model.assert_not_called()
    handle.assert_not_called()


def test_anthropic_messages_endpoint_threads_authorized_flow_to_handler() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    model_config = provider.model_configurations[0]
    request = _anthropic_request()
    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(gateway_api, "check_token_rate_limits"),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, model_config),
        ),
        patch.object(
            gateway_api, "is_anthropic_passthrough_eligible", return_value=False
        ),
        patch.object(gateway_api, "handle_anthropic_messages") as handle,
    ):
        handle.return_value.to_wire.return_value = {}
        gateway_api.gateway_anthropic_messages(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(spec=Session),
        )
    handle.assert_called_once_with(
        request=request,
        provider=provider,
        model_config=model_config,
        flow=LLMFlow.LLM_GATEWAY,
    )


def test_anthropic_count_tokens_endpoint_rejects_non_gateway_credentials() -> None:
    request = AnthropicCountTokensRequest(
        model="1/test", messages=[{"role": "user", "content": "hi"}]
    )
    with (
        patch.object(gateway_api, "gateway_request_flow", MagicMock(return_value=None)),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_anthropic_count_tokens(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(spec=Session),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_gateway_anthropic_count_tokens_includes_tools() -> None:
    provider = _provider(1, "openai", [_model("test")])
    model_config = provider.model_configurations[0]
    request = AnthropicCountTokensRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hello"}],
        system="Be terse.",
        tools=[
            {
                "name": "Bash",
                "description": "run",
                "input_schema": {"type": "object", "properties": {}},
            }
        ],
    )
    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, model_config),
        ),
        patch(
            "onyx.llm.litellm_singleton.litellm.token_counter", return_value=123
        ) as token_counter,
    ):
        response = gateway_api.gateway_anthropic_count_tokens(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(spec=Session),
        )

    payload = json.loads(bytes(response.body))
    assert payload == {"input_tokens": 123}
    token_counter.assert_called_once_with(
        model=model_config.name,
        messages=[
            {"role": "system", "content": "Be terse."},
            {"role": "user", "content": "hello"},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "Bash",
                    "description": "run",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
    )


def test_anthropic_signed_thinking_blocks_survive_input_translation() -> None:
    messages = [
        {"role": "user", "content": "hi"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "hmm", "signature": "sig-1"},
                {"type": "redacted_thinking", "data": "opaque"},
                {"type": "thinking", "thinking": "unsigned", "signature": ""},
                {"type": "text", "text": "sure"},
            ],
        },
        {"role": "user", "content": "go on"},
    ]

    raw = gateway_api._anthropic_messages_to_raw_messages(messages, None)

    assistant_message = next(m for m in raw if m["role"] == "assistant")
    assert assistant_message["thinking_blocks"] == [
        {"type": "thinking", "thinking": "hmm", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "opaque"},
    ]

    validated = _MESSAGES_ADAPTER.validate_python(raw)
    validated_assistant = next(m for m in validated if isinstance(m, AssistantMessage))
    assert validated_assistant.thinking_blocks is not None
    thinking, redacted = validated_assistant.thinking_blocks
    assert isinstance(thinking, ThinkingBlock)
    assert thinking.signature == "sig-1"
    assert isinstance(redacted, RedactedThinkingBlock)
    assert redacted.data == "opaque"
    dumped = validated_assistant.model_dump(exclude_none=True)
    assert dumped["thinking_blocks"][0]["signature"] == "sig-1"


def test_thinking_only_assistant_message_is_not_dropped() -> None:
    message = AssistantMessage(
        content=None,
        thinking_blocks=[ThinkingBlock(thinking="hmm", signature="sig-1")],
    )
    assert gateway_api._drop_empty_text(message) is message


def test_handle_anthropic_messages_prepends_thinking_blocks() -> None:
    response = ModelResponse(
        id="msg-1",
        created="1784577999",
        choice=Choice(
            finish_reason="stop",
            message=Message(
                content="Sure thing",
                thinking_blocks=[
                    ThinkingBlock(thinking="let me see", signature="sig-1"),
                    RedactedThinkingBlock(data="opaque"),
                ],
            ),
        ),
        usage=None,
    )

    with patch.object(
        gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
    ):
        result = _handle_anthropic_call(_anthropic_request())

    assert isinstance(result, AnthropicMessageResponse)
    assert result.to_wire()["content"] == [
        {"type": "thinking", "thinking": "let me see", "signature": "sig-1"},
        {"type": "redacted_thinking", "data": "opaque"},
        {"type": "text", "text": "Sure thing"},
    ]


def test_handle_anthropic_messages_reasoning_content_becomes_unsigned_thinking() -> (
    None
):
    response = ModelResponse(
        id="msg-1",
        created="1784577999",
        choice=Choice(
            finish_reason="stop",
            message=Message(content="Hi", reasoning_content="pondering"),
        ),
        usage=None,
    )

    with patch.object(
        gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
    ):
        result = _handle_anthropic_call(_anthropic_request())

    assert isinstance(result, AnthropicMessageResponse)
    assert result.to_wire()["content"] == [
        {"type": "thinking", "thinking": "pondering", "signature": ""},
        {"type": "text", "text": "Hi"},
    ]


_THINKING_TEXT_AND_TOOL_CHUNKS = [
    ModelResponseStream(
        id="a3",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                reasoning_content="I ",
                thinking_blocks=[ThinkingBlock(thinking="I ")],
            )
        ),
    ),
    ModelResponseStream(
        id="a3",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                reasoning_content="think",
                thinking_blocks=[ThinkingBlock(thinking="think")],
            )
        ),
    ),
    ModelResponseStream(
        id="a3",
        created="0",
        choice=StreamingChoice(
            delta=Delta(thinking_blocks=[ThinkingBlock(signature="sig-1")])
        ),
    ),
    ModelResponseStream(
        id="a3", created="0", choice=StreamingChoice(delta=Delta(content="Hi"))
    ),
    ModelResponseStream(
        id="a3",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="call_1",
                        index=0,
                        function=FunctionCall(name="Bash", arguments='{"cmd":"ls"}'),
                    )
                ]
            )
        ),
    ),
    ModelResponseStream(
        id="a3",
        created="0",
        choice=StreamingChoice(finish_reason="tool_calls", delta=Delta()),
    ),
]


def test_anthropic_stream_emits_thinking_block_before_text_and_tools() -> None:
    events = _anthropic_stream_events(_ChunkStreamLLM(_THINKING_TEXT_AND_TOOL_CHUNKS))

    thinking_start = next(
        e
        for e in events
        if e["type"] == "content_block_start"
        and e["content_block"]["type"] == "thinking"
    )
    assert thinking_start["index"] == 0
    assert thinking_start["content_block"] == {
        "type": "thinking",
        "thinking": "",
        "signature": "",
    }

    content_deltas = [e for e in events if e["type"] == "content_block_delta"]
    assert [d["delta"]["type"] for d in content_deltas] == [
        "thinking_delta",
        "thinking_delta",
        "signature_delta",
        "text_delta",
        "input_json_delta",
    ]
    assert [d["index"] for d in content_deltas] == [0, 0, 0, 1, 2]
    assert content_deltas[0]["delta"]["thinking"] == "I "
    assert content_deltas[2]["delta"]["signature"] == "sig-1"

    text_start = next(
        e
        for e in events
        if e["type"] == "content_block_start" and e["content_block"]["type"] == "text"
    )
    assert text_start["index"] == 1
    tool_start = next(
        e
        for e in events
        if e["type"] == "content_block_start"
        and e["content_block"]["type"] == "tool_use"
    )
    assert tool_start["index"] == 2

    stop_indexes = [e["index"] for e in events if e["type"] == "content_block_stop"]
    assert stop_indexes == [0, 1, 2]

    message_delta = next(e for e in events if e["type"] == "message_delta")
    assert message_delta["delta"]["stop_reason"] == "tool_use"


def test_anthropic_stream_reasoning_content_fallback_emits_unsigned_thinking() -> None:
    chunks = [
        ModelResponseStream(
            id="a4",
            created="0",
            choice=StreamingChoice(delta=Delta(reasoning_content="pondering")),
        ),
        ModelResponseStream(
            id="a4", created="0", choice=StreamingChoice(delta=Delta(content="Hi"))
        ),
        ModelResponseStream(
            id="a4",
            created="0",
            choice=StreamingChoice(finish_reason="stop", delta=Delta()),
        ),
    ]
    events = _anthropic_stream_events(_ChunkStreamLLM(chunks))

    delta_types = [
        e["delta"]["type"] for e in events if e["type"] == "content_block_delta"
    ]
    assert delta_types == ["thinking_delta", "text_delta"]
    assert not any(
        e["type"] == "content_block_delta" and e["delta"]["type"] == "signature_delta"
        for e in events
    )
