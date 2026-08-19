import copy
import math
import os
import time
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, nullcontext
from functools import lru_cache
from typing import TYPE_CHECKING, Any, Union, cast

from readerwriterlock import rwlock

from onyx.configs.app_configs import (
    MOCK_LLM_RESPONSE,
    SEND_USER_METADATA_TO_LLM_PROVIDER,
)
from onyx.configs.chat_configs import (
    LLM_FIRST_CHUNK_MAX_RETRIES,
    LLM_SOCKET_READ_TIMEOUT,
)
from onyx.configs.model_configs import GEN_AI_TEMPERATURE, LITELLM_EXTRA_BODY
from onyx.llm.api_surfaces import (
    OPENAI_COMPATIBLE_SURFACES,
    LlmApiSurface,
    resolve_api_surface,
)
from onyx.llm.constants import MODEL_PREFIX_TO_VENDOR, LlmProviderNames
from onyx.llm.cost import compute_cost_cents
from onyx.llm.custom_config_mapping import (
    UI_ONLY_CONFIG_KEYS,
    map_custom_config_to_model_kwargs,
)
from onyx.llm.interfaces import (
    LLM,
    LanguageModelInput,
    LLMConfig,
    LLMUserIdentity,
    ReasoningEffort,
    ToolChoice,
)
from onyx.llm.model_capabilities import (
    ReasoningParamStyle,
    anthropic_omits_sampling_params,
    anthropic_supports_thinking,
    anthropic_uses_adaptive_thinking,
    is_true_openai_model,
    model_is_reasoning_model,
    openai_chat_variant_rejects_reasoning,
    openai_model_rejects_reasoning_effort,
    resolve_reasoning_param_style,
)
from onyx.llm.model_capabilities import (
    model_identity_names as resolve_model_identity_names,
)
from onyx.llm.model_response import ModelResponse, ModelResponseStream, Usage
from onyx.llm.models import (
    ANTHROPIC_ADAPTIVE_REASONING_EFFORT,
    ANTHROPIC_REASONING_EFFORT_BUDGET,
    OPENAI_REASONING_EFFORT,
    NamedToolChoice,
    ToolChoiceOptions,
    resolve_reasoning_effort,
)
from onyx.llm.request_context import get_llm_mock_response, set_llm_request_params
from onyx.llm.utils import build_litellm_passthrough_kwargs
from onyx.llm.well_known_providers.constants import VERTEX_LOCATION_KWARG
from onyx.tracing.llm_utils import record_llm_request_params
from onyx.utils.encryption import mask_env_value_for_logging, mask_string
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Write-preferring reader-writer lock guarding os.environ during litellm calls.
# Calls that inject custom_config env vars hold the write lock; all other calls
# hold a read lock so they never observe injected secrets but still run
# concurrently with each other.
_env_rwlock = rwlock.RWLockWrite()

if TYPE_CHECKING:
    from litellm import CustomStreamWrapper, HTTPHandler


_LLM_PROMPT_LONG_TERM_LOG_CATEGORY = "llm_prompt"
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

# Best-effort tuning kwargs, never worth failing a chat over. _completion
# retries provider rejections without them: reasoning keys first, then all.
# Semantics-changing keys (tools, tool_choice, messages) are never stripped.
_REASONING_KWARG_KEYS = frozenset(
    {"thinking", "output_config", "reasoning", "reasoning_effort"}
)
_BEST_EFFORT_KWARG_KEYS = _REASONING_KWARG_KEYS | frozenset({"temperature"})

# Substrings provider 400s use to name each strippable kwarg (errors may
# cite only inner fields like budget_tokens or effort).
_KWARG_ERROR_ALIASES: dict[str, tuple[str, ...]] = {
    "thinking": ("thinking", "budget_tokens"),
    "output_config": ("output_config", "effort"),
    "reasoning": ("reasoning", "effort"),
    "reasoning_effort": ("reasoning_effort", "effort"),
    "temperature": ("temperature",),
}


