"""Native Anthropic passthrough for the gateway's Messages API.

When the resolved provider is Anthropic itself, the OpenAI-shaped translation
path (api.py) cannot carry server-side tools, thinking-block signatures,
``pause_turn``, or fine-grained streaming. This module proxies the request
nearly verbatim to Anthropic over httpx instead of going through LiteLLM's
anthropic_messages surface, which reconstructs the body from a fixed param
list and drops unknown fields.
"""

import hashlib
import json
import queue
import threading
from contextlib import ExitStack
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import httpx
from fastapi import Request
from fastapi.responses import JSONResponse, StreamingResponse

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import Usage
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.gateway.configs import (
    ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED,
    ANTHROPIC_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS,
    ANTHROPIC_PASSTHROUGH_READ_TIMEOUT_SECONDS,
)
from onyx.server.gateway.models import (
    AnthropicCountTokensRequest,
    AnthropicErrorEvent,
    AnthropicMessagesRequest,
)
from onyx.server.gateway.stream_bridge import (
    _put_stream_item,
    _sse_response,
    _stream_worker_guard,
    _StreamAccumulator,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace
from onyx.tracing.llm_utils import llm_generation_span, record_llm_span_output
from onyx.utils.headers import build_llm_extra_headers
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Forwarded verbatim to the client: these describe the request/upstream state,
# not our credential. Everything else (401/403 describe OUR credential; other
# 5xx are opaque) is sanitized.
_FORWARDABLE_STATUSES = {400, 404, 413, 429, 529}

# Client-supplied anthropic-beta values we forward; anything else is silently
# dropped rather than passed through to a provider we don't control.
_ANTHROPIC_BETA_PREFIX_ALLOWLIST = (
    "interleaved-thinking",
    "fine-grained-tool-streaming",
    "prompt-caching",
    "extended-cache-ttl",
    "token-efficient-tools",
    "context-management",
    "output-",
    "claude-code",
)

_SANITIZED_ERROR = ("The upstream LLM request failed.", "api_error")
_TIMEOUT_ERROR = ("The selected model did not respond in time.", "api_error")


class AnthropicPassthroughUnavailable(Exception):
    """Raised when the passthrough transport itself fails (connect/read
    timeout, DNS, etc.), distinct from the upstream returning an error
    response. Callers may degrade to a local approximation instead of
    failing the request outright (see the count_tokens fallback)."""


def is_anthropic_passthrough_eligible(provider: LLMProviderView) -> bool:
    # v1 is direct-Anthropic only; bedrock/vertex are phase 2.
    return ANTHROPIC_GATEWAY_PASSTHROUGH_ENABLED and provider.provider == "anthropic"


def _append_api_path(provider: LLMProviderView, suffix: str) -> str:
    parsed = urlsplit(provider.api_base or "https://api.anthropic.com")
    path = parsed.path.rstrip("/").removesuffix("/v1") + suffix
    return urlunsplit(parsed._replace(path=path))


def _messages_url(provider: LLMProviderView) -> str:
    return _append_api_path(provider, "/v1/messages")


def _count_tokens_url(provider: LLMProviderView) -> str:
    return _append_api_path(provider, "/v1/messages/count_tokens")


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(
        ANTHROPIC_PASSTHROUGH_READ_TIMEOUT_SECONDS,
        connect=ANTHROPIC_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS,
    )


def _build_upstream_request(
    request: AnthropicMessagesRequest | AnthropicCountTokensRequest,
    model_name: str,
    user_id: str,
    stream: bool | None,
) -> dict[str, Any]:
    # exclude_unset + extra="allow" means tolerated-unknown client fields
    # forward verbatim.
    body = request.model_dump(exclude_unset=True)
    if "mcp_servers" in body:
        # mcp_servers instructs Anthropic's own servers to connect to
        # arbitrary URLs under our account; refuse rather than forward.
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "mcp_servers is not supported by the Onyx gateway.",
        )
    body["model"] = model_name
    if stream is not None:
        # Always overwrite: opaque provider-side abuse attribution, never a
        # client-supplied identifier.
        body["metadata"] = {"user_id": hashlib.sha256(user_id.encode()).hexdigest()}
        body["stream"] = stream
    else:
        # count_tokens rejects metadata/stream/max_tokens outright.
        body.pop("metadata", None)
        body.pop("stream", None)
        body.pop("max_tokens", None)
    return body


