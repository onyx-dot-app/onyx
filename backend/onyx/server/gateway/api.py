import json
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing
from typing import Any, cast

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import TypeAdapter, ValidationError
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.llm import (
    fetch_accessible_llm_provider_by_id,
    fetch_all_accessible_llm_providers,
)
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.llm.factory import llm_from_provider
from onyx.llm.interfaces import LLM
from onyx.llm.model_response import (
    ChatCompletionDeltaToolCall,
    ChatCompletionMessageToolCall,
    ModelResponseStream,
    Usage,
)
from onyx.llm.models import (
    AssistantMessage,
    ChatCompletionMessage,
    ReasoningEffort,
    TextContentPart,
    ToolCall,
    ToolChoiceOptions,
    UserMessage,
)
from onyx.llm.multi_llm import LLMRateLimitError, LLMTimeoutError
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.tracing_wrap import _finalize_tool_calls, _merge_tool_call_delta
from onyx.server.features.build.craft_gateway import is_gateway_request
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
from onyx.server.gateway.model_catalog import build_gateway_model_catalog
from onyx.server.gateway.models import (
    ChatCompletionChunk,
    ChatCompletionRequest,
    ChatCompletionResponse,
    ModelListResponse,
    ResponsesFunctionCallItem,
    ResponsesMessageItem,
    ResponsesObjectPayload,
    ResponsesOutputItem,
    ResponsesOutputTextPart,
    ResponsesRequest,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace
from onyx.tracing.llm_utils import (
    llm_generation_span,
    record_llm_response,
    record_llm_span_output,
)
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import start_thread_with_context

logger = setup_logger()

router = APIRouter(prefix=GATEWAY_PATH_PREFIX)

# Callers never supply the flow; the endpoint picks it and this mapping
# enforces the matching credential.
_FLOW_ACCESS_CHECKS: dict[LLMFlow, Callable[[Request, User], bool]] = {
    LLMFlow.CRAFT_LLM_GENERATION: is_gateway_request,
}


_MESSAGES_ADAPTER: TypeAdapter[list[ChatCompletionMessage]] = TypeAdapter(
    list[ChatCompletionMessage]
)


def _gateway_trace(flow: LLMFlow, model: str) -> Trace:
    return trace("llm_gateway", metadata={"flow": flow.value, "model": model})


def _authorize_gateway_request(http_request: Request, user: User) -> LLMFlow:
    flow = LLMFlow.CRAFT_LLM_GENERATION
    if not _FLOW_ACCESS_CHECKS[flow](http_request, user):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "This credential is not authorized to use the Onyx LLM gateway.",
        )
    return flow


