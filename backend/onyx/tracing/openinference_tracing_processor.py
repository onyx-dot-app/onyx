from __future__ import annotations

import logging
from collections import OrderedDict
from collections.abc import Iterable
from collections.abc import Iterator
from collections.abc import Mapping
from datetime import datetime
from datetime import timezone
from typing import Any
from typing import Optional
from typing import Union

from openinference.instrumentation import safe_json_dumps
from openinference.semconv.trace import MessageAttributes
from openinference.semconv.trace import MessageContentAttributes
from openinference.semconv.trace import OpenInferenceLLMProviderValues
from openinference.semconv.trace import OpenInferenceLLMSystemValues
from openinference.semconv.trace import OpenInferenceMimeTypeValues
from openinference.semconv.trace import OpenInferenceSpanKindValues
from openinference.semconv.trace import SpanAttributes
from openinference.semconv.trace import ToolAttributes
from openinference.semconv.trace import ToolCallAttributes
from opentelemetry.context import attach
from opentelemetry.context import detach
from opentelemetry.trace import set_span_in_context
from opentelemetry.trace import Span as OtelSpan
from opentelemetry.trace import Status
from opentelemetry.trace import StatusCode
from opentelemetry.trace import Tracer
from opentelemetry.util.types import AttributeValue

from onyx.tracing.framework.processor_interface import TracingProcessor
from onyx.tracing.framework.span_data import AgentSpanData
from onyx.tracing.framework.span_data import FunctionSpanData
from onyx.tracing.framework.span_data import GenerationSpanData
from onyx.tracing.framework.span_data import SpanData
from onyx.tracing.framework.spans import Span
from onyx.tracing.framework.traces import Trace

logger = logging.getLogger(__name__)


