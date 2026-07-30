import json
import queue
import threading
import time
import uuid
from collections.abc import Callable, Iterator
from contextlib import closing, contextmanager
from functools import partial
from itertools import count
from typing import Any, Protocol, cast, runtime_checkable

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
    ResponsesCompletedEvent,
    ResponsesContentPartAddedEvent,
    ResponsesContentPartDoneEvent,
    ResponsesCreatedEvent,
    ResponsesErrorCode,
    ResponsesFailedEvent,
    ResponsesFunctionCallArgumentsDoneEvent,
    ResponsesFunctionCallItem,
    ResponsesMessageItem,
    ResponsesObjectPayload,
    ResponsesOutputItem,
    ResponsesOutputItemAddedEvent,
    ResponsesOutputItemDoneEvent,
    ResponsesOutputTextDeltaEvent,
    ResponsesOutputTextDoneEvent,
    ResponsesOutputTextPart,
    ResponsesRequest,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.spans import Span
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
    if raw is None:
        return None
    if isinstance(raw, str):
        try:
            return ToolChoiceOptions(raw)
        except ValueError as e:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Unsupported tool_choice {raw!r}; expected one of "
                f"{', '.join(option.value for option in ToolChoiceOptions)}.",
            ) from e
    # Silently downgrading to auto would let the model ignore a tool the caller
    # required, so refuse instead of guessing.
    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        "Named-function tool_choice is not supported by the Onyx gateway.",
    )


_STREAM_END = object()


@runtime_checkable
class _ClosableStream(Protocol):
    """LLM.stream is declared Iterator, which carries no close(); every real
    implementation is a generator, and an abandoned one must be closed so the
    provider connection is released."""

    def close(self) -> None: ...


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


class _StreamAccumulator:
    def __init__(self) -> None:
        self.content: list[str] = []
        self.reasoning: list[str] = []
        self.usage: Usage | None = None
        self.tool_call_buffer: dict[int, ChatCompletionDeltaToolCall] = {}
        self.upstream: Iterator[ModelResponseStream] | None = None

    def observe(self, chunk: ModelResponseStream) -> None:
        if chunk.usage:
            self.usage = chunk.usage
        if chunk.choice.delta.content:
            self.content.append(chunk.choice.delta.content)
        if chunk.choice.delta.reasoning_content:
            self.reasoning.append(chunk.choice.delta.reasoning_content)
        for delta_tc in chunk.choice.delta.tool_calls:
            _merge_tool_call_delta(self.tool_call_buffer, delta_tc)

    @property
    def text(self) -> str:
        return "".join(self.content)


_RATE_LIMIT_ERROR = (
    "The selected model is temporarily rate limited.",
    "rate_limit_error",
)
_TIMEOUT_ERROR = ("The selected model did not respond in time.", "timeout_error")
_UPSTREAM_ERROR = ("The upstream LLM request failed.", "upstream_error")


