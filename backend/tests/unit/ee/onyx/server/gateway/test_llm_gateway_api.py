from __future__ import annotations

import json
import threading
from collections.abc import Awaitable, Callable, Generator, Iterator
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

from ee.onyx.server.gateway import api as gateway_api
from ee.onyx.server.gateway import stream_bridge
from ee.onyx.server.gateway.api import _MESSAGES_ADAPTER
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLM, LLMConfig
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
    ChatCompletionMessage,
    ImageContentPart,
    ImageUrlDetail,
    NamedToolChoice,
    ReasoningEffort,
    SystemMessage,
    TextContentPart,
    ToolCall,
    ToolChoice,
    ToolChoiceOptions,
    UserMessage,
)
from onyx.llm.models import FunctionCall as ToolFunctionCall
from onyx.llm.multi_llm import LLMRateLimitError, LLMTimeoutError
from onyx.server.auth_check import check_router_auth
from onyx.server.features.build import craft_gateway
from onyx.server.features.build.craft_gateway import gateway_request_flow
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
from onyx.server.gateway.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
    ResponsesRequest,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import get_current_trace


def _pat_request(token_scopes: list[Permission] | None) -> Request:
    request = Request({"type": "http", "headers": []})
    if token_scopes is not None:
        request.state.token_scopes = token_scopes
    return request


def _route_permission_dependency(path: str) -> Callable[..., Awaitable[User]]:
    # Pulled off the live route rather than rebuilt, so these tests follow the
    # permission the endpoint actually enforces.
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(gateway_api.router)
    route = cast(
        APIRoute,
        next(
            route
            for route in application.routes
            if getattr(route, "path", None)  # ods: ignore[getattr]
            == f"{GATEWAY_PATH_PREFIX}{path}"
        ),
    )
    dependency = next(
        dep.call
        for dep in route.dependant.dependencies
        if getattr(dep.call, "_is_require_permission", False)  # ods: ignore[getattr]
    )
    return cast("Callable[..., Awaitable[User]]", dependency)


def _model(
    name: str,
    *,
    display_name: str | None = None,
    is_visible: bool = True,
    supports_reasoning: bool = False,
    max_input_tokens: int | None = None,
) -> ModelConfigurationView:
    return ModelConfigurationView(
        name=name,
        display_name=display_name,
        is_visible=is_visible,
        supports_image_input=False,
        supports_reasoning=supports_reasoning,
        max_input_tokens=max_input_tokens,
    )


def _provider(
    provider_id: int,
    provider_type: str,
    models: list[ModelConfigurationView],
    *,
    name: str | None = None,
) -> LLMProviderView:
    return LLMProviderView(
        id=provider_id,
        name=name,
        provider=provider_type,
        api_key="test-key",
        model_configurations=models,
    )


class _ConfigOnlyLLM(LLM):
    def __init__(self, config: LLMConfig) -> None:
        self._config = config

    @property
    def config(self) -> LLMConfig:
        return self._config


class _ChunkStreamLLM(_ConfigOnlyLLM):
    def __init__(
        self, chunks: list[ModelResponseStream], provider: str = "openai"
    ) -> None:
        super().__init__(
            LLMConfig(
                model_provider=provider,
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self._chunks = chunks

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        yield from self._chunks


def test_resolve_model_preserves_slashes_after_provider_id() -> None:
    model = _model("anthropic/claude-3.5-sonnet")
    provider = _provider(23, "openrouter", [model])
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))
    with patch.object(
        gateway_api,
        "fetch_accessible_llm_provider_by_id",
        return_value=provider,
    ) as fetch_provider:
        resolved_provider, resolved_model = gateway_api.resolve_gateway_model(
            db_session,
            user,
            "23/anthropic/claude-3.5-sonnet",
        )

    assert resolved_provider is provider
    assert resolved_model is model
    fetch_provider.assert_called_once_with(db_session, user, 23)


@pytest.mark.parametrize(
    "requested_model",
    ["claude-3.5-sonnet", "not-an-id/claude-3.5-sonnet", "23/hidden"],
)
def test_resolve_model_rejects_malformed_or_hidden_models(
    requested_model: str,
) -> None:
    provider = _provider(23, "anthropic", [_model("hidden", is_visible=False)])

    with (
        patch.object(
            gateway_api,
            "fetch_accessible_llm_provider_by_id",
            return_value=provider,
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.resolve_gateway_model(
            cast(Session, MagicMock(spec=Session)),
            cast(User, MagicMock(spec=User)),
            requested_model,
        )

    assert exc_info.value.status_code == 404


class _StreamingLLM(_ConfigOnlyLLM):
    def __init__(
        self,
        closed: threading.Event,
        *,
        fail: bool = False,
        exc: Exception | None = None,
    ) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self._closed = closed
        self._fail = fail
        self._exc = exc or RuntimeError("secret-provider-response")

    def stream(self, *args: object, **kwargs: object):
        del args, kwargs
        try:
            if self._fail:
                raise self._exc
            for index in range(1_000):
                yield ModelResponseStream(
                    id=str(index),
                    created="0",
                    choice=StreamingChoice(delta=Delta(content="x")),
                )
        finally:
            self._closed.set()


class _RaisingCloseStream:
    def __init__(self) -> None:
        self._remaining = 1

    def __iter__(self) -> _RaisingCloseStream:
        return self

    def __next__(self) -> ModelResponseStream:
        if not self._remaining:
            raise StopIteration
        self._remaining -= 1
        return ModelResponseStream(
            id="1",
            created="0",
            choice=StreamingChoice(delta=Delta(content="x")),
        )

    def close(self) -> None:
        raise RuntimeError("cleanup failed")


class _RaisingCloseLLM(_ConfigOnlyLLM):
    def stream(self, *args: object, **kwargs: object) -> _RaisingCloseStream:
        del args, kwargs
        return _RaisingCloseStream()


def _gateway_stream(llm: LLM):
    return stream_bridge._run_bridged_stream(
        gateway_api._stream_worker,
        {
            "llm": llm,
            "flow": LLMFlow.CRAFT_LLM_GENERATION,
            "messages": [UserMessage(content="hello")],
            "tools": None,
            "tool_choice": None,
            "structured_response_format": None,
            "max_tokens": None,
            "reasoning_effort": ReasoningEffort.AUTO,
            "model": "1/test",
        },
    )


def test_stream_disconnect_closes_upstream_producer() -> None:
    closed = threading.Event()
    stream = _gateway_stream(_StreamingLLM(closed))
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        next(stream)
        stream.close()
    assert closed.wait(timeout=2)


def test_stream_error_hides_provider_details() -> None:
    closed = threading.Event()
    stream = _gateway_stream(_StreamingLLM(closed, fail=True))
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        payload = next(stream)
        stream.close()
    assert "upstream LLM request failed" in payload
    assert "secret-provider-response" not in payload


def test_stream_error_is_followed_by_done_terminator() -> None:
    closed = threading.Event()
    stream = _gateway_stream(_StreamingLLM(closed, fail=True))
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        frames = list(stream)

    assert json.loads(frames[0].removeprefix("data: "))["error"]["type"] == (
        "upstream_error"
    )
    assert "upstream LLM request failed" in frames[0]
    assert frames[-1] == "data: [DONE]\n\n"


def test_stream_rate_limit_error_emits_distinguishable_type() -> None:
    closed = threading.Event()
    stream = _gateway_stream(
        _StreamingLLM(closed, fail=True, exc=LLMRateLimitError("slow down"))
    )
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        frames = list(stream)

    error = json.loads(frames[0].removeprefix("data: "))["error"]
    assert error["type"] == "rate_limit_error"
    assert "temporarily rate limited" in error["message"]
    assert "slow down" not in error["message"]
    assert frames[-1] == "data: [DONE]\n\n"


def test_stream_cleanup_failure_does_not_hang_response() -> None:
    llm = _RaisingCloseLLM(
        LLMConfig(
            model_provider="openai",
            model_name="test",
            temperature=0,
            max_input_tokens=1_000,
        )
    )
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        payloads = list(_gateway_stream(llm))

    assert payloads[-1] == "data: [DONE]\n\n"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (None, ReasoningEffort.AUTO),
        ("low", ReasoningEffort.LOW),
        ("medium", ReasoningEffort.MEDIUM),
        ("high", ReasoningEffort.HIGH),
        ("invalid", ReasoningEffort.AUTO),
    ],
)
def test_reasoning_effort_defaults_to_auto(
    raw: str | None,
    expected: ReasoningEffort,
) -> None:
    assert gateway_api._parse_reasoning_effort(raw) is expected


