"""OpenAI reasoning items survive Onyx's message model and replay through
LiteLLM's responses bridge, on the routes that can read them."""

import json
from typing import Any, cast
from unittest.mock import patch

import httpx
import pytest
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    LiteLLMResponsesTransformationHandler as Bridge,
)
from litellm.completion_extras.litellm_responses_transformation.transformation import (
    OpenAiResponsesToChatCompletionStreamIterator as BridgeStream,
)
from litellm.exceptions import BadRequestError
from litellm.types.utils import ModelResponse as LiteLLMModelResponse
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseReasoningItem,
)
from pydantic import TypeAdapter

from onyx.agents.execution_records import messages_for_model
from onyx.chat.prompt_formatting import count_message_tokens
from onyx.llm.constants import LlmProviderNames
from onyx.llm.factory import get_llm
from onyx.llm.interfaces import LLMConfig
from onyx.llm.model_request import AssistantMessage as ProviderAssistantMessage
from onyx.llm.model_request import (
    ChatCompletionMessage,
    ReasoningItem,
    serialize_request,
)
from onyx.llm.model_request import UserMessage as ProviderUserMessage
from onyx.llm.model_response import (
    MessageAccumulator,
    from_litellm_model_response,
    from_litellm_model_response_stream,
    to_assistant_message,
)
from onyx.llm.models import (
    AssistantMessage,
    GenerationRequest,
    Message,
    ReasoningEffort,
    ReasoningItemBlock,
    TextContent,
    ThinkingBlock,
    ThinkingContent,
    ToolCall,
    ToolDefinition,
    ToolResultMessage,
    UserMessage,
    apply_generation_event,
)
from onyx.llm.multi_llm import LitellmLLM
from tests.unit.onyx.agents.fakes import collect_generation

_REASONING = ResponseReasoningItem(
    id="rs_1",
    type="reasoning",
    summary=[{"type": "summary_text", "text": "Plan the lookup."}],
    encrypted_content="encrypted-state",
)
_ANSWER = ResponseOutputMessage(
    id="msg_1",
    type="message",
    role="assistant",
    status="completed",
    content=[{"type": "output_text", "text": "Looking it up.", "annotations": []}],
)
_CALL = ResponseFunctionToolCall(
    id="fc_1",
    call_id="call_1",
    type="function_call",
    name="lookup",
    arguments='{"q": "term"}',
)
_TOOL = ToolDefinition(name="lookup", description="Find facts", parameters={})
_BLOCK = ReasoningItemBlock(
    id="rs_1", summary=["Plan the lookup."], encrypted_content="encrypted-state"
)
_WIRE_ITEM = {
    "type": "reasoning",
    "id": "rs_1",
    "summary": [{"type": "summary_text", "text": "Plan the lookup."}],
    "encrypted_content": "encrypted-state",
}
_CONFIG = LLMConfig(
    model_provider="openai", model_name="gpt-5.4", temperature=0, max_input_tokens=4096
)
_MESSAGE_ADAPTER = TypeAdapter(Message)


def _stream(events: list[dict[str, Any]]) -> AssistantMessage:
    """Run bridge stream events through the accumulator as `LitellmLLM.stream`
    does, applying each event to the caller's copy of the message."""
    stream = BridgeStream(iter([]), sync_stream=True)
    accumulator = MessageAccumulator([_TOOL])
    replayed = AssistantMessage()
    for event in events:
        chunk = stream.chunk_parser(event)
        assert chunk is not None
        for generation_event in accumulator.add(
            from_litellm_model_response_stream(chunk)
        ):
            apply_generation_event(replayed, generation_event)
    for generation_event in accumulator.end():
        apply_generation_event(replayed, generation_event)
    assert replayed == accumulator.message
    return replayed


@pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
def test_reasoning_item_replays_through_the_bridge(streaming: bool) -> None:
    """A reasoning item is kept with its thinking, stored, and replayed before
    the tool call it reasoned for."""
    if streaming:
        # The bridge sends the item on the final chunk, after the tool call.
        message = _stream(
            [
                {
                    "type": "response.reasoning_summary_text.delta",
                    "summary_index": 0,
                    "delta": "Plan the lookup.",
                },
                {
                    "type": "response.output_item.added",
                    "output_index": 1,
                    "item": _CALL.model_dump(),
                },
                {
                    "type": "response.completed",
                    "response": {
                        "id": "resp_1",
                        "output": [_REASONING.model_dump(), _CALL.model_dump()],
                    },
                },
            ]
        )
        assert [type(part) for part in message.content] == [ThinkingContent, ToolCall]
    else:
        choices = Bridge._convert_response_output_to_choices(
            [_REASONING, _ANSWER, _CALL]
        )
        raw = LiteLLMModelResponse(id="resp_1", created=1, choices=choices)
        message = to_assistant_message(
            from_litellm_model_response(raw), GenerationRequest(tools=[_TOOL])
        )
        assert message.text == "Looking it up."
    assert message.thinking == "Plan the lookup."
    assert message.thinking_blocks == [_BLOCK]
    (call,) = message.tool_calls

    stored = _MESSAGE_ADAPTER.validate_json(_MESSAGE_ADAPTER.dump_json(message))
    history: list[Message] = [
        UserMessage(content="Find the term"),
        stored,
        ToolResultMessage(content="found", tool_call_id=call.id, tool_name="lookup"),
    ]
    provider_messages, _ = serialize_request(
        GenerationRequest(messages=messages_for_model(history)), _CONFIG
    )
    # cast-ok: the bridge types its input items loosely
    items = cast(
        list[dict[str, Any]],
        Bridge().convert_chat_completion_messages_to_responses_api(
            [m.model_dump(mode="json", exclude_none=True) for m in provider_messages]
        )[0],
    )

    assert items[1] == _WIRE_ITEM
    assert [item["type"] for item in items] == [
        "message",
        "reasoning",
        *(["message"] if not streaming else []),
        "function_call",
        "function_call_output",
    ]


def test_reasoning_item_without_a_summary_is_kept() -> None:
    """Short answers often come with an empty summary and no reasoning deltas."""
    bare = _REASONING.model_copy(update={"summary": []})
    message = _stream(
        [
            {"type": "response.output_text.delta", "delta": "Looking it up."},
            {
                "type": "response.completed",
                "response": {
                    "id": "resp_1",
                    "output": [bare.model_dump(), _ANSWER.model_dump()],
                },
            },
        ]
    )

    assert message.text == "Looking it up."
    assert message.thinking == ""
    assert message.thinking_blocks == [_BLOCK.model_copy(update={"summary": []})]


_PROMPT: list[ChatCompletionMessage] = [
    # The breakpoint turns on OpenAI's explicit cache copy of the messages.
    ProviderUserMessage(content="hi", cache_breakpoint=True),
    # One message never carries both in practice; the fixture checks each
    # route keeps only the state it can read.
    ProviderAssistantMessage(
        content="answer",
        thinking_blocks=[ThinkingBlock(thinking="signed", signature="proof")],
        reasoning_items=[
            ReasoningItem(id="rs_1", summary=[], encrypted_content="encrypted-state")
        ],
    ),
    ProviderUserMessage(content="more"),
]


_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "search",
            "parameters": {"type": "object", "properties": {}},
        },
    }
]


def _llm(
    provider: str,
    model: str,
    supports_reasoning: bool = False,
    model_kwargs: dict[str, Any] | None = None,
) -> LitellmLLM:
    return LitellmLLM(
        api_key="test-key",
        model_provider=provider,
        model_name=model,
        max_input_tokens=100000,
        api_base="https://example.test" if provider == LlmProviderNames.AZURE else None,
        supports_reasoning=supports_reasoning,
        model_kwargs=model_kwargs,
    )


def _complete(llm: LitellmLLM, completion: Any) -> list[dict[str, Any]]:
    with (
        patch(
            "onyx.llm.litellm_singleton.litellm.completion", side_effect=completion
        ) as mocked,
        # OpenAI's explicit cache breakpoints send a second copy of the messages.
        patch("onyx.llm.multi_llm.uses_explicit_cache_breakpoints", return_value=True),
    ):
        llm._completion(
            prompt=_PROMPT,
            tools=_TOOLS,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=ReasoningEffort.HIGH,
            env_injection_enabled=False,
        )
    return [dict(call.kwargs) for call in mocked.call_args_list]


@pytest.mark.parametrize(
    ("provider", "model", "replays_reasoning_items"),
    [
        (LlmProviderNames.OPENAI, "gpt-5", True),
        (LlmProviderNames.AZURE, "gpt-5", True),
        # An uncatalogued deployment alias the admin flags as reasoning takes
        # LiteLLM's effort style and reaches Responses through the tool-turn
        # bridge.
        (LlmProviderNames.AZURE, "gpt-5.4-team-alias", True),
        (LlmProviderNames.ANTHROPIC, "claude-sonnet-4-5", False),
    ],
)
def test_only_responses_routes_request_and_replay_reasoning_items(
    provider: str, model: str, replays_reasoning_items: bool
) -> None:
    llm = _llm(provider, model, supports_reasoning="alias" in model)
    (kwargs,) = _complete(llm, lambda **_: None)
    assistant = kwargs["messages"][1]

    if replays_reasoning_items:
        assert kwargs["include"] == ["reasoning.encrypted_content"]
        assert assistant["reasoning_items"][0]["encrypted_content"] == "encrypted-state"
        assert "thinking_blocks" not in assistant
    else:
        assert "include" not in kwargs
        assert "reasoning_items" not in assistant
        assert assistant["thinking_blocks"][0]["signature"] == "proof"


