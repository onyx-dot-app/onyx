from __future__ import annotations

import hashlib
import json
from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from fastapi import Request
from fastapi.responses import JSONResponse

from ee.onyx.server.gateway import api as gateway_api
from ee.onyx.server.gateway import openai_passthrough, stream_bridge
from ee.onyx.server.gateway.openai_passthrough import (
    _SANITIZED_ERROR,
    _base_url,
    _build_upstream_headers,
    _build_upstream_request,
    _error_type_and_message,
    _non_streaming_error_response,
    _openai_passthrough_stream_worker,
    _reasoning_tokens,
    _responses_url,
    _usage_from_openai_wire,
    handle_openai_responses_passthrough,
    is_openai_passthrough_eligible,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.interfaces import LLMConfig
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.gateway.models import ResponsesRequest
from onyx.tracing.flows import LLMFlow
from tests.unit.ee.onyx.server.gateway.test_llm_gateway_api import (
    _ConfigOnlyLLM,
    _model,
    _provider,
)


def _openai_llm() -> _ConfigOnlyLLM:
    return _ConfigOnlyLLM(
        LLMConfig(
            model_provider="openai",
            model_name="gpt-5-mini",
            temperature=0,
            max_input_tokens=1_000,
        )
    )


def _real_openai_litellm_llm() -> LitellmLLM:
    """A real LitellmLLM instance so isinstance(llm, LitellmLLM) holds; only
    used with _track_llm_cost patched onto the instance so no DB/network
    call actually happens."""
    return LitellmLLM(
        api_key="test-key",
        model_provider="openai",
        model_name="gpt-5-mini",
        max_input_tokens=1_000,
    )


def _fake_httpx_module(client_factory: Any) -> MagicMock:
    """A stand-in for the ``httpx`` module reference held by
    openai_passthrough, preserving the real exception/Timeout classes so the
    module's own exception handling still works."""
    return MagicMock(
        Client=client_factory,
        Timeout=httpx.Timeout,
        HTTPError=httpx.HTTPError,
        TimeoutException=httpx.TimeoutException,
        ConnectError=httpx.ConnectError,
    )


def test_is_openai_passthrough_eligible_true_for_openai_model() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    with patch.object(openai_passthrough, "OPENAI_GATEWAY_PASSTHROUGH_ENABLED", True):
        assert (
            is_openai_passthrough_eligible(provider, provider.model_configurations[0])
            is True
        )


def test_is_openai_passthrough_eligible_false_for_anthropic_provider() -> None:
    provider = _provider(1, "anthropic", [_model("claude-sonnet-4-6")])
    with patch.object(openai_passthrough, "OPENAI_GATEWAY_PASSTHROUGH_ENABLED", True):
        assert (
            is_openai_passthrough_eligible(provider, provider.model_configurations[0])
            is False
        )


def test_is_openai_passthrough_eligible_false_when_kill_switch_off() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    with patch.object(openai_passthrough, "OPENAI_GATEWAY_PASSTHROUGH_ENABLED", False):
        assert (
            is_openai_passthrough_eligible(provider, provider.model_configurations[0])
            is False
        )


def test_is_openai_passthrough_eligible_false_for_openai_compatible_model() -> None:
    """provider.provider == 'openai' also covers self-hosted/OpenAI-compatible
    servers (vLLM, litellm-proxy) speaking the OpenAI wire shape but not
    registered in litellm's model map under the openai provider. Proves
    is_true_openai_model, not a bare string compare, gates eligibility."""
    provider = _provider(1, "openai", [_model("my-custom-vllm-model")])
    with patch.object(openai_passthrough, "OPENAI_GATEWAY_PASSTHROUGH_ENABLED", True):
        assert (
            is_openai_passthrough_eligible(provider, provider.model_configurations[0])
            is False
        )


def test_is_openai_passthrough_eligible_true_for_litellm_proxy_real_openai_model() -> (
    None
):
    provider = _provider(1, "litellm_proxy", [_model("gpt-4o")])
    with patch.object(openai_passthrough, "OPENAI_GATEWAY_PASSTHROUGH_ENABLED", True):
        assert (
            is_openai_passthrough_eligible(provider, provider.model_configurations[0])
            is True
        )


def test_is_openai_passthrough_eligible_false_for_azure() -> None:
    """Azure is explicitly excluded from v1 passthrough: its Responses API has
    a different auth/URL shape (api-key header, api-version query param,
    deployment-scoped URL) that this module's Bearer-auth /v1/responses
    construction does not fit."""
    provider = _provider(1, "azure", [_model("gpt-4o")])
    with patch.object(openai_passthrough, "OPENAI_GATEWAY_PASSTHROUGH_ENABLED", True):
        assert (
            is_openai_passthrough_eligible(provider, provider.model_configurations[0])
            is False
        )


def test_base_url_defaults_to_openai_when_api_base_unset() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    provider.api_base = None

    assert _base_url(provider) == "https://api.openai.com"
    assert _responses_url(provider) == "https://api.openai.com/v1/responses"


def test_base_url_strips_trailing_v1_without_slash() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    provider.api_base = "https://api.openai.com/v1"

    assert _base_url(provider) == "https://api.openai.com"
    assert _responses_url(provider) == "https://api.openai.com/v1/responses"


def test_base_url_strips_trailing_v1_with_slash() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    provider.api_base = "https://api.openai.com/v1/"

    assert _base_url(provider) == "https://api.openai.com"
    assert _responses_url(provider) == "https://api.openai.com/v1/responses"


def test_base_url_leaves_proxy_base_without_v1_unchanged() -> None:
    provider = _provider(1, "litellm_proxy", [_model("gpt-4o")])
    provider.api_base = "http://localhost:4000"

    assert _base_url(provider) == "http://localhost:4000"
    assert _responses_url(provider) == "http://localhost:4000/v1/responses"


def test_base_url_does_not_over_strip_path_not_ending_in_v1() -> None:
    """A base whose path legitimately ends in something other than /v1 (e.g.
    a deployment-scoped or versioned path) must be left alone; only an exact
    trailing "/v1" segment is stripped."""
    provider = _provider(1, "litellm_proxy", [_model("gpt-4o")])
    provider.api_base = "https://gateway.example.com/openai/v1beta"

    assert _base_url(provider) == "https://gateway.example.com/openai/v1beta"
    assert (
        _responses_url(provider)
        == "https://gateway.example.com/openai/v1beta/v1/responses"
    )


def _responses_request(**overrides: Any) -> ResponsesRequest:
    defaults: dict[str, Any] = {
        "model": "1/gpt-5-mini",
        "input": [{"role": "user", "content": "hi"}],
    }
    defaults.update(overrides)
    return ResponsesRequest.model_validate(defaults)


def test_build_upstream_request_swaps_model_name() -> None:
    request = _responses_request()

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["model"] == "gpt-5-mini"


def test_build_upstream_request_forces_store_false_even_when_client_sends_true() -> (
    None
):
    request = _responses_request(store=True)

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["store"] is False


def test_build_upstream_request_forces_store_false_when_client_omits_it() -> None:
    request = _responses_request()

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["store"] is False


@pytest.mark.parametrize("stream_flag", [True, False])
def test_build_upstream_request_sets_stream_explicitly(stream_flag: bool) -> None:
    request = _responses_request(stream=stream_flag)

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", stream_flag)

    assert body["stream"] is stream_flag


def test_build_upstream_request_overwrites_user_safety_identifier_and_prompt_cache_key() -> (
    None
):
    request = _responses_request(
        user="client-supplied-user",
        safety_identifier="client-supplied-safety",
        prompt_cache_key="client-supplied-cache-key",
    )

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    expected_hash = hashlib.sha256(b"user-1").hexdigest()
    assert body["user"] == expected_hash
    assert body["safety_identifier"] == expected_hash
    assert body["prompt_cache_key"] == expected_hash
    assert body["user"] != "client-supplied-user"
    assert body["safety_identifier"] != "client-supplied-safety"
    assert body["prompt_cache_key"] != "client-supplied-cache-key"


def test_build_upstream_request_rejects_previous_response_id() -> None:
    request = _responses_request(previous_response_id="resp_abc123")

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.NOT_IMPLEMENTED
    assert "previous_response_id" in str(exc_info.value.detail)


def test_build_upstream_request_rejects_conversation() -> None:
    request = _responses_request(conversation="conv_abc123")

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.NOT_IMPLEMENTED
    assert "conversation" in str(exc_info.value.detail)


def test_build_upstream_request_rejects_background() -> None:
    request = _responses_request(background=True)

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.NOT_IMPLEMENTED
    assert "background" in str(exc_info.value.detail)


def test_build_upstream_request_rejects_mcp_tool() -> None:
    request = _responses_request(
        tools=[{"type": "mcp", "server_url": "https://evil.example"}]
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT
    assert "mcp" in str(exc_info.value.detail)


def test_build_upstream_request_rejects_file_search_tool() -> None:
    request = _responses_request(
        tools=[{"type": "file_search", "vector_store_ids": ["vs_1"]}]
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_build_upstream_request_rejects_code_interpreter_with_string_container() -> (
    None
):
    request = _responses_request(
        tools=[{"type": "code_interpreter", "container": "cntr_abc"}]
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_build_upstream_request_rejects_code_interpreter_container_file_ids() -> None:
    request = _responses_request(
        tools=[
            {
                "type": "code_interpreter",
                "container": {"type": "auto", "file_ids": ["file-123"]},
            }
        ]
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_build_upstream_request_allows_code_interpreter_with_auto_container() -> None:
    request = _responses_request(
        tools=[{"type": "code_interpreter", "container": {"type": "auto"}}]
    )

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["tools"] == [
        {"type": "code_interpreter", "container": {"type": "auto"}}
    ]


def test_build_upstream_request_rejects_input_file_with_file_id() -> None:
    request = _responses_request(
        input=[
            {
                "role": "user",
                "content": [{"type": "input_file", "file_id": "file-123"}],
            }
        ]
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_build_upstream_request_rejects_input_image_with_file_id() -> None:
    request = _responses_request(
        input=[
            {
                "role": "user",
                "content": [{"type": "input_image", "file_id": "file-456"}],
            }
        ]
    )

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_build_upstream_request_allows_input_file_with_inline_base64_data() -> None:
    request = _responses_request(
        input=[
            {
                "role": "user",
                "content": [
                    {
                        "type": "input_file",
                        "filename": "doc.pdf",
                        "file_data": "base64-encoded-content",
                    }
                ],
            }
        ]
    )

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["input"][0]["content"][0]["file_data"] == "base64-encoded-content"


def test_build_upstream_request_allows_input_image_with_url() -> None:
    request = _responses_request(
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_image", "image_url": "https://example.com/x.png"}
                ],
            }
        ]
    )

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["input"][0]["content"][0]["image_url"] == "https://example.com/x.png"


def test_build_upstream_request_rejects_top_level_prompt() -> None:
    request = _responses_request(prompt={"id": "pmpt_123"})

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert exc_info.value.error_code is OnyxErrorCode.INVALID_INPUT


def test_build_upstream_request_forwards_hosted_tool_and_include_verbatim() -> None:
    request = _responses_request(
        tools=[{"type": "web_search"}],
        include=["reasoning.encrypted_content"],
    )

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["tools"] == [{"type": "web_search"}]
    assert body["include"] == ["reasoning.encrypted_content"]


def test_build_upstream_request_forwards_unknown_future_fields() -> None:
    request = _responses_request(
        future_field={"anything": True},
        truncation="auto",
    )

    body = _build_upstream_request(request, "gpt-5-mini", "user-1", True)

    assert body["future_field"] == {"anything": True}
    assert body["truncation"] == "auto"


def test_build_upstream_headers_only_authorization_and_content_type() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])

    with patch.object(openai_passthrough, "build_llm_extra_headers", return_value={}):
        headers = _build_upstream_headers(provider)

    assert headers == {
        "Authorization": f"Bearer {provider.api_key}",
        "Content-Type": "application/json",
    }


def test_build_upstream_headers_merges_server_configured_extra_headers() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    with patch.object(
        openai_passthrough,
        "build_llm_extra_headers",
        return_value={"x-proxy-auth": "secret", "Authorization": "must-lose"},
    ):
        headers = _build_upstream_headers(provider)

    assert headers["x-proxy-auth"] == "secret"
    assert headers["Authorization"] == f"Bearer {provider.api_key}"


def test_build_upstream_headers_rejects_provider_without_api_key() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    provider.api_key = None

    with pytest.raises(OnyxError) as exc_info:
        _build_upstream_headers(provider)

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY


def test_usage_from_openai_wire_is_direct_mapping_no_addition() -> None:
    """The highest-risk copy-paste regression: OpenAI's input_tokens is
    already cache-inclusive, unlike Anthropic's, so prompt_tokens must equal
    input_tokens with nothing added back."""
    wire_usage = {
        "input_tokens": 100,
        "input_tokens_details": {"cached_tokens": 30},
        "output_tokens": 42,
        "total_tokens": 142,
    }

    usage = _usage_from_openai_wire(wire_usage)

    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 42
    assert usage.total_tokens == 142
    assert usage.cache_read_input_tokens == 30
    assert usage.cache_creation_input_tokens == 0


def test_usage_from_openai_wire_falls_back_to_input_plus_output_when_total_missing() -> (
    None
):
    wire_usage = {"input_tokens": 100, "output_tokens": 42}

    usage = _usage_from_openai_wire(wire_usage)

    assert usage.total_tokens == 142


def test_usage_from_openai_wire_missing_keys_default_zero() -> None:
    usage = _usage_from_openai_wire({})

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0
    assert usage.cache_read_input_tokens == 0
    assert usage.cache_creation_input_tokens == 0


def test_usage_from_openai_wire_tolerates_none_values() -> None:
    usage = _usage_from_openai_wire(
        {
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
            "input_tokens_details": None,
        }
    )

    assert usage.prompt_tokens == 0
    assert usage.completion_tokens == 0
    assert usage.total_tokens == 0
    assert usage.cache_read_input_tokens == 0


def test_reasoning_tokens_extracted_when_present() -> None:
    usage = {"output_tokens_details": {"reasoning_tokens": 17}}

    assert _reasoning_tokens(usage) == 17


def test_reasoning_tokens_none_when_absent() -> None:
    assert _reasoning_tokens({}) is None


@pytest.mark.parametrize("status_code", [400, 404, 413, 429])
def test_non_streaming_error_response_forwards_body_verbatim(status_code: int) -> None:
    body = {"error": {"type": "invalid_request_error", "message": "bad"}}
    response = httpx.Response(status_code=status_code, json=body)

    result = _non_streaming_error_response(response)

    assert isinstance(result, JSONResponse)
    assert result.status_code == status_code
    assert json.loads(bytes(result.body)) == body


@pytest.mark.parametrize("status_code", [401, 403, 500, 503])
def test_non_streaming_error_response_sanitizes_other_statuses(
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


def test_non_streaming_error_response_wraps_non_json_400_body() -> None:
    response = httpx.Response(status_code=400, content=b"not json")

    result = _non_streaming_error_response(response)

    payload = json.loads(bytes(result.body))
    assert result.status_code == 400
    assert "not json" in payload["error"]["message"]


def test_error_type_and_message_non_json_bytes() -> None:
    error_type, message = _error_type_and_message(b"not json at all")

    assert error_type == "api_error"
    assert message == "Upstream returned a non-JSON error."


def test_error_type_and_message_error_field_is_a_string() -> None:
    body = json.dumps({"error": "just a string"}).encode()

    error_type, message = _error_type_and_message(body)

    assert error_type == "api_error"
    assert message == "Upstream error."


def test_error_type_and_message_well_formed_type_and_message() -> None:
    body = json.dumps(
        {"error": {"type": "rate_limit_exceeded", "message": "quota exceeded"}}
    ).encode()

    error_type, message = _error_type_and_message(body)

    assert error_type == "rate_limit_exceeded"
    assert message == "quota exceeded"


class _FakePostClient:
    def __init__(
        self, response: httpx.Response | None = None, exc: Exception | None = None
    ) -> None:
        self._response = response
        self._exc = exc

    def __enter__(self) -> "_FakePostClient":
        return self

    def __exit__(self, *exc_info: object) -> None:
        pass

    def post(self, *args: object, **kwargs: object) -> httpx.Response:
        del args, kwargs
        if self._exc is not None:
            raise self._exc
        assert self._response is not None
        return self._response


def _non_streaming_run(
    upstream_response: httpx.Response | None = None,
    *,
    exc: Exception | None = None,
    llm_generation_span_patch: Any = None,
    llm: Any = None,
) -> JSONResponse:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    model_config = provider.model_configurations[0]
    span_patch = llm_generation_span_patch or (lambda *a, **k: nullcontext())  # noqa: ARG005

    with (
        patch.object(
            openai_passthrough,
            "httpx",
            _fake_httpx_module(
                MagicMock(return_value=_FakePostClient(upstream_response, exc))
            ),
        ),
        patch.object(
            openai_passthrough, "llm_from_provider", return_value=llm or _openai_llm()
        ),
        patch.object(openai_passthrough, "llm_generation_span", span_patch),
    ):
        result = handle_openai_responses_passthrough(
            request=_responses_request(stream=False),
            provider=provider,
            model_config=model_config,
            flow=LLMFlow.CRAFT_LLM_GENERATION,
            user=MagicMock(id="user-1"),
        )
        assert isinstance(result, JSONResponse)
        return result


def test_handle_openai_passthrough_non_streaming_forwards_400_body_verbatim() -> None:
    error_body = {"error": {"type": "invalid_request_error", "message": "bad"}}
    fake_response = httpx.Response(400, json=error_body)

    result = _non_streaming_run(fake_response)

    assert result.status_code == 400
    assert json.loads(bytes(result.body)) == error_body


def test_handle_openai_passthrough_non_streaming_sanitizes_401() -> None:
    fake_response = httpx.Response(401, json={"error": {"message": "invalid key xyz"}})

    with pytest.raises(OnyxError) as exc_info:
        _non_streaming_run(fake_response)

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY
    assert "invalid key xyz" not in str(exc_info.value.detail)


def test_handle_openai_passthrough_non_streaming_sanitizes_500() -> None:
    fake_response = httpx.Response(500, json={"error": {"message": "boom"}})

    with pytest.raises(OnyxError) as exc_info:
        _non_streaming_run(fake_response)

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY


def test_handle_openai_passthrough_non_streaming_timeout_raises_timeout_message() -> (
    None
):
    with pytest.raises(OnyxError) as exc_info:
        _non_streaming_run(exc=httpx.TimeoutException("timed out"))

    assert "did not respond in time" in exc_info.value.detail


_UPSTREAM_RESPONSE_BODY: dict[str, Any] = {
    "id": "resp_upstream_abc123",
    "object": "response",
    "model": "gpt-5-mini",
    "output": [
        {
            "type": "message",
            "id": "msg_1",
            "status": "completed",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "hi there", "annotations": []}],
        }
    ],
    "usage": {
        "input_tokens": 100,
        "input_tokens_details": {"cached_tokens": 30},
        "output_tokens": 42,
        "total_tokens": 142,
    },
}


