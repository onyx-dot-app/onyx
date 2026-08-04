import json
import queue
import threading
import time
import uuid
from contextlib import closing
from functools import partial
from itertools import count
from typing import TYPE_CHECKING, Any, cast

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
from onyx.llm.model_response import ChatCompletionMessageToolCall
from onyx.llm.models import (
    AnyThinkingBlock,
    AssistantMessage,
    ChatCompletionMessage,
    NamedToolChoice,
    ReasoningEffort,
    RedactedThinkingBlock,
    TextContentPart,
    ThinkingBlock,
    ToolCall,
    ToolChoice,
    ToolChoiceOptions,
    UserMessage,
)
from onyx.llm.multi_llm import LLMRateLimitError, LLMTimeoutError
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.tracing_wrap import _finalize_tool_calls
from onyx.server.features.build.craft_gateway import gateway_request_flow
from onyx.server.gateway.anthropic_passthrough import (
    AnthropicPassthroughUnavailable,
    handle_anthropic_count_tokens_passthrough,
    handle_anthropic_passthrough,
    is_anthropic_passthrough_eligible,
)
from onyx.server.gateway.configs import GATEWAY_PATH_PREFIX
from onyx.server.gateway.model_catalog import build_gateway_model_catalog
from onyx.server.gateway.models import (
    AnthropicContentBlock,
    AnthropicContentBlockDeltaEvent,
    AnthropicContentBlockStartEvent,
    AnthropicContentBlockStopEvent,
    AnthropicCountTokensRequest,
    AnthropicErrorEvent,
    AnthropicInputJsonDelta,
    AnthropicMessageDeltaEvent,
    AnthropicMessageDeltaPayload,
    AnthropicMessageResponse,
    AnthropicMessagesRequest,
    AnthropicMessageStartEvent,
    AnthropicMessageStopEvent,
    AnthropicPingEvent,
    AnthropicRedactedThinkingBlock,
    AnthropicSignatureDelta,
    AnthropicStreamEvent,
    AnthropicTextBlock,
    AnthropicTextDelta,
    AnthropicThinkingBlock,
    AnthropicThinkingDelta,
    AnthropicToolUseBlock,
    AnthropicUsagePayload,
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
from onyx.server.gateway.stream_bridge import (
    _RATE_LIMIT_ERROR,
    _put_stream_item,
    _sse_response,
    _stream_worker_guard,
    _StreamAccumulator,
)
from onyx.server.manage.llm.models import LLMProviderView, ModelConfigurationView
from onyx.server.query_and_chat.token_limit import check_token_rate_limits
from onyx.tracing.flows import LLMFlow
from onyx.tracing.framework.create import trace
from onyx.tracing.framework.traces import Trace
from onyx.tracing.llm_utils import llm_generation_span, record_llm_response
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from litellm.types.llms.anthropic import (
        AnthopicMessagesAssistantMessageParam,
        AnthropicMessagesUserMessageParam,
    )
    from litellm.types.llms.openai import ChatCompletionToolParam

    _AnthropicAdapterMessage = (
        AnthropicMessagesUserMessageParam | AnthopicMessagesAssistantMessageParam
    )

logger = setup_logger()

router = APIRouter(prefix=GATEWAY_PATH_PREFIX)

_MESSAGES_ADAPTER: TypeAdapter[list[ChatCompletionMessage]] = TypeAdapter(
    list[ChatCompletionMessage]
)


def _gateway_trace(flow: LLMFlow, model: str) -> Trace:
    return trace("llm_gateway", metadata={"flow": flow.value, "model": model})


def _authorize_gateway_request(http_request: Request, user: User) -> LLMFlow:
    flow = gateway_request_flow(http_request, user)
    if flow is None:
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
        if (
            message.content is None
            and not message.tool_calls
            and not message.thinking_blocks
        ):
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


def _parse_tool_choice(raw: Any) -> ToolChoice | None:
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
    if isinstance(raw, dict) and raw.get("type") == "function":
        # Chat Completions: {"type": "function", "function": {"name": X}}.
        # Responses API: {"type": "function", "name": X}.
        function = raw.get("function")
        name = function.get("name") if isinstance(function, dict) else raw.get("name")
        if isinstance(name, str) and name:
            return NamedToolChoice(name=name)
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "tool_choice names no function.")
    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"Unsupported tool_choice {raw!r}.",
    )


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
    tool_choice: ToolChoice | None,
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
    _require_named_tool(tool_choice, request.tools)
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
    tool_choice: ToolChoice | None,
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
    _require_named_tool(tool_choice, tools)
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


