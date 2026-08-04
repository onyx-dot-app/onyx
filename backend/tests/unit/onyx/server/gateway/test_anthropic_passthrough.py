from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager, nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLMConfig
from onyx.server.gateway import anthropic_passthrough, stream_bridge
from onyx.server.gateway import api as gateway_api
from onyx.server.gateway.anthropic_passthrough import (
    AnthropicPassthroughUnavailable,
    _build_upstream_headers,
    _build_upstream_request,
    _count_tokens_url,
    _messages_url,
    _non_streaming_error_response,
    _streaming_error_event,
    _usage_from_anthropic_wire,
    handle_anthropic_count_tokens_passthrough,
    handle_anthropic_passthrough,
    is_anthropic_passthrough_eligible,
)
from onyx.server.gateway.models import (
    AnthropicCountTokensRequest,
    AnthropicMessagesRequest,
    AnthropicUsagePayload,
)
from onyx.tracing.flows import LLMFlow
from tests.unit.onyx.server.gateway.test_llm_gateway_api import (
    _ConfigOnlyLLM,
    _model,
    _provider,
)


def _anthropic_llm() -> _ConfigOnlyLLM:
    return _ConfigOnlyLLM(
        LLMConfig(
            model_provider="anthropic",
            model_name="claude-sonnet-4-6",
            temperature=0,
            max_input_tokens=1_000,
        )
    )


def test_passthrough_urls_append_paths_before_query_credentials() -> None:
    provider = _provider(1, "anthropic", [_model("claude-sonnet-4-6")])
    provider.api_base = "https://proxy.example/anthropic?api-key=secret"

    assert _messages_url(provider) == (
        "https://proxy.example/anthropic/v1/messages?api-key=secret"
    )
    assert _count_tokens_url(provider) == (
        "https://proxy.example/anthropic/v1/messages/count_tokens?api-key=secret"
    )

    provider.api_base = "https://proxy.example/anthropic/v1?api-key=secret"
    assert _messages_url(provider) == (
        "https://proxy.example/anthropic/v1/messages?api-key=secret"
    )


def _fake_httpx_module(client_factory: Any) -> MagicMock:
    """A stand-in for the ``httpx`` module reference held by
    anthropic_passthrough, preserving the real exception/Timeout classes so
    the module's own exception handling still works."""
    return MagicMock(
        Client=client_factory,
        Timeout=httpx.Timeout,
        HTTPError=httpx.HTTPError,
        TimeoutException=httpx.TimeoutException,
        ConnectError=httpx.ConnectError,
    )


def test_is_anthropic_passthrough_eligible_true_for_anthropic_provider() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    with patch.object(
        anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", True
    ):
        assert is_anthropic_passthrough_eligible(provider) is True


def test_is_anthropic_passthrough_eligible_false_for_openai_provider() -> None:
    provider = _provider(1, "openai", [_model("test")])
    with patch.object(
        anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", True
    ):
        assert is_anthropic_passthrough_eligible(provider) is False


def test_is_anthropic_passthrough_eligible_false_when_kill_switch_off() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    with patch.object(
        anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", False
    ):
        assert is_anthropic_passthrough_eligible(provider) is False


def test_build_upstream_request_swaps_model_name() -> None:
    request = AnthropicMessagesRequest(
        model="1/claude-code-alias",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
    )

    body = _build_upstream_request(request, "claude-sonnet-4-6", "user-1", True)

    assert body["model"] == "claude-sonnet-4-6"


def test_build_upstream_request_always_overwrites_metadata() -> None:
    request = AnthropicMessagesRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        metadata={"user_id": "client-supplied-id"},
    )

    body = _build_upstream_request(request, "claude-sonnet-4-6", "user-1", True)

    assert body["metadata"] == {"user_id": hashlib.sha256(b"user-1").hexdigest()}
    assert body["metadata"]["user_id"] != "client-supplied-id"