def test_handle_openai_passthrough_non_streaming_forwards_200_body_verbatim() -> None:
    fake_response = httpx.Response(200, json=_UPSTREAM_RESPONSE_BODY)

    result = _non_streaming_run(fake_response)

    assert result.status_code == 200
    payload = json.loads(bytes(result.body))
    assert payload == _UPSTREAM_RESPONSE_BODY
    assert payload["id"] == "resp_upstream_abc123"


def test_handle_openai_passthrough_non_streaming_sanitizes_malformed_200() -> None:
    fake_response = httpx.Response(200, content=b"not json")

    with pytest.raises(OnyxError) as exc_info:
        _non_streaming_run(fake_response)

    assert exc_info.value.error_code is OnyxErrorCode.BAD_GATEWAY
    assert exc_info.value.detail == _SANITIZED_ERROR


def test_handle_openai_passthrough_non_streaming_records_usage() -> None:
    fake_response = httpx.Response(200, json=_UPSTREAM_RESPONSE_BODY)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    with patch.object(openai_passthrough, "record_llm_span_output") as record_output:
        _non_streaming_run(fake_response, llm_generation_span_patch=_span_ctx)

    record_output.assert_called_once()
    usage = record_output.call_args.kwargs["usage"]
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 42


def test_handle_openai_passthrough_non_streaming_tracks_cost_once() -> None:
    fake_response = httpx.Response(200, json=_UPSTREAM_RESPONSE_BODY)
    llm = _real_openai_litellm_llm()

    with patch.object(llm, "_track_llm_cost") as track_cost:
        _non_streaming_run(fake_response, llm=llm)

    track_cost.assert_called_once()
    usage = track_cost.call_args.args[0]
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 42