def _anthropic_system_to_raw_message(
    system: str | list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    if isinstance(system, str):
        return {"role": "system", "content": system} if system.strip() else None
    if isinstance(system, list):
        text = _flatten_text_content(system)
        return {"role": "system", "content": text} if text else None
    return None


def _replayable_thinking_blocks(
    raw_blocks: Any,
) -> list[dict[str, Any]] | None:
    """Unsigned thinking blocks would be rejected by Anthropic's signature
    check, so they are dropped rather than forwarded."""
    if not isinstance(raw_blocks, list):
        return None
    kept: list[dict[str, Any]] = []
    for block in raw_blocks:
        if not isinstance(block, dict):
            continue
        block_type = block.get("type")
        if block_type == "redacted_thinking" and block.get("data"):
            kept.append({"type": "redacted_thinking", "data": block["data"]})
        elif block_type == "thinking" and block.get("signature"):
            kept.append(
                {
                    "type": "thinking",
                    "thinking": block.get("thinking") or "",
                    "signature": block["signature"],
                }
            )
    return kept or None


def _anthropic_messages_to_raw_messages(
    messages: list[dict[str, Any]], system: str | list[dict[str, Any]] | None
) -> list[dict[str, Any]]:
    """LiteLLM's Anthropic adapter handles text/image/tool_use/tool_result block
    translation; system is prepended separately, and any residual list-of-parts
    content on system/tool messages is collapsed because our SystemMessage/
    ToolMessage content is str-only."""
    from litellm.llms.anthropic.experimental_pass_through.adapters.transformation import (
        LiteLLMAnthropicMessagesAdapter,
    )

    for message in messages:
        content = message.get("content")
        if not isinstance(content, list):
            continue
        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_result_content = block.get("content")
            if not isinstance(tool_result_content, list):
                continue
            if any(
                not isinstance(part, dict) or part.get("type") != "text"
                for part in tool_result_content
            ):
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    "Multimodal tool_result content is not supported by the "
                    "Onyx gateway.",
                )

    adapter = LiteLLMAnthropicMessagesAdapter()
    translated = adapter.translate_anthropic_messages_to_openai(
        messages=cast("list[_AnthropicAdapterMessage]", messages)
    )
    raw: list[dict[str, Any]] = []
    system_message = _anthropic_system_to_raw_message(system)
    if system_message is not None:
        raw.append(system_message)
    for message in translated:
        message_dict: dict[str, Any] = dict(message)
        role = message_dict.get("role")
        if role == "assistant":
            message_dict["thinking_blocks"] = _replayable_thinking_blocks(
                message_dict.get("thinking_blocks")
            )
        if role in ("system", "tool") and isinstance(message_dict.get("content"), list):
            message_dict["content"] = _flatten_text_content(message_dict["content"])
        elif role == "assistant" and isinstance(message_dict.get("content"), list):
            message_dict["content"] = (
                _flatten_text_content(message_dict["content"]) or None
            )
        raw.append(message_dict)
    return raw


def _anthropic_tools(
    raw_tools: list[dict[str, Any]] | None,
) -> list[dict[str, Any]] | None:
    if not raw_tools:
        return None
    tools: list[dict[str, Any]] = []
    for tool in raw_tools:
        name = tool.get("name")
        input_schema = tool.get("input_schema")
        if not name or input_schema is None:
            identifier = name or tool.get("type") or "<unknown>"
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                f"Tool {identifier!r} is not supported by the Onyx gateway; "
                "only client tools with an input_schema are accepted.",
            )
        function: dict[str, Any] = {"name": name, "parameters": input_schema}
        if "description" in tool:
            function["description"] = tool["description"]
        tools.append({"type": "function", "function": function})
    return tools