def test_prepare_messages_marks_stable_prefix_for_prompt_cache() -> None:
    config = LLMConfig(
        model_provider="anthropic",
        model_name="claude-sonnet",
        temperature=0,
        max_input_tokens=200_000,
    )
    llm = _ConfigOnlyLLM(config)
    messages: list[ChatCompletionMessage] = [
        SystemMessage(content="stable instructions"),
        UserMessage(content="new request"),
    ]
    raw_messages = [
        {"role": "system", "content": "stable instructions"},
        {"role": "user", "content": "new request"},
    ]
    processed = [*messages]

    with patch.object(
        gateway_api,
        "process_with_prompt_cache",
        return_value=(processed, None),
    ) as process_prompt:
        result = gateway_api._prepare_messages(llm, raw_messages)

    assert result is processed
    process_prompt.assert_called_once_with(
        llm_config=config,
        cacheable_prefix=messages[:-1],
        suffix=messages[-1:],
        continuation=False,
        with_metadata=False,
    )


def test_prepare_messages_uses_no_cacheable_prefix_for_single_message() -> None:
    config = LLMConfig(
        model_provider="openai",
        model_name="gpt-5-mini",
        temperature=0,
        max_input_tokens=128_000,
    )
    llm = _ConfigOnlyLLM(config)
    messages: list[ChatCompletionMessage] = [UserMessage(content="only message")]

    with patch.object(
        gateway_api,
        "process_with_prompt_cache",
        return_value=(messages, None),
    ) as process_prompt:
        gateway_api._prepare_messages(
            llm, [{"role": "user", "content": "only message"}]
        )

    assert process_prompt.call_args.kwargs["cacheable_prefix"] is None
    assert process_prompt.call_args.kwargs["suffix"] == messages


def test_drop_empty_text() -> None:
    tool_call = ToolCall(
        id="call_1", function=ToolFunctionCall(name="bash", arguments="{}")
    )
    image_part = ImageContentPart(image_url=ImageUrlDetail(url="https://x/y.png"))
    messages: list[ChatCompletionMessage] = [
        SystemMessage(content="instructions"),
        UserMessage(content="build me an app"),
        AssistantMessage(content="", tool_calls=[tool_call]),
        AssistantMessage(content="  "),
        UserMessage(content=" "),
        UserMessage(content=[TextContentPart(text=""), image_part]),
    ]

    result = [
        message
        for message in map(gateway_api._drop_empty_text, messages)
        if message is not None
    ]

    assert result == [
        SystemMessage(content="instructions"),
        UserMessage(content="build me an app"),
        AssistantMessage(content=None, tool_calls=[tool_call]),
        UserMessage(content=[image_part]),
    ]


def test_prepare_messages_rejects_all_empty_messages() -> None:
    llm = _ConfigOnlyLLM(
        LLMConfig(
            model_provider="anthropic",
            model_name="claude-sonnet",
            temperature=0,
            max_input_tokens=200_000,
        )
    )
    with pytest.raises(OnyxError) as exc_info:
        gateway_api._prepare_messages(llm, [{"role": "user", "content": ""}])
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def test_prepare_messages_rejects_invalid_messages() -> None:
    llm = _ConfigOnlyLLM(
        LLMConfig(
            model_provider="openai",
            model_name="test",
            temperature=0,
            max_input_tokens=1_000,
        )
    )
    with pytest.raises(OnyxError) as exc_info:
        gateway_api._prepare_messages(llm, [{"role": "not-a-role"}])
    assert exc_info.value.error_code == OnyxErrorCode.INVALID_INPUT


def _wire_usage() -> Usage:
    return Usage(
        prompt_tokens=120,
        completion_tokens=30,
        total_tokens=150,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=100,
    )


def test_completion_payload_serializes_openai_shape() -> None:
    response = ModelResponse(
        id="chatcmpl-1",
        created="1784577906",
        choice=Choice(
            finish_reason="tool_calls",
            message=Message(
                content=None,
                reasoning_content="thinking...",
                tool_calls=[
                    ChatCompletionMessageToolCall(
                        id="call_1",
                        function=FunctionCall(name="bash", arguments='{"cmd":"ls"}'),
                    )
                ],
            ),
        ),
        usage=_wire_usage(),
    )

    payload = ChatCompletionResponse.from_model_response(
        response, "3/gpt-5-mini"
    ).to_wire()

    assert payload["object"] == "chat.completion"
    assert payload["created"] == 1784577906
    assert payload["model"] == "3/gpt-5-mini"
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["message"]["role"] == "assistant"
    assert choice["message"]["reasoning_content"] == "thinking..."
    assert choice["message"]["tool_calls"] == [
        {
            "id": "call_1",
            "type": "function",
            "function": {"name": "bash", "arguments": '{"cmd":"ls"}'},
        }
    ]
    assert payload["usage"] == {
        "prompt_tokens": 120,
        "completion_tokens": 30,
        "total_tokens": 150,
        "prompt_tokens_details": {"cached_tokens": 100},
    }


_TOOL_CALL_STREAM_CHUNKS = [
    ModelResponseStream(
        id="s1",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="call_1",
                        index=0,
                        function=FunctionCall(name="bash", arguments=""),
                    )
                ]
            )
        ),
    ),
    ModelResponseStream(
        id="s1",
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
        id="s1",
        created="0",
        choice=StreamingChoice(finish_reason="tool_calls", delta=Delta()),
        usage=_wire_usage(),
    ),
]