def test_build_upstream_request_preserves_unknown_top_level_fields() -> None:
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "1/test",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "output_config": {"effort": "high"},
            "container": {"id": "container_123"},
            "future_field": {"anything": True},
        }
    )

    body = _build_upstream_request(request, "claude-sonnet-4-6", "user-1", True)

    assert body["output_config"] == {"effort": "high"}
    assert body["container"] == {"id": "container_123"}
    assert body["future_field"] == {"anything": True}


def test_build_upstream_request_rejects_mcp_servers() -> None:
    request = AnthropicMessagesRequest.model_validate(
        {
            "model": "1/test",
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 100,
            "mcp_servers": [{"type": "url", "url": "https://evil.example"}],
        }
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "claude-sonnet-4-6", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


@pytest.mark.parametrize("stream_flag", [True, False])
def test_build_upstream_request_sets_stream_explicitly(stream_flag: bool) -> None:
    request = AnthropicMessagesRequest(
        model="1/test",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        stream=stream_flag,
    )

    body = _build_upstream_request(request, "claude-sonnet-4-6", "user-1", stream_flag)

    assert body["stream"] is stream_flag


def test_build_upstream_request_count_tokens_strips_stream_and_max_tokens() -> None:
    request = AnthropicCountTokensRequest(
        model="1/test", messages=[{"role": "user", "content": "hi"}]
    )

    body = _build_upstream_request(request, "claude-sonnet-4-6", "user-1", None)

    assert "stream" not in body
    assert "max_tokens" not in body


def _http_request(headers: dict[str, str]) -> Request:
    scope = {
        "type": "http",
        "headers": [
            (key.lower().encode(), value.encode()) for key, value in headers.items()
        ],
    }
    return Request(scope)


def test_build_upstream_headers_never_forwards_inbound_authorization() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    http_request = _http_request({"authorization": "Bearer onyx_pat_x"})

    headers = _build_upstream_headers(provider, http_request)

    assert not {k.lower() for k in headers} & {"authorization"}
    assert headers["x-api-key"] == provider.api_key


def test_build_upstream_headers_forwards_anthropic_version_when_present() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    http_request = _http_request({"anthropic-version": "2024-01-01"})

    headers = _build_upstream_headers(provider, http_request)

    assert headers["anthropic-version"] == "2024-01-01"


def test_build_upstream_headers_defaults_anthropic_version_when_absent() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    http_request = _http_request({})

    headers = _build_upstream_headers(provider, http_request)

    assert headers["anthropic-version"] == "2023-06-01"


def test_build_upstream_headers_filters_beta_allowlist() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    http_request = _http_request(
        {
            "anthropic-beta": (
                "interleaved-thinking-2025-05-14,evil-beta-2026,claude-code-20250219"
            )
        }
    )

    headers = _build_upstream_headers(provider, http_request)

    assert headers["anthropic-beta"] == (
        "interleaved-thinking-2025-05-14,claude-code-20250219"
    )


def test_build_upstream_headers_omits_beta_header_when_all_dropped() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    http_request = _http_request({"anthropic-beta": "evil-beta-2026"})

    headers = _build_upstream_headers(provider, http_request)

    assert "anthropic-beta" not in headers


def test_build_upstream_headers_merges_server_configured_extra_headers() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    http_request = _http_request({})
    with patch.object(
        anthropic_passthrough,
        "build_llm_extra_headers",
        return_value={"x-proxy-auth": "secret", "x-api-key": "must-lose"},
    ):
        headers = _build_upstream_headers(provider, http_request)

    assert headers["x-proxy-auth"] == "secret"
    assert headers["x-api-key"] == provider.api_key


def test_build_upstream_headers_rejects_provider_without_api_key() -> None:
    provider = _provider(1, "anthropic", [_model("test")])
    provider.api_key = None
    http_request = _http_request({})

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_headers(provider, http_request)

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY


def test_usage_from_anthropic_wire_round_trips_input_tokens() -> None:
    wire_usage = {
        "input_tokens": 100,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 20,
        "output_tokens": 42,
    }

    usage = _usage_from_anthropic_wire(wire_usage)
    payload = AnthropicUsagePayload.from_usage(usage)

    assert payload.input_tokens == 100
    assert payload.output_tokens == 42
    assert payload.cache_read_input_tokens == 30
    assert payload.cache_creation_input_tokens == 20


def test_usage_from_anthropic_wire_missing_keys_default_zero() -> None:
    usage = _usage_from_anthropic_wire({})

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.cache_read_input_tokens == 0
    assert usage.cache_creation_input_tokens == 0


def test_usage_from_anthropic_wire_tolerates_none_values() -> None:
    usage = _usage_from_anthropic_wire(
        {
            "input_tokens": None,
            "cache_read_input_tokens": None,
            "cache_creation_input_tokens": None,
            "output_tokens": None,
        }
    )

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0


@pytest.mark.parametrize("status_code", [400, 429, 529])
def test_non_streaming_error_response_forwards_body_verbatim(status_code: int) -> None:
    body = {"type": "error", "error": {"type": "overloaded_error", "message": "busy"}}
    response = httpx.Response(status_code=status_code, json=body)

    result = _non_streaming_error_response(response)

    assert isinstance(result, JSONResponse)
    assert result.status_code == status_code
    assert json.loads(bytes(result.body)) == body


@pytest.mark.parametrize("status_code", [401, 403])
def test_non_streaming_error_response_sanitizes_credential_errors(
    status_code: int,
) -> None:
    response = httpx.Response(
        status_code=status_code,
        json={"error": {"type": "authentication_error", "message": "bad key xyz"}},
    )

    with pytest.raises(OnyxError) as exc_info:
        _non_streaming_error_response(response)

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY
    assert "bad key xyz" not in str(exc_info.value.detail)


def test_non_streaming_error_response_wraps_non_json_forwardable_body() -> None:
    response = httpx.Response(status_code=400, content=b"not json at all")

    result = _non_streaming_error_response(response)

    payload = json.loads(bytes(result.body))
    assert payload["error"]["type"] == "api_error"
    assert "not json at all" in payload["error"]["message"]


def test_streaming_error_event_carries_upstream_type_and_message() -> None:
    body = json.dumps(
        {"error": {"type": "invalid_request_error", "message": "bad request"}}
    ).encode()

    event = _streaming_error_event(400, body)

    assert event.error.type == "invalid_request_error"
    assert event.error.message == "bad request"


def test_streaming_error_event_sanitizes_credential_errors() -> None:
    body = json.dumps(
        {"error": {"type": "authentication_error", "message": "leaked-key"}}
    ).encode()

    event = _streaming_error_event(401, body)

    assert event.error.type == "api_error"
    assert "leaked-key" not in event.error.message


_SSE_FRAMES: list[tuple[str, dict[str, Any]]] = [
    (
        "message_start",
        {
            "type": "message_start",
            "message": {
                "id": "msg_1",
                "usage": {
                    "input_tokens": 100,
                    "cache_read_input_tokens": 30,
                    "cache_creation_input_tokens": 20,
                    "output_tokens": 1,
                },
            },
        },
    ),
    ("ping", {"type": "ping"}),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "server_tool_use",
                "id": "srvtoolu_1",
                "name": "web_search",
                "input": {},
            },
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"query":"x"}'},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    (
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "text", "text": ""},
        },
    ),
    (
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "text_delta", "text": "hi there"},
        },
    ),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    (
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 42},
        },
    ),
    ("message_stop", {"type": "message_stop"}),
]


