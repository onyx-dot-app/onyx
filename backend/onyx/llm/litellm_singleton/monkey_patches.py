import json
from typing import cast
from typing import List
from typing import Optional
from typing import Tuple

from litellm import AllMessageValues
from litellm.litellm_core_utils.prompt_templates.common_utils import (
    convert_content_list_to_str,
)
from litellm.litellm_core_utils.prompt_templates.common_utils import (
    extract_images_from_message,
)
from litellm.llms.ollama.chat.transformation import OllamaChatConfig
from litellm.types.llms.ollama import OllamaChatCompletionMessage
from litellm.types.llms.ollama import OllamaToolCall
from litellm.types.llms.ollama import OllamaToolCallFunction
from litellm.types.llms.openai import ChatCompletionAssistantToolCall
from pydantic import BaseModel


def apply_monkey_patches() -> None:
    # Monkey patches for issues that are hopefully resolved soon
    # This is needed for litellm==1.79.0
    # Should be removed once this PR is merged: https://github.com/BerriAI/litellm/pull/
    if (
        getattr(OllamaChatConfig.transform_request, "__name__", "")
        == "_patched_transform_request"
    ):
        return

    def _patched_transform_request(
        self,  # type: ignore
        model: str,
        messages: List[AllMessageValues],
        optional_params: dict,
        litellm_params: dict,
        headers: dict,
    ) -> dict:
        stream = optional_params.pop("stream", False)
        format = optional_params.pop("format", None)
        keep_alive = optional_params.pop("keep_alive", None)
        think = optional_params.pop("think", None)
        function_name = optional_params.pop("function_name", None)
        litellm_params["function_name"] = function_name
        tools = optional_params.pop("tools", None)

        new_messages = []
        for m in messages:
            if isinstance(
                m, BaseModel
            ):  # avoid message serialization issues - https://github.com/BerriAI/litellm/issues/5319
                m = m.model_dump(exclude_none=True)
            tool_calls = m.get("tool_calls")
            new_tools: List[OllamaToolCall] = []
            if tool_calls is not None and isinstance(tool_calls, list):
                for tool in tool_calls:
                    typed_tool = ChatCompletionAssistantToolCall(**tool)
                    if typed_tool["type"] == "function":
                        arguments = {}
                        if "arguments" in typed_tool["function"]:
                            arguments = json.loads(typed_tool["function"]["arguments"])
                        ollama_tool_call = OllamaToolCall(
                            function=OllamaToolCallFunction(
                                name=typed_tool["function"].get("name") or "",
                                arguments=arguments,
                            )
                        )
                        new_tools.append(ollama_tool_call)
                cast(dict, m)["tool_calls"] = new_tools
            reasoning_content, parsed_content = _extract_reasoning_content(
                cast(dict, m)
            )
            content_str = convert_content_list_to_str(cast(AllMessageValues, m))
            images = extract_images_from_message(cast(AllMessageValues, m))

            ollama_message = OllamaChatCompletionMessage(
                role=cast(str, m.get("role")),
            )
            if reasoning_content is not None:
                ollama_message["thinking"] = reasoning_content
            if content_str is not None:
                ollama_message["content"] = content_str
            if images is not None:
                ollama_message["images"] = images
            if new_tools:
                ollama_message["tool_calls"] = new_tools

            new_messages.append(ollama_message)

            # Load Config
        config = self.get_config()
        for k, v in config.items():
            if k not in optional_params:
                optional_params[k] = v

        data = {
            "model": model,
            "messages": new_messages,
            "options": optional_params,
            "stream": stream,
        }
        if format is not None:
            data["format"] = format
        if tools is not None:
            data["tools"] = tools
        if keep_alive is not None:
            data["keep_alive"] = keep_alive
        if think is not None:
            data["think"] = think

        return data

    OllamaChatConfig.transform_request = _patched_transform_request


def _extract_reasoning_content(message: dict) -> Tuple[Optional[str], Optional[str]]:
    from litellm.litellm_core_utils.prompt_templates.common_utils import (
        _parse_content_for_reasoning,
    )

    message_content = message.get("content")
    if "reasoning_content" in message:
        return message["reasoning_content"], message["content"]
    elif "reasoning" in message:
        return message["reasoning"], message["content"]
    elif isinstance(message_content, str):
        return _parse_content_for_reasoning(message_content)
    return None, message_content
