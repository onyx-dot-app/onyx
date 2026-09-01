from datetime import datetime
from typing import Any, cast
from unittest import mock

from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
    OpenAiResponsesToChatCompletionStreamIterator,
)
from litellm.litellm_core_utils.litellm_logging import Logging
from litellm.llms.ollama.chat.transformation import OllamaChatCompletionResponseIterator
from litellm.types.llms.openai import ResponseAPIUsage, ResponsesAPIResponse
from litellm.types.utils import ModelResponse
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_reasoning_item import (
    ResponseReasoningItem,
    Summary,
)

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

    assert (
        getattr(  # ods: ignore[getattr]
            content_response.choices[0].delta, "reasoning_content", None
        )
        is None
    )
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

    assert (
        getattr(  # ods: ignore[getattr]
            close_response.choices[0].delta, "reasoning_content", None
        )
        is None
    )
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


def _minimal_completed_response_dict() -> dict[str, Any]:
    return {
        "id": "resp_dict_1",
        "object": "response",
        "created_at": 0,
        "status": "completed",
        "model": "m",
        "output": None,
        "usage": {"input_tokens": 5, "output_tokens": 3, "total_tokens": 8},
    }


def test_responses_chunk_parser_normalizes_null_output_on_completed() -> None:
    apply_monkey_patches()
    iterator = OpenAiResponsesToChatCompletionStreamIterator(
        streaming_response=iter(()),
        sync_stream=True,
    )
    parsed = iterator.chunk_parser(
        {
            "type": "response.completed",
            "sequence_number": 9,
            "response": _minimal_completed_response_dict(),
        }
    )
    assert parsed.choices[0].finish_reason == "stop"


def test_responses_chunk_parser_ignores_empty_tool_argument_delta() -> None:
    apply_monkey_patches()
    iterator = OpenAiResponsesToChatCompletionStreamIterator(
        streaming_response=iter(()),
        sync_stream=True,
    )
    empty = iterator.chunk_parser(
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "toolu_1",
            "output_index": 0,
            "delta": "",
            "sequence_number": 4,
        }
    )
    assert empty.choices[0].delta.tool_calls is None

    real = iterator.chunk_parser(
        {
            "type": "response.function_call_arguments.delta",
            "item_id": "toolu_1",
            "output_index": 0,
            "delta": '{"query": "onboarding"}',
            "sequence_number": 5,
        }
    )
    tool_calls = real.choices[0].delta.tool_calls
    assert tool_calls is not None
    assert tool_calls[0].function.arguments == '{"query": "onboarding"}'


def test_assembled_streaming_response_handles_dict_response() -> None:
    from types import SimpleNamespace

    from litellm.types.llms.openai import ResponseCompletedEvent

    apply_monkey_patches()
    event = ResponseCompletedEvent.model_construct(
        type="response.completed",
        response=_minimal_completed_response_dict(),
    )
    get_assembled = cast(Any, Logging._get_assembled_streaming_response)
    assembled = get_assembled(
        SimpleNamespace(stream=True),
        event,
        None,
        None,
        False,
        [],
    )
    assert isinstance(assembled, ResponsesAPIResponse)
    assert assembled.usage is not None
    assert assembled.usage.input_tokens == 5
    assert assembled.usage.output_tokens == 3


def test_bridge_check_honors_prefix_for_registry_known_models() -> None:
    # Registry-known compound ids must still bridge when the prefix is explicit.
    import litellm.main as litellm_main

    apply_monkey_patches()
    model_info, model = litellm_main.responses_api_bridge_check(
        model="responses/anthropic/claude-haiku-4-5",
        custom_llm_provider="openai",
    )
    assert model_info["mode"] == "responses"
    assert model == "anthropic/claude-haiku-4-5"


def test_bridge_check_delegates_without_prefix() -> None:
    import litellm.main as litellm_main

    apply_monkey_patches()
    model_info, model = litellm_main.responses_api_bridge_check(
        model="gpt-4o",
        custom_llm_provider="openai",
    )
    assert model_info.get("mode") != "responses"
    assert model == "gpt-4o"


def test_openai_should_fake_stream_streams_natively_on_registry_miss() -> None:
    # Force the registry miss so the except branch is unambiguously covered.
    from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig

    apply_monkey_patches()
    config = OpenAIResponsesAPIConfig()
    with mock.patch(
        "litellm.get_model_info",
        side_effect=Exception("This model isn't mapped yet"),
    ) as get_model_info_mock:
        result = config.should_fake_stream(
            model="bedrock_mantle/openai.gpt-5.6-sol",
            stream=True,
            custom_llm_provider="openai",
        )
    assert get_model_info_mock.called
    assert result is False


def test_openai_should_fake_stream_keeps_faking_for_non_streaming_models() -> None:
    # o1-pro is registry-marked supports_native_streaming=False.
    from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig

    apply_monkey_patches()
    config = OpenAIResponsesAPIConfig()
    assert (
        config.should_fake_stream(
            model="o1-pro",
            stream=True,
            custom_llm_provider="openai",
        )
        is True
    )


def test_openai_should_fake_stream_ignores_non_streaming_requests() -> None:
    from litellm.llms.openai.responses.transformation import OpenAIResponsesAPIConfig

    apply_monkey_patches()
    config = OpenAIResponsesAPIConfig()
    assert (
        config.should_fake_stream(
            model="o1-pro",
            stream=None,
            custom_llm_provider="openai",
        )
        is False
    )


def test_azure_should_fake_stream_inherits_registry_aware_patch() -> None:
    # An upstream override on the Azure subclass would silently bypass the patch.
    from litellm.llms.azure.responses.transformation import (
        AzureOpenAIResponsesAPIConfig,
    )

    apply_monkey_patches()
    assert (
        AzureOpenAIResponsesAPIConfig.should_fake_stream.__name__
        == "_patched_openai_should_fake_stream"
    )
    config = AzureOpenAIResponsesAPIConfig()
    with mock.patch(
        "litellm.get_model_info",
        side_effect=Exception("This model isn't mapped yet"),
    ):
        assert (
            config.should_fake_stream(
                model="my-custom-deployment",
                stream=True,
                custom_llm_provider="azure",
            )
            is False
        )