def test_stream_emits_openai_tool_call_deltas_and_usage() -> None:
    frames = list(_gateway_stream(_ChunkStreamLLM(_TOOL_CALL_STREAM_CHUNKS)))

    assert frames[-1] == "data: [DONE]\n\n"
    payloads = [json.loads(frame.removeprefix("data: ")) for frame in frames[:-1]]

    assert payloads[0]["choices"][0]["delta"]["role"] == "assistant"
    assert all("role" not in p["choices"][0]["delta"] for p in payloads[1:])
    assert all(p["object"] == "chat.completion.chunk" for p in payloads)

    first_tool_delta = payloads[0]["choices"][0]["delta"]["tool_calls"][0]
    assert first_tool_delta["id"] == "call_1"
    assert first_tool_delta["index"] == 0
    assert first_tool_delta["function"]["name"] == "bash"

    second_tool_delta = payloads[1]["choices"][0]["delta"]["tool_calls"][0]
    assert second_tool_delta["index"] == 0
    assert second_tool_delta["function"]["arguments"] == '{"cmd":"ls"}'

    final = payloads[-1]
    assert final["choices"][0]["finish_reason"] == "tool_calls"
    assert final["usage"]["prompt_tokens_details"]["cached_tokens"] == 100


_REASONING_STREAM_CHUNKS = [
    ModelResponseStream(
        id="r1",
        created="0",
        choice=StreamingChoice(delta=Delta(reasoning_content="thinking ")),
    ),
    ModelResponseStream(
        id="r1",
        created="0",
        choice=StreamingChoice(delta=Delta(reasoning_content="hard")),
    ),
    ModelResponseStream(
        id="r1",
        created="0",
        choice=StreamingChoice(finish_reason="stop", delta=Delta(content="done")),
    ),
]


def _reasoning_stream_llm() -> _ChunkStreamLLM:
    return _ChunkStreamLLM(_REASONING_STREAM_CHUNKS, provider="anthropic")


def test_stream_records_accumulated_reasoning_on_span() -> None:
    with (
        patch.object(gateway_api, "llm_generation_span"),
        patch.object(stream_bridge, "record_llm_span_output") as record,
    ):
        frames = list(_gateway_stream(_reasoning_stream_llm()))

    assert frames[-1] == "data: [DONE]\n\n"
    record.assert_called_once()
    assert record.call_args.kwargs["reasoning"] == "thinking hard"
    assert record.call_args.kwargs["output"] == "done"


@contextmanager
def _capture_trace_at_generation_span(captured: list[Any]) -> Iterator[None]:
    real_span = gateway_api.llm_generation_span

    @contextmanager
    def _recording_span(*args: Any, **kwargs: Any) -> Iterator[Any]:
        captured.append(get_current_trace())
        with real_span(*args, **kwargs) as span:
            yield span

    with patch.object(gateway_api, "llm_generation_span", _recording_span):
        yield


def _assert_gateway_trace(active: Any) -> None:
    assert active is not None, "no trace was active when the generation span opened"
    assert active.name == "llm_gateway"
    assert active.metadata == {
        "flow": LLMFlow.CRAFT_LLM_GENERATION.value,
        "model": "test",
    }


def test_stream_worker_opens_trace_before_generation_span() -> None:
    traces: list[Any] = []
    with _capture_trace_at_generation_span(traces):
        frames = list(_gateway_stream(_reasoning_stream_llm()))

    assert frames[-1] == "data: [DONE]\n\n"
    (active,) = traces
    _assert_gateway_trace(active)


class _RaisingInvokeLLM(_ConfigOnlyLLM):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self._exc = exc

    def invoke(self, *args: object, **kwargs: object):
        del args, kwargs
        raise self._exc


class _InvokeLLM(_ConfigOnlyLLM):
    def __init__(self, response: ModelResponse) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self._response = response

    def invoke(self, *args: object, **kwargs: object) -> ModelResponse:
        del args, kwargs
        return self._response


class _RecordingInvokeLLM(_InvokeLLM):
    def __init__(self, response: ModelResponse) -> None:
        super().__init__(response)
        self.received_tool_choice: ToolChoice | None = None

    def invoke(self, *args: object, **kwargs: object) -> ModelResponse:
        self.received_tool_choice = cast("ToolChoice | None", kwargs.get("tool_choice"))
        return super().invoke(*args, **kwargs)


def _handle_completion_call(request: ChatCompletionRequest) -> Any:
    provider = _provider(1, "openai", [_model("test")])
    return gateway_api.handle_chat_completion(
        request=request,
        provider=provider,
        model_config=provider.model_configurations[0],
        flow=LLMFlow.CRAFT_LLM_GENERATION,
    )


def test_handle_chat_completion_happy_path_serializes_response() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    response = ModelResponse(
        id="chatcmpl-2",
        created="1784577999",
        choice=Choice(
            finish_reason="stop",
            message=Message(content="hello there"),
        ),
        usage=_wire_usage(),
    )

    with patch.object(
        gateway_api,
        "llm_from_provider",
        return_value=_InvokeLLM(response),
    ):
        result = _handle_completion_call(request)

    assert isinstance(result, ChatCompletionResponse)
    payload = result.to_wire()
    assert payload["object"] == "chat.completion"
    assert payload["model"] == "1/test"
    assert payload["choices"][0]["message"]["content"] == "hello there"
    assert payload["choices"][0]["message"]["role"] == "assistant"
    assert payload["choices"][0]["finish_reason"] == "stop"
    assert payload["usage"]["total_tokens"] == 150