def _anthropic_tool_choice(raw: dict[str, Any] | None) -> ToolChoice | None:
    if raw is None:
        return None
    choice_type = raw.get("type")
    if choice_type == "auto":
        return ToolChoiceOptions.AUTO
    if choice_type == "any":
        return ToolChoiceOptions.REQUIRED
    if choice_type == "none":
        return ToolChoiceOptions.NONE
    if choice_type == "tool":
        name = raw.get("name")
        if isinstance(name, str) and name:
            return NamedToolChoice(name=name)
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "tool_choice names no function.")
    raise OnyxError(
        OnyxErrorCode.INVALID_INPUT,
        f"Unsupported tool_choice type {choice_type!r}; expected one of "
        "auto, any, none, tool.",
    )


def _require_named_tool(
    tool_choice: ToolChoice | None, tools: list[dict[str, Any]] | None
) -> None:
    """A named tool_choice referencing an absent tool would fail opaquely
    upstream; refuse it with a clear error instead."""
    if not isinstance(tool_choice, NamedToolChoice):
        return
    tool_names = {
        function.get("name")
        for tool in tools or []
        if isinstance(function := tool.get("function"), dict)
    }
    if tool_choice.name not in tool_names:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"tool_choice names unknown tool {tool_choice.name!r}.",
        )


def _anthropic_reasoning_effort(
    thinking: dict[str, Any] | None, output_config: dict[str, Any] | None
) -> ReasoningEffort:
    """Anthropic has two thinking APIs: legacy ``thinking.type=enabled`` with
    ``budget_tokens``, and adaptive ``thinking.type=adaptive`` where effort
    lives in top-level ``output_config.effort``. The downstream LLM layer
    re-derives the right API per model from the single ReasoningEffort, so
    both request shapes must map faithfully here."""
    if thinking is not None and thinking.get("type") == "disabled":
        return ReasoningEffort.OFF
    effort_raw = (output_config or {}).get("effort")
    if isinstance(effort_raw, str):
        return _parse_reasoning_effort(effort_raw)
    if thinking is None or thinking.get("type") == "adaptive":
        # Adaptive without an explicit effort: leave it to the downstream
        # adaptive default rather than pinning an effort tier.
        return ReasoningEffort.AUTO
    from litellm.llms.anthropic.experimental_pass_through.adapters.transformation import (
        LiteLLMAnthropicMessagesAdapter,
    )

    effort = LiteLLMAnthropicMessagesAdapter.translate_anthropic_thinking_to_reasoning_effort(
        thinking
    )
    return _parse_reasoning_effort(effort)


_ANTHROPIC_STOP_REASONS = {
    "stop": "end_turn",
    "length": "max_tokens",
    "tool_calls": "tool_use",
    "content_filter": "refusal",
}


def _anthropic_stop_reason(finish_reason: str | None, has_tool_use: bool) -> str:
    mapped = _ANTHROPIC_STOP_REASONS.get(finish_reason or "", "end_turn")
    # Truncation dominates: a generation cut off mid-tool-call must not be
    # reported as a completed tool_use turn (matches Anthropic's own API).
    if mapped == "max_tokens":
        return mapped
    # Otherwise tool calls dominate: providers routinely report finish_reason
    # "stop" on tool-call turns.
    if has_tool_use:
        return "tool_use"
    return mapped


