import copy
import json
import math
import os
import time
from collections.abc import Generator, Iterable, Iterator, Mapping
from contextlib import AbstractContextManager, contextmanager, nullcontext
from functools import lru_cache
from typing import TYPE_CHECKING, Any, cast, get_type_hints

from pydantic import BaseModel, JsonValue, TypeAdapter
from readerwriterlock import rwlock

from onyx.configs.app_configs import SEND_USER_METADATA_TO_LLM_PROVIDER
from onyx.configs.chat_configs import (
    LLM_FIRST_CHUNK_MAX_RETRIES,
    LLM_INVOKE_TIMEOUT_S,
    LLM_SOCKET_READ_TIMEOUT,
)
from onyx.configs.model_configs import (
    GEN_AI_NUM_RESERVED_OUTPUT_TOKENS,
    GEN_AI_TEMPERATURE,
    LITELLM_EXTRA_BODY,
)
from onyx.llm.api_surfaces import (
    OPENAI_COMPATIBLE_SURFACES,
    LlmApiSurface,
    resolve_api_surface,
)
from onyx.llm.cancellation import (
    AgentCancelled,
    CancellationSignal,
    cancellation_scope,
    check_cancelled,
    current_cancellation,
    isolated_context,
)
from onyx.llm.constants import MODEL_PREFIX_TO_VENDOR, LlmProviderNames
from onyx.llm.cost import compute_cost_cents
from onyx.llm.custom_config_mapping import (
    UI_ONLY_CONFIG_KEYS,
    map_custom_config_to_model_kwargs,
)
from onyx.llm.exceptions import (
    ClassifiedLLMError,
    LLMContextLimitError,
    LLMRateLimitError,
    LLMTimeoutError,
    litellm_exception_to_safe_error,
)
from onyx.llm.interfaces import (
    LLM,
    GenerationContext,
    LLMConfig,
    LLMUserIdentity,
)
from onyx.llm.model_capabilities import (
    OPENAI_API_PROVIDERS,
    ReasoningParamStyle,
    anthropic_identity_is_always_thinking,
    anthropic_identity_turns_thinking_off_between_tools,
    anthropic_omits_sampling_params,
    anthropic_supports_thinking,
    anthropic_uses_adaptive_thinking,
    find_model_obj,
    gemini_lowest_thinking_level_is_low,
    get_model_map,
    is_true_openai_model,
    model_is_reasoning_model,
    model_prefers_auto_tool_choice,
    model_requires_auto_tool_choice,
    openai_chat_tools_require_reasoning_none,
    openai_chat_variant_rejects_reasoning,
    openai_model_rejects_reasoning_effort,
    openai_model_supports_reasoning_none,
    resolve_reasoning_param_style,
)
from onyx.llm.model_capabilities import (
    model_identity_names as resolve_model_identity_names,
)
from onyx.llm.model_request import (
    ChatCompletionMessage,
    RequestFunctionCall,
    cache_split_stats,
    merge_leading_system_messages,
    serialize_request,
    serialize_tools,
)
from onyx.llm.model_request import ToolCall as ProviderToolCall
from onyx.llm.model_response import (
    MessageAccumulator,
    ModelResponse,
    ModelResponseStream,
    to_assistant_message,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationErrorEvent,
    GenerationEvent,
    GenerationRequest,
    GenerationRequestParams,
    GenerationStartEvent,
    NamedToolChoice,
    ReasoningEffort,
    ToolChoice,
    ToolChoiceOptions,
    ToolDefinition,
    Usage,
    resolve_reasoning_effort,
)
from onyx.llm.prompt_cache.processor import process_with_prompt_cache
from onyx.llm.prompt_cache.providers.factory import get_provider_adapter
from onyx.llm.prompt_cache.providers.openai import (
    CACHE_BREAKPOINT_FLAG,
    explicit_cache_breakpoints,
    uses_explicit_cache_breakpoints,
    without_cache_breakpoint_flags,
)
from onyx.llm.utils import build_litellm_passthrough_kwargs, collect_credential_values
from onyx.llm.well_known_providers.constants import VERTEX_LOCATION_KWARG
from onyx.tracing.flows import LLMFlow
from onyx.tracing.llm_utils import (
    llm_generation_span,
    record_llm_request_params,
    record_llm_response,
    record_llm_routed_model,
    record_llm_span_output,
)
from onyx.utils.encryption import mask_env_value_for_logging
from onyx.utils.logger import setup_logger
from onyx.utils.redaction import scrub_sensitive_values

# OpenAI reasoning effort mapping
# Note: OpenAI API does not support "auto" - valid values are: none, minimal, low, medium, high, xhigh
OPENAI_REASONING_EFFORT: dict[ReasoningEffort, str] = {
    ReasoningEffort.AUTO: "medium",  # Default to medium when auto is requested
    ReasoningEffort.OFF: "none",
    ReasoningEffort.LOW: "low",
    ReasoningEffort.MEDIUM: "medium",
    ReasoningEffort.HIGH: "high",
    ReasoningEffort.XHIGH: "xhigh",
}

# Anthropic reasoning effort to budget tokens mapping
# Loosely based on budgets from LiteLLM but this ensures it's not updated without our knowing from a version bump.
ANTHROPIC_REASONING_EFFORT_BUDGET: dict[ReasoningEffort, int] = {
    ReasoningEffort.AUTO: 2048,
    ReasoningEffort.LOW: 1024,
    ReasoningEffort.MEDIUM: 2048,
    ReasoningEffort.HIGH: 4096,
    ReasoningEffort.XHIGH: 4096,
}

# Newer Anthropic models (Claude Opus 4.7+) use adaptive thinking with
# output_config.effort instead of thinking.type.enabled + budget_tokens.
ANTHROPIC_ADAPTIVE_REASONING_EFFORT: dict[ReasoningEffort, str] = {
    ReasoningEffort.AUTO: "medium",
    ReasoningEffort.LOW: "low",
    ReasoningEffort.MEDIUM: "medium",
    ReasoningEffort.HIGH: "high",
    ReasoningEffort.XHIGH: "xhigh",
}


logger = setup_logger()

_PROVIDER_TOOL_CALLS = TypeAdapter(list[ProviderToolCall])

# Write-preferring reader-writer lock guarding os.environ during litellm calls.
# Calls that inject custom_config env vars hold the write lock; all other calls
# hold a read lock so they never observe injected secrets but still run
# concurrently with each other.
_env_rwlock = rwlock.RWLockWrite()

if TYPE_CHECKING:
    from litellm import CustomStreamWrapper, HTTPHandler
    from litellm import ModelResponse as LiteLLMModelResponse
    from litellm.exceptions import BadRequestError


LEGACY_MAX_TOKENS_KWARG = "max_tokens"
STANDARD_MAX_TOKENS_KWARG = "max_completion_tokens"

# Azure api-versions that route to the modern /openai/v1/* surface. Mirrors
# LiteLLM's BaseAzureLLM._is_azure_v1_api_version.
_AZURE_V1_API_VERSIONS = frozenset({"preview", "latest", "v1"})

_VERTEX_ANTHROPIC_MODELS_REJECTING_STREAM_OPTIONS = (
    "claude-opus-4-5",
    "claude-opus-4-6",
    "claude-opus-4-7",
    "claude-opus-4-8",
)
_ANTHROPIC_MIN_THINKING_BUDGET_TOKENS = 1024

# Best-effort tuning kwargs, never worth failing a chat over. _completion
# retries provider rejections without them (cache-only rejections first;
# otherwise reasoning keys, then all),
# keeping keys a provider requires. Never tools, tool_choice or messages.
_REASONING_KWARG_KEYS = frozenset(
    {"thinking", "output_config", "reasoning", "reasoning_effort"}
)
_BEST_EFFORT_KWARG_KEYS = _REASONING_KWARG_KEYS | frozenset(
    {"temperature", "prompt_cache_options"}
)

# Substrings provider 400s use to name each strippable kwarg (errors may
# cite only inner fields like budget_tokens or effort).
_KWARG_ERROR_ALIASES: dict[str, tuple[str, ...]] = {
    "thinking": ("thinking", "budget_tokens"),
    "output_config": ("output_config", "effort"),
    "reasoning": ("reasoning", "effort"),
    "reasoning_effort": ("reasoning_effort", "effort"),
    "temperature": ("temperature",),
    "prompt_cache_options": ("prompt_cache_options", "prompt_cache_breakpoint"),
}

# Substring of the OpenAI-family 400 that names "none" as the only effort
# accepted alongside function tools. Omitting the parameter gets the same 400.
_REASONING_NONE_DEMAND = "set reasoning_effort to 'none'"
_OPENAI_REASONING_NONE = OPENAI_REASONING_EFFORT[ReasoningEffort.OFF]


def _merge_under(
    base: Mapping[str, JsonValue], override: JsonValue
) -> dict[str, JsonValue]:
    """Fill *base* in beneath *override*, recursing so an override key that
    holds a dict keeps the siblings *base* declared under it. Leaves in
    *override* always win."""
    if not isinstance(override, dict):
        raise ValueError("Provider headers and extra_body must be JSON objects")
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_under(existing, value)
        else:
            merged[key] = value
    return merged