def test_non_streaming_opens_trace_before_generation_span() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    response = ModelResponse(
        id="chatcmpl-3",
        created="1784577999",
        choice=Choice(
            finish_reason="stop",
            message=Message(content="hello there"),
        ),
        usage=_wire_usage(),
    )

    traces: list[Any] = []
    with (
        patch.object(
            gateway_api,
            "llm_from_provider",
            return_value=_InvokeLLM(response),
        ),
        _capture_trace_at_generation_span(traces),
    ):
        _handle_completion_call(request)

    (active,) = traces
    _assert_gateway_trace(active)


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (LLMRateLimitError("slow down"), OnyxErrorCode.RATE_LIMITED),
        (LLMTimeoutError("too slow"), OnyxErrorCode.BAD_GATEWAY),
    ],
)
def test_handle_chat_completion_maps_provider_errors_to_onyx_codes(
    exc: Exception, expected_code: OnyxErrorCode
) -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )

    with (
        patch.object(
            gateway_api,
            "llm_from_provider",
            return_value=_RaisingInvokeLLM(exc),
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        _handle_completion_call(request)

    assert exc_info.value.error_code == expected_code


def test_handle_chat_completion_sanitizes_generic_invoke_failure() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )

    with (
        patch.object(
            gateway_api,
            "llm_from_provider",
            return_value=_RaisingInvokeLLM(ValueError("secret-url?key=abc")),
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        _handle_completion_call(request)

    assert exc_info.value.error_code == OnyxErrorCode.BAD_GATEWAY
    assert "secret" not in str(exc_info.value.detail)
    assert "abc" not in str(exc_info.value.detail)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("auto", ToolChoiceOptions.AUTO),
        ("required", ToolChoiceOptions.REQUIRED),
        ("none", ToolChoiceOptions.NONE),
        (None, None),
    ],
)
def test_parse_tool_choice(raw: object, expected: ToolChoiceOptions | None) -> None:
    assert gateway_api._parse_tool_choice(raw) is expected


@pytest.mark.parametrize(
    "raw",
    [
        {"type": "function", "function": {"name": "bash"}},
        {"type": "function", "name": "bash"},
    ],
)
def test_parse_tool_choice_maps_named_function(raw: object) -> None:
    """Both the Chat Completions and Responses API wire shapes for a named
    tool_choice must map to the same NamedToolChoice."""
    assert gateway_api._parse_tool_choice(raw) == NamedToolChoice(name="bash")


@pytest.mark.parametrize(
    "raw",
    ["bogus", {"type": "bogus"}, {"type": "function", "function": {}}],
)
def test_parse_tool_choice_refuses_unsupported(raw: object) -> None:
    """A tool_choice we cannot honor must fail loudly. Downgrading to auto lets
    the model skip a tool the caller required, with nothing in the response to
    say the constraint was dropped."""
    with pytest.raises(OnyxError) as exc_info:
        gateway_api._parse_tool_choice(raw)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


@pytest.mark.parametrize(
    ("tool_choice", "tools", "should_raise"),
    [
        (ToolChoiceOptions.AUTO, None, False),
        (ToolChoiceOptions.REQUIRED, [], False),
        (None, None, False),
        (
            NamedToolChoice(name="bash"),
            [{"type": "function", "function": {"name": "bash"}}],
            False,
        ),
        (
            NamedToolChoice(name="bash"),
            [{"type": "function", "function": {"name": "other"}}],
            True,
        ),
        (NamedToolChoice(name="bash"), None, True),
    ],
)
def test_require_named_tool(
    tool_choice: ToolChoiceOptions | NamedToolChoice | None,
    tools: list[dict[str, Any]] | None,
    should_raise: bool,
) -> None:
    if should_raise:
        with pytest.raises(OnyxError) as exc_info:
            gateway_api._require_named_tool(tool_choice, tools)
        assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    else:
        gateway_api._require_named_tool(tool_choice, tools)


def test_handle_chat_completion_rejects_named_tool_choice_for_unknown_tool() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
        tools=[{"type": "function", "function": {"name": "bash", "parameters": {}}}],
        tool_choice={"type": "function", "function": {"name": "other"}},
    )
    response = ModelResponse(
        id="chatcmpl-1",
        created="1784577999",
        choice=Choice(finish_reason="stop", message=Message(content="ok")),
    )

    with patch.object(
        gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
    ):
        with pytest.raises(OnyxError) as exc_info:
            _handle_completion_call(request)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_gateway_route_exposes_standard_auth_dependency() -> None:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(gateway_api.router)

    check_router_auth(application, public_endpoint_specs=[])


def test_gateway_route_has_single_permission_dependency() -> None:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(gateway_api.router)
    gateway_route = cast(
        APIRoute,
        next(
            route
            for route in application.routes
            if getattr(route, "path", None)  # ods: ignore[getattr]
            == f"{GATEWAY_PATH_PREFIX}/v1/chat/completions"
        ),
    )
    auth_dependencies = [
        dependency.call
        for dependency in gateway_route.dependant.dependencies
        if getattr(  # ods: ignore[getattr]
            dependency.call, "_is_require_permission", False
        )
    ]
    assert len(auth_dependencies) == 1


def test_endpoint_threads_authorized_flow_to_handler() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    provider = _provider(1, "openai", [_model("test")])
    model_config = provider.model_configurations[0]
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))
    http_request = cast(Request, MagicMock(spec=Request))

    check_access = MagicMock(return_value=LLMFlow.LLM_GATEWAY)
    with (
        patch.object(gateway_api, "gateway_request_flow", check_access),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, model_config),
        ) as resolve_model,
        patch.object(gateway_api, "handle_chat_completion") as handle,
        patch.object(gateway_api, "check_token_rate_limits"),
    ):
        handle.return_value.to_wire.return_value = {}
        gateway_api.gateway_chat_completions(
            request=request,
            http_request=http_request,
            user=user,
            db_session=db_session,
        )

    check_access.assert_called_once_with(http_request, user)
    resolve_model.assert_called_once_with(db_session, user, "1/test")
    handle.assert_called_once_with(
        request=request,
        provider=provider,
        model_config=model_config,
        flow=LLMFlow.LLM_GATEWAY,
    )


