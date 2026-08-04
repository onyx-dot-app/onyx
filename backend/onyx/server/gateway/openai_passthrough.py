"""Proxies ``/v1/responses`` to OpenAI over httpx rather than LiteLLM's
Responses bridge, which rebuilds the body from a decomposed parameter list and
drops the unknown fields this passthrough exists to forward.
"""

import hashlib
import json
import queue
import threading
import time
import uuid
from contextlib import ExitStack
from typing import Any

import httpx
from fastapi.responses import JSONResponse, StreamingResponse

from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.llm.model_capabilities import is_true_openai_model
from onyx.llm.model_response import Usage
from onyx.llm.multi_llm import LitellmLLM
from onyx.server.gateway.configs import (
    OPENAI_GATEWAY_PASSTHROUGH_ENABLED,
    OPENAI_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS,
    OPENAI_PASSTHROUGH_READ_TIMEOUT_SECONDS,
)
from onyx.server.gateway.models import (
    ResponsesErrorCode,
    ResponsesFailedEvent,
    ResponsesObjectPayload,
    ResponsesRequest,
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

# 401/403 describe OUR credential, not the caller's request, so they are
# sanitized rather than added here.
_FORWARDABLE_STATUSES = {400, 404, 413, 429}

_SANITIZED_ERROR = "The upstream LLM request failed."
_TIMEOUT_ERROR = "The selected model did not respond in time."

_NO_STORAGE_MESSAGE = (
    "The Onyx gateway does not store responses; send the full "
    "conversation in `input` instead of `{field}`."
)

# OpenAI Responses API `tools[].type` wire values, not identifiers we own.
_TOOL_TYPE_MCP = "mcp"
_TOOL_TYPE_FILE_SEARCH = "file_search"
_TOOL_TYPE_CODE_INTERPRETER = "code_interpreter"


def is_openai_passthrough_eligible(
    provider: LLMProviderView, model_config: ModelConfigurationView
) -> bool:
    # Azure needs api-key auth, an api-version param, and deployment-scoped
    # URLs, none of which this module's Bearer /v1/responses shape produces.
    if provider.provider == LlmProviderNames.AZURE:
        return False
    return OPENAI_GATEWAY_PASSTHROUGH_ENABLED and is_true_openai_model(
        provider.provider, model_config.name
    )


def _base_url(provider: LLMProviderView) -> str:
    base = (provider.api_base or "https://api.openai.com").rstrip("/")
    # Operator-supplied api_base conventionally already ends in /v1; strip it
    # so _responses_url does not double up.
    return base.removesuffix("/v1")


def _responses_url(provider: LLMProviderView) -> str:
    return _base_url(provider) + "/v1/responses"


def _timeout() -> httpx.Timeout:
    return httpx.Timeout(
        OPENAI_PASSTHROUGH_READ_TIMEOUT_SECONDS,
        connect=OPENAI_PASSTHROUGH_CONNECT_TIMEOUT_SECONDS,
    )


def _build_upstream_request(
    request: ResponsesRequest,
    model_name: str,
    user_id: str,
    stream: bool,
) -> dict[str, Any]:
    # exclude_unset + extra="allow" is what forwards unknown client fields
    # verbatim; dropping either silently degrades the passthrough.
    body = request.model_dump(exclude_unset=True)
    if request.previous_response_id is not None:
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            _NO_STORAGE_MESSAGE.format(field="previous_response_id"),
        )
    if body.get("conversation") is not None:
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            _NO_STORAGE_MESSAGE.format(field="conversation"),
        )
    if body.get("background"):
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            "The Onyx gateway does not support `background` responses.",
        )
    for tool in body.get("tools") or []:
        if not isinstance(tool, dict):
            continue
        tool_type = tool.get("type")
        if tool_type == _TOOL_TYPE_MCP:
            # Would make OpenAI connect to a client-specified URL under our
            # account.
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "mcp tools are not supported by the Onyx gateway.",
            )
        if tool_type == _TOOL_TYPE_FILE_SEARCH:
            # Requires org-scoped vector_store_ids no gateway caller can
            # own; we do not proxy /v1/vector_stores.
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "file_search tools are not supported by the Onyx gateway.",
            )
        if tool_type == _TOOL_TYPE_CODE_INTERPRETER:
            container = tool.get("container")
            # A string container references an existing sandbox under our
            # shared org key, and an auto container's file_ids reference
            # org-scoped uploads; only a bare "auto" form is allowed.
            if isinstance(container, str) or (
                isinstance(container, dict) and container.get("file_ids")
            ):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "code_interpreter tools referencing an existing container "
                    "or uploaded files are not supported by the Onyx gateway.",
                )
    if isinstance(body.get("input"), list):
        for item in body["input"]:
            if not isinstance(item, dict):
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if (
                    isinstance(part, dict)
                    and part.get("type") in ("input_file", "input_image")
                    and part.get("file_id")
                ):
                    # References an uploaded file under our shared org key;
                    # we do not proxy /v1/files.
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "file_id references are not supported by the Onyx "
                        "gateway; send file content inline.",
                    )
    if body.get("prompt") is not None:
        # A stored prompt template reference, scoped to our shared org key.
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "prompt template references are not supported by the Onyx gateway.",
        )
    body["model"] = model_name
    body["stream"] = stream
    # OpenAI defaults this to true, which would persist state under our
    # shared key where any other gateway caller could read it back.
    body["store"] = False
    # Always overwrite: opaque provider-side abuse/cache attribution, never a
    # client-supplied identifier.
    hashed_user = hashlib.sha256(user_id.encode()).hexdigest()
    body["user"] = hashed_user
    body["safety_identifier"] = hashed_user
    body["prompt_cache_key"] = hashed_user
    return body