_SSE_EVENTS: list[dict[str, Any]] = [
    {"type": "response.created", "response": {"id": "resp_1"}},
    {
        "type": "response.output_text.delta",
        "item_id": "msg_1",
        "delta": "hi there",
    },
    {
        "type": "response.completed",
        "response": {
            "id": "resp_1",
            "usage": {
                "input_tokens": 100,
                "input_tokens_details": {"cached_tokens": 30},
                "output_tokens": 42,
                "total_tokens": 142,
                "output_tokens_details": {"reasoning_tokens": 5},
            },
        },
    },
]


def _sse_lines(events: list[dict[str, Any]]) -> list[str]:
    lines: list[str] = []
    for event in events:
        lines.append(f"data: {json.dumps(event)}")
        lines.append("")
    return lines


def _expected_sse_text(events: list[dict[str, Any]]) -> str:
    return "".join(f"data: {json.dumps(event)}\n\n" for event in events)


class _FakeStreamResponse:
    def __init__(
        self,
        status_code: int,
        lines: list[str],
        content: bytes = b"",
        stream_error: Exception | None = None,
    ) -> None:
        self.status_code = status_code
        self._lines = lines
        self.content = content
        self.stream_error = stream_error
        self.closed = False

    def iter_lines(self) -> Iterator[str]:
        yield from self._lines
        if self.stream_error is not None:
            raise self.stream_error

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
    "url": "https://api.openai.com/v1/responses",
    "headers": {"Authorization": "Bearer k"},
    "body": {"model": "gpt-5-mini"},
    "flow": LLMFlow.CRAFT_LLM_GENERATION,
    "input_messages": [{"role": "user", "content": "hi"}],
    "tools": None,
    "model": "gpt-5-mini",
}