def test_endpoint_enforces_token_rate_limits_before_calling_provider() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))
    http_request = cast(Request, MagicMock(spec=Request))

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
        patch.object(gateway_api, "handle_chat_completion") as handle,
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_chat_completions(
            request=request,
            http_request=http_request,
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    rate_check.assert_called_once_with(user)
    resolve_model.assert_not_called()
    handle.assert_not_called()


def test_gateway_flow_follows_credential_type() -> None:
    user = cast(User, MagicMock(spec=User))
    with patch.object(craft_gateway, "is_craft_enabled_for_user", return_value=True):
        assert (
            gateway_request_flow(_pat_request([Permission.CRAFT_SANDBOX]), user)
            is LLMFlow.CRAFT_LLM_GENERATION
        )
        assert (
            gateway_request_flow(_pat_request([Permission.USE_LLM_GATEWAY]), user)
            is LLMFlow.LLM_GATEWAY
        )


def test_endpoint_rejects_non_gateway_credentials() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    with (
        patch.object(gateway_api, "gateway_request_flow", MagicMock(return_value=None)),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_chat_completions(
            request=request,
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


class TestGatewayAuthComposition:
    @staticmethod
    def _basic_user() -> User:
        user = MagicMock()
        user.effective_permissions = ["basic"]
        return cast(User, user)

    @staticmethod
    def _base_dep() -> Callable[..., Awaitable[User]]:
        return _route_permission_dependency("/v1/chat/completions")

    @pytest.mark.asyncio
    async def test_plain_gateway_scoped_pat_is_accepted(self) -> None:
        user = self._basic_user()
        request = _pat_request([Permission.READ_SEARCH, Permission.USE_LLM_GATEWAY])
        base_dep = self._base_dep()

        assert await base_dep(request=request, user=user) is user
        with patch.object(
            craft_gateway, "is_craft_enabled_for_user", return_value=False
        ):
            assert gateway_request_flow(request, user) is LLMFlow.LLM_GATEWAY

    @pytest.mark.asyncio
    async def test_craft_sandbox_pat_still_works_unchanged(self) -> None:
        user = self._basic_user()
        request = _pat_request([Permission.CRAFT_SANDBOX])
        base_dep = self._base_dep()

        assert await base_dep(request=request, user=user) is user
        with patch.object(
            craft_gateway, "is_craft_enabled_for_user", return_value=True
        ):
            assert gateway_request_flow(request, user) is LLMFlow.CRAFT_LLM_GENERATION
        with patch.object(
            craft_gateway, "is_craft_enabled_for_user", return_value=False
        ):
            assert gateway_request_flow(request, user) is None

    @pytest.mark.asyncio
    async def test_unrestricted_pat_is_rejected(self) -> None:
        """scopes=None is an unrestricted PAT, not a scope-less one."""
        user = self._basic_user()
        request = _pat_request(None)

        assert gateway_request_flow(request, user) is None

    @pytest.mark.asyncio
    async def test_session_and_api_key_auth_are_rejected(self) -> None:
        """Session auth and plain API keys never set token_scopes."""
        user = self._basic_user()
        request = Request({"type": "http", "headers": []})

        assert gateway_request_flow(request, user) is None

    @pytest.mark.asyncio
    async def test_gateway_scope_alone_passes_both_gates(self) -> None:
        user = self._basic_user()
        request = _pat_request([Permission.USE_LLM_GATEWAY])
        base_dep = self._base_dep()

        assert await base_dep(request=request, user=user) is user
        with patch.object(
            craft_gateway, "is_craft_enabled_for_user", return_value=False
        ):
            assert gateway_request_flow(request, user) is LLMFlow.LLM_GATEWAY

    @pytest.mark.asyncio
    async def test_read_search_scope_alone_fails_base_permission_gate(self) -> None:
        user = self._basic_user()
        request = _pat_request([Permission.READ_SEARCH])
        base_dep = self._base_dep()

        with pytest.raises(OnyxError) as exc_info:
            await base_dep(request=request, user=user)
        assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        with patch.object(
            craft_gateway, "is_craft_enabled_for_user", return_value=False
        ):
            assert gateway_request_flow(request, user) is None


def _catalog_provider() -> LLMProviderView:
    return _provider(
        7,
        "openai",
        [_model("gpt-5-mini"), _model("hidden", is_visible=False)],
    )


def test_list_models_returns_openai_shape_excluding_hidden_models() -> None:
    provider = _catalog_provider()
    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(
            gateway_api,
            "fetch_all_accessible_llm_providers",
            return_value=[provider],
        ) as fetch_providers,
    ):
        response = gateway_api.gateway_list_models(
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
        fetch_providers.assert_called_once()

    payload = json.loads(bytes(response.body))
    assert payload["object"] == "list"
    assert [m["id"] for m in payload["data"]] == ["7/gpt-5-mini"]
    assert payload["data"][0]["object"] == "model"
    assert payload["data"][0]["owned_by"] == "openai"


def test_list_models_ids_round_trip_through_resolve_gateway_model() -> None:
    provider = _catalog_provider()
    with (
        patch.object(
            gateway_api,
            "gateway_request_flow",
            MagicMock(return_value=LLMFlow.LLM_GATEWAY),
        ),
        patch.object(
            gateway_api, "fetch_all_accessible_llm_providers", return_value=[provider]
        ),
    ):
        response = gateway_api.gateway_list_models(
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
    model_id = json.loads(bytes(response.body))["data"][0]["id"]

    with patch.object(
        gateway_api, "fetch_accessible_llm_provider_by_id", return_value=provider
    ):
        resolved_provider, resolved_model = gateway_api.resolve_gateway_model(
            cast(Session, MagicMock(spec=Session)),
            cast(User, MagicMock(spec=User)),
            model_id,
        )

    assert resolved_provider is provider
    assert resolved_model.name == "gpt-5-mini"


def test_list_models_rejects_non_gateway_credentials() -> None:
    with (
        patch.object(gateway_api, "gateway_request_flow", MagicMock(return_value=None)),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_list_models(
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_responses_input_instructions_become_system_message() -> None:
    request = ResponsesRequest(
        model="1/test",
        instructions="You are a coding agent.",
        input=[{"type": "message", "role": "user", "content": "say hi"}],
    )

    raw = gateway_api._responses_input_to_raw_messages(request)

    assert raw[0] == {"role": "system", "content": "You are a coding agent."}
    assert raw[-1]["role"] == "user"


def test_responses_developer_role_collapses_into_system_message() -> None:
    """Our ChatCompletionMessage union has no 'developer' role and
    SystemMessage.content is str-only, so both must collapse to 'system'."""
    request = ResponsesRequest(
        model="1/test",
        input=[
            {
                "type": "message",
                "role": "developer",
                "content": [{"type": "text", "text": "be terse"}],
            },
            {"type": "message", "role": "user", "content": "say hi"},
        ],
    )

    raw = gateway_api._responses_input_to_raw_messages(request)

    assert raw[0] == {"role": "system", "content": "be terse"}


def test_responses_input_items_become_messages() -> None:
    request = ResponsesRequest(
        model="1/test",
        input=[
            {"type": "message", "role": "user", "content": "hello there"},
        ],
    )

    raw = gateway_api._responses_input_to_raw_messages(request)
    llm = _ConfigOnlyLLM(
        LLMConfig(
            model_provider="openai",
            model_name="test",
            temperature=0,
            max_input_tokens=1_000,
        )
    )
    messages = gateway_api._prepare_messages(llm, raw)

    assert messages == [UserMessage(content="hello there")]


def test_responses_request_tolerates_unknown_top_level_fields() -> None:
    """Codex sends fields like prompt_cache_key/client_metadata/include that
    the gateway doesn't act on; these must be accepted, not rejected."""
    request = ResponsesRequest.model_validate(
        {
            "model": "1/test",
            "input": [{"type": "message", "role": "user", "content": "hi"}],
            "store": False,
            "prompt_cache_key": "019fb050-bf28-7812-8a84-5331b2ed60b0",
            "client_metadata": {"turn_id": "abc"},
            "include": ["reasoning.encrypted_content"],
            "parallel_tool_calls": False,
        }
    )

    assert request.model == "1/test"


def test_responses_tools_drop_namespace_entries() -> None:
    """Codex's multi-agent 'namespace' tool has no Chat Completions
    equivalent; it must be silently dropped rather than erroring."""
    request = ResponsesRequest(
        model="1/test",
        input="hi",
        tools=[
            {"type": "function", "name": "exec_command", "parameters": {}},
            {"type": "namespace", "name": "multi_agent_v1", "tools": []},
        ],
    )

    tools = gateway_api._responses_tools(request)

    assert tools is not None
    assert len(tools) == 1
    assert tools[0]["function"]["name"] == "exec_command"


def _handle_responses_call(request: ResponsesRequest) -> Any:
    provider = _provider(1, "openai", [_model("test")])
    return gateway_api.handle_responses_request(
        request=request,
        provider=provider,
        model_config=provider.model_configurations[0],
        flow=LLMFlow.CRAFT_LLM_GENERATION,
    )


def test_handle_responses_request_non_streaming_returns_completed_response() -> None:
    request = ResponsesRequest(model="1/test", input="say hi")
    response = ModelResponse(
        id="chatcmpl-1",
        created="1784577999",
        choice=Choice(finish_reason="stop", message=Message(content="hello there")),
        usage=_wire_usage(),
    )

    with patch.object(
        gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
    ):
        result = _handle_responses_call(request)

    assert isinstance(result, gateway_api.ResponsesObjectPayload)
    payload = result.to_wire()
    assert payload["object"] == "response"
    assert payload["status"] == "completed"
    assert payload["output"][0]["type"] == "message"
    assert payload["output"][0]["content"][0]["text"] == "hello there"
    assert payload["usage"]["input_tokens"] == 120


def test_handle_responses_request_forwards_named_tool_choice() -> None:
    """The Responses request must survive the litellm tools transform plus
    _require_named_tool and reach the LLM as a NamedToolChoice."""
    request = ResponsesRequest(
        model="1/test",
        input="hi",
        tools=[{"type": "function", "name": "bash", "parameters": {}}],
        tool_choice={"type": "function", "name": "bash"},
    )
    response = ModelResponse(
        id="chatcmpl-1",
        created="1784577999",
        choice=Choice(finish_reason="stop", message=Message(content="ok")),
        usage=_wire_usage(),
    )
    fake_llm = _RecordingInvokeLLM(response)

    with patch.object(gateway_api, "llm_from_provider", return_value=fake_llm):
        _handle_responses_call(request)

    assert fake_llm.received_tool_choice == NamedToolChoice(name="bash")


def test_handle_responses_request_rejects_named_tool_choice_for_unknown_tool() -> None:
    request = ResponsesRequest(
        model="1/test",
        input="hi",
        tools=[{"type": "function", "name": "bash", "parameters": {}}],
        tool_choice={"type": "function", "name": "other"},
    )
    response = ModelResponse(
        id="chatcmpl-1",
        created="1784577999",
        choice=Choice(finish_reason="stop", message=Message(content="ok")),
    )

    with patch.object(
        gateway_api, "llm_from_provider", return_value=_InvokeLLM(response)
    ):
        with pytest.raises(OnyxError) as exc_info:
            _handle_responses_call(request)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


_TEXT_CHUNKS = [
    ModelResponseStream(
        id="r1", created="0", choice=StreamingChoice(delta=Delta(content="Hi"))
    ),
    # Two content chunks: with one, a regression re-opening the output item
    # per delta (Codex-fatal) would still pass.
    ModelResponseStream(
        id="r1", created="0", choice=StreamingChoice(delta=Delta(content=" there"))
    ),
    ModelResponseStream(
        id="r1",
        created="0",
        choice=StreamingChoice(finish_reason="stop", delta=Delta()),
        usage=_wire_usage(),
    ),
]

_TOOL_CALL_CHUNKS = [
    ModelResponseStream(
        id="s1",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="call_1",
                        index=0,
                        function=FunctionCall(name="bash", arguments='{"cmd":"ls"}'),
                    )
                ]
            )
        ),
    ),
    ModelResponseStream(
        id="s1",
        created="0",
        choice=StreamingChoice(finish_reason="tool_calls", delta=Delta()),
    ),
]


def _responses_stream_events(
    llm: LLM,
    *,
    tools: list[dict[str, Any]] | None = None,
    model: str = "1/test",
    response_id: str = "resp_1",
    span: Any | None = None,
) -> list[dict[str, Any]]:
    with patch.object(
        gateway_api, "llm_generation_span", return_value=nullcontext(span)
    ):
        frames = list(
            stream_bridge._run_bridged_stream(
                gateway_api._responses_stream_worker,
                {
                    "llm": llm,
                    "flow": LLMFlow.CRAFT_LLM_GENERATION,
                    "messages": [UserMessage(content="hi")],
                    "tools": tools,
                    "tool_choice": None,
                    "max_tokens": None,
                    "reasoning_effort": ReasoningEffort.AUTO,
                    "model": model,
                    "response_id": response_id,
                    "created_at": 100,
                },
            )
        )
    return [json.loads(frame.removeprefix("data: ")) for frame in frames]


def test_responses_stream_emits_created_first_and_completed_last() -> None:
    events = _responses_stream_events(_ChunkStreamLLM(_TEXT_CHUNKS))
    assert events[0]["type"] == "response.created"
    assert events[0]["response"]["status"] == "in_progress"
    assert events[-1]["type"] == "response.completed"
    assert events[-1]["response"]["status"] == "completed"
    assert events[-1]["response"]["output"][0]["content"][0]["text"] == "Hi there"
    delta_events = [e for e in events if e["type"] == "response.output_text.delta"]
    assert [e["delta"] for e in delta_events] == ["Hi", " there"]


def test_responses_stream_emits_full_output_item_lifecycle_in_order() -> None:
    """Codex 0.145 rejects any output_text.delta whose item was never opened
    ("OutputTextDelta without active item")."""
    events = _responses_stream_events(_ChunkStreamLLM(_TEXT_CHUNKS))
    event_types = [e["type"] for e in events]

    assert event_types == [
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]

    added_event = events[1]
    assert added_event["item"]["type"] == "message"
    assert added_event["item"]["status"] == "in_progress"
    message_item_id = added_event["item"]["id"]

    for event in events[2:-1]:
        item_id = (
            event.get("item_id")
            if "item_id" in event
            else event.get("item", {}).get("id")
        )
        assert item_id == message_item_id

    assert [e["delta"] for e in events[3:5]] == ["Hi", " there"]
    assert events[5]["text"] == "Hi there"
    assert events[6]["part"]["text"] == "Hi there"
    done_item_event = events[7]
    assert done_item_event["item"]["status"] == "completed"
    assert done_item_event["item"]["content"][0]["text"] == "Hi there"
    assert events[-1]["response"]["output"] == [done_item_event["item"]]


def test_responses_stream_tool_call_gets_own_output_item_lifecycle() -> None:
    events = _responses_stream_events(
        _ChunkStreamLLM(_TOOL_CALL_CHUNKS), response_id="resp_2"
    )
    event_types = [e["type"] for e in events]

    assert event_types == [
        "response.created",
        "response.output_item.added",
        "response.function_call_arguments.done",
        "response.output_item.done",
        "response.completed",
    ]

    added_event = events[1]
    assert added_event["item"]["type"] == "function_call"
    assert added_event["output_index"] == 0
    call_item_id = added_event["item"]["id"]

    args_done_event = events[2]
    assert args_done_event["item_id"] == call_item_id
    assert args_done_event["arguments"] == '{"cmd":"ls"}'

    done_event = events[3]
    assert done_event["item"]["id"] == call_item_id
    assert done_event["item"]["status"] == "completed"

    assert [item["id"] for item in events[-1]["response"]["output"]] == [call_item_id]


_TEXT_AND_TOOL_CALL_CHUNKS = [
    ModelResponseStream(
        id="m1", created="0", choice=StreamingChoice(delta=Delta(content="Running"))
    ),
    ModelResponseStream(
        id="m1",
        created="0",
        choice=StreamingChoice(
            delta=Delta(
                tool_calls=[
                    ChatCompletionDeltaToolCall(
                        id="call_9",
                        index=0,
                        function=FunctionCall(name="bash", arguments='{"cmd":"ls"}'),
                    )
                ]
            )
        ),
    ),
    ModelResponseStream(
        id="m1",
        created="0",
        choice=StreamingChoice(finish_reason="tool_calls", delta=Delta()),
    ),
]


def test_responses_stream_text_and_tool_call_get_separate_output_indices() -> None:
    """Reusing output_index 0 for both makes Codex reject the tool call."""
    events = _responses_stream_events(
        _ChunkStreamLLM(_TEXT_AND_TOOL_CALL_CHUNKS), response_id="resp_3"
    )

    message_id = events[1]["item"]["id"]
    assert events[1]["output_index"] == 0

    call_added = next(
        e
        for e in events
        if e["type"] == "response.output_item.added"
        and e["item"]["type"] == "function_call"
    )
    assert call_added["output_index"] == 1
    assert call_added["item"]["id"] != message_id

    args_done = next(
        e for e in events if e["type"] == "response.function_call_arguments.done"
    )
    assert args_done["output_index"] == 1
    assert args_done["item_id"] == call_added["item"]["id"]

    output = events[-1]["response"]["output"]
    assert [item["type"] for item in output] == ["message", "function_call"]
    assert output[0]["content"][0]["text"] == "Running"
    assert [item["id"] for item in output] == [message_id, call_added["item"]["id"]]


@pytest.mark.parametrize(
    "exc",
    [
        LLMRateLimitError("slow down"),
        LLMTimeoutError("too slow"),
        RuntimeError("secret-provider-response"),
    ],
)
def test_responses_stream_upstream_failure_emits_response_failed(
    exc: Exception,
) -> None:
    events = _responses_stream_events(
        _StreamingLLM(threading.Event(), fail=True, exc=exc), response_id="resp_err"
    )

    assert events[0]["type"] == "response.created"
    assert events[-1]["type"] == "response.failed"
    assert events[-1]["response"]["status"] == "failed"
    assert events[-1]["response"]["id"] == "resp_err"
    assert "secret-provider-response" not in json.dumps(events)
    assert not any(e["type"] == "response.completed" for e in events)


class _FailAfterTextLLM(_ConfigOnlyLLM):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self._exc = exc

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        yield ModelResponseStream(
            id="p1", created="0", choice=StreamingChoice(delta=Delta(content="partial"))
        )
        raise self._exc


def test_responses_stream_failure_closes_the_open_text_item() -> None:
    events = _responses_stream_events(
        _FailAfterTextLLM(RuntimeError("boom")), response_id="resp_partial"
    )
    event_types = [e["type"] for e in events]

    assert event_types == [
        "response.created",
        "response.output_item.added",
        "response.content_part.added",
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.failed",
    ]
    item_id = events[1]["item"]["id"]
    assert events[1]["item"]["status"] == "in_progress"
    done_item = events[6]["item"]
    assert done_item["id"] == item_id
    assert done_item["status"] == "incomplete"
    assert done_item["content"][0]["text"] == "partial"
    assert events[-1]["response"]["status"] == "failed"


def test_responses_stream_events_carry_monotonic_sequence_numbers() -> None:
    """sequence_number is a required field on every Responses streaming event
    in the OpenAI schema; strict SDK clients fail validation without it."""
    events = _responses_stream_events(
        _ChunkStreamLLM(_TEXT_AND_TOOL_CALL_CHUNKS), response_id="resp_seq"
    )

    assert [e["sequence_number"] for e in events] == list(range(len(events)))


@pytest.mark.parametrize(
    ("exc", "expected_code"),
    [
        (LLMRateLimitError("slow down"), "rate_limit_exceeded"),
        (LLMTimeoutError("too slow"), "server_error"),
        (RuntimeError("secret-provider-response"), "server_error"),
    ],
)
def test_responses_stream_failure_uses_schema_error_codes(
    exc: Exception, expected_code: str
) -> None:
    """response.error must be {code, message} with code from the Responses
    enum, and a rate limit must stay distinguishable for retry-aware clients."""
    events = _responses_stream_events(
        _StreamingLLM(threading.Event(), fail=True, exc=exc), response_id="resp_code"
    )

    error = events[-1]["response"]["error"]
    assert error["code"] == expected_code
    assert "type" not in error
    assert "secret-provider-response" not in error["message"]


def test_responses_stream_validates_against_openai_sdk_models() -> None:
    """The whole emitted stream must parse with the real openai SDK event
    models, which is what a strict client actually runs."""
    from openai.types.responses import ResponseStreamEvent
    from pydantic import TypeAdapter

    adapter: TypeAdapter[Any] = TypeAdapter(ResponseStreamEvent)
    streams = [
        _responses_stream_events(
            _ChunkStreamLLM(_TEXT_AND_TOOL_CALL_CHUNKS), response_id="resp_sdk"
        ),
        _responses_stream_events(
            _FailAfterTextLLM(LLMRateLimitError("slow down")),
            response_id="resp_sdk_err",
        ),
    ]
    for events in streams:
        for event in events:
            adapter.validate_python(event)


def test_responses_stream_disconnect_closes_upstream_and_omits_completed() -> None:
    closed = threading.Event()
    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        stream = stream_bridge._run_bridged_stream(
            gateway_api._responses_stream_worker,
            {
                "llm": _StreamingLLM(closed),
                "flow": LLMFlow.CRAFT_LLM_GENERATION,
                "messages": [UserMessage(content="hi")],
                "tools": None,
                "tool_choice": None,
                "max_tokens": None,
                "reasoning_effort": ReasoningEffort.AUTO,
                "model": "1/test",
                "response_id": "resp_gone",
                "created_at": 100,
            },
        )
        seen = [json.loads(next(stream).removeprefix("data: ")) for _ in range(2)]
        cast(Generator[str, None, None], stream).close()

    assert closed.wait(timeout=2)
    assert seen[0]["type"] == "response.created"
    assert not any(event["type"] == "response.completed" for event in seen)


def test_responses_stream_records_output_usage_and_reasoning_on_span() -> None:
    """The span must be truthy: with a null span every assertion here passes
    silently, because the worker skips all span recording."""
    span = MagicMock()

    with patch.object(stream_bridge, "record_llm_span_output") as record:
        _responses_stream_events(
            _reasoning_stream_llm(), span=span, response_id="resp_span"
        )

    record.assert_called_once()
    assert record.call_args.args[0] is span
    assert record.call_args.kwargs["reasoning"] == "thinking hard"
    assert record.call_args.kwargs["output"] == "done"

    with patch.object(stream_bridge, "record_llm_span_output") as record:
        _responses_stream_events(
            _ChunkStreamLLM(_TEXT_CHUNKS), span=span, response_id="resp_usage"
        )

    usage = record.call_args.kwargs["usage"]
    assert usage is not None and usage.prompt_tokens == 120


@pytest.mark.asyncio
async def test_handle_responses_request_streaming_returns_event_stream() -> None:
    request = ResponsesRequest.model_validate({**_codex_fixture(), "stream": True})

    with (
        patch.object(
            gateway_api, "llm_from_provider", return_value=_ChunkStreamLLM(_TEXT_CHUNKS)
        ),
        patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()),
    ):
        result = _handle_responses_call(request)

        assert isinstance(result, StreamingResponse)
        assert result.media_type == "text/event-stream"
        events = [
            json.loads(frame.removeprefix("data: "))
            async for frame in result.body_iterator
        ]

    # The invariant Codex enforces: no event may reference an unopened item.
    assert events[0]["type"] == "response.created"
    assert events[-1]["type"] == "response.completed"
    open_items: set[str] = set()
    for event in events:
        if event["type"] == "response.output_item.added":
            open_items.add(event["item"]["id"])
        elif event["type"] in (
            "response.output_text.delta",
            "response.output_text.done",
            "response.content_part.added",
            "response.content_part.done",
        ):
            assert event["item_id"] in open_items, (
                f"{event['type']} referenced unopened item {event['item_id']}"
            )


def test_handle_responses_request_refuses_previous_response_id() -> None:
    """We store nothing, so honoring previous_response_id would silently drop
    the conversation history the caller believes we are holding."""
    request = ResponsesRequest(
        model="1/test", input="say hi", previous_response_id="resp_abc"
    )

    with pytest.raises(OnyxError) as exc_info:
        _handle_responses_call(request)

    assert exc_info.value.error_code is OnyxErrorCode.NOT_IMPLEMENTED


def test_responses_request_still_tolerates_codex_session_fields() -> None:
    """Guards the refusals above from over-reaching: Codex sends `store: false`
    and `reasoning.summary`, and both must stay accepted. Reasoning summaries
    are an unimplemented output, not a rejected input."""
    request = ResponsesRequest.model_validate(
        {
            "model": "1/test",
            "input": "hi",
            "store": False,
            "reasoning": {"summary": "auto"},
            "tool_choice": "auto",
        }
    )

    assert request.previous_response_id is None
    assert gateway_api._parse_tool_choice(request.tool_choice) is ToolChoiceOptions.AUTO


def test_responses_gateway_route_carries_same_permission_dependency() -> None:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(gateway_api.router)
    responses_route = cast(
        APIRoute,
        next(
            route
            for route in application.routes
            if getattr(route, "path", None)  # ods: ignore[getattr]
            == f"{GATEWAY_PATH_PREFIX}/v1/responses"
        ),
    )
    auth_dependencies = [
        dependency.call
        for dependency in responses_route.dependant.dependencies
        if getattr(  # ods: ignore[getattr]
            dependency.call, "_is_require_permission", False
        )
    ]
    assert len(auth_dependencies) == 1


def test_responses_endpoint_rejects_non_gateway_credentials() -> None:
    request = ResponsesRequest(model="1/test", input="hi")
    with (
        patch.object(gateway_api, "gateway_request_flow", MagicMock(return_value=None)),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_responses(
            request=request,
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_responses_endpoint_rejects_unrestricted_pat() -> None:
    """An unrestricted PAT (scopes=None) must never be treated as
    gateway-capable, mirroring the chat completions route."""
    user = MagicMock()
    user.effective_permissions = ["basic"]
    request = ResponsesRequest(model="1/test", input="hi")

    with pytest.raises(OnyxError) as exc_info:
        gateway_api.gateway_responses(
            request=request,
            http_request=_pat_request(None),
            user=cast(User, user),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS


def test_responses_endpoint_enforces_token_rate_limits_before_calling_provider() -> (
    None
):
    """Same token/cost budget enforcement as the chat route: an over-budget
    caller must never reach model resolution or the provider."""
    request = ResponsesRequest(model="1/test", input="hi")
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))
    http_request = cast(Request, MagicMock(spec=Request))

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
        patch.object(gateway_api, "handle_responses_request") as handle,
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_responses(
            request=request,
            http_request=http_request,
            user=user,
            db_session=db_session,
        )

    assert exc_info.value.error_code == OnyxErrorCode.RATE_LIMITED
    rate_check.assert_called_once_with(user)
    resolve_model.assert_not_called()
    handle.assert_not_called()


def test_responses_endpoint_resolves_model_same_way_as_chat_route() -> None:
    request = ResponsesRequest(model="1/test", input="hi")
    provider = _provider(1, "openai", [_model("test")])
    model_config = provider.model_configurations[0]
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))
    http_request = cast(Request, MagicMock(spec=Request))

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
        ) as resolve_model,
        patch.object(gateway_api, "handle_responses_request") as handle,
        patch.object(gateway_api, "check_token_rate_limits"),
    ):
        handle.return_value.to_wire.return_value = {}
        gateway_api.gateway_responses(
            request=request,
            http_request=http_request,
            user=user,
            db_session=db_session,
        )

    resolve_model.assert_called_once_with(db_session, user, "1/test")
    handle.assert_called_once_with(
        request=request,
        provider=provider,
        model_config=model_config,
        flow=LLMFlow.LLM_GATEWAY,
    )


