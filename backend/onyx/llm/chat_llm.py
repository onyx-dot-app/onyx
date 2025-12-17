import os
import traceback
from collections.abc import Iterator
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import Union

from langchain_core.messages import BaseMessage

from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.configs.app_configs import SEND_USER_METADATA_TO_LLM_PROVIDER
from onyx.configs.chat_configs import QA_TIMEOUT
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.configs.model_configs import LITELLM_EXTRA_BODY
from onyx.llm.interfaces import LanguageModelInput
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import LLMUserIdentity
from onyx.llm.interfaces import ReasoningEffort
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.llm_provider_options import AZURE_PROVIDER_NAME
from onyx.llm.llm_provider_options import OLLAMA_PROVIDER_NAME
from onyx.llm.llm_provider_options import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.llm_provider_options import VERTEX_LOCATION_KWARG
from onyx.llm.model_response import ModelResponse
from onyx.llm.model_response import ModelResponseStream
from onyx.llm.models import CLAUDE_REASONING_BUDGET_TOKENS
from onyx.llm.models import OPENAI_REASONING_EFFORT
from onyx.llm.utils import is_true_openai_model
from onyx.llm.utils import model_is_reasoning_model
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
MAX_LITELLM_USER_ID_LENGTH = 64


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


def _truncate_litellm_user_id(user_id: str) -> str:
    if len(user_id) <= MAX_LITELLM_USER_ID_LENGTH:
        return user_id
    logger.warning(
        "LLM user id exceeds %d chars (len=%d); truncating for provider compatibility.",
        MAX_LITELLM_USER_ID_LENGTH,
        len(user_id),
    )
    return user_id[:MAX_LITELLM_USER_ID_LENGTH]


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
                if model_provider == "vertex_ai":
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
        # This is needed for Ollama to do proper function calling
        if model_provider == OLLAMA_PROVIDER_NAME and api_base is not None:
            os.environ["OLLAMA_API_BASE"] = api_base
        if extra_headers:
            model_kwargs.update({"extra_headers": extra_headers})
        if extra_body:
            model_kwargs.update({"extra_body": extra_body})

        self._model_kwargs = model_kwargs

        self._max_token_param = LEGACY_MAX_TOKENS_KWARG
        try:
            from litellm.utils import get_supported_openai_params

            params = get_supported_openai_params(model_name, model_provider)
            if STANDARD_MAX_TOKENS_KWARG in (params or []):
                self._max_token_param = STANDARD_MAX_TOKENS_KWARG
        except Exception as e:
            logger.warning(f"Error getting supported openai params: {e}")

    def _safe_model_config(self) -> dict:
        dump = self.config.model_dump()
        dump["api_key"] = mask_string(dump.get("api_key", ""))
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

        is_reasoning = model_is_reasoning_model(
            self.config.model_name, self.config.model_provider
        )

        # Needed to get reasoning tokens from the model
        # NOTE: OpenAI Responses API is disabled for parallel tool calls because LiteLLM's transformation layer
        # doesn't properly pass parallel_tool_calls to the API, causing the model to
        # always return sequential tool calls.
        if not parallel_tool_calls and (
            is_true_openai_model(self.config.model_provider, self.config.model_name)
            or self.config.model_provider == AZURE_PROVIDER_NAME
        ):
            model_provider = f"{self.config.model_provider}/responses"
        else:
            model_provider = self.config.model_provider

        completion_kwargs: dict[str, Any] = self._model_kwargs
        if SEND_USER_METADATA_TO_LLM_PROVIDER and user_identity:
            completion_kwargs = dict(self._model_kwargs)

            if user_identity.user_id:
                completion_kwargs["user"] = _truncate_litellm_user_id(
                    user_identity.user_id
                )

            if user_identity.session_id:
                existing_metadata = completion_kwargs.get("metadata")
                metadata: dict[str, Any] | None
                if existing_metadata is None:
                    metadata = {}
                elif isinstance(existing_metadata, dict):
                    metadata = dict(existing_metadata)
                else:
                    metadata = None

                if metadata is not None:
                    metadata["session_id"] = user_identity.session_id
                    completion_kwargs["metadata"] = metadata

        try:
            response = litellm.completion(
                mock_response=MOCK_LLM_RESPONSE,
                # model choice
                # model="openai/gpt-4",
                model=f"{model_provider}/{self.config.deployment_name or self.config.model_name}",
                # NOTE: have to pass in None instead of empty string for these
                # otherwise litellm can have some issues with bedrock
                api_key=self._api_key or None,
                base_url=self._api_base or None,
                api_version=self._api_version or None,
                custom_llm_provider=self._custom_llm_provider or None,
                # actual input
                messages=_prompt_to_dicts(prompt),
                tools=tools,
                tool_choice=tool_choice if tools else None,
                # streaming choice
                stream=stream,
                # model params
                temperature=(1 if is_reasoning else self._temperature),
                timeout=timeout_override or self._timeout,
                **({"stream_options": {"include_usage": True}} if stream else {}),
                # NOTE: we can't pass parallel_tool_calls if tools are not specified
                # or else OpenAI throws an error
                **({"parallel_tool_calls": parallel_tool_calls} if tools else {}),
                # Anthropic Claude uses `thinking` with budget_tokens for extended thinking
                # This applies to Claude models on any provider (anthropic, vertex_ai, bedrock)
                **(
                    {
                        "thinking": {
                            "type": "enabled",
                            "budget_tokens": CLAUDE_REASONING_BUDGET_TOKENS[
                                reasoning_effort
                            ],
                        }
                    }
                    if reasoning_effort
                    and reasoning_effort != ReasoningEffort.OFF
                    and is_reasoning
                    and "claude" in self.config.model_name.lower()
                    else {}
                ),
                # OpenAI and other providers use reasoning_effort
                # (litellm maps this to thinking_level for Gemini 3 models)
                **(
                    {"reasoning_effort": OPENAI_REASONING_EFFORT[reasoning_effort]}
                    if reasoning_effort
                    and reasoning_effort != ReasoningEffort.OFF
                    and is_reasoning
                    and "claude" not in self.config.model_name.lower()
                    else {}
                ),
                **(
                    {"response_format": structured_response_format}
                    if structured_response_format
                    else {}
                ),
                **({self._max_token_param: max_tokens} if max_tokens else {}),
                **completion_kwargs,
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

        return from_litellm_model_response(response)

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
            yield from_litellm_model_response_stream(chunk)