def _run_passthrough_stream(
    response: _FakeStreamResponse,
    *,
    llm_generation_span_patch: Any = None,
    llm: Any = None,
) -> tuple[list[str], _FakeHttpxClient]:
    fake_client = _FakeHttpxClient(response)
    span_patch = llm_generation_span_patch or (lambda *a, **k: nullcontext())  # noqa: ARG005
    with (
        patch.object(
            openai_passthrough,
            "httpx",
            _fake_httpx_module(MagicMock(return_value=fake_client)),
        ),
        patch.object(openai_passthrough, "llm_generation_span", span_patch),
    ):
        frames = list(
            stream_bridge._run_bridged_stream(
                _openai_passthrough_stream_worker,
                {**_STREAM_WORKER_KWARGS, "llm": llm or _openai_llm()},
            )
        )
    return frames, fake_client


def test_passthrough_stream_forwards_frames_byte_identical() -> None:
    lines = _sse_lines(_SSE_EVENTS)
    response = _FakeStreamResponse(200, lines)

    frames, _ = _run_passthrough_stream(response)

    assert "".join(frames) == _expected_sse_text(_SSE_EVENTS)


def test_passthrough_stream_forwards_malformed_data_line_verbatim() -> None:
    lines = ["data: not json at all", ""]
    response = _FakeStreamResponse(200, lines)

    frames, _ = _run_passthrough_stream(response)

    assert "".join(frames) == "data: not json at all\n\n"


