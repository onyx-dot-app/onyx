import json
import os
import traceback
from collections.abc import Iterator
from collections.abc import Sequence
from typing import Any
from typing import cast
from typing import TYPE_CHECKING
from typing import Union

from httpx import RemoteProtocolError
from langchain.schema.language_model import LanguageModelInput
from langchain_core.messages import AIMessage
from langchain_core.messages import AIMessageChunk
from langchain_core.messages import BaseMessage
from langchain_core.messages import BaseMessageChunk
from langchain_core.messages import ChatMessage
from langchain_core.messages import ChatMessageChunk
from langchain_core.messages import FunctionMessage
from langchain_core.messages import FunctionMessageChunk
from langchain_core.messages import HumanMessage
from langchain_core.messages import HumanMessageChunk
from langchain_core.messages import SystemMessage
from langchain_core.messages import SystemMessageChunk
from langchain_core.messages.tool import ToolCallChunk
from langchain_core.messages.tool import ToolMessage
from langchain_core.prompt_values import PromptValue

from onyx.configs.app_configs import LOG_ONYX_MODEL_INTERACTIONS
from onyx.configs.app_configs import MOCK_LLM_RESPONSE
from onyx.configs.chat_configs import QA_TIMEOUT
from onyx.configs.model_configs import (
    DISABLE_LITELLM_STREAMING,
)
from onyx.configs.model_configs import GEN_AI_TEMPERATURE
from onyx.configs.model_configs import LITELLM_EXTRA_BODY
from onyx.llm.interfaces import LLM
from onyx.llm.interfaces import LLMConfig
from onyx.llm.interfaces import ToolChoiceOptions
from onyx.llm.llm_provider_options import VERTEX_CREDENTIALS_FILE_KWARG
from onyx.llm.llm_provider_options import VERTEX_LOCATION_KWARG
from onyx.llm.utils import model_is_reasoning_model
from onyx.server.utils import mask_string
from onyx.utils.logger import setup_logger
from onyx.utils.long_term_log import LongTermLogger

logger = setup_logger()

if TYPE_CHECKING:
    from litellm import ModelResponse, CustomStreamWrapper, Message


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


def _base_msg_to_role(msg: BaseMessage) -> str:
    if isinstance(msg, HumanMessage) or isinstance(msg, HumanMessageChunk):
        return "user"
    if isinstance(msg, AIMessage) or isinstance(msg, AIMessageChunk):
        return "assistant"
    if isinstance(msg, SystemMessage) or isinstance(msg, SystemMessageChunk):
        return "system"
    if isinstance(msg, FunctionMessage) or isinstance(msg, FunctionMessageChunk):
        return "function"
    return "unknown"


def _convert_litellm_message_to_langchain_message(
    litellm_message: "Message",
) -> BaseMessage:
    from onyx.llm.litellm_singleton import litellm

    # Extracting the basic attributes from the litellm message
    content = litellm_message.content or ""
    role = litellm_message.role

    # Handling function calls and tool calls if present
    tool_calls = (
        cast(
            list[litellm.ChatCompletionMessageToolCall],
            litellm_message.tool_calls,
        )
        if hasattr(litellm_message, "tool_calls")
        else []
    )

    # Create the appropriate langchain message based on the role
    if role == "user":
        return HumanMessage(content=content)
    elif role == "assistant":
        return AIMessage(
            content=content,
            tool_calls=(
                [
                    {
                        "name": tool_call.function.name or "",
                        "args": json.loads(tool_call.function.arguments),
                        "id": tool_call.id,
                    }
                    for tool_call in tool_calls
                ]
                if tool_calls
                else []
            ),
        )
    elif role == "system":
        return SystemMessage(content=content)
    else:
        raise ValueError(f"Unknown role type received: {role}")


def _convert_message_to_dict(message: BaseMessage) -> dict:
    """Adapted from langchain_community.chat_models.litellm._convert_message_to_dict"""
    if isinstance(message, ChatMessage):
        message_dict = {"role": message.role, "content": message.content}
    elif isinstance(message, HumanMessage):
        message_dict = {"role": "user", "content": message.content}
    elif isinstance(message, AIMessage):
        message_dict = {"role": "assistant", "content": message.content}
        if message.tool_calls:
            message_dict["tool_calls"] = [
                {
                    "id": tool_call.get("id"),
                    "function": {
                        "name": tool_call["name"],
                        "arguments": json.dumps(tool_call["args"]),
                    },
                    "type": "function",
                    "index": tool_call.get("index", 0),
                }
                for tool_call in message.tool_calls
            ]
        if "function_call" in message.additional_kwargs:
            message_dict["function_call"] = message.additional_kwargs["function_call"]
    elif isinstance(message, SystemMessage):
        message_dict = {"role": "system", "content": message.content}
    elif isinstance(message, FunctionMessage):
        message_dict = {
            "role": "function",
            "content": message.content,
            "name": message.name,
        }
    elif isinstance(message, ToolMessage):
        message_dict = {
            "tool_call_id": message.tool_call_id,
            "role": "tool",
            "name": message.name or "",
            "content": message.content,
        }
    else:
        raise ValueError(f"Got unknown type {message}")
    if "name" in message.additional_kwargs:
        message_dict["name"] = message.additional_kwargs["name"]
    return message_dict