def _sse_lines(frames: list[tuple[str, dict[str, Any]]]) -> list[str]:
    lines: list[str] = []
    for event_type, data in frames:
        lines.append(f"event: {event_type}")
        lines.append(f"data: {json.dumps(data)}")
        lines.append("")
    return lines


def _expected_sse_text(frames: list[tuple[str, dict[str, Any]]]) -> str:
    """Mirrors the worker's own framing: each frame is its lines joined by
    ``\\n``, terminated by a blank line (``\\n\\n``)."""
    return "".join(
        f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
        for event_type, data in frames
    )


class _FakeStreamResponse:
    def __init__(
        self, status_code: int, lines: list[str], content: bytes = b""
    ) -> None:
        self.status_code = status_code
        self._lines = lines
        self.content = content
        self.closed = False

    def iter_lines(self) -> list[str]:
        return self._lines

    def read(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class _FakeStreamContext:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response

    def __enter__(self) -> _FakeStreamResponse:
        return self._response

    def __exit__(self, *exc_info: object) -> None:
        self._response.close()


class _FakeHttpxClient:
    def __init__(self, response: _FakeStreamResponse) -> None:
        self._response = response
        self.closed = False

    def __enter__(self) -> "_FakeHttpxClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def close(self) -> None:
        self.closed = True

    def stream(self, *args: object, **kwargs: object) -> _FakeStreamContext:
        del args, kwargs
        return _FakeStreamContext(self._response)


_STREAM_WORKER_KWARGS = {
    "url": "https://api.anthropic.com/v1/messages",
    "headers": {"x-api-key": "k"},
    "body": {"model": "claude-sonnet-4-6"},
    "flow": LLMFlow.CRAFT_LLM_GENERATION,
    "input_messages": [{"role": "user", "content": "hi"}],
    "tools": None,
    "model": "claude-sonnet-4-6",
}


def _run_passthrough_stream(
    response: _FakeStreamResponse,
    *,
    llm_generation_span_patch: Any = None,
) -> tuple[list[str], _FakeHttpxClient]:
    fake_client = _FakeHttpxClient(response)
    span_patch = llm_generation_span_patch or (lambda *a, **k: nullcontext())  # noqa: ARG005
    with (
        patch.object(
            anthropic_passthrough,
            "httpx",
            _fake_httpx_module(MagicMock(return_value=fake_client)),
        ),
        patch.object(anthropic_passthrough, "llm_generation_span", span_patch),
    ):
        frames = list(
            stream_bridge._run_bridged_stream(
                anthropic_passthrough._passthrough_stream_worker,
                {**_STREAM_WORKER_KWARGS, "llm": _anthropic_llm()},
            )
        )
    return frames, fake_client


def test_passthrough_stream_forwards_frames_byte_identical() -> None:
    lines = _sse_lines(_SSE_FRAMES)
    # Non-canonical (but valid) JSON must survive byte-exactly: the worker
    # parses data lines for snooping but forwards the ORIGINAL text.
    lines[-3:-3] = ["event: ping", 'data: { "type" :  "ping" }', ""]
    response = _FakeStreamResponse(200, lines)

    frames, _ = _run_passthrough_stream(response)

    assert "".join(frames) == "".join(f"{line}\n" for line in lines)
    assert 'data: { "type" :  "ping" }' in "".join(frames)
    assert "server_tool_use" in "".join(frames)


def test_passthrough_stream_forwards_malformed_data_line_verbatim() -> None:
    lines = ["event: weird", "data: not json at all", ""]
    response = _FakeStreamResponse(200, lines)

    frames, _ = _run_passthrough_stream(response)

    assert "".join(frames) == "event: weird\ndata: not json at all\n\n"


def test_passthrough_stream_upstream_error_emits_single_error_frame() -> None:
    error_body = json.dumps(
        {"error": {"type": "invalid_request_error", "message": "bad request"}}
    ).encode()
    response = _FakeStreamResponse(400, [], content=error_body)

    frames, _ = _run_passthrough_stream(response)

    assert len(frames) == 1
    assert frames[0].startswith("event: error")
    data = json.loads(frames[0].split("data: ", 1)[1])
    assert data["error"]["type"] == "invalid_request_error"
    assert data["error"]["message"] == "bad request"


def test_passthrough_stream_closes_exitstack_resources() -> None:
    lines = _sse_lines(_SSE_FRAMES)
    response = _FakeStreamResponse(200, lines)

    _frames, fake_client = _run_passthrough_stream(response)

    assert fake_client.closed is True
    assert response.closed is True


def test_passthrough_stream_records_usage_on_span() -> None:
    lines = _sse_lines(_SSE_FRAMES)
    response = _FakeStreamResponse(200, lines)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        del args, kwargs
        yield mock_span

    with patch.object(stream_bridge, "record_llm_span_output") as record_output:
        _run_passthrough_stream(response, llm_generation_span_patch=_span_ctx)

    record_output.assert_called_once()
    usage = record_output.call_args.kwargs["usage"]
    assert usage.prompt_tokens == 150
    assert usage.completion_tokens == 42


_UPSTREAM_MESSAGE: dict[str, Any] = {
    "id": "msg_upstream_abc123",
    "type": "message",
    "role": "assistant",
    "model": "claude-sonnet-4-6",
    "content": [
        {
            "type": "server_tool_use",
            "id": "srvtoolu_1",
            "name": "web_search",
            "input": {"query": "x"},
        },
        {"type": "text", "text": "hi"},
    ],
    "stop_reason": "end_turn",
    "stop_sequence": None,
    "usage": {
        "input_tokens": 100,
        "cache_read_input_tokens": 30,
        "cache_creation_input_tokens": 20,
        "output_tokens": 42,
    },
}


class _FakePostClient:
    def __init__(self, response: httpx.Response) -> None:
        self._response = response

    def __enter__(self) -> "_FakePostClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def post(self, *args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        return self._response


def _non_streaming_request() -> AnthropicMessagesRequest:
    return AnthropicMessagesRequest(
        model="1/claude-sonnet-4-6",
        messages=[{"role": "user", "content": "hi"}],
        max_tokens=100,
        stream=False,
    )


def _run_non_streaming_passthrough(
    upstream_response: httpx.Response,
    *,
    llm_generation_span_patch: Any = None,
) -> JSONResponse:
    provider = _provider(1, "anthropic", [_model("claude-sonnet-4-6")])
    model_config = provider.model_configurations[0]
    span_patch = llm_generation_span_patch or (lambda *a, **k: nullcontext())  # noqa: ARG005

    with (
        patch.object(
            anthropic_passthrough,
            "httpx",
            _fake_httpx_module(
                MagicMock(return_value=_FakePostClient(upstream_response))
            ),
        ),
        patch.object(
            anthropic_passthrough, "llm_from_provider", return_value=_anthropic_llm()
        ),
        patch.object(anthropic_passthrough, "llm_generation_span", span_patch),
    ):
        result = handle_anthropic_passthrough(
            request=_non_streaming_request(),
            provider=provider,
            model_config=model_config,
            flow=LLMFlow.CRAFT_LLM_GENERATION,
            http_request=_http_request({}),
            user=MagicMock(id="user-1"),
        )
        # Non-streaming always yields JSONResponse; narrow instead of cast.
        assert isinstance(result, JSONResponse)
        return result


def test_handle_anthropic_passthrough_non_streaming_forwards_body_verbatim() -> None:
    fake_response = httpx.Response(200, json=_UPSTREAM_MESSAGE)

    result = _run_non_streaming_passthrough(fake_response)

    assert isinstance(result, JSONResponse)
    payload = json.loads(bytes(result.body))
    assert payload == _UPSTREAM_MESSAGE
    assert payload["id"] == "msg_upstream_abc123"


def test_handle_anthropic_passthrough_non_streaming_records_usage() -> None:
    fake_response = httpx.Response(200, json=_UPSTREAM_MESSAGE)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        del args, kwargs
        yield mock_span

    with patch.object(anthropic_passthrough, "record_llm_span_output") as record_output:
        _run_non_streaming_passthrough(
            fake_response, llm_generation_span_patch=_span_ctx
        )

    record_output.assert_called_once()
    usage = record_output.call_args.kwargs["usage"]
    assert usage.prompt_tokens == 150
    assert usage.completion_tokens == 42


def test_handle_anthropic_passthrough_non_streaming_upstream_error_marks_span() -> None:
    fake_response = httpx.Response(
        429, json={"type": "error", "error": {"type": "rate_limit_error"}}
    )
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    result = _run_non_streaming_passthrough(
        fake_response, llm_generation_span_patch=_span_ctx
    )

    assert result.status_code == 429
    mock_span.set_error.assert_called_once()
    assert "429" in mock_span.set_error.call_args.args[0]["message"]


def test_passthrough_stream_upstream_error_marks_span() -> None:
    response = _FakeStreamResponse(500, [])
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    _run_passthrough_stream(response, llm_generation_span_patch=_span_ctx)

    mock_span.set_error.assert_called_once()
    assert "500" in mock_span.set_error.call_args.args[0]["message"]


def _count_tokens_request() -> AnthropicCountTokensRequest:
    return AnthropicCountTokensRequest(
        model="1/claude-sonnet-4-6", messages=[{"role": "user", "content": "hi"}]
    )


def _count_tokens_provider() -> Any:
    provider = _provider(1, "anthropic", [_model("claude-sonnet-4-6")])
    return provider, provider.model_configurations[0]


def test_count_tokens_passthrough_forwards_200_verbatim() -> None:
    upstream_body = {"input_tokens": 55}
    fake_response = httpx.Response(200, json=upstream_body)
    provider, model_config = _count_tokens_provider()

    with patch.object(
        anthropic_passthrough,
        "httpx",
        _fake_httpx_module(MagicMock(return_value=_FakePostClient(fake_response))),
    ):
        result = handle_anthropic_count_tokens_passthrough(
            request=_count_tokens_request(),
            provider=provider,
            model_config=model_config,
            http_request=_http_request({}),
            user=MagicMock(id="user-1"),
        )

    assert json.loads(bytes(result.body)) == upstream_body


def test_count_tokens_passthrough_transport_error_raises_unavailable() -> None:
    class _FailingClient:
        def __enter__(self) -> "_FailingClient":
            return self

        def __exit__(self, *exc_info: object) -> None:
            pass

        def post(self, *args: object, **kwargs: object) -> httpx.Response:
            del args, kwargs
            raise httpx.ConnectError("connection refused")

    provider, model_config = _count_tokens_provider()

    with (
        patch.object(
            anthropic_passthrough,
            "httpx",
            _fake_httpx_module(MagicMock(return_value=_FailingClient())),
        ),
        pytest.raises(AnthropicPassthroughUnavailable),
    ):
        handle_anthropic_count_tokens_passthrough(
            request=_count_tokens_request(),
            provider=provider,
            model_config=model_config,
            http_request=_http_request({}),
            user=MagicMock(id="user-1"),
        )


def test_count_tokens_passthrough_forwards_error_status_and_body() -> None:
    error_body = {"error": {"type": "invalid_request_error", "message": "bad"}}
    fake_response = httpx.Response(400, json=error_body)
    provider, model_config = _count_tokens_provider()

    with patch.object(
        anthropic_passthrough,
        "httpx",
        _fake_httpx_module(MagicMock(return_value=_FakePostClient(fake_response))),
    ):
        result = handle_anthropic_count_tokens_passthrough(
            request=_count_tokens_request(),
            provider=provider,
            model_config=model_config,
            http_request=_http_request({}),
            user=MagicMock(id="user-1"),
        )

    assert result.status_code == 400
    assert json.loads(bytes(result.body)) == error_body


def _anthropic_request(**overrides: Any) -> AnthropicMessagesRequest:
    defaults: dict[str, Any] = {
        "model": "1/test",
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1024,
    }
    defaults.update(overrides)
    return AnthropicMessagesRequest(**defaults)


def test_gateway_anthropic_messages_routes_to_passthrough_for_anthropic_provider() -> (
    None
):
    provider = _provider(1, "anthropic", [_model("test")])
    request = _anthropic_request()
    passthrough_response = JSONResponse(content={"id": "msg_1"})

    with (
        patch.object(
            gateway_api,
            "_authorize_gateway_request",
            return_value=LLMFlow.CRAFT_LLM_GENERATION,
        ),
        patch.object(gateway_api, "check_token_rate_limits"),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, provider.model_configurations[0]),
        ),
        patch.object(
            gateway_api,
            "handle_anthropic_passthrough",
            return_value=passthrough_response,
        ) as handle_passthrough,
        patch.object(gateway_api, "handle_anthropic_messages") as handle_translation,
        patch.object(
            anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", True
        ),
    ):
        result = gateway_api.gateway_anthropic_messages(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(),
        )

    assert result is passthrough_response
    handle_passthrough.assert_called_once()
    handle_translation.assert_not_called()