def test_passthrough_stream_records_usage_once_from_terminal_event() -> None:
    lines = _sse_lines(_SSE_EVENTS)
    response = _FakeStreamResponse(200, lines)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    with patch.object(stream_bridge, "record_llm_span_output") as record_output:
        _run_passthrough_stream(response, llm_generation_span_patch=_span_ctx)

    record_output.assert_called_once()
    usage = record_output.call_args.kwargs["usage"]
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 42


def test_passthrough_stream_accumulates_output_text_deltas_into_span_output() -> None:
    delta_events = [
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "delta": "hi ",
        },
        {
            "type": "response.output_text.delta",
            "item_id": "msg_1",
            "delta": "there",
        },
        {"type": "response.completed", "response": {"id": "resp_1"}},
    ]
    lines = _sse_lines(delta_events)
    response = _FakeStreamResponse(200, lines)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    with patch.object(stream_bridge, "record_llm_span_output") as record_output:
        _run_passthrough_stream(response, llm_generation_span_patch=_span_ctx)

    record_output.assert_called_once()
    assert record_output.call_args.kwargs["output"] == "hi there"


def test_passthrough_stream_tracks_cost_once_via_terminal_event() -> None:
    lines = _sse_lines(_SSE_EVENTS)
    response = _FakeStreamResponse(200, lines)
    llm = _real_openai_litellm_llm()

    with patch.object(llm, "_track_llm_cost") as track_cost:
        _run_passthrough_stream(response, llm=llm)

    track_cost.assert_called_once()
    usage = track_cost.call_args.args[0]
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 42


