from collections.abc import Iterator
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import Union

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.configs.chat_configs import LLM_SOCKET_READ_TIMEOUT
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.configs.model_configs import LITELLM_EXTRA_BODY
from onyx.llm.constants import LlmProviderNames
from onyx.llm.cost import calculate_llm_cost_cents
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ReasoningEffort
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.model_response import Usage
from onyx.llm.models import ANTHROPIC_REASONING_EFFORT_BUDGET
from onyx.llm.models import OPENAI_REASONING_EFFORT
from onyx.llm.request_context import get_llm_mock_response
from onyx.llm.utils import build_litellm_passthrough_kwargs
from onyx.llm.utils import is_true_openai_model
from onyx.llm.utils import model_is_reasoning_model
from onyx.llm.well_known_providers.constants import AWS_ACCESS_KEY_ID_KWARG
from onyx.llm.well_known_providers.constants import (
    AWS_ACCESS_KEY_ID_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import (
    AWS_BEARER_TOKEN_BEDROCK_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import AWS_REGION_NAME_KWARG
from onyx.llm.well_known_providers.constants import AWS_REGION_NAME_KWARG_ENV_VAR_FORMAT
from onyx.llm.well_known_providers.constants import AWS_SECRET_ACCESS_KEY_KWARG
from onyx.llm.well_known_providers.constants import (
    AWS_SECRET_ACCESS_KEY_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import OLLAMA_API_KEY_CONFIG_KEY
from onyx.llm.well_known_providers.constants import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.well_known_providers.constants import (
    VERTEX_CREDENTIALS_FILE_KWARG_ENV_VAR_FORMAT,
)
from onyx.llm.well_known_providers.constants import VERTEX_LOCATION_KWARG
from onyx.server.utils import mask_string
from onyx.utils.logger import setup_logger

logger = setup_logger()

if TYPE_CHECKING:
    from litellm import CustomStreamWrapper
    from litellm import HTTPHandler


_LLM_PROMPT_LONG_TERM_LOG_CATEGORY = "llm_prompt"
LEGACY_MAX_TOKENS_KWARG = "max_tokens"
STANDARD_MAX_TOKENS_KWARG = "max_completion_tokens"


class LLMTimeoutError(Exception):
    """
    Exception raised when an LLM call times out.
    """


class LLMRateLimitError(Exception):
    """
    Exception raised when an LLM call is rate limited.
    """


def _prompt_to_dicts(prompt: LanguageModelInput) -> list[dict[str, Any]]:
    """Convert Pydantic message models to dictionaries for LiteLLM.

    LiteLLM expects messages to be dictionaries (with .get() method),
    not Pydantic models. This function serializes the messages.
    """
    if isinstance(prompt, list):
        return [msg.model_dump(exclude_none=True) for msg in prompt]
    return [prompt.model_dump(exclude_none=True)]


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
    ):
        # Timeout in seconds for each socket read operation (i.e., max time between
        # receiving data chunks/tokens). This is NOT a total request timeout - a
        # request can run indefinitely as long as data keeps arriving within this
        # window. If the LLM pauses for longer than this timeout between chunks,
        # a ReadTimeout is raised.
        self._timeout = timeout
        if timeout is None:
            self._timeout = LLM_SOCKET_READ_TIMEOUT

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

        # Create a dictionary for model-specific arguments if it's None
        model_kwargs = model_kwargs or {}

        if custom_config:
            for k, v in custom_config.items():
                if model_provider == LlmProviderNames.VERTEX_AI:
                    if k == VERTEX_CREDENTIALS_FILE_KWARG:
                        model_kwargs[k] = v
                    elif k == VERTEX_CREDENTIALS_FILE_KWARG_ENV_VAR_FORMAT:
                        model_kwargs[VERTEX_CREDENTIALS_FILE_KWARG] = v
                    elif k == VERTEX_LOCATION_KWARG:
                        model_kwargs[k] = v
                elif model_provider == LlmProviderNames.OLLAMA_CHAT:
                    if k == OLLAMA_API_KEY_CONFIG_KEY:
                        model_kwargs["api_key"] = v
                elif model_provider == LlmProviderNames.BEDROCK:
                    if k == AWS_REGION_NAME_KWARG:
                        model_kwargs[k] = v
                    elif k == AWS_REGION_NAME_KWARG_ENV_VAR_FORMAT:
                        model_kwargs[AWS_REGION_NAME_KWARG] = v
                    elif k == AWS_BEARER_TOKEN_BEDROCK_KWARG_ENV_VAR_FORMAT:
                        model_kwargs["api_key"] = v
                    elif k == AWS_ACCESS_KEY_ID_KWARG:
                        model_kwargs[k] = v
                    elif k == AWS_ACCESS_KEY_ID_KWARG_ENV_VAR_FORMAT:
                        model_kwargs[AWS_ACCESS_KEY_ID_KWARG] = v
                    elif k == AWS_SECRET_ACCESS_KEY_KWARG:
                        model_kwargs[k] = v
                    elif k == AWS_SECRET_ACCESS_KEY_KWARG_ENV_VAR_FORMAT:
                        model_kwargs[AWS_SECRET_ACCESS_KEY_KWARG] = v

        # Default vertex_location to "global" if not provided for Vertex AI
        # Latest gemini models are only available through the global region
        if (
            model_provider == LlmProviderNames.VERTEX_AI
            and VERTEX_LOCATION_KWARG not in model_kwargs
        ):
            model_kwargs[VERTEX_LOCATION_KWARG] = "global"

        # This is needed for Ollama to do proper function calling
        if model_provider == LlmProviderNames.OLLAMA_CHAT and api_base is not None:
            model_kwargs["api_base"] = api_base
        if extra_headers:
            model_kwargs.update({"extra_headers": extra_headers})
        if extra_body:
            model_kwargs.update({"extra_body": extra_body})

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
        from onyx.db.usage import increment_usage
        from onyx.db.usage import UsageType

        # Calculate cost in cents
        cost_cents = calculate_llm_cost_cents(
            model_name=self._model_version,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
        )

        if cost_cents <= 0:
            return

        try:
            with get_session_with_current_tenant() as db_session:
                increment_usage(db_session, UsageType.LLM_COST, cost_cents)
                db_session.commit()
        except Exception as e:
            # Log but don't fail the LLM call if tracking fails
            logger.warning(f"Failed to track LLM cost: {e}")

    def _completion(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None,
        tool_choice: ToolChoiceOptions | None,
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
        from onyx.llm.litellm_singleton import litellm
        from litellm.exceptions import Timeout, RateLimitError

        #########################
        # Flags that modify the final arguments
        #########################
        is_claude_model = "claude" in self.config.model_name.lower()
        is_reasoning = model_is_reasoning_model(
            self.config.model_name, self.config.model_provider
        )
        # All OpenAI models will use responses API for consistency
        # Responses API is needed to get reasoning packets from OpenAI models
        is_openai_model = is_true_openai_model(
            self.config.model_provider, self.config.model_name
        )
        is_ollama = self._model_provider == LlmProviderNames.OLLAMA_CHAT
        is_mistral = self._model_provider == LlmProviderNames.MISTRAL
        is_vertex_ai = self._model_provider == LlmProviderNames.VERTEX_AI
        # Vertex Anthropic Opus 4.5 rejects output_config.
        # Keep this guard until LiteLLM/Vertex accept the field for this model.
        is_vertex_opus_4_5 = (
            is_vertex_ai and "claude-opus-4-5" in self.config.model_name.lower()
        )

        #########################
        # Build arguments
        #########################
        # Optional kwargs - should only be passed to LiteLLM under certain conditions
        optional_kwargs: dict[str, Any] = {}

        # Model name
        model_provider = (
            f"{self.config.model_provider}/responses"
            if is_openai_model  # Uses litellm's completions -> responses bridge
            else self.config.model_provider
        )
        model = (
            f"{model_provider}/{self.config.deployment_name or self.config.model_name}"
        )

        # Tool choice
        if is_claude_model and tool_choice == ToolChoiceOptions.REQUIRED:
            # Claude models will not use reasoning if tool_choice is required
            # let it choose tools automatically so reasoning can still be used
            tool_choice = ToolChoiceOptions.AUTO

        # If no tools are provided, tool_choice should be None
        if not tools:
            tool_choice = None

        # Temperature
        temperature = 1 if is_reasoning else self._temperature

        if stream and not is_vertex_opus_4_5:
            optional_kwargs["stream_options"] = {"include_usage": True}

        # Note, there is a reasoning_effort parameter in LiteLLM but it is completely jank and does not work for any
        # of the major providers. Not setting it sets it to OFF.
        if (
            is_reasoning
            # The default of this parameter not set is surprisingly not the equivalent of an Auto but is actually Off
            and reasoning_effort != ReasoningEffort.OFF
            and not is_vertex_opus_4_5
        ):
            if is_openai_model:
                # OpenAI API does not accept reasoning params for GPT 5 chat models
                # (neither reasoning nor reasoning_effort are accepted)
                # even though they are reasoning models (bug in OpenAI)
                if "-chat" not in model:
                    optional_kwargs["reasoning"] = {
                        "effort": OPENAI_REASONING_EFFORT[reasoning_effort],
                        "summary": "auto",
                    }

            elif is_claude_model:
                budget_tokens: int | None = ANTHROPIC_REASONING_EFFORT_BUDGET.get(
                    reasoning_effort
                )

                if budget_tokens is not None:
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

                # LiteLLM just does some mapping like this anyway but is incomplete for Anthropic
                optional_kwargs.pop("reasoning_effort", None)

            else:
                # Hope for the best from LiteLLM
                if reasoning_effort in [
                    ReasoningEffort.LOW,
                    ReasoningEffort.MEDIUM,
                    ReasoningEffort.HIGH,
                ]:
                    optional_kwargs["reasoning_effort"] = reasoning_effort.value
                else:
                    optional_kwargs["reasoning_effort"] = ReasoningEffort.MEDIUM.value

        if tools:
            # OpenAI will error if parallel_tool_calls is True and tools are not specified
            optional_kwargs["parallel_tool_calls"] = parallel_tool_calls

        if structured_response_format:
            optional_kwargs["response_format"] = structured_response_format

        if not (is_claude_model or is_ollama or is_mistral):
            # Litellm bug: tool_choice is dropped silently if not specified here for OpenAI
            # However, this param breaks Anthropic and Mistral models,
            # so it must be conditionally included.
            # Additionally, tool_choice is not supported by Ollama and causes warnings if included.
            # See also, https://github.com/ollama/ollama/issues/11171
            optional_kwargs["allowed_openai_params"] = ["tool_choice"]

        # Passthrough kwargs
        passthrough_kwargs = build_litellm_passthrough_kwargs(
            model_kwargs=self._model_kwargs,
            user_identity=user_identity,
        )

        try:
            # NOTE: must pass in None instead of empty strings otherwise litellm
            # can have some issues with bedrock.
            # NOTE: Sometimes _model_kwargs may have an "api_key" kwarg
            # depending on what the caller passes in for custom_config. If it
            # does we allow it to clobber _api_key.
            if "api_key" not in passthrough_kwargs:
                passthrough_kwargs["api_key"] = self._api_key or None

            response = litellm.completion(
                mock_response=get_llm_mock_response() or MOCK_LLM_RESPONSE,
                model=model,
                base_url=self._api_base or None,
                api_version=self._api_version or None,
                custom_llm_provider=self._custom_llm_provider or None,
                messages=_prompt_to_dicts(prompt),
                tools=tools,
                tool_choice=tool_choice,
                stream=stream,
                temperature=temperature,
                timeout=timeout_override or self._timeout,
                max_tokens=max_tokens,
                client=client,
                **optional_kwargs,
                **passthrough_kwargs,
            )
            return response
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
        )

    def invoke(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
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
        # 3. WHY OTHER PROVIDERS DON'T NEED THIS:
        #    - Other providers (Anthropic, Bedrock, etc.) use litellm.module_level_client
        #      which handles concurrency appropriately
        #    - httpx.Client itself IS thread-safe for concurrent requests
        #    - The issue is specific to OpenAI's responses API path and connection reuse
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
        client = None
        if is_true_openai_model(self.config.model_provider, self.config.model_name):
            client = HTTPHandler(timeout=timeout_override or self._timeout)

        try:
            response = cast(
                LiteLLMModelResponse,
                self._completion(
                    prompt=prompt,
                    tools=tools,
                    tool_choice=tool_choice,
                    stream=False,
                    structured_response_format=structured_response_format,
                    timeout_override=timeout_override,
                    max_tokens=max_tokens,
                    parallel_tool_calls=True,
                    reasoning_effort=reasoning_effort,
                    user_identity=user_identity,
                    client=client,
                ),
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
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort = ReasoningEffort.AUTO,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        from litellm import CustomStreamWrapper as LiteLLMCustomStreamWrapper
        from litellm import HTTPHandler

        from onyx.llm.model_response import from_litellm_model_response_stream

        # HTTPHandler Threading & Connection Pool Notes:
        # =============================================
        # See invoke() method for full explanation. Key points for streaming:
        #
        # 1. SAME RESTRICTIONS APPLY:
        #    - HTTPHandler ONLY for true OpenAI models (use is_true_openai_model())
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
        client = None
        if is_true_openai_model(self.config.model_provider, self.config.model_name):
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

                yield model_response
        finally:
            if client is not None:
                client.close()