class OpenInferenceTracingProcessor(TracingProcessor):
    _MAX_HANDOFFS_IN_FLIGHT = 1000

    def __init__(self, tracer: Tracer) -> None:
        self._tracer = tracer
        self._root_spans: dict[str, OtelSpan] = {}
        self._otel_spans: dict[str, OtelSpan] = {}
        self._tokens: dict[str, object] = {}
        # This captures in flight handoff. Once the handoff is complete, the entry is deleted
        # If the handoff does not complete, the entry stays in the dict.
        # Use an OrderedDict and _MAX_HANDOFFS_IN_FLIGHT to cap the size of the dict
        # in case there are large numbers of orphaned handoffs
        self._reverse_handoffs_dict: OrderedDict[str, str] = OrderedDict()
        self._first_input: dict[str, Any] = {}
        self._last_output: dict[str, Any] = {}

    def on_trace_start(self, trace: Trace) -> None:
        """Called when a trace is started.

        Args:
            trace: The trace that started.
        """
        otel_span = self._tracer.start_span(
            name=trace.name,
            attributes={
                OPENINFERENCE_SPAN_KIND: OpenInferenceSpanKindValues.AGENT.value,
            },
        )
        self._root_spans[trace.trace_id] = otel_span

    def on_trace_end(self, trace: Trace) -> None:
        """Called when a trace is finished.

        Args:
            trace: The trace that started.
        """
        if root_span := self._root_spans.pop(trace.trace_id, None):
            # Get the first input and last output for this specific trace
            trace_first_input = self._first_input.pop(trace.trace_id, None)
            trace_last_output = self._last_output.pop(trace.trace_id, None)

            # Set input/output attributes on the root span
            if trace_first_input is not None:
                try:
                    root_span.set_attribute(
                        INPUT_VALUE, safe_json_dumps(trace_first_input)
                    )
                    root_span.set_attribute(INPUT_MIME_TYPE, JSON)
                except Exception:
                    # Fallback to string if JSON serialization fails
                    root_span.set_attribute(INPUT_VALUE, str(trace_first_input))

            if trace_last_output is not None:
                try:
                    root_span.set_attribute(
                        OUTPUT_VALUE, safe_json_dumps(trace_last_output)
                    )
                    root_span.set_attribute(OUTPUT_MIME_TYPE, JSON)
                except Exception:
                    # Fallback to string if JSON serialization fails
                    root_span.set_attribute(OUTPUT_VALUE, str(trace_last_output))

            root_span.set_status(Status(StatusCode.OK))
            root_span.end()
        else:
            # Clean up stored input/output for this trace if root span doesn't exist
            self._first_input.pop(trace.trace_id, None)
            self._last_output.pop(trace.trace_id, None)

    def on_span_start(self, span: Span[Any]) -> None:
        """Called when a span is started.

        Args:
            span: The span that started.
        """
        if not span.started_at:
            return
        start_time = datetime.fromisoformat(span.started_at)
        parent_span = (
            self._otel_spans.get(span.parent_id)
            if span.parent_id
            else self._root_spans.get(span.trace_id)
        )
        context = set_span_in_context(parent_span) if parent_span else None
        span_name = _get_span_name(span)
        otel_span = self._tracer.start_span(
            name=span_name,
            context=context,
            start_time=_as_utc_nano(start_time),
            attributes={
                OPENINFERENCE_SPAN_KIND: _get_span_kind(span.span_data),
                LLM_SYSTEM: OpenInferenceLLMSystemValues.OPENAI.value,
            },
        )
        self._otel_spans[span.span_id] = otel_span
        self._tokens[span.span_id] = attach(set_span_in_context(otel_span))

    def on_span_end(self, span: Span[Any]) -> None:
        """Called when a span is finished. Should not block or raise exceptions.

        Args:
            span: The span that finished.
        """
        if token := self._tokens.pop(span.span_id, None):
            detach(token)  # type: ignore[arg-type]
        if not (otel_span := self._otel_spans.pop(span.span_id, None)):
            return
        otel_span.update_name(_get_span_name(span))
        # flatten_attributes: dict[str, AttributeValue] = dict(_flatten(span.export()))
        # otel_span.set_attributes(flatten_attributes)
        data = span.span_data
        if isinstance(data, GenerationSpanData):
            for k, v in _get_attributes_from_generation_span_data(data):
                otel_span.set_attribute(k, v)
        elif isinstance(data, FunctionSpanData):
            for k, v in _get_attributes_from_function_span_data(data):
                otel_span.set_attribute(k, v)
        elif isinstance(data, AgentSpanData):
            otel_span.set_attribute(GRAPH_NODE_ID, data.name)
            # Lookup the parent node if exists
            key = f"{data.name}:{span.trace_id}"
            if parent_node := self._reverse_handoffs_dict.pop(key, None):
                otel_span.set_attribute(GRAPH_NODE_PARENT_ID, parent_node)

        end_time: Optional[int] = None
        if span.ended_at:
            try:
                end_time = _as_utc_nano(datetime.fromisoformat(span.ended_at))
            except ValueError:
                pass
        otel_span.set_status(status=_get_span_status(span))
        otel_span.end(end_time)

        # Store first input and last output per trace_id
        trace_id = span.trace_id
        input_: Optional[Any] = None
        output: Optional[Any] = None

        if isinstance(data, FunctionSpanData):
            input_ = data.input
            output = data.output
        elif isinstance(data, GenerationSpanData):
            input_ = data.input
            output = data.output

        if trace_id not in self._first_input and input_ is not None:
            self._first_input[trace_id] = input_

        if output is not None:
            self._last_output[trace_id] = output

    def force_flush(self) -> None:
        """Forces an immediate flush of all queued spans/traces."""
        # TODO

    def shutdown(self) -> None:
        """Called when the application stops."""
        # TODO


def _as_utc_nano(dt: datetime) -> int:
    return int(dt.astimezone(timezone.utc).timestamp() * 1_000_000_000)