def test_passthrough_stream_response_incomplete_still_records_usage_for_cost() -> None:
    """response.incomplete (e.g. max_output_tokens truncation) still bills
    real tokens; usage must not be dropped just because the terminal event
    isn't response.completed, or the caller is undercharged."""
    incomplete_event = {
        "type": "response.incomplete",
        "response": {
            "error": {"message": "max_output_tokens reached"},
            "usage": {
                "input_tokens": 100,
                "output_tokens": 42,
                "total_tokens": 142,
            },
        },
    }
    lines = _sse_lines([incomplete_event])
    response = _FakeStreamResponse(200, lines)
    llm = _real_openai_litellm_llm()

    with patch.object(llm, "_track_llm_cost") as track_cost:
        _run_passthrough_stream(response, llm=llm)

    track_cost.assert_called_once()
    usage = track_cost.call_args.args[0]
    assert usage.prompt_tokens == 100
    assert usage.completion_tokens == 42


@pytest.mark.parametrize("status_code", [401, 500])
def test_passthrough_stream_sanitizes_non_forwardable_statuses(
    status_code: int,
) -> None:
    error_body = json.dumps(
        {"error": {"type": "authentication_error", "message": "leaked key xyz"}}
    ).encode()
    response = _FakeStreamResponse(status_code, [], content=error_body)

    frames, _ = _run_passthrough_stream(response)

    assert len(frames) == 1
    data = json.loads(frames[0][len("data: ") : -2])
    assert data["response"]["error"]["code"] == "server_error"
    assert data["response"]["error"]["message"] == _SANITIZED_ERROR
    assert "leaked key xyz" not in "".join(frames)