def _json_safe(value: JsonValue) -> JsonValue:
    """Drop NaN and Infinity. Postgres rejects them in JSONB, and these params
    ride to the message row, so one would fail the commit that saves the answer."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    return value


def _rejection_names_strippable_kwargs(error: Exception, strippable: set[str]) -> bool:
    """True when the 400's message names a kwarg a later attempt would drop.
    Unrelated 400s (context length, malformed input) must not be retried."""
    message = str(error).lower()
    return any(
        alias in message
        for key in strippable
        for alias in _KWARG_ERROR_ALIASES.get(key, (key,))
    )


def _rejection_demands_reasoning_none(error: Exception) -> bool:
    return _REASONING_NONE_DEMAND in str(error).lower()


def _litellm_bridges_tool_turn_to_responses(
    model: str, custom_llm_provider: str | None
) -> bool:
    """True when LiteLLM sends this chat call to the responses API once it
    carries tools and reasoning_effort. Mirrors `responses_api_bridge_check`."""
    from litellm.llms.openai.chat.gpt_5_transformation import OpenAIGPT5Config

    provider = custom_llm_provider or model.split("/")[0]
    return (
        provider in (LlmProviderNames.OPENAI, LlmProviderNames.AZURE)
        and "responses/" not in model
        and OpenAIGPT5Config.is_model_gpt_5_model(model)
        and not OpenAIGPT5Config.is_model_gpt_5_search_model(model)
        and OpenAIGPT5Config.is_model_gpt_5_4_plus_model(model)
    )


def _retry_attempts(
    kwargs: dict[str, JsonValue], required_keys: frozenset[str]
) -> list[dict[str, JsonValue]]:
    """The ladder: the kwargs as given, then without reasoning keys, then
    without every best-effort key, skipping steps that drop nothing."""
    attempts = [kwargs]
    for strip_keys in (_REASONING_KWARG_KEYS, _BEST_EFFORT_KWARG_KEYS):
        stripped = {
            k: v for k, v in kwargs.items() if k not in strip_keys or k in required_keys
        }
        if len(stripped) < len(attempts[-1]):
            attempts.append(stripped)
    return attempts


def _tools_with_strictness(
    tools: list[dict[str, JsonValue]], *, enabled: bool | None
) -> list[dict[str, JsonValue]]:
    """Copy tool flags without changing schemas; None omits the provider flag."""
    result: list[dict[str, JsonValue]] = []
    for tool in tools:
        function = tool.get("function")
        if not isinstance(function, dict):
            result.append(tool)
            continue
        function = {key: value for key, value in function.items() if key != "strict"}
        if enabled is not None:
            function["strict"] = enabled
        result.append({**tool, "function": function})
    return result


def _rejects_strict_tools(error: "BadRequestError") -> bool:
    """Recognize schema failures without treating unrelated 400s as strict failures."""
    body = error.body
    if isinstance(body, dict):
        details = body.get("error", body)
        if isinstance(details, dict):
            if details.get("code") == "invalid_function_parameters":
                return True
            param = details.get("param")
            if (
                isinstance(param, str)
                and param.startswith("tools")
                and param.endswith(".strict")
            ):
                return True
    message = str(error).lower()
    return "invalid_function_parameters" in message or any(
        phrase in message
        for phrase in (
            "invalid strict tool schema",
            "unsupported parameter: 'strict'",
            'unsupported parameter: "strict"',
        )
    )


class ProviderOperation(BaseModel):
    """Diagnostics for one provider call, including its retry attempts."""

    request_params: GenerationRequestParams | None = None


def _event_with_request_params(
    event: GenerationEvent, operation: ProviderOperation
) -> GenerationEvent:
    return event.model_copy(
        update={"request_params": copy.deepcopy(operation.request_params)}
    )


class _DeadlineCancellationSignal(CancellationSignal):
    def __init__(self, parent: CancellationSignal, timeout: float) -> None:
        super().__init__()
        self.parent = parent
        self.deadline = time.monotonic() + timeout

    def check(self) -> None:
        self.parent.check()
        if time.monotonic() >= self.deadline:
            raise LLMTimeoutError("Model generation exceeded its total timeout")
        super().check()


@contextmanager
def _generation_scope(context: GenerationContext) -> Iterator[CancellationSignal]:
    parent = context.cancellation or current_cancellation() or CancellationSignal()
    if context.total_timeout_s is None:
        with cancellation_scope(parent):
            parent.check()
            yield parent
        return
    signal = _DeadlineCancellationSignal(parent, context.total_timeout_s)
    with (
        parent.on_cancel(lambda: signal.cancel(parent.reason or "requested")),
        cancellation_scope(signal),
    ):
        parent.check()
        yield signal


@contextmanager
def _provider_scope(
    context: GenerationContext, llm: LLM
) -> Iterator[CancellationSignal]:
    from litellm.exceptions import ContextWindowExceededError, RateLimitError, Timeout
    from openai import APIError

    try:
        with _generation_scope(context) as signal:
            yield signal
    except ContextWindowExceededError as error:
        raise LLMContextLimitError("Model input exceeds its context limit") from error
    except Timeout as error:
        raise LLMTimeoutError(str(error)) from error
    except RateLimitError as error:
        raise LLMRateLimitError(str(error)) from error
    except APIError as error:
        # LiteLLM provider exceptions share the OpenAI SDK base class.
        info = litellm_exception_to_safe_error(error, llm)
        raise ClassifiedLLMError(
            client_error_msg=info.message,
            error_code=info.error_code,
            is_retryable=info.is_retryable,
        ) from error


def _as_onyx_llm_error(error: Exception) -> Exception:
    """Translate a litellm exception into the Onyx one callers catch.

    litellm raises a failure during a stream as ``MidStreamFallbackError`` (a
    ``ServiceUnavailableError``), including 429s. It keeps the real cause in
    ``original_exception``, but leaves ``__cause__`` empty and puts only a
    message in ``args``. Chat's error classifier follows ``__cause__``, so we
    set it on the wrapper, whether or not the cause maps to an Onyx error.

    A mapped error also has its ``__cause__`` set to the real cause, so raise
    the result without ``from``.
    """
    from litellm.exceptions import MidStreamFallbackError, RateLimitError, Timeout

    cause = error
    if isinstance(error, MidStreamFallbackError) and error.original_exception:
        cause = error.original_exception
        error.__cause__ = cause
    mapped: Exception
    if isinstance(cause, Timeout):
        mapped = LLMTimeoutError(cause)
    elif isinstance(cause, RateLimitError):
        mapped = LLMRateLimitError(cause)
    else:
        return error
    mapped.__cause__ = cause
    return mapped


def _consume_stream_until_deadline[T](stream: Iterable[T], deadline: float) -> list[T]:
    """Drain provider output within the invocation's remaining budget.

    Socket read timeouts bound the gap between packets, so keepalive pings
    can keep a call open indefinitely. Check the total deadline between chunks
    as well; this check alone can overshoot by up to one socket read timeout.
    """
    chunks: list[T] = []
    try:
        iterator = iter(stream)
        while True:
            check_cancelled()
            try:
                chunk = next(iterator)
            except StopIteration:
                check_cancelled()
                break
            check_cancelled()
            chunks.append(chunk)
            if time.monotonic() > deadline:
                raise LLMTimeoutError("LLM streaming call exceeded its total timeout")
    except Exception as error:
        check_cancelled()
        # The request itself succeeded, so _completion's mapping never saw this.
        raise _as_onyx_llm_error(error)
    return chunks


def _prompt_to_dicts(prompt: list[ChatCompletionMessage]) -> list[dict[str, JsonValue]]:
    """Convert Pydantic message models to dictionaries for LiteLLM.

    LiteLLM expects messages to be dictionaries (with .get() method),
    not Pydantic models. This function serializes the messages. A cache
    breakpoint travels on its message as `CACHE_BREAKPOINT_FLAG`, so it
    survives transforms that add or remove messages.
    """
    return [
        {
            **msg.model_dump(mode="json", exclude_none=True),
            CACHE_BREAKPOINT_FLAG: True,
        }
        if msg.cache_breakpoint
        else msg.model_dump(mode="json", exclude_none=True)
        for msg in prompt
    ]


def _normalize_content(raw: JsonValue) -> str:
    """Normalize a message content field to a plain string.

    Content can be a string, None, or a list of content-block dicts
    (e.g. [{"type": "text", "text": "..."}]).
    """
    if raw is None:
        return ""
    if isinstance(raw, str):
        return raw
    if isinstance(raw, list):
        return "\n".join(
            block.get("text", "") if isinstance(block, dict) else str(block)
            for block in raw
        )
    return str(raw)


# Providers not in this set forward the unknown `thinking_blocks` key verbatim,
# so strip it for them.
_THINKING_BLOCK_PROVIDERS = {
    LlmProviderNames.ANTHROPIC,
    LlmProviderNames.BEDROCK,
    LlmProviderNames.BEDROCK_CONVERSE,
    LlmProviderNames.VERTEX_AI,
}


def _strip_thinking_blocks_from_messages(
    messages: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    return [
        {key: value for key, value in msg.items() if key != "thinking_blocks"}
        for msg in messages
    ]


def _strip_tool_content_from_messages(
    messages: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Convert tool-related messages to plain text.

    Bedrock's Converse API requires toolConfig when messages contain
    toolUse/toolResult content blocks. When no tools are provided for the
    current request, we must convert any tool-related history into plain text
    to avoid the "toolConfig field must be defined" error.

    This is the same approach used by _OllamaHistoryMessageFormatter.
    """
    result: list[dict[str, JsonValue]] = []
    for msg in messages:
        role = msg.get("role")
        tool_calls = msg.get("tool_calls")

        if role == "assistant" and tool_calls:
            # Convert structured tool calls to text representation
            tool_call_lines = []
            calls = _PROVIDER_TOOL_CALLS.validate_python(tool_calls)
            for call in calls:
                name = call.function.name
                args = call.function.arguments
                tc_id = call.id
                tool_call_lines.append(
                    f"[Tool Call] name={name} id={tc_id} args={args}"
                )

            existing_content = _normalize_content(msg.get("content"))
            parts = (
                [existing_content] + tool_call_lines
                if existing_content
                else tool_call_lines
            )
            new_msg: dict[str, JsonValue] = {
                "role": "assistant",
                "content": "\n".join(parts),
            }
            result.append(new_msg)

        elif role == "tool":
            # Convert tool response to user message with text content
            tool_call_id = msg.get("tool_call_id", "")
            content = _normalize_content(msg.get("content"))
            tool_result_text = f"[Tool Result] id={tool_call_id}\n{content}"
            # Merge into previous user message if it is also a converted
            # tool result to avoid consecutive user messages (Bedrock requires
            # strict user/assistant alternation).
            previous_content = (
                _normalize_content(result[-1].get("content")) if result else ""
            )
            if (
                result
                and result[-1]["role"] == "user"
                and "[Tool Result]" in previous_content
            ):
                result[-1]["content"] = previous_content + "\n\n" + tool_result_text
            else:
                result.append({"role": "user", "content": tool_result_text})

        else:
            result.append(msg)

    return result


