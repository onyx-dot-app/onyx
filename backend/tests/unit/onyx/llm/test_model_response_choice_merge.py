"""The OpenAI-responses bridge spreads one answer across several `choices` on a
plain (non-streamed) reply. These tests pin that we reassemble it into the same
single answer the streamed transport produces."""

import pytest
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler,
)
from litellm.types.llms.openai import ResponsesAPIResponse
from openai.types.responses.response_function_tool_call import ResponseFunctionToolCall
from openai.types.responses.response_output_message import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText

from onyx.llm.litellm_conversion import from_litellm_model_response

# Via the singleton, so importing this module applies Onyx's litellm config and
# monkey patches rather than leaving a bare litellm for the rest of the session.
from onyx.llm.litellm_singleton import litellm


def _bridge_response(
    output: list[ResponseOutputMessage | ResponseFunctionToolCall],
) -> litellm.ModelResponse:
    """Run litellm's real bridge so the choice shape is the provider's, not ours."""
    raw = ResponsesAPIResponse(
        id="resp_1",
        created_at=1,
        model="gpt-5",
        object="response",
        output=output,
        parallel_tool_calls=False,
        tool_choice="auto",
        tools=[],
        usage=None,
    )
    model_response = litellm.ModelResponse(id="resp_1", created=1, model="gpt-5")
    model_response.choices = (
        LiteLLMResponsesTransformationHandler._convert_response_output_to_choices(
            raw.output
        )
    )
    return model_response


def _text(text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id="msg_1",
        type="message",
        role="assistant",
        status="completed",
        content=[ResponseOutputText(type="output_text", text=text, annotations=[])],
    )


def _tool_call(call_id: str, name: str, arguments: str) -> ResponseFunctionToolCall:
    return ResponseFunctionToolCall(
        id=f"fc_{call_id}",
        type="function_call",
        call_id=call_id,
        name=name,
        arguments=arguments,
    )


def test_text_and_tool_call_land_in_one_answer() -> None:
    """The bridge puts the text in choices[0] and the tool call in choices[1].
    Reading only the first choice would drop the tool call silently."""
    raw = _bridge_response(
        [_text("Let me look that up."), _tool_call("call_abc", "search", '{"q":"x"}')]
    )
    assert len(raw.choices) == 2, "guard: the bridge still splits the answer"

    response = from_litellm_model_response(raw)

    assert response.choice.message.content == "Let me look that up."
    assert response.choice.finish_reason == "tool_calls"
    tool_calls = response.choice.message.tool_calls
    assert tool_calls is not None
    assert [(call.id, call.function.name) for call in tool_calls] == [
        ("call_abc", "search")
    ]
    assert tool_calls[0].function.arguments == '{"q":"x"}'


def test_parallel_tool_calls_all_survive() -> None:
    raw = _bridge_response(
        [
            _text("Checking both."),
            # Not "call_<digits>": litellm treats those as degenerate and
            # substitutes the output item's own id.
            _tool_call("call_aaa", "search", "{}"),
            _tool_call("call_bbb", "lookup", "{}"),
        ]
    )

    response = from_litellm_model_response(raw)

    tool_calls = response.choice.message.tool_calls
    assert tool_calls is not None
    assert [call.id for call in tool_calls] == ["call_aaa", "call_bbb"]


def test_several_text_parts_join_in_order() -> None:
    raw = _bridge_response([_text("Part one. "), _text("Part two.")])

    response = from_litellm_model_response(raw)

    assert response.choice.message.content == "Part one. Part two."
    assert response.choice.finish_reason == "stop"
    assert response.choice.message.tool_calls is None


def test_a_single_choice_is_passed_through_unchanged() -> None:
    raw = _bridge_response([_text("Just text.")])
    assert len(raw.choices) == 1

    response = from_litellm_model_response(raw)

    assert response.choice.message.content == "Just text."
    assert response.choice.finish_reason == "stop"


def test_no_choices_is_an_error() -> None:
    raw = litellm.ModelResponse(id="resp_1", created=1, model="gpt-5")
    raw.choices = []

    with pytest.raises(ValueError, match="at least one choice"):
        from_litellm_model_response(raw)


def test_preamble_and_answer_are_both_kept() -> None:
    """gpt-5.4+ can put a preamble in choices[0] and the answer in choices[1].
    Reading only choices[0] would return the preamble instead of the answer."""
    raw = _bridge_response([_text("Let me check. "), _text("Your meeting is at 3pm.")])

    response = from_litellm_model_response(raw)

    assert response.choice.message.content == "Let me check. Your meeting is at 3pm."


def test_repeated_parts_are_kept() -> None:
    """A choice has no message item id, so a repeat cannot be told apart from a
    resend. Keep everything: dropping real text would be silent data loss."""
    raw = _bridge_response([_text("Yes. "), _text("Yes. ")])

    response = from_litellm_model_response(raw)

    assert response.choice.message.content == "Yes. Yes. "