def _get_span_name(obj: Span[Any]) -> str:
    if hasattr(data := obj.span_data, "name") and isinstance(name := data.name, str):
        return name
    return obj.span_data.type


def _get_span_kind(obj: SpanData) -> str:
    if isinstance(obj, AgentSpanData):
        return OpenInferenceSpanKindValues.AGENT.value
    if isinstance(obj, FunctionSpanData):
        return OpenInferenceSpanKindValues.TOOL.value
    if isinstance(obj, GenerationSpanData):
        return OpenInferenceSpanKindValues.LLM.value
    return OpenInferenceSpanKindValues.CHAIN.value


def _get_attributes_from_generation_span_data(
    obj: GenerationSpanData,
) -> Iterator[tuple[str, AttributeValue]]:
    if isinstance(model := obj.model, str):
        yield LLM_MODEL_NAME, model
    if isinstance(obj.model_config, dict) and (
        param := {k: v for k, v in obj.model_config.items() if v is not None}
    ):
        yield LLM_INVOCATION_PARAMETERS, safe_json_dumps(param)
        if base_url := param.get("base_url"):
            if "api.openai.com" in base_url:
                yield LLM_PROVIDER, OpenInferenceLLMProviderValues.OPENAI.value
    if obj.time_to_first_action_seconds is not None:
        yield LLM_TIME_TO_FIRST_ACTION_SECONDS, obj.time_to_first_action_seconds
    yield from _get_attributes_from_chat_completions_input(obj.input)
    yield from _get_attributes_from_chat_completions_output(obj.output)
    yield from _get_attributes_from_chat_completions_usage(obj.usage)


def _get_attributes_from_chat_completions_input(
    obj: Optional[Iterable[Mapping[str, Any]]],
) -> Iterator[tuple[str, AttributeValue]]:
    if not obj:
        return
    try:
        yield INPUT_VALUE, safe_json_dumps(obj)
        yield INPUT_MIME_TYPE, JSON
    except Exception:
        pass
    yield from _get_attributes_from_chat_completions_message_dicts(
        obj,
        f"{LLM_INPUT_MESSAGES}.",
    )


def _get_attributes_from_chat_completions_output(
    obj: Optional[Iterable[Mapping[str, Any]]],
) -> Iterator[tuple[str, AttributeValue]]:
    if not obj:
        return
    try:
        yield OUTPUT_VALUE, safe_json_dumps(obj)
        yield OUTPUT_MIME_TYPE, JSON
    except Exception:
        pass
    yield from _get_attributes_from_chat_completions_message_dicts(
        obj,
        f"{LLM_OUTPUT_MESSAGES}.",
    )


def _get_attributes_from_chat_completions_message_dicts(
    obj: Iterable[Mapping[str, Any]],
    prefix: str = "",
    msg_idx: int = 0,
    tool_call_idx: int = 0,
) -> Iterator[tuple[str, AttributeValue]]:
    if not isinstance(obj, Iterable):
        return
    for msg in obj:
        if isinstance(role := msg.get("role"), str):
            yield f"{prefix}{msg_idx}.{MESSAGE_ROLE}", role
        if content := msg.get("content"):
            yield from _get_attributes_from_chat_completions_message_content(
                content,
                f"{prefix}{msg_idx}.",
            )
        if isinstance(tool_call_id := msg.get("tool_call_id"), str):
            yield f"{prefix}{msg_idx}.{MESSAGE_TOOL_CALL_ID}", tool_call_id
        if isinstance(tool_calls := msg.get("tool_calls"), Iterable):
            for tc in tool_calls:
                yield from _get_attributes_from_chat_completions_tool_call_dict(
                    tc,
                    f"{prefix}{msg_idx}.{MESSAGE_TOOL_CALLS}.{tool_call_idx}.",
                )
                tool_call_idx += 1
        msg_idx += 1