def _build_upstream_headers(provider: LLMProviderView) -> dict[str, str]:
    # Never forward inbound headers: OpenAI-Organization/OpenAI-Project would
    # select a billing scope in the caller's OpenAI account, not ours.
    if not provider.api_key:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "The selected provider has no credential configured.",
        )
    # Server-configured proxy/routing headers; the entries below must keep
    # winning on collision.
    headers = build_llm_extra_headers()
    headers.update(
        {
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
        }
    )
    return headers


def _usage_from_openai_wire(usage: dict[str, Any]) -> Usage:
    # input_tokens is already cache-inclusive, so cached tokens must not be
    # subtracted back out.
    input_tokens = usage.get("input_tokens") or 0
    output_tokens = usage.get("output_tokens") or 0
    total_tokens = usage.get("total_tokens") or (input_tokens + output_tokens)
    cache_read = (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
    return Usage(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        total_tokens=total_tokens,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=cache_read,
    )


def _reasoning_tokens(usage: dict[str, Any]) -> int | None:
    return (usage.get("output_tokens_details") or {}).get("reasoning_tokens")


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
            content = {"error": {"message": response.text[:2000]}}
        return JSONResponse(status_code=response.status_code, content=content)
    logger.warning(
        "OpenAI passthrough upstream error (sanitized): status=%s",
        response.status_code,
    )
    raise OnyxError(OnyxErrorCode.BAD_GATEWAY, _SANITIZED_ERROR)


def _gateway_trace(flow: LLMFlow, model: str) -> Trace:
    return trace("llm_gateway", metadata={"flow": flow.value, "model": model})


def handle_openai_responses_passthrough(
    request: ResponsesRequest,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
    user: User,
) -> JSONResponse | StreamingResponse:
    body = _build_upstream_request(
        request, model_config.name, str(user.id), request.stream
    )
    headers = _build_upstream_headers(provider)
    url = _responses_url(provider)
    # llm is built only for tracing config (model/provider metadata); the
    # actual call goes straight over httpx, never through llm.invoke/stream.
    llm = llm_from_provider(model_name=model_config.name, llm_provider=provider)

    if request.stream:
        return _sse_response(
            _openai_passthrough_stream_worker,
            {
                "url": url,
                "headers": headers,
                "body": body,
                "llm": llm,
                "flow": flow,
                "input_messages": request.input,
                "tools": request.tools,
                "model": request.model,
            },
        )

    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm, flow=flow, input_messages=request.input, tools=request.tools
        ) as span,
    ):
        try:
            with httpx.Client(timeout=_timeout()) as client:
                response = client.post(url, json=body, headers=headers)
        except httpx.TimeoutException as e:
            if span is not None:
                span.set_error({"message": f"{type(e).__name__}: {e}", "data": None})
            logger.warning(
                "OpenAI passthrough request timed out for model %s", request.model
            )
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, _TIMEOUT_ERROR) from e
        except httpx.HTTPError as e:
            if span is not None:
                span.set_error({"message": f"{type(e).__name__}: {e}", "data": None})
            # Exception repr carries the request URL, which for custom
            # api_base values can embed query credentials; log the type only.
            logger.warning(
                "OpenAI passthrough transport error for model %s: %s",
                request.model,
                type(e).__name__,
            )
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, _SANITIZED_ERROR) from e

        if response.status_code != 200:
            if span is not None:
                span.set_error(
                    {
                        "message": f"upstream status {response.status_code}",
                        "data": None,
                    }
                )
            return _non_streaming_error_response(response)

        try:
            response_body = response.json()
            if not isinstance(response_body, dict):
                raise ValueError("response body is not an object")
        except ValueError as e:
            if span is not None:
                span.set_error(
                    {
                        "message": f"malformed upstream response: {type(e).__name__}",
                        "data": None,
                    }
                )
            logger.warning(
                "OpenAI passthrough returned a malformed success response for model %s",
                request.model,
            )
            raise OnyxError(OnyxErrorCode.BAD_GATEWAY, _SANITIZED_ERROR) from e
        usage = response_body.get("usage")
        output_items = response_body.get("output") or []
        text = "\n\n".join(
            part.get("text", "")
            for item in output_items
            if isinstance(item, dict) and item.get("type") == "message"
            for part in item.get("content") or []
            if isinstance(part, dict) and part.get("type") == "output_text"
        )
        converted_usage = _usage_from_openai_wire(usage) if usage else None
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
            reasoning_tokens = _reasoning_tokens(usage) if usage else None
            if reasoning_tokens:
                # No Usage slot for reasoning-token pricing yet; surface it
                # in traces instead.
                span.span_data.model_config = {
                    **(span.span_data.model_config or {}),
                    "reasoning_tokens": reasoning_tokens,
                }

    return JSONResponse(content=response_body)