def _fix_tool_user_message_ordering(
    messages: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Insert a synthetic assistant message between tool and user messages.

    Some models (e.g. Mistral on Azure) require strict message ordering where
    a user message cannot immediately follow a tool message. This function
    inserts a minimal assistant message to bridge the gap.
    """
    if len(messages) < 2:
        return messages

    result: list[dict[str, JsonValue]] = [messages[0]]
    for msg in messages[1:]:
        prev_role = result[-1].get("role")
        curr_role = msg.get("role")
        if prev_role == "tool" and curr_role == "user":
            result.append({"role": "assistant", "content": "Noted. Continuing."})
        result.append(msg)
    return result


_MISTRAL_FAMILY_MARKERS: frozenset[str] = frozenset(
    prefix for prefix, vendor in MODEL_PREFIX_TO_VENDOR.items() if vendor == "mistral"
)


def _is_mistral_family_name(identity_names: list[str]) -> bool:
    """Whether any model/deployment identity name looks like a Mistral-family
    model (mistral, mixtral, codestral, ...). The provider name alone is not
    enough: Mistral models are frequently served behind Azure or
    OpenAI-compatible endpoints (e.g. vLLM), where only the configured names
    carry the signal."""
    return any(
        marker in name.lower()
        for name in identity_names
        for marker in _MISTRAL_FAMILY_MARKERS
    )


_JSON_SCHEMA_LITERAL_KEYS = frozenset({"const", "default", "enum", "examples"})


def _convert_type_arrays(schema: JsonValue) -> None:
    """Gemini takes one `type` per schema, so rewrite JSON Schema type arrays
    (e.g. ["string", "null"]) as `nullable` plus a single type or `anyOf`."""
    if isinstance(schema, list):
        for item in schema:
            _convert_type_arrays(item)
        return
    if not isinstance(schema, dict):
        return
    for key, value in schema.items():
        if key == "properties" and isinstance(value, dict):
            for property_schema in value.values():
                _convert_type_arrays(property_schema)
        elif key not in _JSON_SCHEMA_LITERAL_KEYS:
            _convert_type_arrays(value)
    type_value = schema.get("type")
    if not isinstance(type_value, list):
        return
    types = [t for t in type_value if isinstance(t, str) and t != "null"]
    if len(types) < len(type_value):
        schema["nullable"] = True
    if len(types) == 1:
        schema["type"] = types[0]
        return
    del schema["type"]
    if types and "anyOf" not in schema:
        schema["anyOf"] = [{"type": t} for t in types]


def _gemini_compatible_tools(
    tools: list[dict[str, JsonValue]],
) -> list[dict[str, JsonValue]]:
    """Gemini parses function parameters as its OpenAPI Schema subset and
    rejects other JSON Schema keywords (e.g. exclusiveMinimum) with a 400.
    LiteLLM's native Gemini route normalizes them to that subset, but
    OpenAI-compatible routes forward them as-is."""
    from litellm.litellm_core_utils.prompt_templates.common_utils import (
        DEFS_MAX_INLINED_BYTES,
        unpack_defs,
    )
    from litellm.llms.vertex_ai.common_utils import (
        add_object_type,
        convert_anyof_null_to_nullable,
        filter_schema_fields,
        process_items,
    )
    from litellm.types.llms.vertex_ai import Schema

    schema_fields = set(get_type_hints(Schema))
    sanitized = copy.deepcopy(tools)
    for tool in sanitized:
        function = tool.get("function")
        parameters = function.get("parameters") if isinstance(function, dict) else None
        if isinstance(function, dict) and isinstance(parameters, dict):
            original = copy.deepcopy(parameters)
            try:
                unpack_defs(
                    parameters,
                    parameters.pop("$defs", {}),
                    max_inlined_bytes=DEFS_MAX_INLINED_BYTES,
                )
                _convert_type_arrays(parameters)
                convert_anyof_null_to_nullable(parameters)
                process_items(parameters)
                add_object_type(parameters)
                function["parameters"] = filter_schema_fields(parameters, schema_fields)
            except (AttributeError, RecursionError, TypeError, ValueError) as e:
                # Schemas the LiteLLM helpers cannot parse (e.g. boolean
                # subschemas) go to the provider unchanged.
                logger.warning("Could not convert tool schema for Gemini: %s", e)
                function["parameters"] = original
    return sanitized


def _messages_contain_tool_content(messages: list[dict[str, JsonValue]]) -> bool:
    """Check if any messages contain tool-related content blocks."""
    for msg in messages:
        if msg.get("role") == "tool":
            return True
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return True
    return False


def _prompt_in_tool_loop(prompt: list[ChatCompletionMessage]) -> bool:
    """True when the latest assistant message called tools.

    With thinking on, Anthropic requires that message to start with its signed
    thinking block, which we cannot always replay. Earlier turns' thinking
    blocks are optional, so tool calls there do not matter.
    """
    from onyx.llm.model_request import AssistantMessage as ProviderAssistantMessage

    for msg in reversed(prompt):
        if isinstance(msg, ProviderAssistantMessage):
            return bool(msg.tool_calls)
    return False


@lru_cache(maxsize=None)
def _log_azure_responses_api_version_override(
    api_base: str | None, configured_api_version: str
) -> None:
    """Log once per provider config per process (LLM instances and calls are
    per-request, so unconditional logging here would fire on every LLM call)."""
    logger.warning(
        "Azure responses API calls for %s ignore the configured api_version %s: "
        "dated api-versions target the legacy /openai/responses surface, which "
        "some clouds (e.g. Azure Government) do not serve. These calls use "
        "LiteLLM's responses default instead (AZURE_DEFAULT_RESPONSES_API_VERSION, "
        "default 'preview'); the configured version still applies to "
        "chat-completions calls.",
        api_base,
        configured_api_version,
    )


@lru_cache(maxsize=None)
def _log_chat_completions_tools_disable_reasoning(
    model: str, api_base: str | None
) -> None:
    """Log once per model and api_base per process, for the same reason as
    `_log_azure_responses_api_version_override`."""
    logger.warning(
        "%s at %s is reached over chat completions, where GPT-5.4+ cannot "
        "combine function tools with reasoning. Tool-bearing requests send "
        "reasoning_effort=none. To keep reasoning, switch the provider to the "
        "responses API mode or use a model name the registry knows.",
        model,
        api_base,
    )


def _is_vertex_model_rejecting_stream_options(model_name: str) -> bool:
    normalized_model_name = model_name.lower()
    return any(
        blocked_model in normalized_model_name
        for blocked_model in _VERTEX_ANTHROPIC_MODELS_REJECTING_STREAM_OPTIONS
    )


def _env_injection_enabled() -> bool:
    # Deferred import: the security store pulls in the DB layer, which this
    # module must not import at module load.
    from onyx.server.security.store import llm_custom_config_env_injection_enabled

    return llm_custom_config_env_injection_enabled()


def _warn_dropped_env_only_keys(
    model_provider: str, dropped_keys: tuple[str, ...]
) -> None:
    logger.warning(
        "Dropping custom_config key(s) with no LiteLLM kwarg equivalent for "
        "provider %s (env injection is disabled on this deployment): %s",
        model_provider,
        list(dropped_keys),
    )


class LitellmLLM(LLM):
    """Generate assistant messages and expose provider responses for gateways."""

    def __init__(
        self,
        api_key: str | None,
        model_provider: str,
        model_name: str,
        max_input_tokens: int,
        api_base: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        custom_llm_provider: str | None = None,
        temperature: float | None = None,
        custom_config: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict[str, JsonValue] | None = LITELLM_EXTRA_BODY,
        model_kwargs: dict[str, JsonValue] | None = None,
        reasoning_effort_default: ReasoningEffort | None = None,
        reasoning_effort_user_default: ReasoningEffort | None = None,
        reasoning_effort_max: ReasoningEffort | None = None,
        supports_reasoning: bool = False,
        supports_images: bool | None = None,
        is_router: bool = False,
        model_configuration_id: int | None = None,
    ) -> None:
        # No instance-level timeout: invoke() and stream() each take their own,
        # so an instance default would be a second source of truth.
        self._temperature = GEN_AI_TEMPERATURE if temperature is None else temperature

        self._model_provider = model_provider
        self._model_version = model_name
        self._is_router = is_router
        self._model_configuration_id = model_configuration_id
        self._api_key = api_key
        self._deployment_name = deployment_name
        self._api_base = api_base
        self._api_version = api_version
        self._custom_llm_provider = custom_llm_provider
        self._max_input_tokens = max_input_tokens
        self._custom_config = (
            custom_config.copy() if custom_config is not None else None
        )
        self._reasoning_effort_default = reasoning_effort_default
        self._reasoning_effort_user_default = reasoning_effort_user_default
        self._reasoning_effort_max = reasoning_effort_max
        self._supports_reasoning = supports_reasoning

        self._api_surface = resolve_api_surface(model_provider, custom_config)

        # Create a dictionary for model-specific arguments if it's None
        model_kwargs = dict(model_kwargs or {})

        custom_config_mapping = map_custom_config_to_model_kwargs(
            model_provider=model_provider,
            custom_config=custom_config,
            api_key=api_key,
            api_base=api_base,
        )
        model_kwargs.update(custom_config_mapping.model_kwargs)
        # Keys with no LiteLLM kwarg equivalent. Injected into os.environ during
        # the call on deployments that allow it; dropped (with a warning at call
        # time) otherwise. UI-only form-state keys are neither injected nor
        # warned about.
        self._env_only_custom_config: dict[str, str] = {
            k: v
            for k, v in (custom_config or {}).items()
            if k not in custom_config_mapping.consumed_keys
            and k not in UI_ONLY_CONFIG_KEYS
        }

        # LM Studio: LiteLLM defaults to "fake-api-key" when no key is provided,
        # which LM Studio rejects. Ensure we always pass an explicit key (or empty
        # string) to prevent LiteLLM from injecting its fake default.
        if model_provider == LlmProviderNames.LM_STUDIO:
            model_kwargs.setdefault("api_key", "")

            # Users provide the server root (e.g. http://localhost:1234) but LiteLLM
            # needs /v1 for OpenAI-compatible calls.
            if self._api_base is not None:
                base = self._api_base.rstrip("/")
                self._api_base = base if base.endswith("/v1") else f"{base}/v1"
                model_kwargs["api_base"] = self._api_base

        # Default vertex_location to "global" if not provided for Vertex AI
        # Latest gemini models are only available through the global region
        if (
            model_provider == LlmProviderNames.VERTEX_AI
            and VERTEX_LOCATION_KWARG not in model_kwargs
        ):
            model_kwargs[VERTEX_LOCATION_KWARG] = "global"

        if self._api_surface in OPENAI_COMPATIBLE_SURFACES:
            self._custom_llm_provider = "openai"
            # LiteLLM's OpenAI client requires an api_key to be set.
            # Many OpenAI-compatible servers don't need auth, so supply a
            # placeholder to prevent LiteLLM from raising AuthenticationError.
            if not self._api_key:
                model_kwargs.setdefault("api_key", "not-needed")
            if self._api_base is not None:
                base = self._api_base.rstrip("/")
                self._api_base = base if base.endswith("/v1") else f"{base}/v1"
                model_kwargs["api_base"] = self._api_base
        elif self._api_surface is LlmApiSurface.ANTHROPIC_MESSAGES:
            # Base stays bare; LiteLLM appends /v1/messages itself.
            self._custom_llm_provider = "anthropic"
            if self._api_base is not None:
                self._api_base = self._api_base.rstrip("/")

        # This is needed for Ollama to do proper function calling
        if model_provider == LlmProviderNames.OLLAMA_CHAT and api_base is not None:
            model_kwargs["api_base"] = api_base
        # Deployment config merges under anything already in model_kwargs, so a
        # policy-supplied value wins. Incognito retention flags live here, and
        # replacing the dict would silently re-enable provider logging.
        if extra_headers:
            model_kwargs["extra_headers"] = _merge_under(
                extra_headers, model_kwargs.get("extra_headers") or {}
            )
        if extra_body:
            model_kwargs["extra_body"] = _merge_under(
                extra_body, model_kwargs.get("extra_body") or {}
            )

        self._model_kwargs = copy.deepcopy(model_kwargs)
        if supports_images is None:
            model_map: dict[str, dict[str, Any]] = get_model_map()
            identities: list[str] = resolve_model_identity_names(
                model_name, deployment_name
            )
            known: list[dict[str, Any] | None] = [
                find_model_obj(model_map, model_provider, name) for name in identities
            ]
            vision_values: list[bool | None] = [
                entry.get("supports_vision") for entry in known if entry
            ]
            if any(value is not None for value in vision_values):
                supports_images = any(vision_values)
        self._supports_images = supports_images

    def _routed_model(self, response_model: str | None) -> str | None:
        """Model a router served, when it differs from the configured name.
        LiteLLM prefixes some responses with the provider (openrouter/x/y)."""
        if not self._is_router or not response_model:
            return None
        model: str = response_model
        for prefix in (self._model_provider, self._custom_llm_provider):
            if (
                prefix
                and model.startswith(f"{prefix}/")
                and model != self._model_version
            ):
                model = model[len(prefix) + 1 :]
        return model if model != self._model_version else None

    def _track_llm_cost(self, usage: Usage, routed_model: str | None = None) -> None:
        """
        Track LLM usage cost for Onyx-managed API keys.

        This is called after every LLM call completes (streaming or non-streaming).
        Cost is only tracked if:
        1. Usage limits are enabled for this deployment
        2. The API key is one of Onyx's managed default keys
        """

        from onyx.server.usage_limits import is_usage_limits_enabled

        if not is_usage_limits_enabled():
            return

        from onyx.server.usage_limits import is_onyx_managed_api_key

        if not is_onyx_managed_api_key(self._api_key):
            return
        # Import here to avoid circular imports
        from onyx.db.engine.sql_engine import get_session_with_current_tenant
        from onyx.db.usage import UsageType, increment_usage

        provider = self._custom_llm_provider or self._model_provider

        try:
            with get_session_with_current_tenant() as db_session:
                input_cents, output_cents = compute_cost_cents(
                    model=self._model_version,
                    served_model=routed_model,
                    provider=provider,
                    model_configuration_id=self._model_configuration_id,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    cache_read_tokens=usage.cache_read_input_tokens,
                    cache_creation_tokens=usage.cache_creation_input_tokens,
                    db_session=db_session,
                )
                cost_cents = input_cents + output_cents
                if cost_cents <= 0:
                    return
                increment_usage(db_session, UsageType.LLM_COST, cost_cents)
                db_session.commit()
        except Exception as e:
            # Log but don't fail the LLM call if tracking fails
            logger.warning("Failed to track LLM cost: %s", e)

    def _completion(
        self,
        prompt: list[ChatCompletionMessage],
        tools: list[dict[str, JsonValue]] | None,
        tool_choice: ToolChoice | None,
        stream: bool,
        parallel_tool_calls: bool,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        structured_response_format: dict[str, JsonValue] | None = None,
        read_timeout_s: float = LLM_SOCKET_READ_TIMEOUT,
        max_tokens: int | None = None,
        user_identity: LLMUserIdentity | None = None,
        client: "HTTPHandler | None" = None,
        operation: ProviderOperation | None = None,
        manage_tool_strictness: bool = False,
        env_injection_enabled: bool | None = None,
        deadline: float | None = None,
    ) -> "LiteLLMModelResponse | CustomStreamWrapper":
        # Lazy loading to avoid memory bloat for non-inference flows
        from litellm.exceptions import BadRequestError

        from onyx.llm.litellm_singleton import litellm

        # One snapshot of the setting for the whole call. A caller that made a
        # decision on it (invoke's stream choice) passes its own value so the
        # two cannot diverge if an admin flips the setting mid-call.
        if env_injection_enabled is None:
            env_injection_enabled = _env_injection_enabled()

        #########################
        # Flags that modify the final arguments
        #########################
        model_identity_names = resolve_model_identity_names(
            self.config.model_name, self.config.deployment_name
        )
        is_claude_model = any("claude" in name.lower() for name in model_identity_names)
        uses_adaptive_thinking = any(
            anthropic_uses_adaptive_thinking(name) for name in model_identity_names
        )
        model_supports_anthropic_thinking = any(
            anthropic_supports_thinking(name) for name in model_identity_names
        )
        is_reasoning = (
            self.config.supports_reasoning
            or uses_adaptive_thinking
            or model_supports_anthropic_thinking
            or any(
                model_is_reasoning_model(name, self.config.model_provider)
                for name in model_identity_names
            )
        )
        # All OpenAI models will use responses API for consistency
        # Responses API is needed to get reasoning packets from OpenAI models
        is_openai_model = any(
            is_true_openai_model(self.config.model_provider, name)
            for name in model_identity_names
        )
        is_ollama = self._model_provider == LlmProviderNames.OLLAMA_CHAT
        is_mistral = self._model_provider == LlmProviderNames.MISTRAL
        is_vertex_ai = self._model_provider == LlmProviderNames.VERTEX_AI
        # Some Vertex Anthropic models reject stream_options. Reasoning params
        # are sent regardless: a provider that rejects one answers with a 400
        # naming the kwarg, which the retry ladder below strips.
        is_vertex_model_rejecting_stream_options = is_vertex_ai and any(
            _is_vertex_model_rejecting_stream_options(name)
            for name in model_identity_names
        )

        optional_kwargs: dict[str, JsonValue] = {}
        # Kwargs the provider requires, which the retry ladder must never strip.
        required_kwarg_keys: frozenset[str] = frozenset()

        # Model name
        is_openai_compatible_proxy = self._api_surface in OPENAI_COMPATIBLE_SURFACES
        model_provider = (
            f"{self.config.model_provider}/responses"
            if is_openai_model  # Uses litellm's completions -> responses bridge
            else self.config.model_provider
        )

        # Azure responses-bridge calls must target the v1 responses surface:
        # with a dated api-version, LiteLLM builds the legacy /openai/responses
        # URL, which sovereign clouds (e.g. Azure Government) do not serve
        # (#11420). Dropping the dated version lets LiteLLM apply its responses
        # default (AZURE_DEFAULT_RESPONSES_API_VERSION env var, default
        # "preview"), which routes to /openai/v1/responses — working on all
        # clouds with reasoning summaries intact. Admin-configured v1 versions
        # ("preview"/"latest"/"v1") pass through, and the dated version still
        # applies to every non-bridge call (e.g. Azure chat completions).
        api_version = self._api_version or None
        if (
            is_openai_model
            and self._model_provider == LlmProviderNames.AZURE
            and api_version is not None
            and api_version not in _AZURE_V1_API_VERSIONS
        ):
            _log_azure_responses_api_version_override(self._api_base, api_version)
            api_version = None

        model_bare = self.config.deployment_name or self.config.model_name
        if self._api_surface is LlmApiSurface.OPENAI_RESPONSES:
            # Drives LiteLLM's completions -> responses bridge.
            model = f"responses/{model_bare}"
        elif self._api_surface is not None:
            model = model_bare
        else:
            model = f"{model_provider}/{model_bare}"

        # Tool choice
        # Downgrade tool_choice=required to AUTO for models that mishandle it:
        # Claude skips reasoning when it's set, Qwen thinking models reject it
        # with a 400, and Z.AI rejects any GLM tool_choice other than auto
        # ("Tool choice must be auto"). Shared response decoding attempts
        # to recover tool calls from text. Matched by model name
        # rather than `is_reasoning` because the litellm/local registry lags
        # behind new Qwen/GLM releases (e.g. qwen3.7-plus, glm-5.3).
        # Shared requests adapt named choices in _prepare_tools. Raw callers
        # retain their explicit named choice and its provider validation.
        if model_prefers_auto_tool_choice(model_identity_names) and (
            tool_choice == ToolChoiceOptions.REQUIRED
        ):
            tool_choice = ToolChoiceOptions.AUTO

        # These native adapters drop NONE. Omit schemas but retain history;
        # Onyx or LiteLLM serializes prior calls and results for each provider.
        if tool_choice == ToolChoiceOptions.NONE and self._model_provider in {
            LlmProviderNames.BEDROCK,
            LlmProviderNames.BEDROCK_CONVERSE,
            LlmProviderNames.OLLAMA,
            LlmProviderNames.OLLAMA_CHAT,
        }:
            tools = None

        # If no tools are provided, tool_choice should be None
        if not tools:
            tool_choice = None

        # Temperature
        # Some models (e.g. Claude Opus 4.7/4.8) reject a non-default
        # temperature with a 400 invalid_request_error. For those models we
        # must omit the param entirely.
        # LiteLLM's drop_params is not reliable here because the upstream
        # provider config can still claim the param is supported.
        # https://github.com/BerriAI/litellm/issues/26444
        # TODO(acaprau): Consider removing this once the above is resolved,
        # although this assumes users have upgraded their litellm if relevant.
        omits_sampling_params = any(
            anthropic_omits_sampling_params(name) for name in model_identity_names
        )
        if not omits_sampling_params:
            optional_kwargs["temperature"] = 1 if is_reasoning else self._temperature

        if stream and not is_vertex_model_rejecting_stream_options:
            optional_kwargs["stream_options"] = {"include_usage": True}

        # Settle before anything reads it, so every branch below and tracing
        # see the same effort the provider will.
        reasoning_effort = resolve_reasoning_effort(
            reasoning_effort,
            default=self.config.reasoning_effort_default,
            user_default=self.config.reasoning_effort_user_default,
            maximum=self.config.reasoning_effort_max,
        )

        litellm_bridges_tool_turn = bool(
            tools
        ) and _litellm_bridges_tool_turn_to_responses(model, self._custom_llm_provider)

        # Tool turns over chat completions for GPT-5.4+ trade reasoning for a
        # working call. Responses routes, registry bridge included, are exempt.
        if (
            tools
            and not is_openai_model
            and not litellm_bridges_tool_turn
            and (
                self._api_surface is LlmApiSurface.OPENAI_CHAT_COMPLETIONS
                or self._model_provider in OPENAI_API_PROVIDERS
            )
            and any(
                openai_chat_tools_require_reasoning_none(name)
                for name in model_identity_names
            )
        ):
            reasoning_effort = ReasoningEffort.OFF
            optional_kwargs["reasoning_effort"] = _OPENAI_REASONING_NONE
            required_kwarg_keys = frozenset({"reasoning_effort"})
            _log_chat_completions_tools_disable_reasoning(model, self._api_base)

        reasoning_style = resolve_reasoning_param_style(
            self.config.model_provider,
            model_identity_names,
            self._api_surface,
        )

        # Always-thinking Claude models accept no off spelling, so off there
        # means the least reasoning they take rather than the API's default.
        if (
            reasoning_effort is ReasoningEffort.OFF
            and reasoning_style is ReasoningParamStyle.ANTHROPIC_ADAPTIVE
            and anthropic_identity_is_always_thinking(model_identity_names)
        ):
            reasoning_effort = ReasoningEffort.LOW

        if (
            reasoning_effort is ReasoningEffort.OFF
            and reasoning_style is ReasoningParamStyle.LITELLM_EFFORT
            and any(
                gemini_lowest_thinking_level_is_low(name)
                for name in model_identity_names
            )
        ):
            reasoning_effort = ReasoningEffort.LOW

        # The tools block above already forced reasoning_effort "none".
        sends_explicit_reasoning_none = (
            reasoning_effort is ReasoningEffort.OFF
            and "reasoning_effort" not in optional_kwargs
            and any(
                openai_model_supports_reasoning_none(name)
                for name in model_identity_names
            )
        )

        # Note, there is a reasoning_effort parameter in LiteLLM but it is completely jank and does not work for any
        # of the major providers. Not setting it sets it to OFF.
        if (
            is_reasoning
            # The default of this parameter not set is surprisingly not the equivalent of an Auto but is actually Off
            and (
                reasoning_effort != ReasoningEffort.OFF or sends_explicit_reasoning_none
            )
            and not any(
                openai_model_rejects_reasoning_effort(name)
                for name in model_identity_names
            )
        ):
            openai_style_reasoning: dict[str, str] = {
                "effort": OPENAI_REASONING_EFFORT[reasoning_effort],
            }
            if not sends_explicit_reasoning_none:
                openai_style_reasoning["summary"] = "auto"

            if reasoning_style is ReasoningParamStyle.OPENAI:
                if is_claude_model:
                    # Only a gateway routes Claude here, and it still translates
                    # to Anthropic, so the signed-thinking-block constraint
                    # described below applies to these requests too.
                    send_reasoning = not _prompt_in_tool_loop(prompt)
                else:
                    # OpenAI API does not accept reasoning params for GPT 5 chat
                    # models (neither reasoning nor reasoning_effort are accepted)
                    # even though they are reasoning models (bug in OpenAI)
                    send_reasoning = not any(
                        openai_chat_variant_rejects_reasoning(name)
                        for name in model_identity_names
                    )
                if send_reasoning:
                    optional_kwargs["reasoning"] = openai_style_reasoning
                    if (
                        sends_explicit_reasoning_none
                        and self.config.model_provider == LlmProviderNames.OPENAI
                    ):
                        # A retry without "none" runs at the medium default.
                        # Gateways may reject "none", so only OpenAI itself
                        # pins it.
                        required_kwarg_keys = required_kwarg_keys | {"reasoning"}

            elif reasoning_style in (
                ReasoningParamStyle.ANTHROPIC_ADAPTIVE,
                ReasoningParamStyle.ANTHROPIC_BUDGET,
            ):
                # Thinking is sent on every request of the tool loop. Anthropic
                # and Bedrock accept a tool-call message without thinking
                # blocks, and LiteLLM's drop of the param is patched out
                # (_patch_anthropic_keeps_requested_thinking).
                if reasoning_style is ReasoningParamStyle.ANTHROPIC_ADAPTIVE:
                    # No signed blocks to lose, and without it Claude 5 picks
                    # its own effort rather than ours.
                    optional_kwargs["output_config"] = {
                        "effort": ANTHROPIC_ADAPTIVE_REASONING_EFFORT[reasoning_effort],
                    }
                    optional_kwargs["thinking"] = {"type": "adaptive"}
                else:
                    budget_tokens: int | None = ANTHROPIC_REASONING_EFFORT_BUDGET.get(
                        reasoning_effort
                    )
                    # thinking.type=enabled is rejected alongside a forced
                    # tool_choice (only adaptive thinking supports forced tool
                    # use), so skip thinking for a NamedToolChoice.
                    if budget_tokens is not None and not isinstance(
                        tool_choice, NamedToolChoice
                    ):
                        if max_tokens is not None:
                            response_reserve = max(1, GEN_AI_NUM_RESERVED_OUTPUT_TOKENS)
                            budget_tokens = min(
                                budget_tokens, max_tokens - response_reserve
                            )
                        if budget_tokens >= _ANTHROPIC_MIN_THINKING_BUDGET_TOKENS:
                            optional_kwargs["thinking"] = {
                                "type": "enabled",
                                "budget_tokens": budget_tokens,
                            }
                        else:
                            logger.warning(
                                "Skipping Anthropic thinking: max_tokens=%s cannot "
                                "fit the minimum thinking budget and answer reserve",
                                max_tokens,
                            )

            else:
                # Hope for the best from LiteLLM
                if reasoning_effort in [
                    ReasoningEffort.LOW,
                    ReasoningEffort.MEDIUM,
                    ReasoningEffort.HIGH,
                ]:
                    optional_kwargs["reasoning_effort"] = reasoning_effort.value
                elif reasoning_effort is ReasoningEffort.XHIGH:
                    # Provider mappings behind litellm's reasoning_effort are
                    # uneven (Gemini raises on xhigh), clamp to high. The model
                    # picker greys the level out for these models, so reaching
                    # here means a stored override outliving a model switch.
                    optional_kwargs["reasoning_effort"] = ReasoningEffort.HIGH.value
                elif reasoning_effort is ReasoningEffort.OFF:
                    optional_kwargs["reasoning_effort"] = _OPENAI_REASONING_NONE
                else:
                    optional_kwargs["reasoning_effort"] = ReasoningEffort.MEDIUM.value

        # The bridge keys on reasoning_effort, which also takes the summary.
        # Without one the call stays on chat completions and fails.
        if litellm_bridges_tool_turn:
            if "reasoning_effort" not in optional_kwargs:
                optional_kwargs["reasoning_effort"] = optional_kwargs.pop(
                    "reasoning", _OPENAI_REASONING_NONE
                )
            required_kwarg_keys = required_kwarg_keys | {"reasoning_effort"}

        # Claude 5 thinks unless told not to, and 4.7/4.8 take the same param.
        # No effort with it, which Opus 5 and Sonnet 5.5 cap, and no signed-block
        # guard like the sibling branch: that one binds only while thinking is on.
        # Sonnet 5.5 spells off as between_tools.
        if (
            is_reasoning
            and reasoning_effort is ReasoningEffort.OFF
            and reasoning_style is ReasoningParamStyle.ANTHROPIC_ADAPTIVE
        ):
            off_type: str = (
                "between_tools"
                if anthropic_identity_turns_thinking_off_between_tools(
                    model_identity_names
                )
                else "disabled"
            )
            optional_kwargs["thinking"] = {"type": off_type}

        if tools:
            # OpenAI will error if parallel_tool_calls is True and tools are not specified
            optional_kwargs["parallel_tool_calls"] = parallel_tool_calls

        if structured_response_format:
            optional_kwargs["response_format"] = structured_response_format

        if (
            not (is_claude_model or is_ollama or is_mistral)
            or is_openai_compatible_proxy
        ):
            # Litellm bug: tool_choice is dropped silently if not specified here for OpenAI
            # However, this param breaks Anthropic and Mistral models,
            # so it must be conditionally included unless the request is
            # routed through Bifrost's OpenAI-compatible endpoint.
            # Additionally, tool_choice is not supported by Ollama and causes warnings if included.
            # See also, https://github.com/ollama/ollama/issues/11171
            optional_kwargs["allowed_openai_params"] = ["tool_choice"]
            # drop_params removes reasoning_effort for any model LiteLLM does
            # not list as a reasoning model, e.g. Gemini behind a gateway.
            # It also drops the explicit "none" the chat-completions tool-turn
            # path forces (e.g. a new model the release catalog does not know
            # yet). OpenAI then applies its default effort and rejects the
            # tool call, so a required reasoning_effort must stay allowed.
            if "reasoning_effort" in optional_kwargs and (
                is_openai_compatible_proxy or "reasoning_effort" in required_kwarg_keys
            ):
                optional_kwargs["allowed_openai_params"].append("reasoning_effort")

        # Passthrough kwargs
        passthrough_kwargs = build_litellm_passthrough_kwargs(
            model_kwargs=dict(self._model_kwargs),
            user_identity=user_identity,
        )

        # Match LiteLLM's api_base-over-base_url precedence, including custom config.
        base_url = passthrough_kwargs.pop("base_url", self._api_base) or None
        # OpenRouter: inject session_id and user into extra_body.
        #
        # session_id — sticky routing: pins all turns of a conversation to the
        # same upstream provider, enabling prompt cache hits across turns.
        # Without this, OpenRouter may alternate between e.g. Anthropic and Google
        # for the same model, causing cache misses on every other turn.
        # See: https://openrouter.ai/docs/features/provider-routing#session-id
        #
        # user — activity tracking: OpenRouter reads the user identifier from
        # extra_body for its per-user activity logs; the top-level LiteLLM
        # `user` parameter is forwarded to the upstream model but is not picked
        # up by OpenRouter's own tracking dashboard.
        #
        # Both are gated on SEND_USER_METADATA_TO_LLM_PROVIDER: an operator who
        # opted out of sending session/user identifiers to providers should not
        # have them forwarded to OpenRouter either.
        if (
            SEND_USER_METADATA_TO_LLM_PROVIDER
            and self._model_provider == LlmProviderNames.OPENROUTER
            and user_identity is not None
        ):
            extra_body_updates: dict[str, str] = {}
            if user_identity.session_id:
                extra_body_updates["session_id"] = user_identity.session_id
            if user_identity.user_id:
                extra_body_updates["user"] = user_identity.user_id
            if extra_body_updates:
                existing_extra_body = passthrough_kwargs.get("extra_body") or {}
                if isinstance(existing_extra_body, dict):
                    passthrough_kwargs["extra_body"] = {
                        **existing_extra_body,
                        **extra_body_updates,
                    }
                else:
                    logger.warning(
                        "OpenRouter extra_body injection: extra_body is not a dict (%s), "
                        "skipping session_id/user injection",
                        type(existing_extra_body).__name__,
                    )

        try:
            # NOTE: must pass in None instead of empty strings otherwise litellm
            # can have some issues with bedrock.
            # NOTE: Sometimes _model_kwargs may have an "api_key" kwarg
            # depending on what the caller passes in for custom_config. If it
            # does we allow it to clobber _api_key.
            if "api_key" not in passthrough_kwargs:
                passthrough_kwargs["api_key"] = self._api_key or None

            messages = _prompt_to_dicts(prompt)

            if not (
                is_claude_model
                and (
                    self._model_provider in _THINKING_BLOCK_PROVIDERS
                    or self._api_surface is LlmApiSurface.ANTHROPIC_MESSAGES
                )
            ):
                messages = _strip_thinking_blocks_from_messages(messages)

            # Bedrock's Converse API requires toolConfig when messages
            # contain toolUse/toolResult content blocks. When no tools are
            # provided for this request but the history contains tool
            # content from previous turns, strip it to plain text.
            is_bedrock = self._model_provider in {
                LlmProviderNames.BEDROCK,
                LlmProviderNames.BEDROCK_CONVERSE,
            }
            if is_bedrock and not tools and _messages_contain_tool_content(messages):
                messages = _strip_tool_content_from_messages(messages)

            # Some models (e.g. Mistral) reject a user message
            # immediately after a tool message. Insert a synthetic
            # assistant bridge message to satisfy the ordering
            # constraint. Check the provider, the LiteLLM routing
            # override, and every identity name (deployment alias and
            # model name) to catch Mistral served behind Azure or
            # OpenAI-compatible endpoints (e.g. vLLM).
            is_mistral_model = (
                is_mistral
                or self._custom_llm_provider == LlmProviderNames.MISTRAL
                or _is_mistral_family_name(model_identity_names)
            )
            if is_mistral_model:
                messages = _fix_tool_user_message_ordering(messages)

            if (
                tools
                and self._api_surface in OPENAI_COMPATIBLE_SURFACES
                and any("gemini" in name.lower() for name in model_identity_names)
            ):
                tools = _gemini_compatible_tools(tools)

            # Only pass tool_choice when tools are present — some providers (e.g. Fireworks)
            # reject requests where tool_choice is explicitly null.
            if tools and tool_choice is not None:
                if isinstance(tool_choice, NamedToolChoice):
                    optional_kwargs["tool_choice"] = {
                        "type": "function",
                        "function": {"name": tool_choice.name},
                    }
                else:
                    optional_kwargs["tool_choice"] = tool_choice

            if not env_injection_enabled and self._env_only_custom_config:
                _warn_dropped_env_only_keys(
                    self._model_provider,
                    tuple(sorted(self._env_only_custom_config)),
                )

            def _attempt_timeout() -> float:
                # The retry ladder below can make several requests. With a
                # deadline, each one gets only the time left, so retries cannot
                # stretch invoke() past its total timeout.
                if deadline is None:
                    return read_timeout_s
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise LLMTimeoutError("LLM call exceeded its total timeout")
                return min(read_timeout_s, remaining)

            # Cache options are retry policy, including caller-supplied options.
            configured_cache_options = passthrough_kwargs.pop(
                "prompt_cache_options", None
            )
            if configured_cache_options is not None:
                optional_kwargs["prompt_cache_options"] = configured_cache_options
            cache_messages = messages
            cache_options = None
            if is_openai_model or self._api_surface is LlmApiSurface.OPENAI_RESPONSES:
                cache_messages, cache_options = explicit_cache_breakpoints(messages)
            messages = without_cache_breakpoint_flags(messages)
            if cache_options is not None:
                optional_kwargs.setdefault("prompt_cache_options", cache_options)

            strict_disabled = False
            strict_model = (
                bool(tools)
                and manage_tool_strictness
                and self._model_provider == LlmProviderNames.OPENAI
                and not model_bare.startswith("ft:")
                and is_true_openai_model(LlmProviderNames.OPENAI, model_bare)
                and (
                    find_model_obj(get_model_map(), LlmProviderNames.OPENAI, model_bare)
                    or {}
                ).get("supports_function_calling")
                is True
            )

            unmarked_tools = (
                _tools_with_strictness(tools, enabled=None)
                if tools and manage_tool_strictness
                else tools
            )
            non_strict_tools = (
                _tools_with_strictness(tools, enabled=False)
                if tools and strict_model
                else tools
            )

            # Provider 400s degrade to provider defaults with a warning instead
            # of failing the message, or learn the "none" a provider demands.
            attempts = _retry_attempts(optional_kwargs, required_kwarg_keys)
            for i, opts in enumerate(attempts):
                check_cancelled()
                opts = dict(opts)
                # Eligibility and dispatch share the lock for this attempt only.
                env_ctx: AbstractContextManager[None] = (
                    temporary_env_and_lock(
                        self._env_only_custom_config, deadline=deadline
                    )
                    if env_injection_enabled
                    else nullcontext()
                )
                selected_tools = tools
                strict_attempt = False
                try:
                    with env_ctx:
                        from litellm.integrations.anthropic_cache_control_hook import (
                            targets_openai_api,
                        )

                        effective_base = passthrough_kwargs.get("api_base") or base_url
                        if manage_tool_strictness:
                            selected_tools = unmarked_tools
                            if strict_model and targets_openai_api(effective_base):
                                selected_tools = (
                                    non_strict_tools if strict_disabled else tools
                                )
                                strict_attempt = not strict_disabled and any(
                                    isinstance(function := tool.get("function"), dict)
                                    and function.get("strict") is True
                                    for tool in (tools or [])
                                )
                        attempt_messages = messages
                        if cache_options is not None and "prompt_cache_options" in opts:
                            effective_base = (
                                passthrough_kwargs.get("api_base") or base_url
                            )
                            if uses_explicit_cache_breakpoints(
                                model_identity_names,
                                effective_base
                                if isinstance(effective_base, str)
                                else None,
                                azure=self._model_provider == LlmProviderNames.AZURE,
                            ):
                                configured = opts["prompt_cache_options"]
                                if not isinstance(configured, dict):
                                    raise ValueError(
                                        "prompt_cache_options must be a JSON object"
                                    )
                                opts["prompt_cache_options"] = {
                                    **configured,
                                    **cache_options,
                                }
                                attempt_messages = cache_messages
                            elif configured_cache_options is None:
                                opts.pop("prompt_cache_options")

                        # Last write wins: sent_kwargs holds what the returning (or
                        # final failing) attempt sent, reasoning_effort the effective
                        # intent. One dict, two sinks, so they cannot drift.
                        request_params = GenerationRequestParams(
                            model_name=self.config.model_name,
                            model_provider=self.config.model_provider,
                            reasoning_effort=reasoning_effort,
                            max_tokens=max_tokens,
                            sent_kwargs={
                                k: _json_safe(opts[k])
                                for k in sorted(_BEST_EFFORT_KWARG_KEYS & opts.keys())
                            },
                        )
                        record_llm_request_params(request_params)
                        if operation is not None:
                            operation.request_params = request_params
                        timeout = _attempt_timeout()
                        check_cancelled()
                        # LiteLLM's overloads do not express the stream flag's return type.
                        return cast(
                            "LiteLLMModelResponse | CustomStreamWrapper",
                            litellm.completion(
                                model=model,
                                base_url=base_url,
                                api_version=api_version,
                                custom_llm_provider=self._custom_llm_provider or None,
                                messages=attempt_messages,
                                # None (omitted) rather than [] — some OpenAI-compatible
                                # servers reject requests with an empty tools array.
                                tools=selected_tools or None,
                                stream=stream,
                                timeout=timeout,
                                max_tokens=max_tokens,
                                client=client,
                                **opts,
                                **passthrough_kwargs,
                            ),
                        )
                except BadRequestError as e:
                    check_cancelled()
                    if strict_attempt and _rejects_strict_tools(e):
                        strict_disabled = True
                        attempts.insert(i + 1, dict(opts))
                        logger.warning(
                            "OpenAI rejected strict tools; retrying without strict enforcement"
                        )
                        continue
                    if (
                        _rejection_demands_reasoning_none(e)
                        and opts.get("reasoning_effort") != _OPENAI_REASONING_NONE
                    ):
                        # A name the version gate cannot place learns "none" from
                        # the 400 itself, one round trip late. Rebuilt attempts all
                        # carry it, so the loop picks up the tail and this fires once.
                        reasoning_effort = ReasoningEffort.OFF
                        forced = {
                            k: v
                            for k, v in opts.items()
                            if k not in _REASONING_KWARG_KEYS
                        } | {"reasoning_effort": _OPENAI_REASONING_NONE}
                        attempts[i + 1 :] = _retry_attempts(
                            forced, required_kwarg_keys | {"reasoning_effort"}
                        )
                        _log_chat_completions_tools_disable_reasoning(
                            model, self._api_base
                        )
                    elif (
                        "prompt_cache_options" in opts
                        and _rejection_names_strippable_kwargs(
                            e, {"prompt_cache_options"}
                        )
                    ):
                        # A cache rejection must preserve the user's reasoning choice.
                        without_cache = {
                            k: v for k, v in opts.items() if k != "prompt_cache_options"
                        }
                        attempts[i + 1 :] = _retry_attempts(
                            without_cache, required_kwarg_keys
                        )
                    elif i == len(attempts) - 1:
                        raise
                    elif not _rejection_names_strippable_kwargs(
                        e, set(opts) - set(attempts[-1])
                    ):
                        raise
                    logger.warning(
                        "Provider rejected request for model %s. Retrying with %s: %s",
                        model,
                        sorted(_BEST_EFFORT_KWARG_KEYS & attempts[i + 1].keys()),
                        e,
                    )
            raise RuntimeError("Provider retry attempts exhausted")
        except Exception as e:
            check_cancelled()
            raise _as_onyx_llm_error(e)

    def redact_error(self, text: str) -> str:
        config = self.config
        credentials = collect_credential_values(config.api_key, config.custom_config)
        # custom_config can map a key to model_kwargs["api_key"] under a name
        # that is_sensitive_custom_config_key does not match.
        effective_key = self._model_kwargs.get("api_key")
        if isinstance(effective_key, str):
            credentials.append(effective_key)
        return scrub_sensitive_values(text, credentials)

    @property
    def config(self) -> LLMConfig:
        return LLMConfig(
            model_provider=self._model_provider,
            model_name=self._model_version,
            temperature=self._temperature,
            api_key=self._api_key,
            api_base=self._api_base,
            api_version=self._api_version,
            deployment_name=self._deployment_name,
            custom_config=self._custom_config,
            supports_images=self._supports_images,
            max_input_tokens=self._max_input_tokens,
            reasoning_effort_default=self._reasoning_effort_default,
            reasoning_effort_user_default=self._reasoning_effort_user_default,
            reasoning_effort_max=self._reasoning_effort_max,
            supports_reasoning=self._supports_reasoning,
            model_configuration_id=self._model_configuration_id,
        )

    def _uses_isolated_client(self) -> bool:
        """Providers whose sync calls need a fresh per-call HTTPHandler instead of
        litellm's shared module_level_client (see threading notes in invoke())."""
        return any(
            is_true_openai_model(self.config.model_provider, name)
            for name in resolve_model_identity_names(
                self.config.model_name, self.config.deployment_name
            )
        ) or self.config.model_provider in (
            LlmProviderNames.ANTHROPIC,
            LlmProviderNames.BEDROCK,
            LlmProviderNames.BEDROCK_CONVERSE,
        )

    def invoke_raw(
        self,
        prompt: list[ChatCompletionMessage],
        tools: list[dict[str, JsonValue]] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict[str, JsonValue] | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_s: float = LLM_INVOKE_TIMEOUT_S,
        operation: ProviderOperation | None = None,
        manage_tool_strictness: bool = False,
    ) -> ModelResponse:
        """One complete provider response within ``total_timeout_s``.

        The caller owns the generation span. Use ``invoke`` for shared messages.

        Sends one plain request, so the socket read timeout is the whole budget.
        Calls that inject custom_config into the environment stream and reassemble
        to release the write lock after connection setup. Other calls use a plain
        request and hold a shared read lock when injection is enabled. The deadline
        includes lock acquisition and applies between chunks for streamed calls.
        """
        from litellm import HTTPHandler
        from litellm import ModelResponse as LiteLLMModelResponse

        from onyx.llm.model_response import (
            from_litellm_model_response,
            served_model_from_litellm_response,
        )

        # HTTPHandler Threading & Connection Pool Notes:
        # =============================================
        # We create an isolated HTTPHandler ONLY for true OpenAI models (not OpenAI-compatible
        # providers like glm-4.7, DeepSeek, etc.). This distinction is critical:
        #
        # 1. WHY ONLY TRUE OPENAI MODELS:
        #    - True OpenAI models use litellm's "responses API" path which expects HTTPHandler
        #    - OpenAI-compatible providers (model_provider="openai" with non-OpenAI models)
        #      use the standard completion path which expects OpenAI SDK client objects
        #    - Passing HTTPHandler to OpenAI-compatible providers causes:
        #      AttributeError: 'HTTPHandler' object has no attribute 'api_key'
        #      (because _get_openai_client() calls openai_client.api_key on line ~929)
        #
        # 2. WHY ISOLATED HTTPHandler FOR OPENAI:
        #    - Prevents "Bad file descriptor" errors when multiple threads stream concurrently
        #    - Shared connection pools can have stale connections or abandoned streams that
        #      corrupt the pool state for other threads
        #    - Each request gets its own fresh httpx.Client via HTTPHandler
        #
        # 3. WHY ANTHROPIC AND BEDROCK ALSO GET AN ISOLATED CLIENT:
        #    - An abandoned sync stream is finalized by GC, which can fire on a thread
        #      already inside the shared pool's non-reentrant lock and deadlock it,
        #      wedging all later LLM calls (encode/httpcore#996; seen in prod).
        #    - A per-call client keeps abandoned streams off the shared pool. The
        #      litellm anthropic and bedrock handlers both use module_level_client
        #      only when client is None.
        #
        # 4. PITFALL - is_true_openai_model() CHECK:
        #    - Must use is_true_openai_model() NOT just check model_provider == "openai"
        #    - Many OpenAI-compatible providers set model_provider="openai" but are NOT true
        #      OpenAI models (glm-4.7, DeepSeek, local proxies, etc.)
        #    - is_true_openai_model() checks both provider AND model name patterns
        #
        # This note may not be entirely accurate as there is a lot of complexity in the LiteLLM codebase around this
        # and not every model path was traced thoroughly. It is also possible that in future versions of LiteLLM
        # they will realize that their OpenAI handling is not threadsafe. Hope they will just fix it.
        deadline = time.monotonic() + total_timeout_s
        env_injection_enabled = _env_injection_enabled()
        use_stream = env_injection_enabled and bool(self._env_only_custom_config)
        read_timeout = max(1, math.ceil(total_timeout_s))

        client = None
        if self._uses_isolated_client():
            client = HTTPHandler(timeout=read_timeout)

        try:
            raw_response = self._completion(
                prompt=prompt,
                tools=tools,
                tool_choice=tool_choice,
                stream=use_stream,
                structured_response_format=structured_response_format,
                read_timeout_s=read_timeout,
                max_tokens=max_tokens,
                parallel_tool_calls=True,
                reasoning_effort=reasoning_effort,
                user_identity=user_identity,
                client=client,
                operation=operation,
                manage_tool_strictness=manage_tool_strictness,
                env_injection_enabled=env_injection_enabled,
                deadline=deadline,
            )
            if use_stream:
                from litellm import CustomStreamWrapper as LiteLLMCustomStreamWrapper
                from litellm import stream_chunk_builder

                chunks = _consume_stream_until_deadline(
                    cast(LiteLLMCustomStreamWrapper, raw_response), deadline
                )
                # stream_chunk_builder returns None for an empty stream. Without
                # this the cast would hide it until an AttributeError downstream.
                built = stream_chunk_builder(chunks)
                if built is None:
                    raise ValueError(
                        f"LLM {self.config.model_name} returned an empty stream"
                    )
                response = cast(LiteLLMModelResponse, built)
                # stream_chunk_builder reports the requested model; keep the served one
                served_model: str | None = next(
                    (
                        m
                        for m in (
                            served_model_from_litellm_response(c.model_dump())
                            for c in chunks
                        )
                        if m
                    ),
                    None,
                )
                if served_model:
                    response.model = served_model
            else:
                response = cast(LiteLLMModelResponse, raw_response)

            model_response = from_litellm_model_response(response)

            routed_model: str | None = self._routed_model(model_response.model)
            if routed_model:
                record_llm_routed_model(routed_model)
            # Track LLM cost for Onyx-managed API keys
            if model_response.usage:
                self._track_llm_cost(model_response.usage, routed_model)

            return model_response
        finally:
            if client is not None:
                client.close()

    def stream_raw(
        self,
        prompt: list[ChatCompletionMessage],
        tools: list[dict[str, JsonValue]] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict[str, JsonValue] | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        stall_timeout_s: int = LLM_SOCKET_READ_TIMEOUT,
        operation: ProviderOperation | None = None,
        manage_tool_strictness: bool = False,
    ) -> Iterator[ModelResponseStream]:
        """Yield provider chunks as they arrive; the caller owns the generation span.

        ``stall_timeout_s`` bounds the gap between deltas, not the whole run. A
        stream takes no total timeout: its consumer sees progress and owns the
        end-to-end deadline, and some runs (deep research reports) take many
        minutes.
        """
        from litellm import CustomStreamWrapper as LiteLLMCustomStreamWrapper
        from litellm import HTTPHandler
        from litellm.exceptions import APIConnectionError as LiteLLMAPIConnectionError
        from litellm.exceptions import InternalServerError as LiteLLMInternalServerError
        from litellm.exceptions import (
            ServiceUnavailableError as LiteLLMServiceUnavailableError,
        )
        from litellm.exceptions import Timeout as LiteLLMTimeout

        from onyx.llm.model_response import from_litellm_model_response_stream

        retryable_exceptions = (
            LiteLLMTimeout,
            LiteLLMAPIConnectionError,
            LiteLLMServiceUnavailableError,
            LiteLLMInternalServerError,
        )
        max_attempts: int = 1 + LLM_FIRST_CHUNK_MAX_RETRIES
        yielded_any: bool = False
        finished: bool = False

        # HTTPHandler Threading & Connection Pool Notes:
        # =============================================
        # See invoke() method for full explanation. Key points for streaming:
        #
        # 1. SAME RESTRICTIONS APPLY:
        #    - HTTPHandler only for providers in _uses_isolated_client()
        #    - OpenAI-compatible providers will fail with AttributeError on api_key
        #
        # 2. STREAMING-SPECIFIC CONCERNS:
        #    - "Bad file descriptor" errors are MORE common during streaming because:
        #      a) Streams hold connections open longer, increasing conflict window
        #      b) Multiple concurrent streams (e.g., deep research) share the pool
        #      c) Abandoned/interrupted streams can leave connections in bad state
        #
        # 3. ABANDONED STREAM PITFALL:
        #    - If callers abandon this generator without fully consuming it (e.g.,
        #      early return, exception, or break), the finally block won't execute
        #      until the generator is garbage collected
        #    - This is acceptable because:
        #      a) CPython's refcounting typically finalizes generators promptly
        #      b) Each HTTPHandler has its own isolated connection pool
        #      c) httpx has built-in connection timeouts as a fallback
        #    - If abandoned streams become problematic, consider using contextlib
        #      or explicit stream.close() at call sites
        #
        # 4. WHY NOT USE SHARED HTTPHandler:
        #    - litellm's InMemoryCache (used for client caching) is NOT thread-safe
        #    - Shared pools can have connections corrupted by other threads
        #    - Per-request HTTPHandler eliminates cross-thread interference
        for attempt in range(max_attempts):
            check_cancelled()
            client = None
            if self._uses_isolated_client():
                client = HTTPHandler(timeout=stall_timeout_s)

            try:
                # stream=True fixes the third-party return union to an iterator.
                response = cast(
                    "LiteLLMCustomStreamWrapper",
                    self._completion(
                        prompt=prompt,
                        tools=tools,
                        tool_choice=tool_choice,
                        stream=True,
                        structured_response_format=structured_response_format,
                        read_timeout_s=stall_timeout_s,
                        max_tokens=max_tokens,
                        parallel_tool_calls=True,
                        reasoning_effort=reasoning_effort,
                        user_identity=user_identity,
                        client=client,
                        operation=operation,
                        manage_tool_strictness=manage_tool_strictness,
                    ),
                )

                routed_model: str | None = None
                stream_started = time.monotonic()
                chunk_count = 0
                finish_reason: str | None = None
                logger.debug(
                    "LLM stream for %s started (attempt %d/%d)",
                    self.config.model_name,
                    attempt + 1,
                    max_attempts,
                )
                iterator = iter(response)
                while True:
                    check_cancelled()
                    try:
                        chunk = next(iterator)
                    except StopIteration:
                        check_cancelled()
                        break
                    check_cancelled()
                    model_response = from_litellm_model_response_stream(chunk)
                    chunk_count += 1
                    # The stream ends at end of body, not at finish_reason; a
                    # gap between these two log lines is time spent waiting
                    # for the provider to close the stream.
                    if finish_reason is None and model_response.choice.finish_reason:
                        finish_reason = model_response.choice.finish_reason
                        logger.debug(
                            "LLM stream for %s sent finish_reason=%s after %.1fs "
                            "and %d chunks",
                            self.config.model_name,
                            finish_reason,
                            time.monotonic() - stream_started,
                            chunk_count,
                        )

                    chunk_routed: str | None = self._routed_model(model_response.model)
                    if chunk_routed and chunk_routed != routed_model:
                        routed_model = chunk_routed
                        record_llm_routed_model(routed_model)
                    # Track LLM cost when usage info is available (typically in the last chunk)
                    if model_response.usage:
                        self._track_llm_cost(model_response.usage, routed_model)

                    yielded_any = True
                    finished = finished or bool(model_response.choice.finish_reason)
                    yield model_response
                logger.debug(
                    "LLM stream for %s ended after %.1fs: %d chunks, finish_reason=%s",
                    self.config.model_name,
                    time.monotonic() - stream_started,
                    chunk_count,
                    finish_reason,
                )
                return
            except retryable_exceptions as e:
                check_cancelled()
                # The stream ends at end of body, after the provider's terminal
                # event; a transport error past finish_reason loses no answer.
                if finished:
                    logger.warning(
                        "Stream for model %s failed after finish_reason with %s; "
                        "keeping the complete response, which may lack usage",
                        self.config.model_name,
                        type(e).__name__,
                    )
                    return
                if yielded_any or attempt >= max_attempts - 1:
                    raise _as_onyx_llm_error(e)
                logger.warning(
                    "Retrying pre-chunk stream for model %s after %s on attempt %d/%d",
                    self.config.model_name,
                    type(e).__name__,
                    attempt + 1,
                    max_attempts,
                )
            finally:
                if client is not None:
                    client.close()

    def _prepare_tools(
        self, request: GenerationRequest
    ) -> tuple[list[ToolDefinition], ToolChoice]:
        """Apply provider constraints without changing the run's declared tools or policy."""
        tools = request.tools
        choice = request.options.tool_choice
        allowed = request.allowed_tool_names
        model_names = resolve_model_identity_names(
            self.config.model_name, self.config.deployment_name
        )
        if allowed is not None:
            if unknown := allowed - {tool.name for tool in tools}:
                raise ValueError(f"Allowed tools are not declared: {sorted(unknown)}")
            if isinstance(choice, NamedToolChoice) and choice.name not in allowed:
                raise ValueError("Named tool is not allowed for this request")
            if not allowed:
                if choice == ToolChoiceOptions.REQUIRED:
                    raise ValueError("Required tool choice needs an allowed tool")
                choice = ToolChoiceOptions.NONE
            elif choice == ToolChoiceOptions.REQUIRED and len(allowed) == 1:
                choice = NamedToolChoice(name=next(iter(allowed)))
        if isinstance(choice, NamedToolChoice):
            if choice.name not in {tool.name for tool in tools}:
                raise ValueError("Named tool is not declared for this request")
            if model_prefers_auto_tool_choice(model_names):
                tools = [tool for tool in tools if tool.name == choice.name]
                choice = ToolChoiceOptions.AUTO
        if choice == ToolChoiceOptions.NONE and model_requires_auto_tool_choice(
            model_names
        ):
            tools = []
        return tools, choice

    def _prepare_request(
        self, request: GenerationRequest
    ) -> tuple[list[ChatCompletionMessage], dict[str, str]]:
        config = self.config
        messages, request_prefix = serialize_request(request, config)
        # request_prefix counts the request's messages, which cache_split_stats
        # walks. cacheable_prefix counts the provider messages; it is smaller
        # when the leading system messages are merged into one.
        cacheable_prefix = request_prefix
        if not get_provider_adapter(config).caches_leading_system_messages_separately():
            messages, cacheable_prefix = merge_leading_system_messages(
                messages, cacheable_prefix
            )
        if cacheable_prefix:
            messages, _ = process_with_prompt_cache(
                llm_config=config,
                cacheable_prefix=messages[:cacheable_prefix],
                suffix=messages[cacheable_prefix:],
                continuation=False,
                with_metadata=False,
            )
        return messages, cache_split_stats(request, request_prefix)

    def invoke(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> AssistantMessage:
        context = context or GenerationContext()
        messages, cache_stats = self._prepare_request(request)
        definitions, tool_choice = self._prepare_tools(request)
        tools = serialize_tools(definitions) or None
        with (
            _provider_scope(context, self) as signal,
            llm_generation_span(
                self,
                context.flow or LLMFlow.UNTAGGED_INVOKE,
                input_messages=messages,
                tools=tools,
                content_mode=context.content_mode,
            ) as span,
        ):
            span.span_data.model_config = {
                **(span.span_data.model_config or {}),
                **cache_stats,
            }
            try:
                signal.check()
                response = self.invoke_raw(
                    messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    structured_response_format=request.options.structured_response_format,
                    manage_tool_strictness=True,
                    total_timeout_s=context.total_timeout_s or LLM_INVOKE_TIMEOUT_S,
                    max_tokens=request.options.max_tokens,
                    reasoning_effort=request.options.reasoning_effort,
                    user_identity=context.user_identity,
                )
                record_llm_response(span, response)
                # A completed response survives its deadline, but explicit Stop wins.
                if signal.cancelled:
                    raise AgentCancelled()
                return to_assistant_message(response, request)
            except (Exception, AgentCancelled) as error:
                span.set_error(
                    {
                        "message": self.redact_error(
                            f"{type(error).__name__}: {error}"
                        ),
                        "data": None,
                    }
                )
                raise

    @isolated_context
    def stream(
        self, request: GenerationRequest, context: GenerationContext | None = None
    ) -> Generator[GenerationEvent, None, None]:
        context = context or GenerationContext()
        operation = ProviderOperation()
        accumulator = MessageAccumulator(request.tools)
        messages, cache_stats = self._prepare_request(request)
        definitions, tool_choice = self._prepare_tools(request)
        tools = serialize_tools(definitions) or None
        with (
            _provider_scope(context, self) as signal,
            llm_generation_span(
                self,
                context.flow or LLMFlow.UNTAGGED_STREAM,
                input_messages=messages,
                tools=tools,
                content_mode=context.content_mode,
            ) as span,
        ):
            span.span_data.model_config = {
                **(span.span_data.model_config or {}),
                **cache_stats,
            }
            started = time.monotonic()
            first_action = False
            request_params_sent = False
            events = None
            try:
                signal.check()
                yield GenerationStartEvent()
                events = accumulator.consume(
                    iter(
                        self.stream_raw(
                            messages,
                            tools=tools,
                            tool_choice=tool_choice,
                            max_tokens=request.options.max_tokens,
                            reasoning_effort=request.options.reasoning_effort,
                            user_identity=context.user_identity,
                            operation=operation,
                            manage_tool_strictness=True,
                            stall_timeout_s=context.stall_timeout_s
                            or LLM_SOCKET_READ_TIMEOUT,
                            structured_response_format=request.options.structured_response_format,
                        )
                    ),
                    request,
                )
                for event in events:
                    signal.check()
                    if not first_action:
                        span.span_data.time_to_first_action_seconds = (
                            time.monotonic() - started
                        )
                        first_action = True
                    if not request_params_sent and operation.request_params is not None:
                        event = _event_with_request_params(event, operation)
                        request_params_sent = True
                    yield event
                signal.check()
                if not (
                    accumulator.message.text
                    or accumulator.message.thinking
                    or accumulator.message.thinking_blocks
                    or accumulator.message.tool_calls
                ):
                    logger.warning(
                        "Empty generation: provider=%s model=%s stop_reason=%s chunks=%s",
                        self.config.model_provider,
                        self.config.model_name,
                        accumulator.message.stop_reason,
                        accumulator.chunk_count,
                    )
                for event in accumulator.end():
                    yield (
                        _event_with_request_params(event, operation)
                        if event.type == "done"
                        else event
                    )
            except (Exception, AgentCancelled) as error:
                span.set_error(
                    {
                        "message": self.redact_error(
                            f"{type(error).__name__}: {error}"
                        ),
                        "data": None,
                    }
                )
                accumulator.message.stop_reason = (
                    "aborted" if isinstance(error, AgentCancelled) else "error"
                )
                accumulator.message.error_message = (
                    "Generation cancelled"
                    if isinstance(error, AgentCancelled)
                    else "Generation failed"
                )
                yield _event_with_request_params(
                    GenerationErrorEvent(
                        stop_reason="aborted"
                        if isinstance(error, AgentCancelled)
                        else "error",
                        error_message=accumulator.message.error_message,
                        usage=accumulator.message.usage.model_copy(deep=True)
                        if accumulator.message.usage
                        else None,
                    ),
                    operation,
                )
                raise
            finally:
                # Providers bill for tokens streamed before consumer abandonment.
                # Record partial content and usage on errors and GeneratorExit,
                # not just clean completion. GeneratorExit is a BaseException,
                # so it does not pass through the Exception handler above.
                if events is not None:
                    events.close()
                accumulator.finalize()
                message = accumulator.message
                record_llm_span_output(
                    span,
                    output=message.text or None,
                    usage=message.usage,
                    reasoning=message.thinking or None,
                    tool_calls=[
                        ProviderToolCall(
                            id=call.id,
                            function=RequestFunctionCall(
                                name=call.name, arguments=json.dumps(call.arguments)
                            ),
                        )
                        for call in message.tool_calls
                    ]
                    or None,
                )


@contextmanager
def temporary_env_and_lock(
    env_variables: dict[str, str], *, deadline: float | None = None
) -> Iterator[None]:
    """
    Temporarily sets the environment variables to the given values while holding
    the exclusive write side of _env_rwlock, so no concurrent LLM call can
    observe them. Then cleans up the environment and releases the lock.

    Calls without env_variables hold the shared read side instead: they run
    concurrently with each other and only block while a writer has env vars
    injected.
    """
    lock = _env_rwlock.gen_wlock() if env_variables else _env_rwlock.gen_rlock()
    timeout = -1 if deadline is None else max(0, deadline - time.monotonic())
    if not lock.acquire(timeout=timeout):
        raise LLMTimeoutError("LLM call timed out waiting for the environment lock")
    try:
        if not env_variables:
            yield
            return

        masked_env = {
            key: mask_env_value_for_logging(key, value)
            for key, value in env_variables.items()
        }
        logger.info(
            "temporary_env_and_lock setting custom_config env var(s): %s",
            masked_env,
        )
        start_time = time.monotonic()
        logger.debug("Acquired env write lock in temporary_env_and_lock")
        # Store original values (None if key didn't exist)
        original_values: dict[str, str | None] = {
            key: os.environ.get(key) for key in env_variables
        }
        try:
            os.environ.update(env_variables)
            yield
        finally:
            for key, original_value in original_values.items():
                if original_value is None:
                    os.environ.pop(key, None)  # Remove if it didn't exist before
                else:
                    os.environ[key] = original_value  # Restore original value

        logger.info(
            "temporary_env_and_lock write section took %.3f seconds",
            time.monotonic() - start_time,
        )
    finally:
        lock.release()