def _get_attributes_from_chat_completions_message_content(
    obj: Union[str, Iterable[Mapping[str, Any]]],
    prefix: str = "",
) -> Iterator[tuple[str, AttributeValue]]:
    if isinstance(obj, str):
        yield f"{prefix}{MESSAGE_CONTENT}", obj
    elif isinstance(obj, Iterable):
        for i, item in enumerate(obj):
            if not isinstance(item, Mapping):
                continue
            yield from _get_attributes_from_chat_completions_message_content_item(
                item,
                f"{prefix}{MESSAGE_CONTENTS}.{i}.",
            )


def _get_attributes_from_chat_completions_message_content_item(
    obj: Mapping[str, Any],
    prefix: str = "",
) -> Iterator[tuple[str, AttributeValue]]:
    if obj.get("type") == "text" and (text := obj.get("text")):
        yield f"{prefix}{MESSAGE_CONTENT_TYPE}", "text"
        yield f"{prefix}{MESSAGE_CONTENT_TEXT}", text


def _get_attributes_from_chat_completions_tool_call_dict(
    obj: Mapping[str, Any],
    prefix: str = "",
) -> Iterator[tuple[str, AttributeValue]]:
    if id_ := obj.get("id"):
        yield f"{prefix}{TOOL_CALL_ID}", id_
    if function := obj.get("function"):
        if name := function.get("name"):
            yield f"{prefix}{TOOL_CALL_FUNCTION_NAME}", name
        if arguments := function.get("arguments"):
            if arguments != "{}":
                yield f"{prefix}{TOOL_CALL_FUNCTION_ARGUMENTS_JSON}", arguments


def _get_attributes_from_chat_completions_usage(
    obj: Optional[Mapping[str, Any]],
) -> Iterator[tuple[str, AttributeValue]]:
    if not obj:
        return
    if input_tokens := obj.get("input_tokens"):
        yield LLM_TOKEN_COUNT_PROMPT, input_tokens
    if output_tokens := obj.get("output_tokens"):
        yield LLM_TOKEN_COUNT_COMPLETION, output_tokens