def _build_upstream_headers(
    provider: LLMProviderView, http_request: Request
) -> dict[str, str]:
    # Fresh dict only — never copy client headers wholesale; the inbound
    # Authorization header is an Onyx PAT, not an Anthropic key.
    if not provider.api_key:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "The selected provider has no credential configured.",
        )
    # Server-configured proxy/routing headers (LITELLM_EXTRA_HEADERS) that the
    # translation path sends on every provider call; the passthrough's own
    # entries below always win on collision.
    headers = build_llm_extra_headers()
    headers.update(
        {
            "x-api-key": provider.api_key,
            "content-type": "application/json",
            "anthropic-version": http_request.headers.get(
                "anthropic-version", "2023-06-01"
            ),
        }
    )
    beta_raw = http_request.headers.get("anthropic-beta")
    if beta_raw:
        entries = [entry.strip() for entry in beta_raw.split(",") if entry.strip()]
        allowed = [e for e in entries if e.startswith(_ANTHROPIC_BETA_PREFIX_ALLOWLIST)]
        dropped = [e for e in entries if e not in allowed]
        if dropped:
            logger.debug(
                "Anthropic passthrough dropped anthropic-beta entries: %s", dropped
            )
        if allowed:
            headers["anthropic-beta"] = ",".join(allowed)
    return headers


