import json
import queue
import threading
from collections.abc import Iterator
from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    ModelResponse,
    ModelResponseStream,
    Usage,
)
from onyx.llm.models import ChatCompletionMessage, ReasoningEffort, ToolChoiceOptions
from onyx.llm.multi_llm import LLMRateLimitError, LLMTimeoutError
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.tracing_wrap import _finalize_tool_calls, _merge_tool_call_delta
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
from onyx.server.gateway.consumers import ProviderFetcher, resolve_gateway_consumer
from onyx.server.gateway.models import ChatCompletionRequest
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import (
    llm_generation_span,
    record_llm_response,
    record_llm_span_output,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

logger = setup_logger()

router = APIRouter(prefix=GATEWAY_PATH_PREFIX)

_MESSAGES_ADAPTER: TypeAdapter[list[ChatCompletionMessage]] = TypeAdapter(
    list[ChatCompletionMessage]
)


def resolve_gateway_model(
    db_session: Session,
    user: User,
    requested_model: str,
    fetch_provider: ProviderFetcher,
) -> tuple[LLMProviderView, ModelConfigurationView]:
    not_found_error = OnyxError(
        OnyxErrorCode.NOT_FOUND,
        f"Model {requested_model!r} is not available through the Onyx gateway.",
    )

    provider_id_text, separator, model_name = requested_model.partition("/")
    try:
        provider_id = int(provider_id_text)
    except ValueError:
        provider_id = -1
    if not separator or not model_name or provider_id < 0:
        logger.warning(
            "Gateway received malformed model identifier %r "
            "(expected '<provider_id>/<model_name>')",
            requested_model,
        )
        raise not_found_error

    provider = fetch_provider(db_session, user, provider_id)
    if provider is None:
        raise not_found_error
    model = next(
        (
            model
            for model in provider.model_configurations
            if model.is_visible and model.name == model_name
        ),
        None,
    )
    if model is None:
        raise not_found_error
    return provider, model


def _parse_reasoning_effort(
    raw: str | None, supports_reasoning: bool, default: ReasoningEffort
) -> ReasoningEffort:
    if raw is None:
        return default if supports_reasoning else ReasoningEffort.AUTO
    try:
        return ReasoningEffort(raw.lower())
    except ValueError:
        return ReasoningEffort.AUTO


def _prepare_messages(
    llm: LLM, raw_messages: list[dict[str, Any]]
) -> list[ChatCompletionMessage]:
    try:
        messages = _MESSAGES_ADAPTER.validate_python(raw_messages)
    except ValidationError as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Invalid messages: {e.error_count()} errors"
        ) from e
    if not messages:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "messages must not be empty")
    cacheable_prefix = messages[:-1] or None
    processed_messages, _ = process_with_prompt_cache(
        llm_config=llm.config,
        cacheable_prefix=cacheable_prefix,
        suffix=messages[-1:],
        continuation=False,
        with_metadata=False,
    )
    if not isinstance(processed_messages, list):
        raise RuntimeError("LLM gateway message processing returned non-list input")
    return processed_messages


def _parse_tool_choice(raw: Any) -> ToolChoiceOptions | None:
    if isinstance(raw, str):
        try:
            return ToolChoiceOptions(raw)
        except ValueError:
            return None
    # Named-function tool_choice objects are not supported; fall back to auto.
    return None


def _created_epoch(created: str) -> int:
    try:
        return int(float(created))
    except (TypeError, ValueError):
        return 0


def _usage_payload(usage: Usage) -> dict[str, Any]:
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
        "prompt_tokens_details": {"cached_tokens": usage.cache_read_input_tokens},
    }


def _completion_payload(response: ModelResponse, model: str) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": response.choice.message.role,
        "content": response.choice.message.content,
    }
    if response.choice.message.reasoning_content:
        message["reasoning_content"] = response.choice.message.reasoning_content
    if response.choice.message.tool_calls:
        message["tool_calls"] = [
            tc.model_dump() for tc in response.choice.message.tool_calls
        ]
    payload: dict[str, Any] = {
        "id": response.id,
        "object": "chat.completion",
        "created": _created_epoch(response.created),
        "model": model,
        "choices": [
            {
                "index": response.choice.index,
                "message": message,
                "finish_reason": response.choice.finish_reason,
            }
        ],
    }
    if response.usage is not None:
        payload["usage"] = _usage_payload(response.usage)
    return payload