def test_gateway_anthropic_messages_uses_translation_path_for_openai_provider() -> None:
    provider = _provider(1, "openai", [_model("test")])
    request = _anthropic_request()

    with (
        patch.object(
            gateway_api,
            "_authorize_gateway_request",
            return_value=LLMFlow.CRAFT_LLM_GENERATION,
        ),
        patch.object(gateway_api, "check_token_rate_limits"),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, provider.model_configurations[0]),
        ),
        patch.object(gateway_api, "handle_anthropic_passthrough") as handle_passthrough,
        patch.object(gateway_api, "handle_anthropic_messages") as handle_translation,
        patch.object(
            anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", True
        ),
    ):
        handle_translation.return_value.to_wire.return_value = {"id": "msg_1"}
        gateway_api.gateway_anthropic_messages(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(),
        )

    handle_passthrough.assert_not_called()
    handle_translation.assert_called_once()


def test_gateway_anthropic_count_tokens_routes_to_passthrough_for_anthropic_provider() -> (
    None
):
    provider = _provider(1, "anthropic", [_model("test")])
    request = AnthropicCountTokensRequest(
        model="1/test", messages=[{"role": "user", "content": "hi"}]
    )
    passthrough_response = JSONResponse(content={"input_tokens": 42})

    with (
        patch.object(
            gateway_api,
            "_authorize_gateway_request",
            return_value=LLMFlow.CRAFT_LLM_GENERATION,
        ),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, provider.model_configurations[0]),
        ),
        patch.object(
            gateway_api,
            "handle_anthropic_count_tokens_passthrough",
            return_value=passthrough_response,
        ) as handle_passthrough,
        patch.object(
            anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", True
        ),
    ):
        result = gateway_api.gateway_anthropic_count_tokens(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(),
        )

    assert result is passthrough_response
    handle_passthrough.assert_called_once()


def test_gateway_anthropic_count_tokens_falls_back_to_local_estimate_on_unavailable() -> (
    None
):
    provider = _provider(1, "anthropic", [_model("test")])
    request = AnthropicCountTokensRequest(
        model="1/test", messages=[{"role": "user", "content": "hi"}]
    )

    with (
        patch.object(
            gateway_api,
            "_authorize_gateway_request",
            return_value=LLMFlow.CRAFT_LLM_GENERATION,
        ),
        patch.object(
            gateway_api,
            "resolve_gateway_model",
            return_value=(provider, provider.model_configurations[0]),
        ),
        patch.object(
            gateway_api,
            "handle_anthropic_count_tokens_passthrough",
            side_effect=AnthropicPassthroughUnavailable(),
        ),
        patch.object(
            anthropic_passthrough, "ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED", True
        ),
        patch("onyx.llm.litellm_singleton.litellm.token_counter", return_value=123),
    ):
        result = gateway_api.gateway_anthropic_count_tokens(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(),
        )

    payload = json.loads(bytes(result.body))
    assert payload["input_tokens"] == 123