def _convert_delta_to_message_chunk(
    _dict: dict[str, Any],
    curr_msg: BaseMessage | None,
    stop_reason: str | None = None,
) -> BaseMessageChunk:
    from litellm.utils import ChatCompletionDeltaToolCall

    """Adapted from langchain_community.chat_models.litellm._convert_delta_to_message_chunk"""
    role = _dict.get("role") or (_base_msg_to_role(curr_msg) if curr_msg else "unknown")
    content = _dict.get("content") or ""
    additional_kwargs = {}
    if _dict.get("function_call"):
        additional_kwargs.update({"function_call": dict(_dict["function_call"])})
    tool_calls = cast(list[ChatCompletionDeltaToolCall] | None, _dict.get("tool_calls"))

    if role == "user":
        return HumanMessageChunk(content=content)
    # NOTE: if tool calls are present, then it's an assistant.
    # In Ollama, the role will be None for tool-calls
    elif role == "assistant" or tool_calls:
        if tool_calls:
            tool_call = tool_calls[0]
            tool_name = tool_call.function.name or (curr_msg and curr_msg.name) or ""
            idx = tool_call.index

            tool_call_chunk = ToolCallChunk(
                name=tool_name,
                id=tool_call.id,
                args=tool_call.function.arguments,
                index=idx,
            )

            return AIMessageChunk(
                content=content,
                tool_call_chunks=[tool_call_chunk],
                additional_kwargs={
                    "usage_metadata": {"stop": stop_reason},
                    **additional_kwargs,
                },
            )

        return AIMessageChunk(
            content=content,
            additional_kwargs={
                "usage_metadata": {"stop": stop_reason},
                **additional_kwargs,
            },
        )
    elif role == "system":
        return SystemMessageChunk(content=content)
    elif role == "function":
        return FunctionMessageChunk(content=content, name=_dict["name"])
    elif role:
        return ChatMessageChunk(content=content, role=role)

    raise ValueError(f"Unknown role: {role}")


def _prompt_to_dict(
    prompt: LanguageModelInput,
) -> Sequence[str | list[str] | dict[str, Any] | tuple[str, str]]:
    # NOTE: this must go first, since it is also a Sequence
    if isinstance(prompt, str):
        return [_convert_message_to_dict(HumanMessage(content=prompt))]

    if isinstance(prompt, (list, Sequence)):
        return [
            _convert_message_to_dict(msg) if isinstance(msg, BaseMessage) else msg
            for msg in prompt
        ]

    if isinstance(prompt, PromptValue):
        return [_convert_message_to_dict(message) for message in prompt.to_messages()]


