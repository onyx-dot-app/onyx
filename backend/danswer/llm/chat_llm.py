import json
import os
from collections.abc import Iterator
from typing import Any
from typing import cast

import litellm  # type: ignore
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

from danswer.configs.app_configs import LOG_ALL_MODEL_INTERACTIONS
from danswer.configs.app_configs import LOG_DANSWER_MODEL_INTERACTIONS
from danswer.configs.model_configs import DISABLE_LITELLM_STREAMING
from danswer.configs.model_configs import GEN_AI_API_ENDPOINT
from danswer.configs.model_configs import GEN_AI_API_VERSION
from danswer.configs.model_configs import GEN_AI_LLM_PROVIDER_TYPE
from danswer.configs.model_configs import GEN_AI_MAX_OUTPUT_TOKENS
from danswer.configs.model_configs import GEN_AI_TEMPERATURE
from danswer.llm.interfaces import LLM
from danswer.llm.interfaces import LLMConfig
from danswer.llm.interfaces import ToolChoiceOptions
from danswer.utils.logger import setup_logger


logger = setup_logger()

# If a user configures a different model and it doesn't support all the same
# parameters like frequency and presence, just ignore them
litellm.drop_params = True
litellm.telemetry = False

litellm.set_verbose = LOG_ALL_MODEL_INTERACTIONS


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
    litellm_message: litellm.Message,
) -> BaseMessage:
    # Extracting the basic attributes from the litellm message
    content = litellm_message.content
    role = litellm_message.role

    # Handling function calls and tool calls if present
    tool_calls = (
        cast(
            list[litellm.utils.ChatCompletionMessageToolCall],
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
            tool_calls=[
                {
                    "name": tool_call.function.name or "",
                    "args": json.loads(tool_call.function.arguments),
                    "id": tool_call.id,
                }
                for tool_call in tool_calls
            ],
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
                    "index": 0,  # only support a single tool call atm
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
    _dict: dict[str, Any], curr_msg: BaseMessage | None
) -> BaseMessageChunk:
    """Adapted from langchain_community.chat_models.litellm._convert_delta_to_message_chunk"""
    role = _dict.get("role") or (_base_msg_to_role(curr_msg) if curr_msg else None)
    content = _dict.get("content") or ""
    additional_kwargs = {}
    if _dict.get("function_call"):
        additional_kwargs.update({"function_call": dict(_dict["function_call"])})
    tool_calls = cast(
        list[litellm.utils.ChatCompletionDeltaToolCall] | None, _dict.get("tool_calls")
    )

    if role == "user":
        return HumanMessageChunk(content=content)
    elif role == "assistant":
        if tool_calls:
            tool_call = tool_calls[0]
            tool_name = tool_call.function.name or (curr_msg and curr_msg.name) or ""

            tool_call_chunk = ToolCallChunk(
                name=tool_name,
                id=tool_call.id,
                args=tool_call.function.arguments,
                index=0,  # only support a single tool call atm
            )
            return AIMessageChunk(
                content=content,
                additional_kwargs=additional_kwargs,
                tool_call_chunks=[tool_call_chunk],
            )
        return AIMessageChunk(content=content, additional_kwargs=additional_kwargs)
    elif role == "system":
        return SystemMessageChunk(content=content)
    elif role == "function":
        return FunctionMessageChunk(content=content, name=_dict["name"])
    elif role:
        return ChatMessageChunk(content=content, role=role)

    raise ValueError(f"Unknown role: {role}")


class DefaultMultiLLM(LLM):
    """Uses Litellm library to allow easy configuration to use a multitude of LLMs
    See https://python.langchain.com/docs/integrations/chat/litellm"""

    def __init__(
        self,
        api_key: str | None,
        timeout: int,
        model_provider: str,
        model_name: str,
        api_base: str | None = GEN_AI_API_ENDPOINT,
        api_version: str | None = GEN_AI_API_VERSION,
        custom_llm_provider: str | None = GEN_AI_LLM_PROVIDER_TYPE,
        max_output_tokens: int = GEN_AI_MAX_OUTPUT_TOKENS,
        temperature: float = GEN_AI_TEMPERATURE,
        custom_config: dict[str, str] | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self._timeout = timeout
        self._model_provider = model_provider
        self._model_version = model_name
        self._temperature = temperature
        self._api_key = api_key
        self._api_base = api_base
        self._api_version = api_version
        self._custom_llm_provider = custom_llm_provider
        self._max_output_tokens = max_output_tokens
        self._custom_config = custom_config

        # NOTE: have to set these as environment variables for Litellm since
        # not all are able to passed in but they always support them set as env
        # variables
        if custom_config:
            for k, v in custom_config.items():
                os.environ[k] = v

        model_kwargs: dict[str, Any] = {}
        if extra_headers:
            model_kwargs.update({"extra_headers": extra_headers})

        self._model_kwargs = model_kwargs

    def log_model_configs(self) -> None:
        logger.debug(f"Config: {self.config}")

    def _completion(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None,
        tool_choice: ToolChoiceOptions | None,
        stream: bool,
    ) -> litellm.ModelResponse | litellm.CustomStreamWrapper:
        if isinstance(prompt, list):
            prompt = [
                _convert_message_to_dict(msg) if isinstance(msg, BaseMessage) else msg
                for msg in prompt
            ]
        elif isinstance(prompt, str):
            prompt = [_convert_message_to_dict(HumanMessage(content=prompt))]

        try:
            return litellm.completion(
                # model choice
                model=f"{self.config.model_provider}/{self.config.model_name}",
                api_key=self._api_key,
                base_url=self._api_base,
                api_version=self._api_version,
                custom_llm_provider=self._custom_llm_provider,
                # actual input
                messages=prompt,
                tools=tools,
                tool_choice=tool_choice if tools else None,
                # streaming choice
                stream=stream,
                # model params
                temperature=self._temperature,
                max_tokens=self._max_output_tokens
                if self._max_output_tokens > 0
                else None,
                timeout=self._timeout,
                # For now, we don't support parallel tool calls
                # NOTE: we can't pass this in if tools are not specified
                # or else OpenAI throws an error
                **({"parallel_tool_calls": False} if tools else {}),
                **self._model_kwargs,
            )
        except Exception as e:
            # for break pointing
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
        )

    def _invoke_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> BaseMessage:
        if LOG_DANSWER_MODEL_INTERACTIONS:
            self.log_model_configs()

        response = cast(
            litellm.ModelResponse, self._completion(prompt, tools, tool_choice, False)
        )
        return _convert_litellm_message_to_langchain_message(
            response.choices[0].message
        )

    def _stream_implementation(
        self,
        prompt: LanguageModelInput,
        tools: list[dict] | None = None,
        tool_choice: ToolChoiceOptions | None = None,
    ) -> Iterator[BaseMessage]:
        if LOG_DANSWER_MODEL_INTERACTIONS:
            self.log_model_configs()

        if DISABLE_LITELLM_STREAMING:
            yield self.invoke(prompt)
            return

        output = None
        response = self._completion(prompt, tools, tool_choice, True)
        try:
            for part in response:
                if len(part["choices"]) == 0:
                    continue
                delta = part["choices"][0]["delta"]
                message_chunk = _convert_delta_to_message_chunk(delta, output)
                if output is None:
                    output = message_chunk
                else:
                    output += message_chunk

                yield message_chunk

        except RemoteProtocolError:
            raise RuntimeError(
                "The AI model failed partway through generation, please try again."
            )

        if LOG_DANSWER_MODEL_INTERACTIONS and output:
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