def test_responses_model_not_found_matches_chat_route_behavior() -> None:
    provider = _provider(1, "anthropic", [_model("visible-model")])
    with (
        patch.object(
            gateway_api, "fetch_accessible_llm_provider_by_id", return_value=provider
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.resolve_gateway_model(
            cast(Session, MagicMock(spec=Session)),
            cast(User, MagicMock(spec=User)),
            "1/does-not-exist",
        )
    assert exc_info.value.status_code == 404


def test_models_route_has_single_permission_dependency() -> None:
    application = FastAPI(openapi_url=None, docs_url=None, redoc_url=None)
    application.include_router(gateway_api.router)
    models_route = cast(
        APIRoute,
        next(
            route
            for route in application.routes
            if getattr(route, "path", None)  # ods: ignore[getattr]
            == f"{GATEWAY_PATH_PREFIX}/v1/models"
        ),
    )
    auth_dependencies = [
        dependency.call
        for dependency in models_route.dependant.dependencies
        if getattr(  # ods: ignore[getattr]
            dependency.call, "_is_require_permission", False
        )
    ]
    assert len(auth_dependencies) == 1


def _codex_fixture() -> dict[str, Any]:
    path = Path(__file__).parent / "fixtures" / "codex_responses_request.json"
    return cast(dict[str, Any], json.loads(path.read_text()))


def test_codex_capture_converts_without_rejecting_input() -> None:
    """Replay of a real Codex CLI request. Our own synthetic payloads all
    passed while Codex was failing, so the shapes it actually sends
    (top-level instructions, function_call/reasoning items, namespace and
    web_search tools) are pinned here rather than invented."""
    request = ResponsesRequest.model_validate(_codex_fixture())

    raw_messages = gateway_api._responses_input_to_raw_messages(request)
    _MESSAGES_ADAPTER.validate_python(raw_messages)

    assert raw_messages[0]["role"] == "system"
    assert {m["role"] for m in raw_messages} <= {"system", "user", "assistant", "tool"}

    tools = gateway_api._responses_tools(request)
    assert tools is not None
    assert {t["type"] for t in tools} == {"function"}
    assert len(tools) < len(request.tools or [])


def test_responses_tool_round_trip_assistant_content_is_flattened() -> None:
    """Regression: on a tool round-trip the prior assistant turn comes back
    with list-of-parts content, but AssistantMessage.content is str-only, so
    the whole turn 400'd with "Invalid messages". Only reachable on the second
    turn, which is why first-turn tests missed it."""
    request = ResponsesRequest.model_validate(
        {
            "model": "1/test",
            "input": [
                {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "run it"}],
                },
                {
                    "type": "function_call",
                    "id": "fc_1",
                    "call_id": "call_1",
                    "name": "exec_command",
                    "arguments": '{"cmd":"cat probe.txt"}',
                    "status": "completed",
                },
                {
                    "type": "function_call_output",
                    "call_id": "call_1",
                    "output": "hello",
                },
            ],
        }
    )

    raw = gateway_api._responses_input_to_raw_messages(request)
    _MESSAGES_ADAPTER.validate_python(raw)

    assistant = [m for m in raw if m.get("role") == "assistant"]
    assert assistant, raw
    for message in assistant:
        assert not isinstance(message["content"], list)