def _openai_passthrough_stream_worker(
    url: str,
    headers: dict[str, str],
    body: dict[str, Any],
    llm: LLM,
    flow: LLMFlow,
    input_messages: Any,
    tools: list[dict[str, Any]] | None,
    model: str,
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> None:
    response_id = f"resp_{uuid.uuid4().hex}"
    response_created_at = int(time.time())
    next_sequence_number = 0

    def emit_error(*, message: str, error_type: str) -> None:
        code: ResponsesErrorCode = (
            "rate_limit_exceeded"
            if error_type in ("rate_limit_error", "rate_limit_exceeded")
            else "server_error"
        )
        payload = {
            **ResponsesFailedEvent.create(
                ResponsesObjectPayload.failed(
                    response_id=response_id,
                    created_at=response_created_at,
                    model=model,
                    message=message,
                    code=code,
                )
            ).to_wire(),
            "sequence_number": next_sequence_number,
        }
        _put_stream_item(out, f"data: {json.dumps(payload)}\n\n", cancelled)

    # Runs on its own thread after the endpoint returned, so the trace must be
    # opened here or the generation span sees no active trace.
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
            label="openai passthrough stream",
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
            # A disconnected client only sets `cancelled`; without this
            # watchdog a blocking iter_lines() holds the thread and the
            # upstream request until the next SSE line or the read timeout.
            threading.Thread(
                target=lambda: (cancelled.wait(), stack.close()),
                name="openai-passthrough-cancel-watchdog",
                daemon=True,
            ).start()

            if response.status_code != 200:
                response.read()
                if response.status_code in _FORWARDABLE_STATUSES:
                    error_type, message = _error_type_and_message(response.content)
                else:
                    logger.warning(
                        "OpenAI passthrough upstream stream error (sanitized): "
                        "status=%s",
                        response.status_code,
                    )
                    error_type, message = "api_error", _SANITIZED_ERROR
                if span is not None:
                    span.set_error(
                        {
                            "message": f"upstream status {response.status_code}",
                            "data": None,
                        }
                    )
                emit_error(message=message, error_type=error_type)
                return

            frame_lines: list[str] = []
            frame_response_id: str | None = None
            frame_created_at: int | None = None
            frame_next_sequence: int | None = None
            for line in response.iter_lines():
                if cancelled.is_set():
                    break
                if line == "":
                    if frame_lines:
                        frame_text = "\n".join(frame_lines)
                        frame_lines = []
                        if not _put_stream_item(out, frame_text + "\n\n", cancelled):
                            break
                        if frame_response_id is not None:
                            response_id = frame_response_id
                        if frame_created_at is not None:
                            response_created_at = frame_created_at
                        if frame_next_sequence is not None:
                            next_sequence_number = frame_next_sequence
                        frame_response_id = None
                        frame_created_at = None
                        frame_next_sequence = None
                    continue
                frame_lines.append(line)
                if not line.startswith("data: "):
                    continue
                raw_data = line[len("data: ") :]
                try:
                    event = json.loads(raw_data)
                except json.JSONDecodeError:
                    logger.warning(
                        "OpenAI passthrough: unparsable SSE data line, "
                        "forwarding verbatim"
                    )
                    continue
                event_type = event.get("type")
                event_response = event.get("response")
                if isinstance(event_response, dict):
                    upstream_response_id = event_response.get("id")
                    if isinstance(upstream_response_id, str):
                        frame_response_id = upstream_response_id
                    upstream_created_at = event_response.get("created_at")
                    if isinstance(upstream_created_at, int):
                        frame_created_at = upstream_created_at
                upstream_sequence = event.get("sequence_number")
                if isinstance(upstream_sequence, int):
                    frame_next_sequence = upstream_sequence + 1
                if event_type == "response.output_text.delta":
                    delta_text = event.get("delta")
                    if isinstance(delta_text, str):
                        state.content.append(delta_text)
                elif event_type in (
                    "response.completed",
                    "response.failed",
                    "response.incomplete",
                ):
                    # incomplete/failed also bill real tokens, so usage
                    # cannot be read from completed alone.
                    response_obj = event.get("response") or {}
                    usage = response_obj.get("usage")
                    if isinstance(usage, dict):
                        state.usage = _usage_from_openai_wire(usage)
                        reasoning_tokens = _reasoning_tokens(usage)
                        if reasoning_tokens and span is not None:
                            span.span_data.model_config = {
                                **(span.span_data.model_config or {}),
                                "reasoning_tokens": reasoning_tokens,
                            }
                    if event_type in ("response.failed", "response.incomplete"):
                        error = response_obj.get("error")
                        if error and span is not None:
                            span.set_error({"message": str(error), "data": None})
            if frame_lines and not cancelled.is_set():
                if _put_stream_item(out, "\n".join(frame_lines) + "\n\n", cancelled):
                    if frame_response_id is not None:
                        response_id = frame_response_id
                    if frame_created_at is not None:
                        response_created_at = frame_created_at
                    if frame_next_sequence is not None:
                        next_sequence_number = frame_next_sequence
            # Managed-key cost accounting normally happens inside
            # LLM.invoke/stream, which this path bypasses.
            if state.usage is not None and isinstance(llm, LitellmLLM):
                llm._track_llm_cost(state.usage)
