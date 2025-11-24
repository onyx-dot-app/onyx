import json
import time
import uuid
from typing import Any
from typing import cast
from typing import Dict
from typing import List
from typing import Optional
from typing import Tuple
from typing import Union

from litellm import AllMessageValues
from litellm import LiteLLMLoggingObj
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
)
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    OpenAiResponsesToChatCompletionStreamIterator,
)
from litellm.litellm_core_utils.prompt_templates.common_utils import (
    convert_content_list_to_str,
)
from litellm.litellm_core_utils.prompt_templates.common_utils import (
    extract_images_from_message,
)
from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator
from litellm.llms.ollama.chat.transformation import OllamaChatConfig
from litellm.llms.ollama.common_utils import OllamaError
from litellm.types.llms.ollama import OllamaChatCompletionMessage
from litellm.types.llms.ollama import OllamaToolCall
from litellm.types.llms.ollama import OllamaToolCallFunction
from litellm.types.llms.openai import ChatCompletionAssistantToolCall
from litellm.types.utils import ChatCompletionUsageBlock
from litellm.types.utils import GenericStreamingChunk
from litellm.types.utils import ModelResponseStream
from litellm.utils import verbose_logger
from pydantic import BaseModel


def _patch_ollama_transform_request_so_tool_calls_streamed() -> None:
    if (
        getattr(OllamaChatConfig.transform_request, "__name__", "")
        == "_patched_transform_request"
    ):
        return

    def _patched_transform_request(
        self: Any,
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
                    typed_tool = ChatCompletionAssistantToolCall(**tool)  # type: ignore[typeddict-item]
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

    OllamaChatConfig.transform_request = _patched_transform_request  # type: ignore[method-assign]


def _patch_ollama_chunk_parser_so_reasoning_streamed() -> None:
    if (
        getattr(OllamaChatCompletionResponseIterator.chunk_parser, "__name__", "")
        == "_patched_chunk_parser"
    ):
        return

    def _patched_chunk_parser(self: Any, chunk: dict) -> ModelResponseStream:
        try:
            """
            Expected chunk format:
            {
                "model": "llama3.1",
                "created_at": "2025-05-24T02:12:05.859654Z",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "tool_calls": [{
                        "function": {
                            "name": "get_latest_album_ratings",
                            "arguments": {
                                "artist_name": "Taylor Swift"
                            }
                        }
                    }]
                },
                "done_reason": "stop",
                "done": true,
                ...
            }
            Need to:
            - convert 'message' to 'delta'
            - return finish_reason when done is true
            - return usage when done is true
            """
            from litellm.types.utils import Delta
            from litellm.types.utils import StreamingChoices

            # process tool calls - if complete function arg - add id to tool call
            tool_calls = chunk["message"].get("tool_calls")
            if tool_calls is not None:
                for tool_call in tool_calls:
                    function_args = tool_call.get("function").get("arguments")
                    if function_args is not None and len(function_args) > 0:
                        is_function_call_complete = self._is_function_call_complete(
                            function_args
                        )
                        if is_function_call_complete:
                            tool_call["id"] = str(uuid.uuid4())

            # PROCESS REASONING CONTENT
            reasoning_content: Optional[str] = None
            content: Optional[str] = None
            if chunk["message"].get("thinking") is not None:
                # Always process thinking content when present
                reasoning_content = chunk["message"].get("thinking")
                if self.started_reasoning_content is False:
                    self.started_reasoning_content = True
            elif chunk["message"].get("content") is not None:
                # Mark thinking as finished when we start getting regular content
                if (
                    self.started_reasoning_content
                    and not self.finished_reasoning_content
                ):
                    self.finished_reasoning_content = True

                message_content = chunk["message"].get("content")
                if "<think>" in message_content:
                    message_content = message_content.replace("<think>", "")
                    self.started_reasoning_content = True
                if "</think>" in message_content and self.started_reasoning_content:
                    message_content = message_content.replace("</think>", "")
                    self.finished_reasoning_content = True
                if (
                    self.started_reasoning_content
                    and not self.finished_reasoning_content
                ):
                    reasoning_content = message_content
                else:
                    content = message_content

            delta = Delta(
                content=content,
                reasoning_content=reasoning_content,
                tool_calls=tool_calls,
            )
            if chunk["done"] is True:
                finish_reason = chunk.get("done_reason", "stop")
                choices = [
                    StreamingChoices(
                        delta=delta,
                        finish_reason=finish_reason,
                    )
                ]
            else:
                choices = [
                    StreamingChoices(
                        delta=delta,
                    )
                ]

            usage = ChatCompletionUsageBlock(
                prompt_tokens=chunk.get("prompt_eval_count", 0),
                completion_tokens=chunk.get("eval_count", 0),
                total_tokens=chunk.get("prompt_eval_count", 0)
                + chunk.get("eval_count", 0),
            )

            return ModelResponseStream(
                id=str(uuid.uuid4()),
                object="chat.completion.chunk",
                created=int(time.time()),  # ollama created_at is in UTC
                usage=usage,
                model=chunk["model"],
                choices=choices,
            )
        except KeyError as e:
            raise OllamaError(
                message=f"KeyError: {e}, Got unexpected response from Ollama: {chunk}",
                status_code=400,
                headers={"Content-Type": "application/json"},
            )
        except Exception as e:
            raise e

    OllamaChatCompletionResponseIterator.chunk_parser = _patched_chunk_parser  # type: ignore[method-assign]


def _patch_openai_responses_chunk_parser_so_reasoning_streamed() -> None:
    if (
        getattr(
            OpenAiResponsesToChatCompletionStreamIterator.chunk_parser,
            "__name__",
            "",
        )
        == "_patched_openai_responses_chunk_parser"
    ):
        return

    def _patched_openai_responses_chunk_parser(
        self: Any, chunk: dict
    ) -> Union["GenericStreamingChunk", "ModelResponseStream"]:
        # Transform responses API streaming chunk to chat completion format
        from litellm.types.llms.openai import ChatCompletionToolCallFunctionChunk
        from litellm.types.utils import (
            ChatCompletionToolCallChunk,
            GenericStreamingChunk,
        )

        verbose_logger.debug(
            f"Chat provider: transform_streaming_response called with chunk: {chunk}"
        )
        parsed_chunk = chunk
        if not parsed_chunk:
            raise ValueError("Chat provider: Empty parsed_chunk")
        if not isinstance(parsed_chunk, dict):
            raise ValueError(f"Chat provider: Invalid chunk type {type(parsed_chunk)}")
        # Handle different event types from responses API

        event_type = parsed_chunk.get("type")
        verbose_logger.debug(f"Chat provider: Processing event type: {event_type}")

        if event_type == "response.created":
            # Initial response creation event
            verbose_logger.debug(f"Chat provider: response.created -> {chunk}")
            return GenericStreamingChunk(
                text="", tool_use=None, is_finished=False, finish_reason="", usage=None
            )

        elif event_type == "response.output_item.added":
            # New output item added
            output_item = parsed_chunk.get("item", {})
            if output_item.get("type") == "function_call":
                return GenericStreamingChunk(
                    text="",
                    tool_use=ChatCompletionToolCallChunk(
                        id=output_item.get("call_id"),
                        index=0,
                        type="function",
                        function=ChatCompletionToolCallFunctionChunk(
                            name=output_item.get("name", None),
                            arguments=parsed_chunk.get("arguments", ""),
                        ),
                    ),
                    is_finished=False,
                    finish_reason="",
                    usage=None,
                )
            elif output_item.get("type") == "message":
                pass
            elif output_item.get("type") == "reasoning":
                pass
            else:
                raise ValueError(f"Chat provider: Invalid output_item  {output_item}")

        elif event_type == "response.function_call_arguments.delta":
            content_part: Optional[str] = parsed_chunk.get("delta", None)
            if content_part:
                return GenericStreamingChunk(
                    text="",
                    tool_use=ChatCompletionToolCallChunk(
                        id=None,
                        index=0,
                        type="function",
                        function=ChatCompletionToolCallFunctionChunk(
                            name=None, arguments=content_part
                        ),
                    ),
                    is_finished=False,
                    finish_reason="",
                    usage=None,
                )
            else:
                raise ValueError(
                    f"Chat provider: Invalid function argument delta {parsed_chunk}"
                )

        elif event_type == "response.output_item.done":
            # New output item added
            output_item = parsed_chunk.get("item", {})
            if output_item.get("type") == "function_call":
                return GenericStreamingChunk(
                    text="",
                    tool_use=ChatCompletionToolCallChunk(
                        id=output_item.get("call_id"),
                        index=0,
                        type="function",
                        function=ChatCompletionToolCallFunctionChunk(
                            name=parsed_chunk.get("name", None),
                            arguments="",  # responses API sends everything again, we don't
                        ),
                    ),
                    is_finished=True,
                    finish_reason="tool_calls",
                    usage=None,
                )
            elif output_item.get("type") == "message":
                return GenericStreamingChunk(
                    finish_reason="stop", is_finished=True, usage=None, text=""
                )
            elif output_item.get("type") == "reasoning":
                pass
            else:
                raise ValueError(f"Chat provider: Invalid output_item  {output_item}")

        elif event_type == "response.output_text.delta":
            # Content part added to output
            content_part = parsed_chunk.get("delta", None)
            if content_part is not None:
                return GenericStreamingChunk(
                    text=content_part,
                    tool_use=None,
                    is_finished=False,
                    finish_reason="",
                    usage=None,
                )
            else:
                raise ValueError(f"Chat provider: Invalid text delta {parsed_chunk}")

        elif event_type == "response.reasoning_summary_text.delta":
            content_part = parsed_chunk.get("delta", None)
            if content_part:
                from litellm.types.utils import (
                    Delta,
                    ModelResponseStream,
                    StreamingChoices,
                )

                return ModelResponseStream(
                    choices=[
                        StreamingChoices(
                            index=cast(int, parsed_chunk.get("summary_index")),
                            delta=Delta(reasoning_content=content_part),
                        )
                    ]
                )

        else:
            pass

        # For any unhandled event types, create a minimal valid chunk or skip
        verbose_logger.debug(
            f"Chat provider: Unhandled event type '{event_type}', creating empty chunk"
        )
        # Return a minimal valid chunk for unknown events
        return GenericStreamingChunk(
            text="", tool_use=None, is_finished=False, finish_reason="", usage=None
        )

    _patched_openai_responses_chunk_parser.__name__ = (
        "_patched_openai_responses_chunk_parser"
    )
    OpenAiResponsesToChatCompletionStreamIterator.chunk_parser = _patched_openai_responses_chunk_parser  # type: ignore[method-assign]


def _patch_litellm_responses_transformation_handler_so_tool_choice_formatted() -> None:
    if (
        getattr(
            LiteLLMResponsesTransformationHandler.transform_request,
            "__name__",
            "",
        )
        == "_patched_transform_request"
    ):
        return

    def _patched_transform_request(
        self,
        model: str,
        messages: List["AllMessageValues"],
        optional_params: dict,
        litellm_params: dict,
        headers: dict,
        litellm_logging_obj: "LiteLLMLoggingObj",
        client: Optional[Any] = None,
    ) -> dict:
        from litellm.types.llms.openai import ResponsesAPIOptionalRequestParams

        (
            input_items,
            instructions,
        ) = self.convert_chat_completion_messages_to_responses_api(messages)

        # Build responses API request using the reverse transformation logic
        responses_api_request = ResponsesAPIOptionalRequestParams()

        # Set instructions if we found a system message
        if instructions:
            responses_api_request["instructions"] = instructions

        # Map optional parameters
        for key, value in optional_params.items():
            if value is None:
                continue
            if key in ("max_tokens", "max_completion_tokens"):
                responses_api_request["max_output_tokens"] = value
            elif key == "tools" and value is not None:
                # Convert chat completion tools to responses API tools format
                responses_api_request["tools"] = (
                    LiteLLMResponsesTransformationHandler._convert_tools_to_responses_format(
                        None, cast(List[Dict[str, Any]], value)
                    )
                )
            elif key == "tool_choice" and value is not None:
                # TODO this needs to be way more sophisticated
                responses_api_request["tool_choice"] = (
                    {
                        "type": "function",
                        "name": (
                            value
                            if isinstance(value, str)
                            else value["function"]["name"]
                        ),
                    }
                    if isinstance(value, dict)
                    else value
                )
            elif key in ResponsesAPIOptionalRequestParams.__annotations__.keys():
                responses_api_request[key] = value  # type: ignore
            elif key in ("metadata"):
                responses_api_request["metadata"] = value
            elif key in ("previous_response_id"):
                responses_api_request["previous_response_id"] = value
            elif key == "reasoning_effort":
                responses_api_request["reasoning"] = self._map_reasoning_effort(value)

        # Get stream parameter from litellm_params if not in optional_params
        stream = optional_params.get("stream") or litellm_params.get("stream", False)
        verbose_logger.debug(f"Chat provider: Stream parameter: {stream}")

        # Ensure stream is properly set in the request
        if stream:
            responses_api_request["stream"] = True

        # Handle session management if previous_response_id is provided
        previous_response_id = optional_params.get("previous_response_id")
        if previous_response_id:
            # Use the existing session handler for responses API
            verbose_logger.debug(
                f"Chat provider: Warning ignoring previous response ID: {previous_response_id}"
            )

        # Convert back to responses API format for the actual request

        api_model = model

        from litellm.types.utils import CallTypes

        setattr(litellm_logging_obj, "call_type", CallTypes.responses.value)

        request_data = {
            "model": api_model,
            "input": input_items,
            "litellm_logging_obj": litellm_logging_obj,
            **litellm_params,
            "client": client,
        }

        verbose_logger.debug(
            f"Chat provider: Final request model={api_model}, input_items={len(input_items)}"
        )

        # Add non-None values from responses_api_request
        for key, value in responses_api_request.items():
            if value is not None:
                if key == "instructions" and instructions:
                    request_data["instructions"] = instructions
                elif key == "stream_options" and isinstance(value, dict):
                    request_data["stream_options"] = value.get("include_obfuscation")
                elif key == "user":  # string can't be longer than 64 characters
                    if isinstance(value, str) and len(value) <= 64:
                        request_data["user"] = value
                else:
                    request_data[key] = value

        return request_data

    _patched_transform_request.__name__ = "_patched_transform_request"
    LiteLLMResponsesTransformationHandler.transform_request = _patched_transform_request  # type: ignore[method-assign]


def apply_monkey_patches() -> None:
    """
    Apply all necessary monkey patches to LiteLLM for compatibility.

    This includes:
    - Patching OllamaChatConfig.transform_request for reasoning content support
    - Patching OllamaChatCompletionResponseIterator.chunk_parser for streaming content
    - Patching OpenAiResponsesToChatCompletionStreamIterator.chunk_parser for OpenAI Responses API
    - Patching LiteLLMResponsesTransformationHandler.transform_request for tool choice formatting
    """
    _patch_ollama_transform_request_so_tool_calls_streamed()
    _patch_ollama_chunk_parser_so_reasoning_streamed()
    _patch_openai_responses_chunk_parser_so_reasoning_streamed()
    _patch_litellm_responses_transformation_handler_so_tool_choice_formatted()


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