def resolve_gateway_model(
    db_session: Session,
    user: User,
    requested_model: str,
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

    provider = fetch_accessible_llm_provider_by_id(db_session, user, provider_id)
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


def _parse_reasoning_effort(raw: str | None) -> ReasoningEffort:
    if raw is None:
        return ReasoningEffort.AUTO
    try:
        return ReasoningEffort(raw.lower())
    except ValueError:
        return ReasoningEffort.AUTO


def _drop_empty_text(message: ChatCompletionMessage) -> ChatCompletionMessage | None:
    """Remove empty/whitespace-only text from a message; returns None when the
    whole message carries no information. Clients routinely send ``content: ""``
    on assistant tool-call turns, which LiteLLM would rewrite into a visible
    "[System: Empty message content sanitised ...]" placeholder for Anthropic."""
    if isinstance(message, AssistantMessage):
        if isinstance(message.content, str) and not message.content.strip():
            message = message.model_copy(update={"content": None})
        if message.content is None and not message.tool_calls:
            return None
        return message
    if isinstance(message, UserMessage):
        if isinstance(message.content, str):
            return message if message.content.strip() else None
        parts = [
            part
            for part in message.content
            if not (isinstance(part, TextContentPart) and not part.text.strip())
        ]
        if not parts:
            return None
        if len(parts) != len(message.content):
            message = message.model_copy(update={"content": parts})
        return message
    return message


def _prepare_messages(
    llm: LLM, raw_messages: list[dict[str, Any]]
) -> list[ChatCompletionMessage]:
    try:
        messages = _MESSAGES_ADAPTER.validate_python(raw_messages)
    except ValidationError as e:
        # Shapes only: message content is user data the gateway does not persist.
        logger.warning(
            "LLM gateway rejected %d message(s): roles=%s errors=%s",
            len(raw_messages),
            [m.get("role") for m in raw_messages if isinstance(m, dict)],
            [(tuple(err["loc"][:4]), err["type"]) for err in e.errors()[:10]],
        )
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, f"Invalid messages: {e.error_count()} errors"
        ) from e
    messages = [
        message for message in map(_drop_empty_text, messages) if message is not None
    ]
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
    # Runs on its own thread after the endpoint has returned the
    # StreamingResponse, so the trace must be opened here rather than in the
    # endpoint for the generation span to see an active trace.
    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm, flow=flow, input_messages=messages, tools=tools
        ) as span,
    ):
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
                payload = ChatCompletionChunk.from_stream_chunk(
                    chunk, model, include_role=not sent_role
                )
                sent_role = True
                if not _put_stream_item(
                    out, f"data: {json.dumps(payload.to_wire())}\n\n", cancelled
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
    """Bridge the worker through a queue so the whole stream consumption —
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
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
) -> StreamingResponse | ChatCompletionResponse:
    llm = llm_from_provider(
        model_name=model_config.name,
        llm_provider=provider,
        temperature=request.temperature,
    )
    messages = _prepare_messages(llm, request.messages)
    tool_choice = _parse_tool_choice(request.tool_choice)
    reasoning_effort = _parse_reasoning_effort(request.reasoning_effort)
    max_tokens = request.max_completion_tokens or request.max_tokens

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

    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm,
            flow=flow,
            input_messages=messages,
            tools=request.tools,
        ) as span,
    ):
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

    return ChatCompletionResponse.from_model_response(response, request.model)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _flatten_text_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n\n".join(
            part.get("text", "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        )
    return ""


def _responses_input_to_raw_messages(request: ResponsesRequest) -> list[dict[str, Any]]:
    """LiteLLM's Responses->Chat bridge emits an OpenAI 'developer' role and
    list-of-parts system/developer content; our ChatCompletionMessage union has
    no developer role and SystemMessage.content is str-only, so collapse both."""
    from litellm.responses.litellm_completion_transformation.transformation import (
        LiteLLMCompletionResponsesConfig,
    )

    litellm_messages = (
        LiteLLMCompletionResponsesConfig.transform_responses_api_input_to_messages(
            input=cast(Any, request.input),
            responses_api_request=cast(Any, {"instructions": request.instructions}),
        )
    )
    raw: list[dict[str, Any]] = []
    for message in litellm_messages:
        message_dict: dict[str, Any] = dict(message)
        role = message_dict.get("role")
        if role in ("system", "developer"):
            raw.append(
                {
                    "role": "system",
                    "content": _flatten_text_content(message_dict.get("content")),
                }
            )
        elif role == "assistant" and isinstance(message_dict.get("content"), list):
            # AssistantMessage.content is str, but LiteLLM emits parts here.
            raw.append(
                {
                    **message_dict,
                    "content": _flatten_text_content(message_dict["content"]) or None,
                }
            )
        else:
            raw.append(message_dict)
    return raw


def _responses_tools(request: ResponsesRequest) -> list[dict[str, Any]] | None:
    from litellm.responses.litellm_completion_transformation.transformation import (
        LiteLLMCompletionResponsesConfig,
    )

    tools, _ = (
        LiteLLMCompletionResponsesConfig.transform_responses_api_tools_to_chat_completion_tools(
            cast(Any, request.tools)
        )
    )
    return cast(list[dict[str, Any]], tools) or None


def _function_call_item(
    tool_call: ToolCall | ChatCompletionMessageToolCall,
) -> ResponsesFunctionCallItem | None:
    # A nameless tool call has no valid function_call representation.
    name = tool_call.function.name
    if not name:
        return None
    return ResponsesFunctionCallItem.create(
        id=_new_id("fc"),
        call_id=tool_call.id,
        name=name,
        arguments=tool_call.function.arguments or "",
    )


def _build_responses_output_items(
    content: str | None,
    tool_calls: list[ToolCall] | list[ChatCompletionMessageToolCall] | None,
    message_item_id: str,
) -> list[ResponsesOutputItem]:
    items: list[ResponsesOutputItem] = []
    if content:
        items.append(
            ResponsesMessageItem.create(
                id=message_item_id,
                status="completed",
                content=[ResponsesOutputTextPart.create(content)],
            )
        )
    items.extend(
        item
        for item in (_function_call_item(tc) for tc in tool_calls or [])
        if item is not None
    )
    return items


def handle_responses_request(
    request: ResponsesRequest,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
) -> ResponsesObjectPayload:
    if request.stream:
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            "Streaming is not yet supported on the Responses API.",
        )
    llm = llm_from_provider(
        model_name=model_config.name,
        llm_provider=provider,
        temperature=request.temperature,
    )
    raw_messages = _responses_input_to_raw_messages(request)
    messages = _prepare_messages(llm, raw_messages)
    tools = _responses_tools(request)
    tool_choice = _parse_tool_choice(request.tool_choice)
    reasoning_effort = _parse_reasoning_effort(
        request.reasoning.get("effort") if request.reasoning else None
    )
    max_tokens = request.max_output_tokens
    response_id = _new_id("resp")
    created_at = int(time.time())

    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm,
            flow=flow,
            input_messages=messages,
            tools=tools,
        ) as span,
    ):
        try:
            response = llm.invoke(
                prompt=messages,
                tools=tools,
                tool_choice=tool_choice,
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
            logger.exception(
                "LLM gateway responses invoke failed for model %s", request.model
            )
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The upstream LLM request failed.",
            ) from e
        if span is not None:
            record_llm_response(span, response)

    return ResponsesObjectPayload.from_parts(
        response_id=response_id,
        created_at=created_at,
        model=request.model,
        status="completed",
        output=_build_responses_output_items(
            response.choice.message.content,
            response.choice.message.tool_calls,
            _new_id("msg"),
        ),
        usage=response.usage,
    )


@router.get("/v1/models")
def gateway_list_models(
    http_request: Request,
    user: User = Depends(require_permission(Permission.USE_LLM_GATEWAY)),
    db_session: Session = Depends(get_session),
) -> Response:
    _authorize_gateway_request(http_request, user)
    providers = fetch_all_accessible_llm_providers(db_session, user)
    catalog = build_gateway_model_catalog(providers)
    return JSONResponse(content=ModelListResponse.from_catalog(catalog).to_wire())


@router.post("/v1/chat/completions")
def gateway_chat_completions(
    request: ChatCompletionRequest,
    http_request: Request,
    user: User = Depends(require_permission(Permission.USE_LLM_GATEWAY)),
    db_session: Session = Depends(get_session),
) -> Response:
    flow = _authorize_gateway_request(http_request, user)
    check_token_rate_limits(user)
    with closing(db_session):
        provider, model_config = resolve_gateway_model(db_session, user, request.model)
    result = handle_chat_completion(
        request=request,
        provider=provider,
        model_config=model_config,
        flow=flow,
    )
    if isinstance(result, StreamingResponse):
        return result
    # Serialize explicitly: FastAPI's default model serialization would emit
    # unset fields as nulls, violating the wire contract's presence semantics.
    return JSONResponse(content=result.to_wire())


@router.post("/v1/responses")
def gateway_responses(
    request: ResponsesRequest,
    http_request: Request,
    user: User = Depends(require_permission(Permission.USE_LLM_GATEWAY)),
    db_session: Session = Depends(get_session),
) -> Response:
    flow = _authorize_gateway_request(http_request, user)
    check_token_rate_limits(user)
    with closing(db_session):
        provider, model_config = resolve_gateway_model(db_session, user, request.model)
    result = handle_responses_request(
        request=request,
        provider=provider,
        model_config=model_config,
        flow=flow,
    )
    return JSONResponse(content=result.to_wire())