def test_configured_include_is_sent_once_with_encrypted_reasoning() -> None:
    llm = _llm(
        LlmProviderNames.OPENAI,
        "gpt-5",
        model_kwargs={"include": ["web_search_call.results"]},
    )

    (kwargs,) = _complete(llm, lambda **_: None)

    assert kwargs["include"] == [
        "web_search_call.results",
        "reasoning.encrypted_content",
    ]


@pytest.mark.parametrize(
    ("rejection", "dropped"),
    [
        pytest.param(
            "The encrypted content for item rs_1 could not be verified.",
            "reasoning_items",
            id="foreign-item",
        ),
        pytest.param(
            "Item 'rs_1' of type 'reasoning' was provided without its required "
            "following item.",
            "reasoning_items",
            id="lone-item",
        ),
        pytest.param("Unknown parameter: 'include'.", "include", id="include"),
    ],
)
def test_rejected_replay_state_is_retried_without_it(
    rejection: str, dropped: str
) -> None:
    """A rejected item or `include` costs one retry, never the reasoning effort."""
    calls: list[dict[str, Any]] = []

    def completion(**kwargs: Any) -> None:
        if not calls:
            calls.append(kwargs)
            raise BadRequestError(message=rejection, model="m", llm_provider="openai")

    first, second = _complete(_llm(LlmProviderNames.OPENAI, "gpt-5"), completion)

    assert "reasoning_items" in first["messages"][1] and "include" in first
    assert second["reasoning"] == first["reasoning"]
    if dropped == "include":
        assert "include" not in second
        assert "reasoning_items" in second["messages"][1]
    else:
        assert "reasoning_items" not in second["messages"][1]
        assert second["include"] == first["include"]


@pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
def test_request_body_carries_include_and_the_replayed_item(
    monkeypatch: pytest.MonkeyPatch, streaming: bool
) -> None:
    """Through LiteLLM's request transform: the first turn asks for encrypted
    reasoning, and the second turn's body replays the item it received."""
    bodies: list[dict[str, Any]] = []
    response = {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6-luna",
        "status": "completed",
        "output": [_REASONING.model_dump(), _ANSWER.model_dump()],
        "usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2},
    }

    def send(
        _client: httpx.Client, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        bodies.append(json.loads(request.content))
        if streaming:
            event = {"type": "response.completed", "response": response}
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/event-stream"},
                content=f"event: response.completed\ndata: {json.dumps(event)}\n\n",
            )
        return httpx.Response(200, request=request, json=response)

    monkeypatch.setattr(httpx.Client, "send", send)
    llm = get_llm(
        provider="openai",
        model="gpt-6-luna",
        deployment_name=None,
        api_key="test-key",
        max_input_tokens=10000,
    )

    def turn(history: list[Message]) -> AssistantMessage:
        request = GenerationRequest(messages=history)
        with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False):
            if streaming:
                return collect_generation(list(llm.stream(request)))
            return llm.invoke(request)

    first = turn([UserMessage(content="Find the term")])
    assert first.thinking_blocks == [_BLOCK]
    turn([UserMessage(content="Find the term"), first, UserMessage(content="More")])

    assert [body["include"] for body in bodies] == [["reasoning.encrypted_content"]] * 2
    assert [item["type"] for item in bodies[1]["input"]] == [
        "message",
        "reasoning",
        "message",
        "message",
    ]
    assert bodies[1]["input"][1] == _WIRE_ITEM


def test_token_estimate_ignores_encrypted_reasoning() -> None:
    long_block = _BLOCK.model_copy(update={"encrypted_content": "x" * 40000})
    long_message = AssistantMessage(
        content=[ThinkingContent(text="Plan.", blocks=[long_block])]
    )
    short_message = AssistantMessage(
        content=[ThinkingContent(text="Plan.", blocks=[_BLOCK])]
    )
    text_only = AssistantMessage(content=[TextContent(text="Plan.")])

    assert count_message_tokens(long_message, len) == count_message_tokens(
        short_message, len
    )
    assert count_message_tokens(short_message, len) > count_message_tokens(
        text_only, len
    )