def test_passthrough_stream_forwards_429_type_and_message_verbatim() -> None:
    error_body = json.dumps(
        {"error": {"type": "rate_limit_exceeded", "message": "quota exceeded"}}
    ).encode()
    response = _FakeStreamResponse(429, [], content=error_body)

    frames, _ = _run_passthrough_stream(response)

    assert len(frames) == 1
    data = json.loads(frames[0][len("data: ") : -2])
    assert data["response"]["error"]["code"] == "rate_limit_exceeded"
    assert data["response"]["error"]["message"] == "quota exceeded"


def test_passthrough_stream_response_failed_records_span_error_and_forwards_verbatim() -> (
    None
):
    failed_event = {
        "type": "response.failed",
        "response": {"error": {"message": "the model produced invalid output"}},
    }
    lines = _sse_lines([failed_event])
    response = _FakeStreamResponse(200, lines)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    frames, _ = _run_passthrough_stream(response, llm_generation_span_patch=_span_ctx)

    assert "".join(frames) == _expected_sse_text([failed_event])
    mock_span.set_error.assert_called_once()


def test_passthrough_stream_response_incomplete_records_span_error() -> None:
    incomplete_event = {
        "type": "response.incomplete",
        "response": {"error": {"message": "max_output_tokens reached"}},
    }
    lines = _sse_lines([incomplete_event])
    response = _FakeStreamResponse(200, lines)
    mock_span = MagicMock()

    @contextmanager
    def _span_ctx(*args: object, **kwargs: object):
        del args, kwargs
        yield mock_span

    _run_passthrough_stream(response, llm_generation_span_patch=_span_ctx)

    mock_span.set_error.assert_called_once()


