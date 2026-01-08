import os
import traceback
from collections.abc import Iterator
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import Union

from langchain_core.messages import BaseMessage

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.configs.chat_configs import QA_TIMEOUT
from onyx.configs.model_configs import DEFAULT_REASONING_EFFORT
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
from onyx.llm.models import OPENAI_REASONING_EFFORT
from onyx.llm.utils import build_litellm_passthrough_kwargs
from onyx.llm.utils import is_true_openai_model
from onyx.llm.utils import model_is_reasoning_model
from onyx.llm.well_known_providers.constants import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.well_known_providers.constants import VERTEX_LOCATION_KWARG
from onyx.server.utils import mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger
from onyx.utils.special_types import JSON_ro

logger = setup_logger()

if TYPE_CHECKING:
    from litellm import CustomStreamWrapper


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
    if isinstance(prompt, str):
        return [{"role": "user", "content": prompt}]
    return [msg.model_dump(exclude_none=True) for msg in prompt]


def _prompt_as_json(prompt: LanguageModelInput) -> JSON_ro:
    return cast(JSON_ro, _prompt_to_dicts(prompt))


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
        long_term_logger: LongTermLogger | None = None,
    ):
        self._timeout = timeout
        if timeout is None:
            if model_is_reasoning_model(model_name, model_provider):
                self._timeout = QA_TIMEOUT * 10  # Reasoning models are slow
            else:
                self._timeout = QA_TIMEOUT

        self._temperature = GEN_AI_TEMPERATURE if temperature is None else temperature

        self._model_provider = model_provider
        self._model_version = model_name
        self._api_key = api_key
        self._deployment_name = deployment_name
        self._api_base = api_base
        self._api_version = api_version
        self._custom_llm_provider = custom_llm_provider
        self._long_term_logger = long_term_logger
        self._max_input_tokens = max_input_tokens
        self._custom_config = custom_config

        # Create a dictionary for model-specific arguments if it's None
        model_kwargs = model_kwargs or {}

        # NOTE: have to set these as environment variables for Litellm since
        # not all are able to passed in but they always support them set as env
        # variables. We'll also try passing them in, since litellm just ignores
        # addtional kwargs (and some kwargs MUST be passed in rather than set as
        # env variables)
        if custom_config:
            # Specifically pass in "vertex_credentials" / "vertex_location" as a
            # model_kwarg to the completion call for vertex AI. More details here:
            # https://docs.litellm.ai/docs/providers/vertex
            for k, v in custom_config.items():
                if model_provider == LlmProviderNames.VERTEX_AI:
                    if k == VERTEX_CREDENTIALS_FILE_KWARG:
                        model_kwargs[k] = v
                        continue
                    elif k == VERTEX_LOCATION_KWARG:
                        model_kwargs[k] = v
                        continue

                # If there are any empty or null values,
                # they MUST NOT be set in the env
                if v is not None and v.strip():
                    os.environ[k] = v
                else:
                    os.environ.pop(k, None)

        # Default vertex_location to "global" if not provided for Vertex AI
        # Latest gemini models are only available through the global region
        if (
            model_provider == LlmProviderNames.VERTEX_AI
            and VERTEX_LOCATION_KWARG not in model_kwargs
        ):
            model_kwargs[VERTEX_LOCATION_KWARG] = "global"

        # This is needed for Ollama to do proper function calling
        if model_provider == LlmProviderNames.OLLAMA_CHAT and api_base is not None:
            os.environ["OLLAMA_API_BASE"] = api_base
        if extra_headers:
            model_kwargs.update({"extra_headers": extra_headers})
        if extra_body:
            model_kwargs.update({"extra_body": extra_body})

        self._model_kwargs = model_kwargs

    def _safe_model_config(self) -> dict:
        dump = self.config.model_dump()
        dump["api_key"] = mask_string(dump.get("api_key") or "")
        credentials_file = dump.get("credentials_file")
        if isinstance(credentials_file, str) and credentials_file:
            dump["credentials_file"] = mask_string(credentials_file)
        return dump

    def _record_call(
        self,
        prompt: LanguageModelInput,
    ) -> None:
        if self._long_term_logger:
            prompt_json = _prompt_as_json(prompt)
            self._long_term_logger.record(
                {
                    "prompt": prompt_json,
                    "model": cast(JSON_ro, self._safe_model_config()),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _record_result(
        self,
        prompt: LanguageModelInput,
        model_output: BaseMessage,
    ) -> None:
        if self._long_term_logger:
            prompt_json = _prompt_as_json(prompt)
            tool_calls = (
                model_output.tool_calls if hasattr(model_output, "tool_calls") else []
            )
            self._long_term_logger.record(
                {
                    "prompt": prompt_json,
                    "content": model_output.content,
                    "tool_calls": cast(JSON_ro, tool_calls),
                    "model": cast(JSON_ro, self._safe_model_config()),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _record_error(
        self,
        prompt: LanguageModelInput,
        error: Exception,
    ) -> None:
        if self._long_term_logger:
            prompt_json = _prompt_as_json(prompt)
            self._long_term_logger.record(
                {
                    "prompt": prompt_json,
                    "error": str(error),
                    "traceback": "".join(
                        traceback.format_exception(
                            type(error), error, error.__traceback__
                        )
                    ),
                    "model": cast(JSON_ro, self._safe_model_config()),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

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
        reasoning_effort: ReasoningEffort | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> Union["ModelResponse", "CustomStreamWrapper"]:
        self._record_call(prompt)
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

        if stream:
            optional_kwargs["stream_options"] = {"include_usage": True}

        # Use configured default if not provided (if not set in env, low)
        reasoning_effort = reasoning_effort or ReasoningEffort(DEFAULT_REASONING_EFFORT)
        if is_reasoning and reasoning_effort != ReasoningEffort.OFF:
            if is_openai_model:
                # OpenAI API does not accept reasoning params for GPT 5 chat models
                # (neither reasoning nor reasoning_effort are accepted)
                # even though they are reasoning models (bug in OpenAI)
                if "-chat" not in model:
                    optional_kwargs["reasoning"] = {
                        "effort": OPENAI_REASONING_EFFORT[reasoning_effort],
                        "summary": "auto",
                    }
            else:
                # Note that litellm auto maps reasoning_effort to thinking
                # and budget_tokens for Anthropic Claude models
                optional_kwargs["reasoning_effort"] = reasoning_effort

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
            # NOTE: must pass in None instead of empty strings
            # otherwise litellm can have some issues with bedrock
            response = litellm.completion(
                mock_response=MOCK_LLM_RESPONSE,
                model=model,
                api_key=self._api_key or None,
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
                **optional_kwargs,
                **passthrough_kwargs,
            )
            return response
        except Exception as e:
            self._record_error(prompt, e)
            # for break pointing
            if isinstance(e, Timeout):
                raise LLMTimeoutError(e)

            elif isinstance(e, RateLimitError):
                raise LLMRateLimitError(e)

            raise e

    @property
    def config(self) -> LLMConfig:
        credentials_file: str | None = (
            self._custom_config.get(VERTEX_CREDENTIALS_FILE_KWARG, None)
            if self._custom_config
            else None
        )

        return LLMConfig(
            model_provider=self._model_provider,
            model_name=self._model_version,
            temperature=self._temperature,
            api_key=self._api_key,
            api_base=self._api_base,
            api_version=self._api_version,
            deployment_name=self._deployment_name,
            credentials_file=credentials_file,
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
        reasoning_effort: ReasoningEffort | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> ModelResponse:
        from litellm import ModelResponse as LiteLLMModelResponse

        from onyx.llm.model_response import from_litellm_model_response

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
            ),
        )

        model_response = from_litellm_model_response(response)

        # Track LLM cost for Onyx-managed API keys
        if model_response.usage:
            self._track_llm_cost(model_response.usage)

        return model_response

    def stream(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
        reasoning_effort: ReasoningEffort | None = None,
        user_identity: LLMUserIdentity | None = None,
    ) -> Iterator[ModelResponseStream]:
        from litellm import CustomStreamWrapper as LiteLLMCustomStreamWrapper
        from onyx.llm.model_response import from_litellm_model_response_stream

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
            ),
        )

        for chunk in response:
            model_response = from_litellm_model_response_stream(chunk)

            # Track LLM cost when usage info is available (typically in the last chunk)
            if model_response.usage:
                self._track_llm_cost(model_response.usage)

            yield model_response