def _anthropic_thinking_content_blocks(
    thinking_blocks: list[AnyThinkingBlock] | None,
    reasoning_content: str | None,
) -> list[AnthropicContentBlock]:
    """Unsigned fallback blocks are safe to emit because the input path drops
    unsigned blocks on replay, so they can never reach a signature check."""
    blocks: list[AnthropicContentBlock] = []
    for block in thinking_blocks or []:
        if isinstance(block, RedactedThinkingBlock):
            blocks.append(AnthropicRedactedThinkingBlock.create(data=block.data))
        elif block.thinking or block.signature:
            blocks.append(
                AnthropicThinkingBlock.create(
                    thinking=block.thinking, signature=block.signature or ""
                )
            )
    if not blocks and reasoning_content:
        blocks.append(
            AnthropicThinkingBlock.create(thinking=reasoning_content, signature="")
        )
    return blocks


def _anthropic_tool_use_blocks(
    tool_calls: list[ToolCall] | list[ChatCompletionMessageToolCall] | None,
) -> list[AnthropicToolUseBlock]:
    blocks: list[AnthropicToolUseBlock] = []
    for tool_call in tool_calls or []:
        name = tool_call.function.name
        if not name:
            continue
        arguments = tool_call.function.arguments
        try:
            parsed_input = json.loads(arguments) if arguments else {}
        except json.JSONDecodeError as e:
            raise ValueError("Upstream tool arguments are not valid JSON") from e
        if not isinstance(parsed_input, dict):
            raise ValueError("Upstream tool arguments must be a JSON object")
        blocks.append(
            AnthropicToolUseBlock.create(id=tool_call.id, name=name, input=parsed_input)
        )
    return blocks


