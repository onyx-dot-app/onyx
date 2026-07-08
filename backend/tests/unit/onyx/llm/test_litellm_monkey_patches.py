from datetime import datetime
from typing import Any

from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
)
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator
from litellm.types.llms.openai import ResponseAPIUsage
from litellm.types.llms.openai import ResponsesAPIResponse
from litellm.types.utils import ModelResponse
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_reasoning_item import ResponseReasoningItem
from openai.types.responses.response_reasoning_item import Summary

from onyx.llm.litellm_singleton.monkey_patches import apply_monkey_patches

_UNSET = object()


def _create_iterator() -> OllamaChatCompletionResponseIterator:
    apply_monkey_patches()
    return OllamaChatCompletionResponseIterator(
        streaming_response=iter(()),
        sync_stream=True,
    )


def _build_chunk(
    *,
    thinking: object = _UNSET,
    content: object = _UNSET,
) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "assistant"}
    if thinking is not _UNSET:
        message["thinking"] = thinking
    if content is not _UNSET:
        message["content"] = content

    return {
        "model": "llama3.1",
        "message": message,
        "done": False,
        "prompt_eval_count": 0,
        "eval_count": 0,
    }


def test_ollama_chunk_parser_transitions_from_native_thinking_to_content() -> None:
    iterator = _create_iterator()

    thinking_chunk = _build_chunk(thinking="Let me think")
    content_chunk = _build_chunk(thinking="", content="Final answer")

    thinking_response = iterator.chunk_parser(thinking_chunk)
    content_response = iterator.chunk_parser(content_chunk)

    assert thinking_response.choices[0].delta.reasoning_content == "Let me think"
    assert thinking_response.choices[0].delta.content is None

    assert getattr(content_response.choices[0].delta, "reasoning_content", None) is None
    assert content_response.choices[0].delta.content == "Final answer"
    assert iterator.finished_reasoning_content is True


def test_ollama_chunk_parser_keeps_tagged_thinking_until_close_tag() -> None:
    iterator = _create_iterator()

    start_chunk = _build_chunk(content="<think>step 1")
    middle_chunk = _build_chunk(content="step 2")
    close_chunk = _build_chunk(content="final</think>")

    start_response = iterator.chunk_parser(start_chunk)
    middle_response = iterator.chunk_parser(middle_chunk)
    close_response = iterator.chunk_parser(close_chunk)

    assert start_response.choices[0].delta.reasoning_content == "step 1"
    assert start_response.choices[0].delta.content is None

    assert middle_response.choices[0].delta.reasoning_content == "step 2"
    assert middle_response.choices[0].delta.content is None

    assert getattr(close_response.choices[0].delta, "reasoning_content", None) is None
    assert close_response.choices[0].delta.content == "final"
    assert iterator.finished_reasoning_content is True


def test_ollama_chunk_parser_handles_think_tag_after_native_thinking() -> None:
    iterator = _create_iterator()

    native_thinking_chunk = _build_chunk(thinking="native reasoning")
    tagged_thinking_chunk = _build_chunk(content="<think>tagged reasoning")

    iterator.chunk_parser(native_thinking_chunk)
    tagged_response = iterator.chunk_parser(tagged_thinking_chunk)

    assert tagged_response.choices[0].delta.reasoning_content == "tagged reasoning"
    assert tagged_response.choices[0].delta.content is None


def test_ollama_chunk_parser_preserves_content_when_thinking_and_content_coexist() -> (
    None
):
    iterator = _create_iterator()

    combined_chunk = _build_chunk(
        thinking="Need one thought",
        content="Visible answer token",
    )

    response = iterator.chunk_parser(combined_chunk)

    assert response.choices[0].delta.reasoning_content == "Need one thought"
    assert response.choices[0].delta.content == "Visible answer token"


def test_responses_transform_response_preserves_reasoning_summary_sections() -> None:
    apply_monkey_patches()
    raw_response = ResponsesAPIResponse(
        id="resp_1",
        created_at=0,
        error=None,
        incomplete_details=None,
        instructions=None,
        metadata={},
        model="m",
        object="response",
        output=[
            ResponseReasoningItem(
                id="rs_1",
                type="reasoning",
                summary=[
                    Summary(text="first section", type="summary_text"),
                    Summary(text="second section", type="summary_text"),
                ],
            ),
            ResponseOutputMessage(
                id="msg_1",
                type="message",
                role="assistant",
                status="completed",
                content=[
                    ResponseOutputText(
                        type="output_text",
                        text="answer",
                        annotations=[],
                    )
                ],
            ),
        ],
        parallel_tool_calls=False,
        temperature=None,
        tool_choice="auto",
        tools=[],
        top_p=None,
        max_output_tokens=None,
        previous_response_id=None,
        reasoning=None,
        status="completed",
        text=None,
        truncation=None,
        usage=ResponseAPIUsage(input_tokens=2, output_tokens=3, total_tokens=5),
        user=None,
        store=False,
    )

    result = LiteLLMResponsesTransformationHandler().transform_response(
        model="m",
        raw_response=raw_response,
        model_response=ModelResponse(),
        logging_obj=Logging(
            model="m",
            messages=[],
            stream=False,
            call_type="responses",
            start_time=datetime.now(),
            litellm_call_id="test-call-id",
            function_id="test-function-id",
        ),
        request_data={},
        messages=[],
        optional_params={},
        litellm_params={},
        encoding=None,
    )

    assert (
        result.choices[0].message.reasoning_content == "first section\n\nsecond section"
    )