class DefaultMultiLLM(LLM):
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

                # for all values, set them as env variables
                os.environ[k] = v

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

    def log_model_configs(self) -> None:
        logger.debug(f"Config: {self._safe_model_config()}")

    def _record_call(self, prompt: LanguageModelInput) -> None:
        if self._long_term_logger:
            self._long_term_logger.record(
                {"prompt": _prompt_to_dict(prompt), "model": self._safe_model_config()},
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _record_result(
        self, prompt: LanguageModelInput, model_output: BaseMessage
    ) -> None:
        if self._long_term_logger:
            self._long_term_logger.record(
                {
                    "prompt": _prompt_to_dict(prompt),
                    "content": model_output.content,
                    "tool_calls": (
                        model_output.tool_calls
                        if hasattr(model_output, "tool_calls")
                        else []
                    ),
                    "model": self._safe_model_config(),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _record_error(self, prompt: LanguageModelInput, error: Exception) -> None:
        if self._long_term_logger:
            self._long_term_logger.record(
                {
                    "prompt": _prompt_to_dict(prompt),
                    "error": str(error),
                    "traceback": "".join(
                        traceback.format_exception(
                            type(error), error, error.__traceback__
                        )
                    ),
                    "model": self._safe_model_config(),
                },
                category=_LLM_PROMPT_LONG_TERM_LOG_CATEGORY,
            )

    def _completion(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None,
        tool_choice: ToolChoiceOptions | None,
        stream: bool,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Union["ModelResponse", "CustomStreamWrapper"]:
        # litellm doesn't accept LangChain BaseMessage objects, so we need to convert them
        # to a dict representation
        processed_prompt = _prompt_to_dict(prompt)
        self._record_call(processed_prompt)
        from onyx.llm.litellm_singleton import litellm
        from litellm.exceptions import Timeout, RateLimitError

        try:
            return litellm.completion(
                mock_response=MOCK_LLM_RESPONSE,
                # model choice
                # model="openai/gpt-4",
                model=f"{self.config.model_provider}/{self.config.deployment_name or self.config.model_name}",
                # NOTE: have to pass in None instead of empty string for these
                # otherwise litellm can have some issues with bedrock
                api_key=self._api_key or None,
                base_url=self._api_base or None,
                api_version=self._api_version or None,
                custom_llm_provider=self._custom_llm_provider or None,
                # actual input
                messages=processed_prompt,
                tools=tools,
                tool_choice=tool_choice if tools else None,
                # streaming choice
                stream=stream,
                # model params
                temperature=(
                    1
                    if self.config.model_name in ["gpt-5", "gpt-5-mini", "gpt-5-nano"]
                    else self._temperature
                ),
                timeout=timeout_override or self._timeout,
                # For now, we don't support parallel tool calls
                # NOTE: we can't pass this in if tools are not specified
                # or else OpenAI throws an error
                **(
                    {"parallel_tool_calls": False}
                    if tools
                    and self.config.model_name
                    not in [
                        "o3-mini",
                        "o3-preview",
                        "o1",
                        "o1-preview",
                        "o1-mini",
                        "o1-mini-2024-09-12",
                        "o3-mini-2025-01-31",
                    ]
                    else {}
                ),  # TODO: remove once LITELLM has patched
                **(
                    {"reasoning_effort": "minimal"}
                    if self.config.model_name
                    in [
                        "gpt-5",
                        "gpt-5-mini",
                        "gpt-5-nano",
                    ]
                    else {}
                ),  # TODO: remove once LITELLM has better support/we change API
                **(
                    {"response_format": structured_response_format}
                    if structured_response_format
                    else {}
                ),
                **({self._max_token_param: max_tokens} if max_tokens else {}),
                **self._model_kwargs,
            )
        except Exception as e:

            self._record_error(processed_prompt, e)
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

    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> BaseMessage:
        from litellm import ModelResponse

        if LOG_ONYX_MODEL_INTERACTIONS:
            self.log_model_configs()

        response = cast(
            ModelResponse,
            self._completion(
                prompt=prompt,
                tools=tools,
                tool_choice=tool_choice,
                stream=False,
                structured_response_format=structured_response_format,
                timeout_override=timeout_override,
                max_tokens=max_tokens,
            ),
        )
        choice = response.choices[0]
        if hasattr(choice, "message"):
            output = _convert_litellm_message_to_langchain_message(choice.message)
            if output:
                self._record_result(prompt, output)
            return output
        else:
            raise ValueError("Unexpected response choice type")

    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
        structured_response_format: dict | None = None,
        timeout_override: int | None = None,
        max_tokens: int | None = None,
    ) -> Iterator[BaseMessage]:
        from litellm import CustomStreamWrapper

        if LOG_ONYX_MODEL_INTERACTIONS:
            self.log_model_configs()

        if DISABLE_LITELLM_STREAMING:
            yield self.invoke(
                prompt,
                tools,
                tool_choice,
                structured_response_format,
                timeout_override,
                max_tokens,
            )
            return

        output = None
        response = cast(
            CustomStreamWrapper,
            self._completion(
                prompt=prompt,
                tools=tools,
                tool_choice=tool_choice,
                stream=True,
                structured_response_format=structured_response_format,
                timeout_override=timeout_override,
                max_tokens=max_tokens,
            ),
        )
        try:
            for part in response:
                if not part["choices"]:
                    continue

                choice = part["choices"][0]
                message_chunk = _convert_delta_to_message_chunk(
                    choice["delta"],
                    output,
                    stop_reason=choice["finish_reason"],
                )

                if output is None:
                    output = message_chunk
                else:
                    output += message_chunk

                yield message_chunk

        except RemoteProtocolError:
            raise RuntimeError(
                "The AI model failed partway through generation, please try again."
            )

        if output:
            self._record_result(prompt, output)

        if LOG_ONYX_MODEL_INTERACTIONS and output:
            content = output.content or ""
            if isinstance(output, AIMessage):
                if content:
                    log_msg = content
                elif output.tool_calls:
                    log_msg = "Tool Calls: " + str(
                        [
                            {
                                key: value
                                for key, value in tool_call.items()
                                if key != "index"
                            }
                            for tool_call in output.tool_calls
                        ]
                    )
                else:
                    log_msg = ""
                logger.debug(f"Raw Model Output:\n{log_msg}")
            else:
                logger.debug(f"Raw Model Output:\n{content}")