def _anthropic_stream_worker(
    llm: LLM,
    flow: LLMFlow,
    messages: list[ChatCompletionMessage],
    tools: list[dict[str, Any]] | None,
    tool_choice: ToolChoice | None,
    max_tokens: int,
    reasoning_effort: ReasoningEffort,
    model: str,
    message_id: str,
    out: "queue.Queue[Any]",
    cancelled: threading.Event,
) -> None:
    def emit(event: AnthropicStreamEvent) -> bool:
        payload = event.to_wire()
        return _put_stream_item(
            out, f"event: {payload['type']}\ndata: {json.dumps(payload)}\n\n", cancelled
        )

    emit(
        AnthropicMessageStartEvent.create(
            AnthropicMessageResponse.from_parts(
                message_id=message_id,
                model=model,
                content=[],
                stop_reason=None,
                usage=AnthropicUsagePayload.zero(),
            )
        )
    )
    emit(AnthropicPingEvent.create())

    def emit_error(*, message: str, error_type: str) -> None:
        anthropic_error_type = (
            "rate_limit_error" if error_type == "rate_limit_error" else "api_error"
        )
        emit(
            AnthropicErrorEvent.create(message=message, error_type=anthropic_error_type)
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
        state = _StreamAccumulator()
        open_kind: str | None = None
        open_index: int | None = None
        next_index = 0

        def close_open_block() -> bool:
            nonlocal open_kind, open_index
            if open_index is None:
                return True
            index = open_index
            open_kind = None
            open_index = None
            return emit(AnthropicContentBlockStopEvent.create(index=index))

        def ensure_block_open(kind: str) -> bool:
            nonlocal open_kind, open_index, next_index
            if open_kind == kind:
                return True
            if not close_open_block():
                return False
            content_block: AnthropicContentBlock = (
                AnthropicThinkingBlock.create(thinking="", signature="")
                if kind == "thinking"
                else AnthropicTextBlock.create(text="")
            )
            open_kind = kind
            open_index = next_index
            next_index += 1
            return emit(
                AnthropicContentBlockStartEvent.create(
                    index=open_index, content_block=content_block
                )
            )

        def emit_thinking_deltas(blocks: list[AnyThinkingBlock]) -> bool:
            nonlocal next_index
            for block in blocks:
                if isinstance(block, RedactedThinkingBlock):
                    if not close_open_block():
                        return False
                    index = next_index
                    next_index += 1
                    if not emit(
                        AnthropicContentBlockStartEvent.create(
                            index=index,
                            content_block=AnthropicRedactedThinkingBlock.create(
                                data=block.data
                            ),
                        )
                    ) or not emit(AnthropicContentBlockStopEvent.create(index=index)):
                        return False
                    continue
                if not ensure_block_open("thinking"):
                    return False
                assert open_index is not None
                if block.thinking and not emit(
                    AnthropicContentBlockDeltaEvent.create(
                        index=open_index,
                        delta=AnthropicThinkingDelta.create(thinking=block.thinking),
                    )
                ):
                    return False
                if block.signature and not emit(
                    AnthropicContentBlockDeltaEvent.create(
                        index=open_index,
                        delta=AnthropicSignatureDelta.create(signature=block.signature),
                    )
                ):
                    return False
            return True

        with _stream_worker_guard(
            span,
            model,
            state,
            label="anthropic stream",
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
            finish_reason: str | None = None
            for chunk in state.upstream:
                if cancelled.is_set():
                    break
                state.observe(chunk)
                if chunk.choice.finish_reason is not None:
                    finish_reason = chunk.choice.finish_reason
                delta = chunk.choice.delta
                # Anthropic-family chunks carry reasoning_content mirroring
                # thinking_blocks, so only one of the two may be emitted.
                if delta.thinking_blocks:
                    if not emit_thinking_deltas(delta.thinking_blocks):
                        break
                elif delta.reasoning_content:
                    if not emit_thinking_deltas(
                        [ThinkingBlock(thinking=delta.reasoning_content)]
                    ):
                        break
                if delta.content:
                    if not ensure_block_open("text"):
                        break
                    assert open_index is not None
                    if not emit(
                        AnthropicContentBlockDeltaEvent.create(
                            index=open_index,
                            delta=AnthropicTextDelta.create(text=delta.content),
                        )
                    ):
                        break
            else:
                close_open_block()
                finalized_tool_calls = _finalize_tool_calls(state.tool_call_buffer)
                tool_blocks = _anthropic_tool_use_blocks(finalized_tool_calls)
                named_tool_calls = [
                    tc for tc in finalized_tool_calls or [] if tc.function.name
                ]
                for tool_index, (tool_block, tool_call) in enumerate(
                    zip(tool_blocks, named_tool_calls), start=next_index
                ):
                    emit(
                        AnthropicContentBlockStartEvent.create(
                            index=tool_index,
                            content_block=AnthropicToolUseBlock.create(
                                id=tool_block.id, name=tool_block.name, input={}
                            ),
                        )
                    )
                    emit(
                        AnthropicContentBlockDeltaEvent.create(
                            index=tool_index,
                            delta=AnthropicInputJsonDelta.create(
                                partial_json=tool_call.function.arguments or "{}"
                            ),
                        )
                    )
                    emit(AnthropicContentBlockStopEvent.create(index=tool_index))
                emit(
                    AnthropicMessageDeltaEvent.create(
                        delta=AnthropicMessageDeltaPayload.create(
                            stop_reason=_anthropic_stop_reason(
                                finish_reason, bool(tool_blocks)
                            )
                        ),
                        usage=(
                            AnthropicUsagePayload.from_usage(state.usage)
                            if state.usage
                            else AnthropicUsagePayload.zero()
                        ),
                    )
                )
                emit(AnthropicMessageStopEvent.create())


def handle_anthropic_messages(
    request: AnthropicMessagesRequest,
    provider: LLMProviderView,
    model_config: ModelConfigurationView,
    flow: LLMFlow,
) -> StreamingResponse | AnthropicMessageResponse:
    llm = llm_from_provider(
        model_name=model_config.name,
        llm_provider=provider,
        temperature=request.temperature,
    )
    raw_messages = _anthropic_messages_to_raw_messages(request.messages, request.system)
    messages = _prepare_messages(llm, raw_messages)
    tools = _anthropic_tools(request.tools)
    tool_choice = _anthropic_tool_choice(request.tool_choice)
    _require_named_tool(tool_choice, tools)
    reasoning_effort = _anthropic_reasoning_effort(
        request.thinking, request.output_config
    )
    max_tokens = request.max_tokens
    message_id = _new_id("msg")

    if request.stream:
        return _sse_response(
            _anthropic_stream_worker,
            {
                "llm": llm,
                "flow": flow,
                "messages": messages,
                "tools": tools,
                "tool_choice": tool_choice,
                "max_tokens": max_tokens,
                "reasoning_effort": reasoning_effort,
                "model": request.model,
                "message_id": message_id,
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
                "LLM gateway anthropic invoke failed for model %s", request.model
            )
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "The upstream LLM request failed.",
            ) from e
        if span is not None:
            record_llm_response(span, response)

    content: list[AnthropicContentBlock] = _anthropic_thinking_content_blocks(
        response.choice.message.thinking_blocks,
        response.choice.message.reasoning_content,
    )
    if response.choice.message.content:
        content.append(AnthropicTextBlock.create(text=response.choice.message.content))
    try:
        tool_blocks = _anthropic_tool_use_blocks(response.choice.message.tool_calls)
    except ValueError as e:
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "The upstream LLM returned invalid tool arguments.",
        ) from e
    content.extend(tool_blocks)
    return AnthropicMessageResponse.from_parts(
        message_id=message_id,
        model=request.model,
        content=content,
        stop_reason=_anthropic_stop_reason(
            response.choice.finish_reason, bool(tool_blocks)
        ),
        usage=(
            AnthropicUsagePayload.from_usage(response.usage)
            if response.usage
            else AnthropicUsagePayload.zero()
        ),
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


@router.post("/v1/messages")
def gateway_anthropic_messages(
    request: AnthropicMessagesRequest,
    http_request: Request,
    user: User = Depends(require_permission(Permission.USE_LLM_GATEWAY)),
    db_session: Session = Depends(get_session),
) -> Response:
    flow = _authorize_gateway_request(http_request, user)
    check_token_rate_limits(user)
    with closing(db_session):
        provider, model_config = resolve_gateway_model(db_session, user, request.model)
    if is_anthropic_passthrough_eligible(provider):
        return handle_anthropic_passthrough(
            request=request,
            provider=provider,
            model_config=model_config,
            flow=flow,
            http_request=http_request,
            user=user,
        )
    result = handle_anthropic_messages(
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


@router.post("/v1/messages/count_tokens")
def gateway_anthropic_count_tokens(
    request: AnthropicCountTokensRequest,
    http_request: Request,
    user: User = Depends(require_permission(Permission.USE_LLM_GATEWAY)),
    db_session: Session = Depends(get_session),
) -> Response:
    # No token rate limit check: nothing is generated by this endpoint.
    _authorize_gateway_request(http_request, user)
    with closing(db_session):
        provider, model_config = resolve_gateway_model(db_session, user, request.model)
    if is_anthropic_passthrough_eligible(provider):
        try:
            return handle_anthropic_count_tokens_passthrough(
                request=request,
                provider=provider,
                model_config=model_config,
                http_request=http_request,
                user=user,
            )
        except AnthropicPassthroughUnavailable:
            logger.warning(
                "Anthropic passthrough count_tokens unavailable for model %s; "
                "falling back to the local estimate",
                request.model,
            )
    raw_messages = _anthropic_messages_to_raw_messages(request.messages, request.system)
    tools = _anthropic_tools(request.tools)
    from onyx.llm.litellm_singleton import litellm

    try:
        input_tokens = litellm.token_counter(
            model=model_config.name,
            messages=raw_messages,
            tools=cast("list[ChatCompletionToolParam] | None", tools),
        )
    except Exception:
        logger.exception("LLM gateway token count failed for model %s", request.model)
        # Rough fallback so Claude Code's context tracking degrades instead of
        # breaking.
        countable_input: dict[str, Any] = {"messages": raw_messages}
        if tools is not None:
            countable_input["tools"] = tools
        input_tokens = len(json.dumps(countable_input)) // 4
    return JSONResponse(content={"input_tokens": input_tokens})
