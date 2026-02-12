"""
LiteLLM Monkey Patches

This module addresses the following issues in LiteLLM:

Status checked against LiteLLM v1.81.6-nightly (2026-02-02):

1. Ollama Streaming Reasoning Content (_patch_ollama_chunk_parser):
   - LiteLLM's chunk_parser doesn't properly handle reasoning content in streaming
     responses from Ollama
   - Processes native "thinking" field from Ollama responses
   - Also handles <think>...</think> tags in content for models that use that format
   - Tracks reasoning state to properly separate thinking from regular content
   STATUS: STILL NEEDED - LiteLLM has a bug where it only yields thinking content on
           the first two chunks, then stops (lines 504-510). Our patch correctly yields
           ALL thinking chunks. The upstream logic sets finished_reasoning_content=True
           on the second chunk instead of when regular content starts.

2. OpenAI Responses API Parallel Tool Calls (_patch_openai_responses_parallel_tool_calls):
   - LiteLLM's translate_responses_chunk_to_openai_stream hardcodes index=0 for all tool calls
   - This breaks parallel tool calls where multiple functions are called simultaneously
   - The OpenAI Responses API provides output_index in streaming events to track which
     tool call each event belongs to
   STATUS: STILL NEEDED - LiteLLM hardcodes index=0 in translate_responses_chunk_to_openai_stream
           for response.output_item.added (line 962), response.function_call_arguments.delta
           (line 989), and response.output_item.done (line 1033). Our patch uses output_index
           from the event to properly track parallel tool calls.

3. OpenAI Responses API Non-Streaming (_patch_openai_responses_transform_response):
   - LiteLLM's transform_response doesn't properly concatenate multiple reasoning
     summary parts in non-streaming responses
   - Multiple ReasoningSummaryItem objects should be joined with newlines
   STATUS: STILL NEEDED - LiteLLM's _convert_response_output_to_choices (lines 366-370)
           only keeps the LAST summary item text, discarding earlier parts. Our patch
           concatenates all summary texts with double newlines.

4. Azure Responses API Fake Streaming (_patch_azure_responses_should_fake_stream):
   - LiteLLM uses "fake streaming" (MockResponsesAPIStreamingIterator) for models
     not in its database, which buffers the entire response before yielding
   - This causes poor time-to-first-token for Azure custom model deployments
   - Azure's Responses API supports native streaming, so we force real streaming
   STATUS: STILL NEEDED - AzureOpenAIResponsesAPIConfig does NOT override should_fake_stream,
           so it inherits from OpenAIResponsesAPIConfig which returns True for models not
           in litellm.utils.supports_native_streaming(). Custom Azure deployments will
           still use fake streaming without this patch.

# Note: 5 and 6 are to supress a warning and may fix usage info but is not strictly required for the app to run
5. Responses API Usage Format Mismatch (_patch_responses_api_usage_format):
   - LiteLLM uses model_construct as a fallback in multiple places when
     ResponsesAPIResponse validation fails
   - This bypasses the usage validator, allowing chat completion format usage
     (completion_tokens, prompt_tokens) to be stored instead of Responses API format
     (input_tokens, output_tokens)
   - When model_dump() is later called, Pydantic emits a serialization warning
   STATUS: STILL NEEDED - Multiple files use model_construct which bypasses validation:
           openai/responses/transformation.py, chatgpt/responses/transformation.py,
           manus/responses/transformation.py, volcengine/responses/transformation.py,
           and handler.py. Our patch wraps ResponsesAPIResponse.model_construct itself
           to transform usage in all code paths.

6. Logging Usage Transformation Warning (_patch_logging_assembled_streaming_response):
   - LiteLLM's _get_assembled_streaming_response in litellm_logging.py transforms
     ResponseAPIUsage to chat completion format and sets it as a dict on the
     ResponsesAPIResponse.usage field
   - This replaces the proper ResponseAPIUsage object with a dict, causing Pydantic
     to emit a serialization warning when model_dump() is called later
   STATUS: STILL NEEDED - litellm_core_utils/litellm_logging.py lines 3185-3199 set
           usage as a dict with chat completion format instead of keeping it as
           ResponseAPIUsage. Our patch creates a deep copy before modification.
"""