@contextmanager
def _stream_worker_guard(
    span: Span[GenerationSpanData] | None,
    model: str,
    state: _StreamAccumulator,
    *,
    label: str,
    emit_error: Callable[..., None],
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> Iterator[None]:
    """The HTTP status is already sent by the time a worker runs, so upstream
    failures surface in-band as a protocol error frame rather than raising."""
    try:
        yield
    except Exception as exc:
        if isinstance(exc, LLMRateLimitError):
            message, error_type = _RATE_LIMIT_ERROR
        elif isinstance(exc, LLMTimeoutError):
            message, error_type = _TIMEOUT_ERROR
        else:
            message, error_type = _UPSTREAM_ERROR
        if span is not None:
            span.set_error({"message": f"{type(exc).__name__}: {exc}", "data": None})
        logger.exception(
            "LLM gateway %s failed (%s) for model %s", label, error_type, model
        )
        emit_error(message=message, error_type=error_type)
    finally:
        try:
            if isinstance(state.upstream, _ClosableStream):
                state.upstream.close()
        except Exception:
            logger.exception("LLM gateway %s cleanup failed for model %s", label, model)
        try:
            if span is not None:
                record_llm_span_output(
                    span,
                    output=state.text or None,
                    usage=state.usage,
                    reasoning="".join(state.reasoning) or None,
                    tool_calls=_finalize_tool_calls(state.tool_call_buffer),
                )
        except Exception:
            logger.exception(
                "LLM gateway %s span cleanup failed for model %s", label, model
            )
        finally:
            _put_stream_item(out, _STREAM_END, cancelled)


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
        state = _StreamAccumulator()
        sent_role = False
        with _stream_worker_guard(
            span,
            model,
            state,
            label="stream",
            emit_error=partial(_emit_stream_error, out, cancelled),
            out=out,
            cancelled=cancelled,
        ):
            state.upstream = llm.stream(
                prompt=messages,
                tools=tools,
                tool_choice=tool_choice,
                structured_response_format=structured_response_format,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            for chunk in state.upstream:
                if cancelled.is_set():
                    break
                state.observe(chunk)
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


def _run_bridged_stream(
    worker: Callable[..., None], worker_kwargs: dict[str, Any]
) -> Iterator[str]:
    """Bridge a stream worker through a queue so the whole consumption —
    including the generation span's ContextVar enter/exit — happens on ONE
    thread. Yielding directly from a sync generator breaks under Starlette,
    which resumes the generator on varying threadpool threads (ContextVar
    tokens can't be reset across contexts)."""
    out: "queue.Queue[Any]" = queue.Queue(maxsize=256)
    cancelled = threading.Event()
    worker_thread = start_thread_with_context(
        worker,
        name="llm-gateway-stream",
        daemon=True,
        kwargs={**worker_kwargs, "out": out, "cancelled": cancelled},
    )
    try:
        while True:
            if worker_thread.is_alive():
                try:
                    item = out.get(timeout=0.5)
                except queue.Empty:
                    continue
            else:
                # Worker died before signalling: drain, or the stream truncates.
                try:
                    item = out.get_nowait()
                except queue.Empty:
                    return
            if item is _STREAM_END:
                return
            yield item
    finally:
        cancelled.set()


def _sse_response(
    worker: Callable[..., None], worker_kwargs: dict[str, Any]
) -> StreamingResponse:
    return StreamingResponse(
        _run_bridged_stream(worker, worker_kwargs),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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
        return _sse_response(
            _stream_worker,
            {
                "llm": llm,
                "flow": flow,
                "messages": messages,
                "tools": request.tools,
                "tool_choice": tool_choice,
                "structured_response_format": request.response_format,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
                "model": request.model,
            },
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
                content=[ResponsesOutputTextPart.create(text=content)],
            )
        )
    items.extend(
        item
        for item in (_function_call_item(tc) for tc in tool_calls or [])
        if item is not None
    )
    return items


def _responses_stream_worker(
    llm: LLM,
    flow: LLMFlow,
    messages: list[ChatCompletionMessage],
    tools: list[dict[str, Any]] | None,
    tool_choice: ToolChoiceOptions | None,
    max_tokens: int | None,
    reasoning_effort: ReasoningEffort,
    model: str,
    response_id: str,
    created_at: int,
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> None:
    sequence = count()

    def emit(event: Any) -> bool:
        # Stamped here rather than in the models so it always matches emission
        # order and no event can be built without one.
        payload = {**event.to_wire(), "sequence_number": next(sequence)}
        return _put_stream_item(out, f"data: {json.dumps(payload)}\n\n", cancelled)

    emit(
        ResponsesCreatedEvent.create(
            ResponsesObjectPayload.from_parts(
                response_id=response_id,
                created_at=created_at,
                model=model,
                status="in_progress",
                output=[],
            )
        )
    )
    message_item_id = _new_id("msg")
    state = _StreamAccumulator()
    text_item_open = False

    def close_text_item(status: str) -> ResponsesMessageItem:
        part = ResponsesOutputTextPart.create(text=state.text)
        item = ResponsesMessageItem.create(
            id=message_item_id, status=status, content=[part]
        )
        emit(
            ResponsesOutputTextDoneEvent.create(
                item_id=message_item_id, output_index=0, text=state.text
            )
        )
        emit(
            ResponsesContentPartDoneEvent.create(
                item_id=message_item_id, output_index=0, part=part
            )
        )
        emit(ResponsesOutputItemDoneEvent.create(output_index=0, item=item))
        return item

    def emit_error(*, message: str, error_type: str) -> None:
        code: ResponsesErrorCode = (
            "rate_limit_exceeded"
            if error_type == _RATE_LIMIT_ERROR[1]
            else "server_error"
        )
        if text_item_open:
            close_text_item("incomplete")
        emit(
            ResponsesFailedEvent.create(
                ResponsesObjectPayload.failed(
                    response_id=response_id,
                    created_at=created_at,
                    model=model,
                    message=message,
                    code=code,
                )
            )
        )

    # Runs on its own thread after the endpoint has returned the
    # StreamingResponse, so the trace must be opened here rather than in the
    # endpoint for the generation span to see an active trace.
    with (
        _gateway_trace(flow, llm.config.model_name),
        llm_generation_span(
            llm, flow=flow, input_messages=messages, tools=tools
        ) as span,
    ):
        with _stream_worker_guard(
            span,
            model,
            state,
            label="responses stream",
            emit_error=emit_error,
            out=out,
            cancelled=cancelled,
        ):
            state.upstream = llm.stream(
                prompt=messages,
                tools=tools,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
                reasoning_effort=reasoning_effort,
            )
            for chunk in state.upstream:
                if cancelled.is_set():
                    break
                state.observe(chunk)
                if not chunk.choice.delta.content:
                    continue
                if not text_item_open:
                    # Open the item before the first delta; Codex drops
                    # deltas for items it has not seen added.
                    if not emit(
                        ResponsesOutputItemAddedEvent.create(
                            output_index=0,
                            item=ResponsesMessageItem.create(
                                id=message_item_id, status="in_progress", content=[]
                            ),
                        )
                    ):
                        break
                    if not emit(
                        ResponsesContentPartAddedEvent.create(
                            item_id=message_item_id,
                            output_index=0,
                            part=ResponsesOutputTextPart.create(text=""),
                        )
                    ):
                        break
                    text_item_open = True
                if not emit(
                    ResponsesOutputTextDeltaEvent.create(
                        item_id=message_item_id,
                        delta=chunk.choice.delta.content,
                    )
                ):
                    break
            else:
                # Build each item once and reuse it below: re-deriving items
                # for the terminal payload remints ids the client never saw.
                completed_items: list[ResponsesOutputItem] = []
                if text_item_open:
                    completed_items.append(close_text_item("completed"))
                # Filter before enumerating, or a dropped nameless call leaves
                # a hole in the output_index sequence.
                call_items = [
                    item
                    for item in (
                        _function_call_item(tool_call)
                        for tool_call in _finalize_tool_calls(state.tool_call_buffer)
                        or []
                    )
                    if item is not None
                ]
                for tool_index, call_item in enumerate(
                    call_items, start=len(completed_items)
                ):
                    completed_items.append(call_item)
                    emit(
                        ResponsesOutputItemAddedEvent.create(
                            output_index=tool_index, item=call_item
                        )
                    )
                    emit(
                        ResponsesFunctionCallArgumentsDoneEvent.create(
                            item_id=call_item.id,
                            output_index=tool_index,
                            arguments=call_item.arguments,
                            name=call_item.name,
                        )
                    )
                    emit(
                        ResponsesOutputItemDoneEvent.create(
                            output_index=tool_index, item=call_item
                        )
                    )
                emit(
                    ResponsesCompletedEvent.create(
                        ResponsesObjectPayload.from_parts(
                            response_id=response_id,
                            created_at=created_at,
                            model=model,
                            status="completed",
                            output=completed_items,
                            usage=state.usage,
                        )
                    )
                )


def handle_responses_request(
    request: ResponsesRequest,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
) -> StreamingResponse | ResponsesObjectPayload:
    if request.previous_response_id is not None:
        raise OnyxError(
            OnyxErrorCode.NOT_IMPLEMENTED,
            "The Onyx gateway does not store responses; send the full "
            "conversation in `input` instead of `previous_response_id`.",
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

    if request.stream:
        return _sse_response(
            _responses_stream_worker,
            {
                "llm": llm,
                "flow": flow,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
                "model": request.model,
                "response_id": response_id,
                "created_at": created_at,
            },
        )

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
    if isinstance(result, StreamingResponse):
        return result
    return JSONResponse(content=result.to_wire())
