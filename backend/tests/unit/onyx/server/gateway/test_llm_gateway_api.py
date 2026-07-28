from __future__ import annotations

import json
import threading
from contextlib import nullcontext
from typing import Any, cast
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI, Request
from fastapi.routing import APIRoute
from sqlalchemy.orm import Session

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
    ReasoningEffort,
    SystemMessage,
    TextContentPart,
    ToolCall,
    ToolChoiceOptions,
    UserMessage,
)
from onyx.llm.models import FunctionCall as ToolFunctionCall
from onyx.llm.multi_llm import (
    LLMRateLimitError,
    LLMStreamingToolUseUnsupportedError,
    LLMTimeoutError,
)
from onyx.server.auth_check import check_router_auth
from onyx.server.features.build.craft_gateway import is_craft_gateway_request
from onyx.server.gateway import api as gateway_api
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
from onyx.server.gateway.models import (
    ChatCompletionRequest,
    ChatCompletionResponse,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.tracing.flows import LLMFlow


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

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
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
    def stream(self, *args: object, **kwargs: object) -> _RaisingCloseStream:  # type: ignore[override]
        del args, kwargs
        return _RaisingCloseStream()


def _gateway_stream(
    llm: LLM,
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: ToolChoiceOptions | None = None,
    structured_response_format: dict[str, Any] | None = None,
    max_tokens: int | None = None,
    reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
):
    return gateway_api._stream_sse(
        llm=llm,
        flow=LLMFlow.CRAFT_LLM_GENERATION,
        messages=[UserMessage(content="hello")],
        tools=tools,
        tool_choice=tool_choice,
        structured_response_format=structured_response_format,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        model="1/test",
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


def _tool_call(arguments: str = '{"cmd":"pwd"}') -> ChatCompletionMessageToolCall:
    return ChatCompletionMessageToolCall(
        id="call_1",
        function=FunctionCall(name="bash", arguments=arguments),
    )


def _model_response(
    *,
    response_id: str = "fallback-1",
    created: str = "1784577906",
    content: str | None = None,
    reasoning_content: str | None = None,
    tool_calls: list[ChatCompletionMessageToolCall] | None = None,
    finish_reason: str | None = None,
    usage: Usage | None = None,
) -> ModelResponse:
    return ModelResponse(
        id=response_id,
        created=created,
        choice=Choice(
            finish_reason=finish_reason,
            message=Message(
                content=content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
            ),
        ),
        usage=usage,
    )


def _empty_model_response() -> ModelResponse:
    return _model_response(response_id="unused", created="0", content="unused")


def _sse_payload(frame: str) -> dict[str, Any]:
    return json.loads(frame.removeprefix("data: "))


def test_completion_payload_serializes_openai_shape() -> None:
    response = _model_response(
        response_id="chatcmpl-1",
        reasoning_content="thinking...",
        tool_calls=[_tool_call('{"cmd":"ls"}')],
        finish_reason="tool_calls",
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


class _ToolCallStreamLLM(_ConfigOnlyLLM):
    def __init__(self) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        yield ModelResponseStream(
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
        )
        yield ModelResponseStream(
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
        )
        yield ModelResponseStream(
            id="s1",
            created="0",
            choice=StreamingChoice(finish_reason="tool_calls", delta=Delta()),
            usage=_wire_usage(),
        )


def test_stream_emits_openai_tool_call_deltas_and_usage() -> None:
    frames = list(_gateway_stream(_ToolCallStreamLLM()))

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


class _ReasoningStreamLLM(_ConfigOnlyLLM):
    def __init__(self) -> None:
        super().__init__(
            LLMConfig(
                model_provider="anthropic",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        yield ModelResponseStream(
            id="r1",
            created="0",
            choice=StreamingChoice(delta=Delta(reasoning_content="thinking ")),
        )
        yield ModelResponseStream(
            id="r1",
            created="0",
            choice=StreamingChoice(delta=Delta(reasoning_content="hard")),
        )
        yield ModelResponseStream(
            id="r1",
            created="0",
            choice=StreamingChoice(finish_reason="stop", delta=Delta(content="done")),
        )


def test_stream_records_accumulated_reasoning_on_span() -> None:
    with (
        patch.object(gateway_api, "llm_generation_span"),
        patch.object(gateway_api, "record_llm_span_output") as record,
    ):
        frames = list(_gateway_stream(_ReasoningStreamLLM()))

    assert frames[-1] == "data: [DONE]\n\n"
    record.assert_called_once()
    assert record.call_args.kwargs["reasoning"] == "thinking hard"
    assert record.call_args.kwargs["output"] == "done"


class _StreamingToolFallbackLLM(_ConfigOnlyLLM):
    def __init__(
        self,
        response: ModelResponse,
        *,
        fail_after_frame: bool = False,
        fallback_exc: Exception | None = None,
    ) -> None:
        super().__init__(
            LLMConfig(
                model_provider="bedrock",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self.response = response
        self.fail_after_frame = fail_after_frame
        self.fallback_exc = fallback_exc
        self.invoke_nonstream_calls: list[dict[str, Any]] = []

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        if self.fail_after_frame:
            yield ModelResponseStream(
                id="before-error",
                created="0",
                choice=StreamingChoice(delta=Delta(content="partial")),
            )
        raise LLMStreamingToolUseUnsupportedError(
            "This model doesn't support tool use in streaming mode."
        )

    def invoke_nonstream(self, *args: object, **kwargs: object) -> ModelResponse:  # type: ignore[override]
        del args
        self.invoke_nonstream_calls.append(kwargs)
        if self.fallback_exc is not None:
            raise self.fallback_exc
        return self.response


class _StreamErrorFallbackSpyLLM(_ConfigOnlyLLM):
    def __init__(self, exc: Exception) -> None:
        super().__init__(
            LLMConfig(
                model_provider="openai",
                model_name="test",
                temperature=0,
                max_input_tokens=1_000,
            )
        )
        self.exc = exc
        self.invoke_nonstream_calls = 0

    def stream(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
        del args, kwargs
        raise self.exc
        yield

    def invoke_nonstream(self, *args: object, **kwargs: object) -> ModelResponse:  # type: ignore[override]
        del args, kwargs
        self.invoke_nonstream_calls += 1
        raise AssertionError("invoke_nonstream must not be called")


def test_pre_frame_streaming_tool_error_falls_back_to_nonstream_sse() -> None:
    response = _model_response(
        content="complete",
        reasoning_content="reasoned",
        tool_calls=[_tool_call()],
        finish_reason="tool_calls",
        usage=_wire_usage(),
    )
    llm = _StreamingToolFallbackLLM(response)
    tools = [{"type": "function", "function": {"name": "bash"}}]
    response_format = {"type": "json_object"}

    with (
        patch.object(gateway_api, "llm_generation_span"),
        patch.object(gateway_api, "record_llm_span_output") as record,
    ):
        frames = list(
            _gateway_stream(
                llm,
                tools=tools,
                tool_choice=ToolChoiceOptions.REQUIRED,
                structured_response_format=response_format,
                max_tokens=77,
                reasoning_effort=ReasoningEffort.HIGH,
            )
        )

    assert frames[-1] == "data: [DONE]\n\n"
    payload = _sse_payload(frames[0])
    assert payload["object"] == "chat.completion.chunk"
    choice = payload["choices"][0]
    assert choice["finish_reason"] == "tool_calls"
    assert choice["delta"]["role"] == "assistant"
    assert choice["delta"]["content"] == "complete"
    assert choice["delta"]["reasoning_content"] == "reasoned"
    assert choice["delta"]["tool_calls"][0]["index"] == 0
    assert choice["delta"]["tool_calls"][0]["function"]["arguments"] == (
        '{"cmd":"pwd"}'
    )
    assert payload["usage"]["total_tokens"] == 150
    assert llm.invoke_nonstream_calls == [
        {
            "prompt": [UserMessage(content="hello")],
            "tools": tools,
            "tool_choice": ToolChoiceOptions.REQUIRED,
            "structured_response_format": response_format,
            "max_tokens": 77,
            "reasoning_effort": ReasoningEffort.HIGH,
        }
    ]
    record.assert_called_once()
    recorded_tool_calls = record.call_args.kwargs["tool_calls"]
    assert recorded_tool_calls is not None
    assert recorded_tool_calls[0].id == "call_1"
    assert recorded_tool_calls[0].function.name == "bash"
    assert recorded_tool_calls[0].function.arguments == '{"cmd":"pwd"}'


@pytest.mark.parametrize(
    ("tools", "fail_after_frame", "error_frame_index"),
    [
        ([{"type": "function"}], True, 1),
        (None, False, 0),
    ],
)
def test_streaming_tool_error_when_fallback_is_unsafe_does_not_fallback(
    tools: list[dict[str, Any]] | None,
    fail_after_frame: bool,
    error_frame_index: int,
) -> None:
    llm = _StreamingToolFallbackLLM(
        _empty_model_response(),
        fail_after_frame=fail_after_frame,
    )

    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        frames = list(_gateway_stream(llm, tools=tools))

    assert len(llm.invoke_nonstream_calls) == 0
    if fail_after_frame:
        assert _sse_payload(frames[0])["choices"][0]["delta"]["content"] == "partial"
    error = _sse_payload(frames[error_frame_index])["error"]
    assert error["type"] == "upstream_error"
    assert frames[-1] == "data: [DONE]\n\n"


@pytest.mark.parametrize(
    "exc",
    [
        LLMTimeoutError("too slow"),
        RuntimeError("generic upstream failure"),
    ],
)
def test_non_tool_mismatch_stream_errors_do_not_fallback(exc: Exception) -> None:
    llm = _StreamErrorFallbackSpyLLM(exc)

    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        frames = list(_gateway_stream(llm, tools=[{"type": "function"}]))

    assert llm.invoke_nonstream_calls == 0
    error = _sse_payload(frames[0])["error"]
    assert error["type"] in {"timeout_error", "upstream_error"}
    assert frames[-1] == "data: [DONE]\n\n"


def test_streaming_tool_fallback_failure_uses_sanitized_stream_error() -> None:
    llm = _StreamingToolFallbackLLM(
        _empty_model_response(),
        fallback_exc=RuntimeError("secret-provider-response"),
    )

    with patch.object(gateway_api, "llm_generation_span", return_value=nullcontext()):
        frames = list(_gateway_stream(llm, tools=[{"type": "function"}]))

    assert len(llm.invoke_nonstream_calls) == 1
    assert "upstream LLM request failed" in frames[0]
    assert "secret-provider-response" not in frames[0]
    assert frames[-1] == "data: [DONE]\n\n"


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

    def invoke(self, *args: object, **kwargs: object):  # type: ignore[no-untyped-def,override]
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

    def invoke(self, *args: object, **kwargs: object) -> ModelResponse:  # type: ignore[override]
        del args, kwargs
        return self._response


def _handle_completion_call(request: ChatCompletionRequest) -> Any:
    provider = _provider(1, "openai", [_model("test")])
    return gateway_api.handle_chat_completion(
        request=request,
        db_session=cast(Session, MagicMock(spec=Session)),
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
        ("bogus", None),
        ({"type": "function", "function": {"name": "bash"}}, None),
        (None, None),
    ],
)
def test_parse_tool_choice(raw: object, expected: ToolChoiceOptions | None) -> None:
    assert gateway_api._parse_tool_choice(raw) is expected


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
            if getattr(route, "path", None)
            == f"{GATEWAY_PATH_PREFIX}/v1/chat/completions"
        ),
    )
    auth_dependencies = [
        dependency.call
        for dependency in gateway_route.dependant.dependencies
        if getattr(dependency.call, "_is_require_permission", False)
    ]
    assert len(auth_dependencies) == 1


def test_endpoint_applies_craft_policy() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    provider = _provider(1, "openai", [_model("test")])
    model_config = provider.model_configurations[0]
    db_session = cast(Session, MagicMock(spec=Session))
    user = cast(User, MagicMock(spec=User))
    http_request = cast(Request, MagicMock(spec=Request))

    check_access = MagicMock(return_value=True)
    with (
        patch.dict(
            gateway_api._FLOW_ACCESS_CHECKS,
            {LLMFlow.CRAFT_LLM_GENERATION: check_access},
        ),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, model_config),
        ) as resolve_model,
        patch.object(gateway_api, "handle_chat_completion") as handle,
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
        db_session=db_session,
        provider=provider,
        model_config=model_config,
        flow=LLMFlow.CRAFT_LLM_GENERATION,
    )


def test_craft_flow_is_gated_by_craft_credential_check() -> None:
    assert (
        gateway_api._FLOW_ACCESS_CHECKS[LLMFlow.CRAFT_LLM_GENERATION]
        is is_craft_gateway_request
    )


def test_endpoint_rejects_non_gateway_credentials() -> None:
    request = ChatCompletionRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
    )
    with (
        patch.dict(
            gateway_api._FLOW_ACCESS_CHECKS,
            {LLMFlow.CRAFT_LLM_GENERATION: MagicMock(return_value=False)},
        ),
        pytest.raises(OnyxError) as exc_info,
    ):
        gateway_api.gateway_chat_completions(
            request=request,
            http_request=cast(Request, MagicMock(spec=Request)),
            user=cast(User, MagicMock(spec=User)),
            db_session=cast(Session, MagicMock(spec=Session)),
        )
    assert exc_info.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
