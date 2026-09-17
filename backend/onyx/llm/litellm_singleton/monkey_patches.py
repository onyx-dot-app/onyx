"""
LiteLLM Monkey Patches

This module addresses the following issues in LiteLLM:

Status checked against LiteLLM v1.93.0 (2026-07-20):

1. Ollama Streaming Reasoning Content (_patch_ollama_chunk_parser):
   - LiteLLM's chunk_parser doesn't properly handle reasoning content in streaming
     responses from Ollama
   - Processes native "thinking" field from Ollama responses
   - Also handles <think>...</think> tags in content for models that use that format
   - Tracks reasoning state to properly separate thinking from regular content
   STATUS: STILL NEEDED - Upstream v1.85.1 adopted the truthy check on thinking and the
           elif→if fix for simultaneous thinking+content chunks, but still does not track
           <think>...</think> tag boundaries within content. Our `_in_think_tag_block`
           state is required to correctly classify content that crosses a </think> boundary.

2. Reasoning Summary Newlines (_patch_responses_reasoning_summary_newlines):
   - LiteLLM passes through reasoning_summary_text.delta content as-is without
     separating different summary_index sections
   - Our patch inserts "\\n\\n" when the summary_index changes
   - Also normalizes terminal events (response.completed/incomplete/failed)
     whose response carries "output": null (newer Bifrost gateways, e.g.
     fronting Bedrock) — upstream iterates output and raises TypeError
   - Also turns empty function_call_arguments.delta events into no-op chunks;
     Anthropic-backed gateways open tool-call streams with an empty delta and
     upstream raises ValueError on falsy deltas
   STATUS: STILL NEEDED - Upstream does not insert separators between summary sections,
           does not guard against null output in terminal events, and rejects empty
           tool-argument deltas.

3. OpenAI Responses API Non-Streaming (_patch_openai_responses_transform_response):
   - LiteLLM's transform_response joins multiple reasoning summary parts with spaces
   - We prefer double newlines for readability
   STATUS: STILL NEEDED - Upstream now uses " ".join() instead of discarding earlier
           parts, but we override to use "\\n\\n".join() for readable section breaks.

4. Responses API Fake Streaming (_patch_openai_responses_should_fake_stream):
   - LiteLLM fake-streams (MockResponsesAPIStreamingIterator) any responses-API
     call whose model its registry doesn't recognize, buffering the whole
     generation before the first chunk. Azure custom deployments and
     OpenAI-compatible gateway aliases (Bifrost/Portkey responses mode) are
     never in the registry
   - Patched on the base OpenAIResponsesAPIConfig; AzureOpenAIResponsesAPIConfig
     inherits it (no upstream override). Models the registry explicitly marks
     supports_native_streaming=False (e.g. o1-pro) keep the fake stream
   STATUS: STILL NEEDED - v1.93.0 treats a registry miss as "cannot stream".

# Note: 5 and 6 suppress a warning and may fix usage info but are not strictly required
5. Responses API Usage Format Mismatch (_patch_responses_api_usage_format):
   - LiteLLM uses model_construct as a fallback in multiple places when
     ResponsesAPIResponse validation fails
   - This bypasses the usage validator, allowing chat completion format usage
     (completion_tokens, prompt_tokens) to be stored instead of Responses API format
     (input_tokens, output_tokens)
   - When model_dump() is later called, Pydantic emits a serialization warning
   STATUS: STILL NEEDED - Multiple files use model_construct which bypasses validation.

6. Logging Usage Transformation Warning (_patch_logging_assembled_streaming_response):
   - LiteLLM's _get_assembled_streaming_response transforms ResponseAPIUsage to chat
     completion format and sets it as a dict on ResponsesAPIResponse.usage
   - This replaces the proper ResponseAPIUsage object with a dict, causing Pydantic
     serialization warnings
   STATUS: STILL NEEDED - Upstream still mutates result.response.usage in place via
         setattr in v1.93.0. Our patch rebuilds the response via model_construct so the
         original ResponseAPIUsage object is preserved. Handles ResponseCompletedEvent,
         ResponseIncompleteEvent, and ResponseFailedEvent (matching upstream), and
         tolerates result.response being a plain dict (validation-fallback payloads
         from gateways whose responses litellm cannot strictly parse).

7. Explicit responses/ Prefix Ignored (_patch_responses_api_bridge_check):
   - responses_api_bridge_check only engages the completions->responses bridge when
     the model is unknown to LiteLLM's registry (model_info mode is None / lookup
     raises). Gateway model ids like "anthropic/claude-haiku-4-5" resolve in the
     registry (valid provider prefix + known tail, mode "chat"), so an explicit
     "responses/" prefix is left attached and the request is sent to
     /chat/completions with the mangled model name
   - The prefix is only ever set deliberately (Onyx API-surface routing for
     OpenAI-compatible gateways such as Bifrost and Portkey), so honor it
     unconditionally and pass the remainder through as the literal model id
   STATUS: STILL NEEDED - v1.93.0 consults the registry before honoring the prefix.

"""