def test_passthrough_stream_upstream_error_emits_single_error_frame() -> None:
    error_body = json.dumps(
        {"error": {"type": "invalid_request_error", "message": "bad request"}}
    ).encode()
    response = _FakeStreamResponse(400, [], content=error_body)

    frames, _ = _run_passthrough_stream(response)

    assert len(frames) == 1
    data = json.loads(frames[0][len("data: ") : -2])
    assert data["type"] == "response.failed"
    assert data["response"]["error"]["message"] == "bad request"
    assert data["response"]["status"] == "failed"
    assert data["response"]["model"] == "gpt-5-mini"
    assert data["response"]["output"] == []
    assert data["sequence_number"] == 0


def test_passthrough_stream_transport_error_continues_response_identity() -> None:
    created_event = {
        "type": "response.created",
        "sequence_number": 7,
        "response": {
            "id": "resp_upstream",
            "created_at": 123,
        },
    }
    response = _FakeStreamResponse(
        200,
        _sse_lines([created_event]),
        stream_error=httpx.ReadError("stream failed"),
    )

    frames, _ = _run_passthrough_stream(response)

    assert json.loads(frames[0][len("data: ") : -2]) == created_event
    failure = json.loads(frames[1][len("data: ") : -2])
    assert failure["response"]["id"] == "resp_upstream"
    assert failure["response"]["created_at"] == 123
    assert failure["sequence_number"] == 8


def test_passthrough_stream_closes_exitstack_resources() -> None:
    lines = _sse_lines(_SSE_EVENTS)
    response = _FakeStreamResponse(200, lines)

    _frames, fake_client = _run_passthrough_stream(response)

    assert fake_client.closed is True
    assert response.closed is True


def _responses_endpoint_request() -> ResponsesRequest:
    return ResponsesRequest(
        model="1/gpt-5-mini", input=[{"role": "user", "content": "hi"}]
    )


def test_gateway_responses_routes_to_passthrough_when_eligible() -> None:
    provider = _provider(1, "openai", [_model("gpt-5-mini")])
    model_config = provider.model_configurations[0]
    request = _responses_endpoint_request()
    passthrough_response = JSONResponse(content={"id": "resp_1"})

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
            return_value=(provider, model_config),
        ),
        patch.object(gateway_api, "is_openai_passthrough_eligible", return_value=True),
        patch.object(
            gateway_api,
            "handle_openai_responses_passthrough",
            return_value=passthrough_response,
        ) as handle_passthrough,
        patch.object(gateway_api, "handle_responses_request") as handle_translation,
    ):
        result = gateway_api.gateway_responses(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(),
        )

    assert result is passthrough_response
    handle_passthrough.assert_called_once()
    assert handle_passthrough.call_args.kwargs["provider"] is provider
    assert handle_passthrough.call_args.kwargs["model_config"] is model_config
    handle_translation.assert_not_called()


def test_gateway_responses_uses_translation_path_when_not_eligible() -> None:
    provider = _provider(1, "anthropic", [_model("claude-sonnet-4-6")])
    model_config = provider.model_configurations[0]
    request = _responses_endpoint_request()

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
            return_value=(provider, model_config),
        ),
        patch.object(gateway_api, "is_openai_passthrough_eligible", return_value=False),
        patch.object(
            gateway_api, "handle_openai_responses_passthrough"
        ) as handle_passthrough,
        patch.object(gateway_api, "handle_responses_request") as handle_translation,
    ):
        handle_translation.return_value.to_wire.return_value = {"id": "resp_1"}
        gateway_api.gateway_responses(
            request=request,
            http_request=MagicMock(spec=Request),
            user=MagicMock(),
            db_session=MagicMock(),
        )

    handle_passthrough.assert_not_called()
    handle_translation.assert_called_once()