# convert dict, tuple, etc into one of these types ['bool', 'str', 'bytes', 'int', 'float']
def _convert_to_primitive(value: Any) -> Union[bool, str, bytes, int, float]:
    if isinstance(value, (bool, str, bytes, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return safe_json_dumps(value)
    if isinstance(value, dict):
        return safe_json_dumps(value)
    return str(value)


def _get_attributes_from_function_span_data(
    obj: FunctionSpanData,
) -> Iterator[tuple[str, AttributeValue]]:
    yield TOOL_NAME, obj.name
    if obj.input:
        yield INPUT_VALUE, obj.input
        yield INPUT_MIME_TYPE, JSON
    if obj.output is not None:
        yield OUTPUT_VALUE, _convert_to_primitive(obj.output)
        if (
            isinstance(obj.output, str)
            and len(obj.output) > 1
            and obj.output[0] == "{"
            and obj.output[-1] == "}"
        ):
            yield OUTPUT_MIME_TYPE, JSON


def _get_span_status(obj: Span[Any]) -> Status:
    if error := getattr(obj, "error", None):
        return Status(
            status_code=StatusCode.ERROR,
            description=f"{error.get('message')}: {error.get('data')}",
        )
    else:
        return Status(StatusCode.OK)


def _flatten(
    obj: Mapping[str, Any],
    prefix: str = "",
) -> Iterator[tuple[str, AttributeValue]]:
    for key, value in obj.items():
        if isinstance(value, dict):
            yield from _flatten(value, f"{prefix}{key}.")
        elif isinstance(value, (str, int, float, bool, str)):
            yield f"{prefix}{key}", value
        else:
            yield f"{prefix}{key}", str(value)


INPUT_MIME_TYPE = SpanAttributes.INPUT_MIME_TYPE
INPUT_VALUE = SpanAttributes.INPUT_VALUE
LLM_INPUT_MESSAGES = SpanAttributes.LLM_INPUT_MESSAGES
LLM_INVOCATION_PARAMETERS = SpanAttributes.LLM_INVOCATION_PARAMETERS
LLM_MODEL_NAME = SpanAttributes.LLM_MODEL_NAME
LLM_OUTPUT_MESSAGES = SpanAttributes.LLM_OUTPUT_MESSAGES
LLM_PROVIDER = SpanAttributes.LLM_PROVIDER
LLM_SYSTEM = SpanAttributes.LLM_SYSTEM
LLM_TOKEN_COUNT_COMPLETION = SpanAttributes.LLM_TOKEN_COUNT_COMPLETION
LLM_TOKEN_COUNT_PROMPT = SpanAttributes.LLM_TOKEN_COUNT_PROMPT
LLM_TOKEN_COUNT_TOTAL = SpanAttributes.LLM_TOKEN_COUNT_TOTAL
LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_READ = (
    SpanAttributes.LLM_TOKEN_COUNT_PROMPT_DETAILS_CACHE_READ
)
LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING = (
    SpanAttributes.LLM_TOKEN_COUNT_COMPLETION_DETAILS_REASONING
)
LLM_TOOLS = SpanAttributes.LLM_TOOLS
METADATA = SpanAttributes.METADATA
OPENINFERENCE_SPAN_KIND = SpanAttributes.OPENINFERENCE_SPAN_KIND
OUTPUT_MIME_TYPE = SpanAttributes.OUTPUT_MIME_TYPE
OUTPUT_VALUE = SpanAttributes.OUTPUT_VALUE
TOOL_DESCRIPTION = SpanAttributes.TOOL_DESCRIPTION
TOOL_NAME = SpanAttributes.TOOL_NAME
TOOL_PARAMETERS = SpanAttributes.TOOL_PARAMETERS
GRAPH_NODE_ID = SpanAttributes.GRAPH_NODE_ID
GRAPH_NODE_PARENT_ID = SpanAttributes.GRAPH_NODE_PARENT_ID
LLM_TIME_TO_FIRST_ACTION_SECONDS = "llm.time_to_first_action_seconds"

MESSAGE_CONTENT = MessageAttributes.MESSAGE_CONTENT
MESSAGE_CONTENTS = MessageAttributes.MESSAGE_CONTENTS
MESSAGE_CONTENT_IMAGE = MessageContentAttributes.MESSAGE_CONTENT_IMAGE
MESSAGE_CONTENT_TEXT = MessageContentAttributes.MESSAGE_CONTENT_TEXT
MESSAGE_CONTENT_TYPE = MessageContentAttributes.MESSAGE_CONTENT_TYPE
MESSAGE_FUNCTION_CALL_ARGUMENTS_JSON = (
    MessageAttributes.MESSAGE_FUNCTION_CALL_ARGUMENTS_JSON
)
MESSAGE_FUNCTION_CALL_NAME = MessageAttributes.MESSAGE_FUNCTION_CALL_NAME
MESSAGE_ROLE = MessageAttributes.MESSAGE_ROLE
MESSAGE_TOOL_CALLS = MessageAttributes.MESSAGE_TOOL_CALLS
MESSAGE_TOOL_CALL_ID = MessageAttributes.MESSAGE_TOOL_CALL_ID

TOOL_CALL_FUNCTION_ARGUMENTS_JSON = ToolCallAttributes.TOOL_CALL_FUNCTION_ARGUMENTS_JSON
TOOL_CALL_FUNCTION_NAME = ToolCallAttributes.TOOL_CALL_FUNCTION_NAME
TOOL_CALL_ID = ToolCallAttributes.TOOL_CALL_ID

TOOL_JSON_SCHEMA = ToolAttributes.TOOL_JSON_SCHEMA

JSON = OpenInferenceMimeTypeValues.JSON.value