def _usage_from_anthropic_wire(usage: dict[str, Any]) -> Usage:
    # Exact inverse of AnthropicUsagePayload.from_usage: the ledger assumes
    # LiteLLM-normalized accounting, where prompt_tokens INCLUDES cache
    # tokens, while Anthropic's own input_tokens excludes both.
    input_tokens = usage.get("input_tokens") or 0
    cache_read = usage.get("cache_read_input_tokens") or 0
    cache_creation = usage.get("cache_creation_input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    prompt_tokens = input_tokens + cache_read + cache_creation
    return Usage(
        prompt_tokens=prompt_tokens,
        completion_tokens=output_tokens,
        total_tokens=prompt_tokens + output_tokens,
        cache_creation_input_tokens=cache_creation,
        cache_read_input_tokens=cache_read,
    )


def _error_type_and_message(body: bytes) -> tuple[str, str]:
    try:
        parsed = json.loads(body)
    except (json.JSONDecodeError, TypeError, UnicodeDecodeError):
        return "api_error", "Upstream returned a non-JSON error."
    error = parsed.get("error") if isinstance(parsed, dict) else None
    if isinstance(error, dict):
        return (
            str(error.get("type") or "api_error"),
            str(error.get("message") or "Upstream error."),
        )
    return "api_error", "Upstream error."


def _non_streaming_error_response(response: httpx.Response) -> JSONResponse:
    if response.status_code in _FORWARDABLE_STATUSES:
        try:
            content = response.json()
        except ValueError:
            content = {"error": {"type": "api_error", "message": response.text[:2000]}}
        return JSONResponse(status_code=response.status_code, content=content)
    logger.warning(
        "Anthropic passthrough upstream error (sanitized): status=%s",
        response.status_code,
    )
    message, _ = _SANITIZED_ERROR
    raise OnyxError(OnyxErrorCode.BAD_GATEWAY, message)


def _streaming_error_event(status_code: int, body: bytes) -> AnthropicErrorEvent:
    if status_code in _FORWARDABLE_STATUSES:
        error_type, message = _error_type_and_message(body)
        return AnthropicErrorEvent.create(message=message, error_type=error_type)
    logger.warning(
        "Anthropic passthrough upstream stream error (sanitized): status=%s",
        status_code,
    )
    message, error_type = _SANITIZED_ERROR
    return AnthropicErrorEvent.create(message=message, error_type=error_type)


def _gateway_trace(flow: LLMFlow, model: str) -> Trace:
    return trace("llm_gateway", metadata={"flow": flow.value, "model": model})


def handle_anthropic_passthrough(
    request: AnthropicMessagesRequest,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
    http_request: Request,
    user: User,
) -> JSONResponse | StreamingResponse:
    body = _build_upstream_request(
        request, model_config.name, str(user.id), request.stream
    )
    headers = _build_upstream_headers(provider, http_request)
    url = _messages_url(provider)
    # llm is built only for tracing config (model/provider metadata); the
    # actual call goes straight over httpx, never through llm.invoke/stream.
    llm = llm_from_provider(model_name=model_config.name, llm_provider=provider)

    if request.stream:
        return _sse_response(
            _passthrough_stream_worker,
            {
                "url": url,
                "headers": headers,
                "body": body,
                "llm": llm,
                "flow": flow,
                "input_messages": request.messages,
                "tools": request.tools,
                "model": request.model,
            },
        )

    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm, flow=flow, input_messages=request.messages, tools=request.tools
        ) as span,
    ):
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as e:
            if span is not None:
                span.set_error({"message": f"{type(e).__name__}: {e}", "data": None})
            logger.warning(
                "Anthropic passthrough request timed out for model %s", request.model
            )
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, _TIMEOUT_ERROR[0]) from e
        except httpx.HTTPError as e:
            if span is not None:
                span.set_error({"message": f"{type(e).__name__}: {e}", "data": None})
            # Exception repr carries the request URL, which for custom
            # api_base values can embed query credentials; log the type only.
            logger.warning(
                "Anthropic passthrough transport error for model %s: %s",
                request.model,
                type(e).__name__,
            )
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, _SANITIZED_ERROR[0]) from e

        if response.status_code != 200:
            if span is not None:
                span.set_error(
                    {
                        "message": f"upstream status {response.status_code}",
                        "data": None,
                    }
                )
            return _non_streaming_error_response(response)

        response_body = response.json()
        usage = response_body.get("usage")
        content_blocks = response_body.get("content") or []
        text = "\n\n".join(
            block.get("text", "")
            for block in content_blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        converted_usage = _usage_from_anthropic_wire(usage) if usage else None
        if converted_usage is not None and isinstance(llm, LitellmLLM):
            # Managed-key cost accounting normally happens inside
            # LLM.invoke/stream, which this path bypasses.
            llm._track_llm_cost(converted_usage)
        if span is not None:
            record_llm_span_output(
                span,
                output=text or None,
                usage=converted_usage,
                reasoning=None,
                tool_calls=None,
            )
            server_tool_use = (usage or {}).get("server_tool_use")
            if server_tool_use:
                # No dedicated Usage slot for per-search pricing (that's the
                # cost-tracking project); attach it to model_config so it is
                # at least visible in traces.
                span.span_data.model_config = {
                    **(span.span_data.model_config or {}),
                    "server_tool_use": server_tool_use,
                }

    # Forward Anthropic's own response verbatim, including its own id.
    return JSONResponse(content=response_body)


def _passthrough_stream_worker(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    llm: LLM,
    flow: LLMFlow,
    input_messages: list[dict[str, Any]],
    tools: list[dict[str, Any]] | None,
    model: str,
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> None:
    def emit(event: AnthropicErrorEvent) -> bool:
        payload = event.to_wire()
        return _put_stream_item(
            out, f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n", cancelled
        )

    def emit_error(*, message: str, error_type: str) -> None:
        emit(AnthropicErrorEvent.create(message=message, error_type=error_type))

    # Runs on its own thread after the endpoint has returned the
    # StreamingResponse, so the trace must be opened here rather than in the
    # endpoint for the generation span to see an active trace.
    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm, flow=flow, input_messages=input_messages, tools=tools
        ) as span,
    ):
        state = _StreamAccumulator()
        with _stream_worker_guard(
            span,
            model,
            state,
            label="anthropic passthrough stream",
            emit_error=emit_error,
            out=out,
            cancelled=cancelled,
        ):
            # ExitStack becomes state.upstream so the guard's finally can
            # close both the response and the client via one .close() call.
            stack = ExitStack()
            state.upstream = stack
            client = stack.enter_context(httpx.Client(timeout=_timeout()))
            response = stack.enter_context(
                client.stream("POST", url, json=body, headers=headers)
            )
            # A disconnected client only sets `cancelled`; a blocking
            # iter_lines() read would otherwise hold the worker thread and the
            # upstream request until the next SSE line or the read timeout.
            # Closing the stack from a watchdog raises in the reader
            # immediately; ExitStack.close is idempotent w.r.t. the guard's
            # own teardown.
            threading.Thread(
                target=lambda: (cancelled.wait(), stack.close()),
                name="anthropic-passthrough-cancel-watchdog",
                daemon=True,
            ).start()

            if response.status_code != 200:
                response.read()
                error_type, message = _error_type_and_message(response.content)
                if response.status_code not in _FORWARDABLE_STATUSES:
                    logger.warning(
                        "Anthropic passthrough upstream stream error (sanitized): "
                        "status=%s",
                        response.status_code,
                    )
                    message, error_type = _SANITIZED_ERROR
                if span is not None:
                    span.set_error(
                        {
                            "message": f"upstream status {response.status_code}",
                            "data": None,
                        }
                    )
                emit_error(message=message, error_type=error_type)
                return

            usage_parts: dict[str, Any] = {}
            frame_lines: list[str] = []
            for line in response.iter_lines():
                if cancelled.is_set():
                    break
                if line == "":
                    if frame_lines:
                        frame_text = "\n".join(frame_lines)
                        frame_lines = []
                        if not _put_stream_item(out, frame_text + "\n\n", cancelled):
                            break
                    continue
                frame_lines.append(line)
                if not line.startswith("data: "):
                    continue
                raw_data = line[len("data: ") :]
                try:
                    event = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(
                        "Anthropic passthrough: unparsable SSE data line, "
                        "forwarding verbatim"
                    )
                    continue
                event_type = event.get("type")
                if event_type == "content_block_delta":
                    delta = event.get("delta") or {}
                    if delta.get("type") == "text_delta":
                        state.content.append(delta.get("text", ""))
                elif event_type == "message_start":
                    message_usage = (event.get("message") or {}).get("usage")
                    if isinstance(message_usage, dict):
                        usage_parts.update(message_usage)
                elif event_type == "message_delta":
                    delta_usage = event.get("usage")
                    if isinstance(delta_usage, dict):
                        server_tool_use = delta_usage.get("server_tool_use")
                        if server_tool_use and span is not None:
                            # No dedicated Usage slot for per-search pricing
                            # (that's the cost-tracking project); attach it to
                            # model_config so it is at least visible in traces.
                            span.span_data.model_config = {
                                **(span.span_data.model_config or {}),
                                "server_tool_use": server_tool_use,
                            }
                        usage_parts.update(delta_usage)
                if event_type in ("message_start", "message_delta") and usage_parts:
                    state.usage = _usage_from_anthropic_wire(usage_parts)
            if frame_lines and not cancelled.is_set():
                _put_stream_item(out, "\n".join(frame_lines) + "\n\n", cancelled)
            # Managed-key cost accounting normally happens inside
            # LLM.invoke/stream, which this path bypasses.
            if state.usage is not None and isinstance(llm, LitellmLLM):
                llm._track_llm_cost(state.usage)


def handle_anthropic_count_tokens_passthrough(
    request: AnthropicCountTokensRequest,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    http_request: Request,
    user: User,
) -> JSONResponse:
    body = _build_upstream_request(request, model_config.name, str(user.id), None)
    headers = _build_upstream_headers(provider, http_request)
    url = _count_tokens_url(provider)
    try:
        with httpx.Client(timeout=_timeout()) as client:
            response = client.post(url, json=body, headers=headers)
    except httpx.HTTPError as e:
        # Transport failure, not an upstream error response: let the caller
        # degrade to its local token estimate instead of failing the request.
        logger.warning(
            "Anthropic passthrough count_tokens transport error for model %s: %s",
            request.model,
            type(e).__name__,
        )
        raise AnthropicPassthroughUnavailable() from e

    if response.status_code != 200:
        return _non_streaming_error_response(response)
    return JSONResponse(content=response.json())