import time
import uuid
from typing import Any, List, Optional, cast

from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
    OpenAiResponsesToChatCompletionStreamIterator,
)
from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator
from litellm.llms.ollama.common_utils import OllamaError
from litellm.types.utils import ChatCompletionUsageBlock, ModelResponseStream

# Original upstream chunk_parser, saved before any patching for fallback use
_original_responses_chunk_parser = (
    OpenAiResponsesToChatCompletionStreamIterator.chunk_parser
)


def _patch_ollama_chunk_parser() -> None:
    """
    Patches OllamaChatCompletionResponseIterator.chunk_parser to properly handle
    reasoning content and content in streaming responses.
    """
    if (
        getattr(  # ods: ignore[getattr]
            OllamaChatCompletionResponseIterator.chunk_parser, "__name__", ""
        )
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
            from litellm.types.utils import Delta, StreamingChoices

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
                in_think_tag_block = bool(
                    getattr(self, "_in_think_tag_block", False)  # ods: ignore[getattr]
                )
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
                finish_reason = chunk.get("done_reason") or "stop"
                # Mirror upstream's fix for BerriAI/litellm#18922: when tool
                # calls are present, override done_reason to "tool_calls" so
                # downstream consumers branch correctly.
                if tool_calls:
                    finish_reason = "tool_calls"
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

    OllamaChatCompletionResponseIterator.chunk_parser = _patched_chunk_parser


def _patch_responses_reasoning_summary_newlines() -> None:
    """
    Patches OpenAiResponsesToChatCompletionStreamIterator.chunk_parser to insert
    newlines between different reasoning summary sections in streaming responses.

    LiteLLM passes through reasoning_summary_text.delta content as-is, without
    separating different summary_index sections. This patch prepends "\\n\\n" when
    the summary_index changes, producing readable section breaks.
    """
    if (
        getattr(  # ods: ignore[getattr]
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
        from litellm.types.llms.openai import ResponsesAPIStreamEvents
        from litellm.types.utils import Delta, ModelResponseStream, StreamingChoices
        from pydantic import BaseModel

        parsed_chunk = chunk
        if isinstance(parsed_chunk, BaseModel):
            parsed_chunk = parsed_chunk.model_dump()

        event_type = (
            parsed_chunk.get("type") if isinstance(parsed_chunk, dict) else None
        )
        if isinstance(event_type, ResponsesAPIStreamEvents):
            event_type = event_type.value

        if event_type == "response.reasoning_summary_text.delta":
            content_part = parsed_chunk.get("delta", None)
            if content_part:
                summary_index = parsed_chunk.get("summary_index", 0)

                # Track the last summary index to insert newlines between parts
                last_summary_index = getattr(  # ods: ignore[getattr]
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

        # Gateways may open tool-call streams with an empty arguments delta;
        # upstream raises on falsy deltas, so emit a no-op chunk instead.
        if event_type == "response.function_call_arguments.delta" and not (
            isinstance(parsed_chunk, dict) and parsed_chunk.get("delta")
        ):
            return ModelResponseStream(
                choices=[StreamingChoices(index=0, delta=Delta(), finish_reason=None)]
            )

        # Terminal events may carry "output": null, which upstream iterates.
        if (
            event_type
            in (
                "response.completed",
                "response.incomplete",
                "response.failed",
            )
            and isinstance(parsed_chunk, dict)
            and isinstance(parsed_chunk.get("response"), dict)
            and parsed_chunk["response"].get("output") is None
        ):
            parsed_chunk["response"]["output"] = []
            chunk = parsed_chunk

        # For all other event types, use the original upstream chunk_parser
        return _original_responses_chunk_parser(self, chunk)

    _patched_responses_chunk_parser.__name__ = "_patched_responses_chunk_parser"
    OpenAiResponsesToChatCompletionStreamIterator.chunk_parser = (
        _patched_responses_chunk_parser
    )


def _patch_openai_responses_transform_response() -> None:
    """
    Patches LiteLLMResponsesTransformationHandler.transform_response to properly
    concatenate multiple reasoning summary parts with newlines in non-streaming responses.
    """
    original_transform_response = (
        LiteLLMResponsesTransformationHandler.transform_response
    )

    if (
        getattr(  # ods: ignore[getattr]
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
        from litellm.types.llms.openai import ResponsesAPIResponse
        from openai.types.responses.response_reasoning_item import ResponseReasoningItem

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

        combined_text: str | None = None
        if isinstance(raw_response, ResponsesAPIResponse) and raw_response.output:
            for item in raw_response.output:
                if not isinstance(item, ResponseReasoningItem) or not item.summary:
                    continue

                summary_texts = [
                    text
                    for summary_item in item.summary
                    if (
                        text := getattr(  # ods: ignore[getattr]
                            summary_item, "text", ""
                        )
                    )
                ]
                if len(summary_texts) > 1:
                    combined_text = "\n\n".join(summary_texts)
                break

        if combined_text and hasattr(result, "choices"):
            for choice in result.choices:
                message = getattr(choice, "message", None)  # ods: ignore[getattr]
                if message is not None and getattr(  # ods: ignore[getattr]
                    message, "reasoning_content", None
                ):
                    message.reasoning_content = combined_text

        return result

    _patched_transform_response.__name__ = "_patched_transform_response"
    LiteLLMResponsesTransformationHandler.transform_response = (
        _patched_transform_response
    )


def _patch_openai_responses_should_fake_stream() -> None:
    """
    Patches OpenAIResponsesAPIConfig.should_fake_stream so a registry miss
    (e.g. a gateway model alias or Azure custom deployment) streams natively
    instead of buffering the generation. Models explicitly marked
    supports_native_streaming=False (e.g. o1-pro) keep the fake stream — a
    native stream request would be rejected upstream.
    AzureOpenAIResponsesAPIConfig inherits this patch.
    """
    from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig

    if (
        getattr(  # ods: ignore[getattr]
            OpenAIResponsesAPIConfig.should_fake_stream, "__name__", ""
        )
        == "_patched_openai_should_fake_stream"
    ):
        return

    def _patched_openai_should_fake_stream(
        self: Any,  # noqa: ARG001
        model: Optional[str],
        stream: Optional[bool],
        custom_llm_provider: Optional[str] = None,
    ) -> bool:
        import litellm

        if stream is not True or model is None:
            return False
        try:
            model_info = litellm.get_model_info(
                model=model, custom_llm_provider=custom_llm_provider
            )
        except Exception:
            # Registry miss (e.g. gateway alias): assume native streaming.
            return False
        return model_info.get("supports_native_streaming") is False

    _patched_openai_should_fake_stream.__name__ = "_patched_openai_should_fake_stream"
    OpenAIResponsesAPIConfig.should_fake_stream = _patched_openai_should_fake_stream


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

    Affected locations in LiteLLM v1.93.0:
    - litellm/llms/openai/responses/transformation.py (lines 268, 635)
    - litellm/llms/chatgpt/responses/transformation.py (line 212)
    - litellm/llms/manus/responses/transformation.py (lines 223, 311)
    - litellm/llms/volcengine/responses/transformation.py (line 262)
    - litellm/completion_extras/litellm_responses_transformation/handler.py (line 57)
    """
    from litellm.types.llms.openai import ResponseAPIUsage, ResponsesAPIResponse

    original_model_construct = ResponsesAPIResponse.model_construct

    if getattr(original_model_construct, "_is_patched", False):  # ods: ignore[getattr]
        return

    @classmethod
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
                        # Already in Responses API format, just convert to proper type.
                        # List every field explicitly so a new field added upstream
                        # surfaces here (and in the audit header) instead of being
                        # silently dropped or silently absorbed.
                        values["usage"] = ResponseAPIUsage(
                            input_tokens=usage.get("input_tokens", 0),
                            input_tokens_details=usage.get("input_tokens_details"),
                            output_tokens=usage.get("output_tokens", 0),
                            output_tokens_details=usage.get("output_tokens_details"),
                            total_tokens=usage.get("total_tokens", 0),
                            cost=usage.get("cost"),
                        )

        # Call original model_construct (need to call it as unbound method)
        return original_model_construct.__func__(cls, _fields_set, **values)

    _patched_model_construct._is_patched = True  # ty: ignore[unresolved-attribute]
    ResponsesAPIResponse.model_construct = (  # ty: ignore[invalid-assignment]
        _patched_model_construct
    )


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
    from litellm.litellm_core_utils.litellm_logging import Logging as LiteLLMLoggingObj
    from litellm.responses.utils import ResponseAPILoggingUtils
    from litellm.types.llms.openai import (
        ResponseAPIUsage,
        ResponseCompletedEvent,
        ResponseFailedEvent,
        ResponseIncompleteEvent,
        ResponsesAPIResponse,
    )
    from litellm.types.utils import ModelResponse, TextCompletionResponse

    original_method = LiteLLMLoggingObj._get_assembled_streaming_response

    if getattr(original_method, "_is_patched", False):  # ods: ignore[getattr]
        return

    def _patched_get_assembled_streaming_response(
        self: Any,
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
        if self.stream is not True:
            return None
        if isinstance(result, ModelResponse):
            return result
        elif isinstance(result, TextCompletionResponse):
            return result
        elif isinstance(
            result,
            (ResponseCompletedEvent, ResponseIncompleteEvent, ResponseFailedEvent),
        ):
            # result.response stays a plain dict when the payload failed
            # litellm's strict validation; handle both shapes.
            original_response = result.response
            if isinstance(original_response, dict):
                response_data = dict(original_response)
                raw_usage = original_response.get("usage")
                usage: ResponseAPIUsage | None = (
                    ResponseAPIUsage.model_construct(**raw_usage)
                    if isinstance(raw_usage, dict) and "input_tokens" in raw_usage
                    else None
                )
            else:
                response_data = original_response.model_dump()
                usage = (
                    original_response.usage
                    if isinstance(original_response.usage, ResponseAPIUsage)
                    else None
                )

            # Transform usage if present
            if usage is not None:
                transformed_usage = (
                    ResponseAPILoggingUtils._transform_response_api_usage_to_chat_usage(
                        usage
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

    _patched_get_assembled_streaming_response._is_patched = (  # ty: ignore[unresolved-attribute]
        True
    )
    LiteLLMLoggingObj._get_assembled_streaming_response = (
        _patched_get_assembled_streaming_response
    )


def _patch_responses_api_bridge_check() -> None:
    """
    Patches litellm.main.responses_api_bridge_check to honor an explicit
    "responses/" model prefix unconditionally.

    Upstream only bridges when its registry doesn't recognize the model, so
    gateway ids like "anthropic/claude-haiku-4-5" (valid provider prefix +
    registry-known tail) skip the bridge and hit /chat/completions with the
    prefix still attached. The prefix is only ever set deliberately, so it
    always wins; the remainder passes through as the literal model id.
    """
    import litellm.main as litellm_main

    if (
        getattr(  # ods: ignore[getattr]
            litellm_main.responses_api_bridge_check, "__name__", ""
        )
        == "_patched_responses_api_bridge_check"
    ):
        return

    original_bridge_check = litellm_main.responses_api_bridge_check

    def _patched_responses_api_bridge_check(
        model: str,
        custom_llm_provider: str,
        web_search_options: Optional[Any] = None,
        tools: Optional[list[Any]] = None,
        reasoning_effort: Optional[Any] = None,
        reasoning_summary: Optional[Any] = None,
    ) -> tuple[dict, str]:
        if model.startswith("responses/"):
            return {"mode": "responses"}, model.removeprefix("responses/")
        return original_bridge_check(
            model=model,
            custom_llm_provider=custom_llm_provider,
            web_search_options=web_search_options,
            tools=tools,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
        )

    _patched_responses_api_bridge_check.__name__ = "_patched_responses_api_bridge_check"
    litellm_main.responses_api_bridge_check = (  # ty: ignore[invalid-assignment]
        _patched_responses_api_bridge_check
    )


def apply_monkey_patches() -> None:
    """
    Apply all necessary monkey patches to LiteLLM for compatibility.

    This includes:
    - Patching OllamaChatCompletionResponseIterator.chunk_parser for streaming content
    - Patching chunk_parser for reasoning summary newline insertion between sections
    - Patching LiteLLMResponsesTransformationHandler.transform_response for non-streaming responses
    - Patching OpenAIResponsesAPIConfig.should_fake_stream (Azure inherits) to stream
      natively on registry misses
    - Patching ResponsesAPIResponse.model_construct to fix usage format in all code paths
    - Patching Logging._get_assembled_streaming_response to avoid mutating original response
    - Patching responses_api_bridge_check to always honor an explicit responses/ prefix
    """
    _patch_ollama_chunk_parser()
    _patch_responses_reasoning_summary_newlines()
    _patch_openai_responses_transform_response()
    _patch_openai_responses_should_fake_stream()
    _patch_responses_api_usage_format()
    _patch_logging_assembled_streaming_response()
    _patch_responses_api_bridge_check()