import time
import uuid
from typing import Any
from typing import cast
from typing import List
from typing import Optional

from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
)
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    OpenAiResponsesToChatCompletionStreamIterator,
)
from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator
from litellm.llms.ollama.common_utils import OllamaError
from litellm.types.utils import ChatCompletionUsageBlock
from litellm.types.utils import ModelResponseStream


def _patch_ollama_chunk_parser() -> None:
    """
    Patches OllamaChatCompletionResponseIterator.chunk_parser to properly handle
    reasoning content and content in streaming responses.
    """
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
            thinking_content = chunk["message"].get("thinking")
            if thinking_content:  # Truthy check: skips None and empty string ""
                reasoning_content = thinking_content
                if self.started_reasoning_content is False:
                    self.started_reasoning_content = True
            if chunk["message"].get("content") is not None:
                message_content = chunk["message"].get("content")
                # Track whether we are inside <think>...</think> tagged content.
                in_think_tag_block = bool(getattr(self, "_in_think_tag_block", False))
                if "<think>" in message_content:
                    message_content = message_content.replace("<think>", "")
                    self.started_reasoning_content = True
                    self.finished_reasoning_content = False
                    in_think_tag_block = True
                if "</think>" in message_content and self.started_reasoning_content:
                    message_content = message_content.replace("</think>", "")
                    self.finished_reasoning_content = True
                    in_think_tag_block = False

                # For native Ollama "thinking" streams, content without active
                # think tags indicates a transition into regular assistant output.
                if (
                    self.started_reasoning_content
                    and not self.finished_reasoning_content
                    and not in_think_tag_block
                    and not thinking_content
                ):
                    self.finished_reasoning_content = True

                self._in_think_tag_block = in_think_tag_block

                # When Ollama returns both "thinking" and "content" in the same
                # chunk, preserve both instead of classifying content as reasoning.
                if thinking_content and not in_think_tag_block:
                    content = message_content
                elif (
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


def _patch_openai_responses_parallel_tool_calls() -> None:
    """
    Patches OpenAiResponsesToChatCompletionStreamIterator to properly handle:
    1. Parallel tool calls by using output_index from streaming events
    2. Reasoning summary sections by inserting newlines between different summary indices

    LiteLLM's implementation hardcodes index=0 for all tool calls, breaking parallel tool calls.
    The OpenAI Responses API provides output_index in each event to track which tool call
    the event belongs to.

    STATUS: STILL NEEDED - LiteLLM hardcodes index=0 in translate_responses_chunk_to_openai_stream
            for response.output_item.added (line 962), response.function_call_arguments.delta
            (line 989), and response.output_item.done (line 1033). Our patch uses output_index
            from the event to properly track parallel tool calls.
    """
    if (
        getattr(
            OpenAiResponsesToChatCompletionStreamIterator.chunk_parser,
            "__name__",
            "",
        )
        == "_patched_responses_chunk_parser"
    ):
        return

    def _patched_responses_chunk_parser(
        self: Any, chunk: dict
    ) -> "ModelResponseStream":
        from pydantic import BaseModel

        from litellm.types.llms.openai import (
            ChatCompletionToolCallFunctionChunk,
            ResponsesAPIStreamEvents,
        )
        from litellm.types.utils import (
            ChatCompletionToolCallChunk,
            Delta,
            ModelResponseStream,
            StreamingChoices,
        )

        parsed_chunk = chunk
        if not parsed_chunk:
            raise ValueError("Chat provider: Empty parsed_chunk")

        if isinstance(parsed_chunk, BaseModel):
            parsed_chunk = parsed_chunk.model_dump()
        if not isinstance(parsed_chunk, dict):
            raise ValueError(f"Chat provider: Invalid chunk type {type(parsed_chunk)}")

        event_type = parsed_chunk.get("type")
        if isinstance(event_type, ResponsesAPIStreamEvents):
            event_type = event_type.value

        # Get the output_index for proper parallel tool call tracking
        output_index = parsed_chunk.get("output_index", 0)

        if event_type == "response.output_item.added":
            output_item = parsed_chunk.get("item", {})
            if output_item.get("type") == "function_call":
                provider_specific_fields = output_item.get("provider_specific_fields")
                if provider_specific_fields and not isinstance(
                    provider_specific_fields, dict
                ):
                    provider_specific_fields = (
                        dict(provider_specific_fields)
                        if hasattr(provider_specific_fields, "__dict__")
                        else {}
                    )

                function_chunk = ChatCompletionToolCallFunctionChunk(
                    name=output_item.get("name", None),
                    arguments=parsed_chunk.get("arguments", ""),
                )
                if provider_specific_fields:
                    function_chunk["provider_specific_fields"] = (
                        provider_specific_fields
                    )

                tool_call_chunk = ChatCompletionToolCallChunk(
                    id=output_item.get("call_id"),
                    index=output_index,  # Use output_index for parallel tool calls
                    type="function",
                    function=function_chunk,
                )
                if provider_specific_fields:
                    tool_call_chunk.provider_specific_fields = provider_specific_fields  # type: ignore

                return ModelResponseStream(
                    choices=[
                        StreamingChoices(
                            index=0,
                            delta=Delta(tool_calls=[tool_call_chunk]),
                            finish_reason=None,
                        )
                    ]
                )

        elif event_type == "response.function_call_arguments.delta":
            content_part: Optional[str] = parsed_chunk.get("delta", None)
            if content_part:
                return ModelResponseStream(
                    choices=[
                        StreamingChoices(
                            index=0,
                            delta=Delta(
                                tool_calls=[
                                    ChatCompletionToolCallChunk(
                                        id=None,
                                        index=output_index,  # Use output_index for parallel tool calls
                                        type="function",
                                        function=ChatCompletionToolCallFunctionChunk(
                                            name=None, arguments=content_part
                                        ),
                                    )
                                ]
                            ),
                            finish_reason=None,
                        )
                    ]
                )
            else:
                raise ValueError(
                    f"Chat provider: Invalid function argument delta {parsed_chunk}"
                )

        elif event_type == "response.output_item.done":
            output_item = parsed_chunk.get("item", {})
            if output_item.get("type") == "function_call":
                provider_specific_fields = output_item.get("provider_specific_fields")
                if provider_specific_fields and not isinstance(
                    provider_specific_fields, dict
                ):
                    provider_specific_fields = (
                        dict(provider_specific_fields)
                        if hasattr(provider_specific_fields, "__dict__")
                        else {}
                    )

                function_chunk = ChatCompletionToolCallFunctionChunk(
                    name=output_item.get("name", None),
                    arguments="",  # responses API sends everything again, we don't need it
                )
                if provider_specific_fields:
                    function_chunk["provider_specific_fields"] = (
                        provider_specific_fields
                    )

                tool_call_chunk = ChatCompletionToolCallChunk(
                    id=output_item.get("call_id"),
                    index=output_index,  # Use output_index for parallel tool calls
                    type="function",
                    function=function_chunk,
                )
                if provider_specific_fields:
                    tool_call_chunk.provider_specific_fields = provider_specific_fields  # type: ignore

                return ModelResponseStream(
                    choices=[
                        StreamingChoices(
                            index=0,
                            delta=Delta(tool_calls=[tool_call_chunk]),
                            finish_reason="tool_calls",
                        )
                    ]
                )

        elif event_type == "response.reasoning_summary_text.delta":
            # Handle reasoning summary with newlines between sections
            content_part = parsed_chunk.get("delta", None)
            if content_part:
                summary_index = parsed_chunk.get("summary_index", 0)

                # Track the last summary index to insert newlines between parts
                last_summary_index = getattr(
                    self, "_last_reasoning_summary_index", None
                )
                if (
                    last_summary_index is not None
                    and summary_index != last_summary_index
                ):
                    # New summary part started, prepend newlines to separate them
                    content_part = "\n\n" + content_part
                self._last_reasoning_summary_index = summary_index

                return ModelResponseStream(
                    choices=[
                        StreamingChoices(
                            index=cast(int, summary_index),
                            delta=Delta(reasoning_content=content_part),
                        )
                    ]
                )

        # For all other event types, use the original static method
        return OpenAiResponsesToChatCompletionStreamIterator.translate_responses_chunk_to_openai_stream(
            parsed_chunk
        )

    _patched_responses_chunk_parser.__name__ = "_patched_responses_chunk_parser"
    OpenAiResponsesToChatCompletionStreamIterator.chunk_parser = _patched_responses_chunk_parser  # type: ignore[method-assign]


def _patch_openai_responses_transform_response() -> None:
    """
    Patches LiteLLMResponsesTransformationHandler.transform_response to properly
    concatenate multiple reasoning summary parts with newlines in non-streaming responses.
    """
    # Store the original method
    original_transform_response = (
        LiteLLMResponsesTransformationHandler.transform_response
    )

    if (
        getattr(
            original_transform_response,
            "__name__",
            "",
        )
        == "_patched_transform_response"
    ):
        return

    def _patched_transform_response(
        self: Any,
        model: str,
        raw_response: Any,
        model_response: Any,
        logging_obj: Any,
        request_data: dict,
        messages: List[Any],
        optional_params: dict,
        litellm_params: dict,
        encoding: Any,
        api_key: Optional[str] = None,
        json_mode: Optional[bool] = None,
    ) -> Any:
        """
        Patched transform_response that properly concatenates reasoning summary parts
        with newlines.
        """
        from openai.types.responses.response import Response as ResponsesAPIResponse
        from openai.types.responses.response_reasoning_item import ResponseReasoningItem

        # Check if raw_response has reasoning items that need concatenation
        if isinstance(raw_response, ResponsesAPIResponse) and raw_response.output:
            for item in raw_response.output:
                if isinstance(item, ResponseReasoningItem) and item.summary:
                    # Concatenate summary texts with double newlines
                    summary_texts = []
                    for summary_item in item.summary:
                        text = getattr(summary_item, "text", "")
                        if text:
                            summary_texts.append(text)

                    if len(summary_texts) > 1:
                        # Modify the first summary item to contain all concatenated text
                        combined_text = "\n\n".join(summary_texts)
                        if hasattr(item.summary[0], "text"):
                            # Create a modified copy of the response with concatenated text
                            # Since OpenAI types are typically frozen, we need to work around this
                            # by modifying the object after the fact or using the result
                            pass  # The fix is applied in the result processing below

        # Call the original method
        result = original_transform_response(
            self,
            model,
            raw_response,
            model_response,
            logging_obj,
            request_data,
            messages,
            optional_params,
            litellm_params,
            encoding,
            api_key,
            json_mode,
        )

        # Post-process: If there are multiple summary items, fix the reasoning_content
        if isinstance(raw_response, ResponsesAPIResponse) and raw_response.output:
            for item in raw_response.output:
                if isinstance(item, ResponseReasoningItem) and item.summary:
                    if len(item.summary) > 1:
                        # Concatenate all summary texts with double newlines
                        summary_texts = []
                        for summary_item in item.summary:
                            text = getattr(summary_item, "text", "")
                            if text:
                                summary_texts.append(text)

                        if summary_texts:
                            combined_text = "\n\n".join(summary_texts)
                            # Update the reasoning_content in the result choices
                            if hasattr(result, "choices"):
                                for choice in result.choices:
                                    if hasattr(choice, "message") and hasattr(
                                        choice.message, "reasoning_content"
                                    ):
                                        choice.message.reasoning_content = combined_text
                    break  # Only process the first reasoning item

        return result

    _patched_transform_response.__name__ = "_patched_transform_response"
    LiteLLMResponsesTransformationHandler.transform_response = _patched_transform_response  # type: ignore[method-assign]


def _patch_azure_responses_should_fake_stream() -> None:
    """
    Patches AzureOpenAIResponsesAPIConfig.should_fake_stream to always return False.

    By default, LiteLLM uses "fake streaming" (MockResponsesAPIStreamingIterator) for models
    not in its database. This causes Azure custom model deployments to buffer the entire
    response before yielding, resulting in poor time-to-first-token.

    Azure's Responses API supports native streaming, so we override this to always use
    real streaming (SyncResponsesAPIStreamingIterator).
    """
    from litellm.llms.azure.responses.transformation import (
        AzureOpenAIResponsesAPIConfig,
    )

    if (
        getattr(AzureOpenAIResponsesAPIConfig.should_fake_stream, "__name__", "")
        == "_patched_should_fake_stream"
    ):
        return

    def _patched_should_fake_stream(
        self: Any,  # noqa: ARG001
        model: Optional[str],  # noqa: ARG001
        stream: Optional[bool],  # noqa: ARG001
        custom_llm_provider: Optional[str] = None,  # noqa: ARG001
    ) -> bool:
        # Azure Responses API supports native streaming - never fake it
        return False

    _patched_should_fake_stream.__name__ = "_patched_should_fake_stream"
    AzureOpenAIResponsesAPIConfig.should_fake_stream = _patched_should_fake_stream  # type: ignore[method-assign]


def _patch_responses_api_usage_format() -> None:
    """
    Patches ResponsesAPIResponse.model_construct to properly transform usage data
    from chat completion format to Responses API format.

    LiteLLM uses model_construct as a fallback in multiple places when ResponsesAPIResponse
    validation fails. This bypasses the usage validator, allowing usage data in chat
    completion format (completion_tokens, prompt_tokens) to be stored instead of Responses
    API format (input_tokens, output_tokens), causing Pydantic serialization warnings.

    This patch wraps model_construct to transform usage before construction, ensuring
    the correct type regardless of which code path calls model_construct.

    Affected locations in LiteLLM:
    - litellm/llms/openai/responses/transformation.py (lines 183, 563)
    - litellm/llms/chatgpt/responses/transformation.py (line 153)
    - litellm/llms/manus/responses/transformation.py (lines 243, 334)
    - litellm/llms/volcengine/responses/transformation.py (line 280)
    - litellm/completion_extras/litellm_responses_transformation/handler.py (line 51)
    """
    from litellm.types.llms.openai import ResponseAPIUsage, ResponsesAPIResponse

    original_model_construct = ResponsesAPIResponse.model_construct

    if getattr(original_model_construct, "_is_patched", False):
        return

    @classmethod  # type: ignore[misc]
    def _patched_model_construct(
        cls: Any,
        _fields_set: Optional[set[str]] = None,
        **values: Any,
    ) -> "ResponsesAPIResponse":
        """
        Patched model_construct that ensures usage is a ResponseAPIUsage object.
        """
        # Transform usage if present and not already the correct type
        if "usage" in values and values["usage"] is not None:
            usage = values["usage"]
            if not isinstance(usage, ResponseAPIUsage):
                if isinstance(usage, dict):
                    values = dict(values)  # Don't mutate original
                    # Check if it's in chat completion format
                    if "prompt_tokens" in usage or "completion_tokens" in usage:
                        # Transform from chat completion format
                        values["usage"] = ResponseAPIUsage(
                            input_tokens=usage.get("prompt_tokens", 0),
                            output_tokens=usage.get("completion_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                        )
                    elif "input_tokens" in usage or "output_tokens" in usage:
                        # Already in Responses API format, just convert to proper type
                        values["usage"] = ResponseAPIUsage(
                            input_tokens=usage.get("input_tokens", 0),
                            output_tokens=usage.get("output_tokens", 0),
                            total_tokens=usage.get("total_tokens", 0),
                        )

        # Call original model_construct (need to call it as unbound method)
        return original_model_construct.__func__(cls, _fields_set, **values)  # type: ignore[attr-defined]

    _patched_model_construct._is_patched = True  # type: ignore[attr-defined]
    ResponsesAPIResponse.model_construct = _patched_model_construct  # type: ignore[method-assign, assignment]


def _patch_logging_assembled_streaming_response() -> None:
    """
    Patches LiteLLMLoggingObj._get_assembled_streaming_response to create a deep copy
    of the ResponsesAPIResponse before modifying its usage field.

    The original code transforms usage to chat completion format and sets it as a dict
    directly on the ResponsesAPIResponse.usage field. This mutates the original object,
    causing Pydantic serialization warnings when model_dump() is called later because
    the usage field contains a dict instead of the expected ResponseAPIUsage type.

    This patch creates a copy of the response before modification, preserving the
    original object with its proper ResponseAPIUsage type.
    """
    from litellm import LiteLLMLoggingObj
    from litellm.responses.utils import ResponseAPILoggingUtils
    from litellm.types.llms.openai import (
        ResponseAPIUsage,
        ResponseCompletedEvent,
        ResponsesAPIResponse,
    )
    from litellm.types.utils import ModelResponse, TextCompletionResponse

    original_method = LiteLLMLoggingObj._get_assembled_streaming_response

    if getattr(original_method, "_is_patched", False):
        return

    def _patched_get_assembled_streaming_response(
        self: Any,  # noqa: ARG001
        result: Any,
        start_time: Any,  # noqa: ARG001
        end_time: Any,  # noqa: ARG001
        is_async: bool,  # noqa: ARG001
        streaming_chunks: List[Any],  # noqa: ARG001
    ) -> Any:
        """
        Patched version that creates a copy before modifying usage.

        The original LiteLLM code transforms usage to chat completion format and
        sets it directly as a dict, which causes Pydantic serialization warnings.
        This patch uses model_construct to rebuild the response with the transformed
        usage, ensuring proper typing.
        """
        if isinstance(result, ModelResponse):
            return result
        elif isinstance(result, TextCompletionResponse):
            return result
        elif isinstance(result, ResponseCompletedEvent):
            # Get the original response data
            original_response = result.response
            response_data = original_response.model_dump()

            # Transform usage if present
            if isinstance(original_response.usage, ResponseAPIUsage):
                transformed_usage = (
                    ResponseAPILoggingUtils._transform_response_api_usage_to_chat_usage(
                        original_response.usage
                    )
                )
                # Put the transformed usage (in chat completion format) into response_data
                # Our patched model_construct will convert it back to ResponseAPIUsage
                response_data["usage"] = (
                    transformed_usage.model_dump()
                    if hasattr(transformed_usage, "model_dump")
                    else dict(transformed_usage)
                )

            # Rebuild using model_construct - our patch ensures usage is properly typed
            response_copy = ResponsesAPIResponse.model_construct(**response_data)

            # Copy hidden params
            if hasattr(original_response, "_hidden_params"):
                response_copy._hidden_params = dict(original_response._hidden_params)

            return response_copy
        else:
            return None

    _patched_get_assembled_streaming_response._is_patched = True  # type: ignore[attr-defined]
    LiteLLMLoggingObj._get_assembled_streaming_response = _patched_get_assembled_streaming_response  # type: ignore[method-assign]


def apply_monkey_patches() -> None:
    """
    Apply all necessary monkey patches to LiteLLM for compatibility.

    This includes:
    - Patching OllamaChatCompletionResponseIterator.chunk_parser for streaming content
    - Patching translate_responses_chunk_to_openai_stream for parallel tool calls
    - Patching LiteLLMResponsesTransformationHandler.transform_response for non-streaming responses
    - Patching AzureOpenAIResponsesAPIConfig.should_fake_stream to enable native streaming
    - Patching ResponsesAPIResponse.model_construct to fix usage format in all code paths
    - Patching LiteLLMLoggingObj._get_assembled_streaming_response to avoid mutating original response
    """
    _patch_ollama_chunk_parser()
    _patch_openai_responses_parallel_tool_calls()
    _patch_openai_responses_transform_response()
    _patch_azure_responses_should_fake_stream()
    _patch_responses_api_usage_format()
    _patch_logging_assembled_streaming_response()