def _chunk_payload(
    chunk: ModelResponseStream, model: str, include_role: bool
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if include_role:
        delta["role"] = "assistant"
    if chunk.choice.delta.content is not None:
        delta["content"] = chunk.choice.delta.content
    if chunk.choice.delta.reasoning_content is not None:
        delta["reasoning_content"] = chunk.choice.delta.reasoning_content
    if chunk.choice.delta.tool_calls:
        delta["tool_calls"] = [
            tc.model_dump(exclude_none=True) for tc in chunk.choice.delta.tool_calls
        ]
    payload: dict[str, Any] = {
        "id": chunk.id,
        "object": "chat.completion.chunk",
        "created": _created_epoch(chunk.created),
        "model": model,
        "choices": [
            {
                "index": chunk.choice.index,
                "delta": delta,
                "finish_reason": chunk.choice.finish_reason,
            }
        ],
    }
    if chunk.usage is not None:
        payload["usage"] = _usage_payload(chunk.usage)
    return payload


_STREAM_END = object()


def _put_stream_item(
    out: "queue.Queue[Any]", item: Any, cancelled: threading.Event
) -> bool:
    while not cancelled.is_set():
        try:
            out.put(item, timeout=0.1)
            return True
        except queue.Full:
            continue
    return False


def _emit_stream_error(
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
    *,
    message: str,
    error_type: str,
) -> None:
    error_payload = {"error": {"message": message, "type": error_type}}
    _put_stream_item(out, f"data: {json.dumps(error_payload)}\n\n", cancelled)
    _put_stream_item(out, "data: [DONE]\n\n", cancelled)


def _stream_worker(
    llm: LLM,
    flow: LLMFlow,
    messages: list[ChatCompletionMessage],
    tools: list[dict[str, Any]] | None,
    tool_choice: ToolChoiceOptions | None,
    structured_response_format: dict[str, Any] | None,
    max_tokens: int | None,
    reasoning_effort: ReasoningEffort,
    model: str,
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> None:
    with llm_generation_span(
        llm, flow=flow, input_messages=messages, tools=tools
    ) as span:
        accumulated_content: list[str] = []
        accumulated_reasoning: list[str] = []
        final_usage: Usage | None = None
        tool_call_buffer: dict[int, ChatCompletionDeltaToolCall] = {}
        sent_role = False
        upstream: Iterator[ModelResponseStream] | None = None
        try:
            upstream = llm.stream(
                prompt=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_response_format=structured_response_format,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            for chunk in upstream:
                if cancelled.is_set():
                    break
                if chunk.usage:
                    final_usage = chunk.usage
                if chunk.choice.delta.content:
                    accumulated_content.append(chunk.choice.delta.content)
                if chunk.choice.delta.reasoning_content:
                    accumulated_reasoning.append(chunk.choice.delta.reasoning_content)
                for delta_tc in chunk.choice.delta.tool_calls:
                    _merge_tool_call_delta(tool_call_buffer, delta_tc)
                payload = _chunk_payload(chunk, model, include_role=not sent_role)
                sent_role = True
                if not _put_stream_item(
                    out, f"data: {json.dumps(payload)}\n\n", cancelled
                ):
                    break
            else:
                _put_stream_item(out, "data: [DONE]\n\n", cancelled)
        except LLMRateLimitError as exc:
            if span is not None:
                span.set_error(
                    {"message": f"{type(exc).__name__}: {exc}", "data": None}
                )
            logger.exception("LLM gateway stream rate limited for model %s", model)
            # The HTTP status is already sent; surface the failure in-band the
            # way OpenAI-compatible servers do so the client fails the turn.
            _emit_stream_error(
                out,
                cancelled,
                message="The selected model is temporarily rate limited.",
                error_type="rate_limit_error",
            )
        except LLMTimeoutError as exc:
            if span is not None:
                span.set_error(
                    {"message": f"{type(exc).__name__}: {exc}", "data": None}
                )
            logger.exception("LLM gateway stream timed out for model %s", model)
            _emit_stream_error(
                out,
                cancelled,
                message="The selected model did not respond in time.",
                error_type="timeout_error",
            )
        except Exception as exc:
            if span is not None:
                span.set_error(
                    {"message": f"{type(exc).__name__}: {exc}", "data": None}
                )
            logger.exception("LLM gateway stream failed for model %s", model)
            _emit_stream_error(
                out,
                cancelled,
                message="The upstream LLM request failed.",
                error_type="upstream_error",
            )
        finally:
            try:
                close = getattr(upstream, "close", None)
                if callable(close):
                    close()
            except Exception:
                logger.exception(
                    "LLM gateway stream cleanup failed for model %s", model
                )
            try:
                if span is not None:
                    record_llm_span_output(
                        span,
                        output="".join(accumulated_content) or None,
                        usage=final_usage,
                        reasoning="".join(accumulated_reasoning) or None,
                        tool_calls=_finalize_tool_calls(tool_call_buffer),
                    )
            except Exception:
                logger.exception("LLM gateway span cleanup failed for model %s", model)
            finally:
                _put_stream_item(out, _STREAM_END, cancelled)


def _stream_sse(
    llm: LLM,
    flow: LLMFlow,
    messages: list[ChatCompletionMessage],
    tools: list[dict[str, Any]] | None,
    tool_choice: ToolChoiceOptions | None,
    structured_response_format: dict[str, Any] | None,
    max_tokens: int | None,
    reasoning_effort: ReasoningEffort,
    model: str,
) -> Iterator[str]:
    """Bridge the LLM stream through a queue so the whole consumption —
    including the generation span's ContextVar enter/exit — happens on ONE
    thread. Yielding directly from a sync generator breaks under Starlette,
    which resumes the generator on varying threadpool threads (ContextVar
    tokens can't be reset across contexts)."""
    out: "queue.Queue[Any]" = queue.Queue(maxsize=256)
    cancelled = threading.Event()
    worker = start_thread_with_context(
        _stream_worker,
        name="llm-gateway-stream",
        daemon=True,
        kwargs={
            "llm": llm,
            "flow": flow,
            "messages": messages,
            "tools": tools,
            "tool_choice": tool_choice,
            "structured_response_format": structured_response_format,
            "max_tokens": max_tokens,
            "reasoning_effort": reasoning_effort,
            "model": model,
            "out": out,
            "cancelled": cancelled,
        },
    )
    try:
        while True:
            try:
                item = out.get(timeout=0.5)
            except queue.Empty:
                if not worker.is_alive():
                    return
                continue
            if item is _STREAM_END:
                return
            yield item
    finally:
        cancelled.set()


def handle_chat_completion(
    request: ChatCompletionRequest,
    db_session: Session,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
    default_reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
) -> Any:
    llm = llm_from_provider(
        model_name=model_config.name,
        llm_provider=provider,
        temperature=request.temperature,
    )
    messages = _prepare_messages(llm, request.messages)
    tool_choice = _parse_tool_choice(request.tool_choice)
    reasoning_effort = _parse_reasoning_effort(
        request.reasoning_effort,
        model_config.supports_reasoning,
        default_reasoning_effort,
    )
    max_tokens = request.max_completion_tokens or request.max_tokens
    db_session.close()

    if request.stream:
        return StreamingResponse(
            _stream_sse(
                llm=llm,
                flow=flow,
                messages=messages,
                tools=request.tools,
                tool_choice=tool_choice,
                structured_response_format=request.response_format,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
                model=request.model,
            ),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    with llm_generation_span(
        llm,
        flow=flow,
        input_messages=messages,
        tools=request.tools,
    ) as span:
        try:
            response = llm.invoke(
                prompt=messages,
                tools=request.tools,
                tool_choice=tool_choice,
                structured_response_format=request.response_format,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
        except LLMRateLimitError as e:
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "The selected model is temporarily rate limited.",
            ) from e
        except LLMTimeoutError as e:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The selected model did not respond in time.",
            ) from e
        except Exception as e:
            if span is not None:
                span.set_error({"message": f"{type(e).__name__}: {e}", "data": None})
            logger.exception("LLM gateway invoke failed for model %s", request.model)
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The upstream LLM request failed.",
            ) from e
        if span is not None:
            record_llm_response(span, response)

    return _completion_payload(response, request.model)


@router.post("/v1/chat/completions")
def gateway_chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    user: User = Depends(require_permission(Permission.READ_SEARCH)),
    db_session: Session = Depends(get_session),
) -> Any:
    consumer = resolve_gateway_consumer(http_request, user)
    provider, model_config = resolve_gateway_model(
        db_session, user, request.model, fetch_provider=consumer.fetch_provider
    )
    return handle_chat_completion(
        request=request,
        db_session=db_session,
        provider=provider,
        model_config=model_config,
        flow=consumer.flow,
        default_reasoning_effort=consumer.default_reasoning_effort,
    )