def _merge_under(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Fill *base* in beneath *override*, recursing so an override key that
    holds a dict keeps the siblings *base* declared under it. Leaves in
    *override* always win."""
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _merge_under(existing, value)
        else:
            merged[key] = value
    return merged


def _json_safe(value: Any) -> Any:
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


class LLMTimeoutError(Exception):
    """
    Exception raised when an LLM call times out.
    """


class LLMRateLimitError(Exception):
    """
    Exception raised when an LLM call is rate limited.
    """


def _consume_stream_with_timeout(stream: Any, total_timeout: float | None) -> list[Any]:
    """Drain a litellm stream, capping total wall-clock time when set.

    The socket read timeout only bounds the gap between packets, so keepalive
    pings defeat it; this caps the whole call. On breach we raise — never close,
    since litellm 1.93.0 exposes only async ``aclose`` — which frees the thread;
    GC releases the connection.
    """
    if total_timeout is None:
        return list(stream)

    deadline = time.monotonic() + total_timeout
    chunks: list[Any] = []
    for chunk in stream:
        chunks.append(chunk)
        if time.monotonic() > deadline:
            raise LLMTimeoutError(
                f"LLM streaming call exceeded total timeout of {total_timeout}s"
            )
    return chunks


def _prompt_to_dicts(prompt: LanguageModelInput) -> list[dict[str, Any]]:
    """Convert Pydantic message models to dictionaries for LiteLLM.

    LiteLLM expects messages to be dictionaries (with .get() method),
    not Pydantic models. This function serializes the messages.
    """
    if isinstance(prompt, list):
        return [msg.model_dump(exclude_none=True) for msg in prompt]
    return [prompt.model_dump(exclude_none=True)]


def _normalize_content(raw: Any) -> str:
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
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in msg.items() if key != "thinking_blocks"}
        for msg in messages
    ]


def _strip_tool_content_from_messages(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Convert tool-related messages to plain text.

    Bedrock's Converse API requires toolConfig when messages contain
    toolUse/toolResult content blocks. When no tools are provided for the
    current request, we must convert any tool-related history into plain text
    to avoid the "toolConfig field must be defined" error.

    This is the same approach used by _OllamaHistoryMessageFormatter.
    """
    result: list[dict[str, Any]] = []
    for msg in messages:
        role = msg.get("role")
        tool_calls = msg.get("tool_calls")

        if role == "assistant" and tool_calls:
            # Convert structured tool calls to text representation
            tool_call_lines = []
            for tc in tool_calls:
                func = tc.get("function", {})
                name = func.get("name", "unknown")
                args = func.get("arguments", "{}")
                tc_id = tc.get("id", "")
                tool_call_lines.append(
                    f"[Tool Call] name={name} id={tc_id} args={args}"
                )

            existing_content = _normalize_content(msg.get("content"))
            parts = (
                [existing_content] + tool_call_lines
                if existing_content
                else tool_call_lines
            )
            new_msg = {
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
            if (
                result
                and result[-1]["role"] == "user"
                and "[Tool Result]" in result[-1].get("content", "")
            ):
                result[-1]["content"] += "\n\n" + tool_result_text
            else:
                result.append({"role": "user", "content": tool_result_text})

        else:
            result.append(msg)

    return result


def _fix_tool_user_message_ordering(
    messages: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Insert a synthetic assistant message between tool and user messages.

    Some models (e.g. Mistral on Azure) require strict message ordering where
    a user message cannot immediately follow a tool message. This function
    inserts a minimal assistant message to bridge the gap.
    """
    if len(messages) < 2:
        return messages

    result: list[dict[str, Any]] = [messages[0]]
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


def _messages_contain_tool_content(messages: list[dict[str, Any]]) -> bool:
    """Check if any messages contain tool-related content blocks."""
    for msg in messages:
        if msg.get("role") == "tool":
            return True
        if msg.get("role") == "assistant" and msg.get("tool_calls"):
            return True
    return False


def _prompt_contains_tool_call_history(prompt: LanguageModelInput) -> bool:
    """Check if the prompt contains any assistant messages with tool_calls.

    When Anthropic's extended thinking is enabled, the API requires every
    assistant message to start with a thinking block before any tool_use
    blocks.  Since we don't preserve thinking_blocks (they carry
    cryptographic signatures that can't be reconstructed), we must skip
    the thinking param whenever history contains prior tool-calling turns.
    """
    from onyx.llm.models import AssistantMessage

    msgs = prompt if isinstance(prompt, list) else [prompt]
    return any(isinstance(msg, AssistantMessage) and msg.tool_calls for msg in msgs)


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
    """Uses Litellm library to allow easy configuration to use a multitude of LLMs
    See https://python.langchain.com/docs/integrations/chat/litellm"""

    def __init__(
        self,
        api_key: str | None,
        model_provider: str,
        model_name: str,
        max_input_tokens: int,
        timeout: int | None = None,
        api_base: str | None = None,
        api_version: str | None = None,
        deployment_name: str | None = None,
        custom_llm_provider: str | None = None,
        temperature: float | None = None,
        custom_config: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
        extra_body: dict | None = LITELLM_EXTRA_BODY,
        model_kwargs: dict[str, Any] | None = None,
        reasoning_effort_default: ReasoningEffort | None = None,
        reasoning_effort_max: ReasoningEffort | None = None,
    ):
        # Timeout in seconds for each socket read operation (i.e., max time between
        # receiving data chunks/tokens). This is NOT a total request timeout - a
        # request can run indefinitely as long as data keeps arriving within this
        # window. If the LLM pauses for longer than this timeout between chunks,
        # a ReadTimeout is raised.
        self._timeout = timeout if timeout is not None else LLM_SOCKET_READ_TIMEOUT

        self._temperature = GEN_AI_TEMPERATURE if temperature is None else temperature

        self._model_provider = model_provider
        self._model_version = model_name
        self._api_key = api_key
        self._deployment_name = deployment_name
        self._api_base = api_base
        self._api_version = api_version
        self._custom_llm_provider = custom_llm_provider
        self._max_input_tokens = max_input_tokens
        self._custom_config = custom_config
        self._reasoning_effort_default = reasoning_effort_default
        self._reasoning_effort_max = reasoning_effort_max

        self._api_surface = resolve_api_surface(model_provider, custom_config)

        # Create a dictionary for model-specific arguments if it's None
        model_kwargs = model_kwargs or {}

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

        self._model_kwargs = model_kwargs

    def _safe_model_config(self) -> dict:
        dump = self.config.model_dump()
        dump["api_key"] = mask_string(dump.get("api_key") or "")
        custom_config = dump.get("custom_config")
        if isinstance(custom_config, dict):
            # Mask sensitive values in custom_config
            masked_config = {}
            for k, v in custom_config.items():
                masked_config[k] = mask_string(v) if v else v
            dump["custom_config"] = masked_config
        return dump

    def _track_llm_cost(self, usage: Usage) -> None:
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
                    provider=provider,
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
        prompt: LanguageModelInput,
        tools: list[dict] | None,
        tool_choice: ToolChoice | None,
        stream: bool,
        parallel_tool_calls: bool,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        user_identity: LLMUserIdentity | None = None,
        client: "HTTPHandler | None" = None,
    ) -> Union["ModelResponse", "CustomStreamWrapper"]:
        # Lazy loading to avoid memory bloat for non-inference flows
        from litellm.exceptions import BadRequestError, RateLimitError, Timeout

        from onyx.llm.litellm_singleton import litellm

        #########################
        # Flags that modify the final arguments
        #########################
        model_identity_names = resolve_model_identity_names(
            self.config.model_name, self.config.deployment_name
        )
        is_claude_model = any("claude" in name.lower() for name in model_identity_names)
        is_qwen_model = any("qwen" in name.lower() for name in model_identity_names)
        uses_adaptive_thinking = any(
            anthropic_uses_adaptive_thinking(name) for name in model_identity_names
        )
        model_supports_anthropic_thinking = any(
            anthropic_supports_thinking(name) for name in model_identity_names
        )
        is_reasoning = (
            uses_adaptive_thinking
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

        #########################
        # Build arguments
        #########################
        # Optional kwargs - should only be passed to LiteLLM under certain conditions
        optional_kwargs: dict[str, Any] = {}

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
        # Claude skips reasoning when it's set, and Qwen thinking models reject
        # it with a 400. The chat loop's fallback tool-call extraction still
        # enforces the forced tool. Matched by model name rather than
        # `is_reasoning` because the litellm/local registry lags behind new
        # Qwen releases (e.g. qwen3.7-plus).
        # A NamedToolChoice is deliberately NOT downgraded: legacy Claude
        # thinking is skipped below instead, and Qwen thinking models may still
        # reject the forced tool upstream (a loud 400 beats silently ignoring
        # the caller's forced tool).
        if (is_claude_model or is_qwen_model) and (
            tool_choice == ToolChoiceOptions.REQUIRED
        ):
            tool_choice = ToolChoiceOptions.AUTO

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
            self.config.reasoning_effort_default,
            self.config.reasoning_effort_max,
        )

        # Note, there is a reasoning_effort parameter in LiteLLM but it is completely jank and does not work for any
        # of the major providers. Not setting it sets it to OFF.
        if (
            is_reasoning
            # The default of this parameter not set is surprisingly not the equivalent of an Auto but is actually Off
            and reasoning_effort != ReasoningEffort.OFF
            and not any(
                openai_model_rejects_reasoning_effort(name)
                for name in model_identity_names
            )
        ):
            openai_style_reasoning = {
                "effort": OPENAI_REASONING_EFFORT[reasoning_effort],
                "summary": "auto",
            }
            reasoning_style = resolve_reasoning_param_style(
                self.config.model_provider,
                model_identity_names,
                self._api_surface,
            )

            if reasoning_style is ReasoningParamStyle.OPENAI:
                if is_claude_model:
                    # Only a gateway routes Claude here, and it still translates
                    # to Anthropic, so the signed-thinking-block constraint
                    # described below applies to these requests too.
                    send_reasoning = not _prompt_contains_tool_call_history(prompt)
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

            elif reasoning_style in (
                ReasoningParamStyle.ANTHROPIC_ADAPTIVE,
                ReasoningParamStyle.ANTHROPIC_BUDGET,
            ):
                # Anthropic requires every assistant message with tool_use
                # blocks to start with a thinking block that carries a
                # cryptographic signature.  We don't preserve those blocks
                # across turns, so skip thinking when the history already
                # contains tool-calling assistant messages.  LiteLLM's
                # modify_params workaround doesn't cover all providers
                # (notably Bedrock).
                has_tool_call_history = _prompt_contains_tool_call_history(prompt)

                if reasoning_style is ReasoningParamStyle.ANTHROPIC_ADAPTIVE:
                    # Newer Anthropic models (Claude Opus 4.7+) reject
                    # thinking.type.enabled — they require the adaptive
                    # thinking config with output_config.effort.
                    if not has_tool_call_history:
                        optional_kwargs["thinking"] = {"type": "adaptive"}
                        optional_kwargs["output_config"] = {
                            "effort": ANTHROPIC_ADAPTIVE_REASONING_EFFORT[
                                reasoning_effort
                            ],
                        }
                else:
                    budget_tokens: int | None = ANTHROPIC_REASONING_EFFORT_BUDGET.get(
                        reasoning_effort
                    )
                    # thinking.type=enabled is rejected alongside a forced
                    # tool_choice (only adaptive thinking supports forced tool
                    # use), so skip thinking for a NamedToolChoice.
                    if (
                        budget_tokens is not None
                        and not has_tool_call_history
                        and not isinstance(tool_choice, NamedToolChoice)
                    ):
                        if max_tokens is not None:
                            # Anthropic has a weird rule where max token has to be at least as much as budget tokens if set
                            # and the minimum budget tokens is 1024
                            # Will note that overwriting a developer set max tokens is not ideal but is the best we can do for now
                            # It is better to allow the LLM to output more reasoning tokens even if it results in a fairly small tool
                            # call as compared to reducing the budget for reasoning.
                            max_tokens = max(budget_tokens + 1, max_tokens)
                        optional_kwargs["thinking"] = {
                            "type": "enabled",
                            "budget_tokens": budget_tokens,
                        }

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
                else:
                    optional_kwargs["reasoning_effort"] = ReasoningEffort.MEDIUM.value

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

        # Passthrough kwargs
        passthrough_kwargs = build_litellm_passthrough_kwargs(
            model_kwargs=self._model_kwargs,
            user_identity=user_identity,
        )

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
                if passthrough_kwargs is self._model_kwargs:
                    passthrough_kwargs = copy.deepcopy(self._model_kwargs)
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

            if not _env_injection_enabled() and self._env_only_custom_config:
                _warn_dropped_env_only_keys(
                    self._model_provider,
                    tuple(sorted(self._env_only_custom_config)),
                )

            def _call_litellm(opts: dict[str, Any]) -> Any:
                # Injection disabled means no env writer exists anywhere in
                # the process, so skip the rwlock entirely. Built per attempt
                # because the context manager is single-use.
                env_ctx: AbstractContextManager[None] = (
                    temporary_env_and_lock(self._env_only_custom_config)
                    if _env_injection_enabled()
                    else nullcontext()
                )
                with env_ctx:
                    return litellm.completion(
                        mock_response=get_llm_mock_response() or MOCK_LLM_RESPONSE,
                        model=model,
                        base_url=self._api_base or None,
                        api_version=api_version,
                        custom_llm_provider=self._custom_llm_provider or None,
                        messages=messages,
                        # None (omitted) rather than [] — some OpenAI-compatible
                        # servers reject requests with an empty tools array.
                        tools=tools or None,
                        stream=stream,
                        timeout=timeout_override or self._timeout,
                        max_tokens=max_tokens,
                        client=client,
                        **opts,
                        **passthrough_kwargs,
                    )

            # Retry ladder for provider 400s: drop reasoning kwargs, then every
            # best-effort kwarg. Unknown models or capability drift degrade to
            # provider defaults with a warning instead of failing the message.
            attempts = [optional_kwargs]
            for strip_keys in (_REASONING_KWARG_KEYS, _BEST_EFFORT_KWARG_KEYS):
                stripped = {
                    k: v for k, v in optional_kwargs.items() if k not in strip_keys
                }
                if len(stripped) < len(attempts[-1]):
                    attempts.append(stripped)

            for i, opts in enumerate(attempts):
                # Last write wins: sent_kwargs holds what the returning (or
                # final failing) attempt sent, reasoning_effort the effective
                # intent. One dict, two sinks, so they cannot drift.
                request_params = {
                    "model_name": self.config.model_name,
                    "model_provider": self.config.model_provider,
                    "reasoning_effort": reasoning_effort.value,
                    "max_tokens": max_tokens,
                    "sent_kwargs": {
                        k: _json_safe(opts[k])
                        for k in sorted(_BEST_EFFORT_KWARG_KEYS & opts.keys())
                    },
                }
                record_llm_request_params(request_params)
                set_llm_request_params(request_params)
                try:
                    return _call_litellm(opts)
                except BadRequestError as e:
                    if i == len(attempts) - 1:
                        raise
                    # Only retry rejections a later attempt can strip away.
                    remaining_strippable = set(opts) - set(attempts[-1])
                    if not _rejection_names_strippable_kwargs(e, remaining_strippable):
                        raise
                    logger.warning(
                        "Provider rejected request for model %s. Retrying "
                        "without %s: %s",
                        model,
                        sorted(set(opts) - set(attempts[i + 1])),
                        e,
                    )
            raise RuntimeError("unreachable: retry ladder always returns or raises")
        except Exception as e:
            # for break pointing
            if isinstance(e, Timeout):
                raise LLMTimeoutError(e)

            elif isinstance(e, RateLimitError):
                raise LLMRateLimitError(e)

            raise e

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
            max_input_tokens=self._max_input_tokens,
            reasoning_effort_default=self._reasoning_effort_default,
            reasoning_effort_max=self._reasoning_effort_max,
        )

    def _uses_isolated_client(self) -> bool:
        """Providers whose sync calls need a fresh per-call HTTPHandler instead of
        litellm's shared module_level_client (see threading notes in invoke())."""
        return (
            any(
                is_true_openai_model(self.config.model_provider, name)
                for name in resolve_model_identity_names(
                    self.config.model_name, self.config.deployment_name
                )
            )
            or self.config.model_provider == LlmProviderNames.ANTHROPIC
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
        total_timeout_override: float | None = None,
    ) -> ModelResponse:
        from litellm import HTTPHandler
        from litellm import ModelResponse as LiteLLMModelResponse

        from onyx.llm.model_response import from_litellm_model_response

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
        # 3. WHY ANTHROPIC ALSO GETS AN ISOLATED CLIENT:
        #    - An abandoned sync stream is finalized by GC, which can fire on a thread
        #      already inside the shared pool's non-reentrant lock and deadlock it,
        #      wedging all later LLM calls (encode/httpcore#996; seen in prod).
        #    - A per-call client keeps abandoned streams off the shared pool. litellm's
        #      anthropic handler uses module_level_client only when client is None.
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
        # Cap the per-read timeout at the total budget. The deadline is only
        # checked between chunks, so without this a single blocking read could
        # overshoot a total shorter than the socket read timeout. No-op when the
        # total exceeds it (our defaults do).
        read_timeout = timeout_override or self._timeout
        if total_timeout_override is not None:
            read_timeout = min(read_timeout, max(1, int(total_timeout_override)))

        client = None
        if self._uses_isolated_client():
            client = HTTPHandler(timeout=read_timeout)

        try:
            # When env-only custom_config keys are injected (self-hosted
            # deployments only), they are set under a global lock. Using
            # stream=True here means the lock is only held during connection
            # setup (not the full inference). The chunks are then collected
            # outside the lock and reassembled into a single ModelResponse
            # via stream_chunk_builder.
            from litellm import CustomStreamWrapper as LiteLLMCustomStreamWrapper
            from litellm import stream_chunk_builder

            stream_response = cast(
                LiteLLMCustomStreamWrapper,
                self._completion(
                    prompt=prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    stream=True,
                    structured_response_format=structured_response_format,
                    timeout_override=read_timeout,
                    max_tokens=max_tokens,
                    parallel_tool_calls=True,
                    reasoning_effort=reasoning_effort,
                    user_identity=user_identity,
                    client=client,
                ),
            )
            chunks = _consume_stream_with_timeout(
                stream_response, total_timeout_override
            )
            response = cast(
                LiteLLMModelResponse,
                stream_chunk_builder(chunks),
            )

            model_response = from_litellm_model_response(response)

            # Track LLM cost for Onyx-managed API keys
            if model_response.usage:
                self._track_llm_cost(model_response.usage)

            return model_response
        finally:
            if client is not None:
                client.close()

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoice | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
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
            client = None
            if self._uses_isolated_client():
                client = HTTPHandler(timeout=timeout_override or self._timeout)

            try:
                response = cast(
                    LiteLLMCustomStreamWrapper,
                    self._completion(
                        prompt=prompt,
                        tools=tools,
                        tool_choice=tool_choice,
                        stream=True,
                        structured_response_format=structured_response_format,
                        timeout_override=timeout_override,
                        max_tokens=max_tokens,
                        parallel_tool_calls=True,
                        reasoning_effort=reasoning_effort,
                        user_identity=user_identity,
                        client=client,
                    ),
                )

                for chunk in response:
                    model_response = from_litellm_model_response_stream(chunk)

                    # Track LLM cost when usage info is available (typically in the last chunk)
                    if model_response.usage:
                        self._track_llm_cost(model_response.usage)

                    yielded_any = True
                    yield model_response
                return
            except retryable_exceptions as e:
                if yielded_any or attempt >= max_attempts - 1:
                    raise
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


@contextmanager
def temporary_env_and_lock(env_variables: dict[str, str]) -> Iterator[None]:
    """
    Temporarily sets the environment variables to the given values while holding
    the exclusive write side of _env_rwlock, so no concurrent LLM call can
    observe them. Then cleans up the environment and releases the lock.

    Calls without env_variables hold the shared read side instead: they run
    concurrently with each other and only block while a writer has env vars
    injected.
    """
    if not env_variables:
        with _env_rwlock.gen_rlock():
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
    with _env_rwlock.gen_wlock():
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
