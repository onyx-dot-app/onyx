"""Requests to GPT-5.6+ models on OpenAI and Azure APIs mark every tool result with an
explicit prompt_cache_breakpoint and send prompt_cache_options."""

import json
import os
from collections.abc import Iterator, Mapping
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
from threading import Event
from typing import Any
from unittest.mock import patch

import httpx
import litellm
import pytest
from litellm import ModelResponse as LiteLLMModelResponse
from litellm import ModelResponseStream
from litellm.exceptions import BadRequestError
from litellm.types.utils import Delta, StreamingChoices
from pydantic import JsonValue

from onyx.llm import multi_llm
from onyx.llm.factory import get_llm
from onyx.llm.models import (
    AssistantMessage,
    GenerationOptions,
    GenerationRequest,
    GenerationRequestParams,
    Message,
    ReasoningEffort,
    TextContent,
    TextDeltaEvent,
    ToolCall,
    ToolResultMessage,
    UserMessage,
)
from onyx.llm.prompt_cache.providers.openai import (
    CACHE_BREAKPOINT_FLAG,
    explicit_cache_breakpoints,
)

_RESPONSE = LiteLLMModelResponse(
    id="r",
    created=1,
    choices=[
        {"message": {"role": "assistant", "content": "done"}, "finish_reason": "stop"}
    ],
)
_RESULTS = [f"Evidence {index}" for index in range(6)]


def _turn(results: list[str] = _RESULTS, cacheable: bool = False) -> list[Message]:
    """A question, its tool steps and a reminder. `cacheable` puts the question
    and the tool steps in the cacheable prefix, as chat history caching does."""
    messages: list[Message] = [UserMessage(content="Question", cacheable=cacheable)]
    for index, text in enumerate(results):
        call_id = f"c{index}"
        messages += [
            AssistantMessage(
                content=[ToolCall(id=call_id, name="internal_search", arguments={})],
                cacheable=cacheable,
            ),
            ToolResultMessage(
                content=text,
                tool_call_id=call_id,
                tool_name="internal_search",
                cacheable=cacheable,
            ),
        ]
    return [
        *messages,
        UserMessage(content="<system-reminder>Cite sources.</system-reminder>"),
    ]


def _sent(
    provider: str,
    model: str,
    messages: list[Message],
    *,
    api_base: str | None = None,
    deployment_name: str | None = None,
    custom_config: dict[str, str] | None = None,
    model_kwargs: dict[str, JsonValue] | None = None,
) -> Mapping[str, Any]:
    client = get_llm(
        provider=provider,
        model=model,
        deployment_name=deployment_name,
        max_input_tokens=100_000,
        api_base=api_base,
        custom_config=custom_config,
        model_kwargs=model_kwargs,
    )
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion", return_value=_RESPONSE) as completion,
    ):
        client.invoke(GenerationRequest(messages=messages))
    return completion.call_args.kwargs


def _tool_contents(sent: Mapping[str, Any]) -> list[Any]:
    return [m["content"] for m in sent["messages"] if m["role"] == "tool"]


@pytest.mark.parametrize(
    ("provider", "model", "api_base"),
    [
        ("openai", "gpt-4.1", None),
        ("openai", "gpt-5.5", None),
        ("anthropic", "claude-sonnet-5", None),
        # An OpenAI-compatible server may reject the extra keys.
        ("openai", "gpt-5.6-luna", "https://proxy.example.com/v1"),
        ("azure", "gpt-5.6-luna", "https://proxy.example.com/v1"),
        ("azure", "gpt-5.5", "https://test.openai.azure.com"),
    ],
)
def test_other_requests_keep_plain_tool_results(
    provider: str, model: str, api_base: str | None
) -> None:
    sent = _sent(provider, model, _turn(), api_base=api_base)
    assert all(isinstance(content, str) for content in _tool_contents(sent))
    assert "prompt_cache_options" not in sent


# A user message keeps the chat-completions part type; the Responses bridge
# converts it to input_text with its marker.
_MARKED_QUESTION = [
    {
        "type": "text",
        "text": "Question",
        "prompt_cache_breakpoint": {"mode": "explicit"},
    }
]


def _user_contents(sent: Mapping[str, Any]) -> list[Any]:
    return [m["content"] for m in sent["messages"] if m["role"] == "user"]


def test_first_call_marks_the_prefix_that_later_calls_repeat() -> None:
    """The first call of a turn has no tool result yet. It marks the end of its
    cacheable prefix, so the next call, which repeats that marker before its
    marked tool results, reads the entry the first call wrote."""
    first = _sent("openai", "gpt-5.6-luna", _turn([], cacheable=True))
    second = _sent("openai", "gpt-5.6-luna", _turn(_RESULTS[:1], cacheable=True))

    for sent in (first, second):
        assert sent["prompt_cache_options"] == {"mode": "explicit"}
        assert _user_contents(sent) == [
            _MARKED_QUESTION,
            "<system-reminder>Cite sources.</system-reminder>",
        ]
    assert second["messages"][: len(first["messages"]) - 1] == first["messages"][:-1]
    assert _tool_contents(second)[0][0]["prompt_cache_breakpoint"] == {
        "mode": "explicit"
    }


def test_next_turn_repeats_the_marker_on_earlier_questions() -> None:
    """A request reads an entry only at a marker it carries. The next turn
    keeps the marker on the first question, so it reads the entry the first
    turn wrote even though the tool results after it changed."""
    first_turn = _sent("openai", "gpt-5.6-luna", _turn([], cacheable=True))
    history = [
        *_turn(["Shortened evidence"], cacheable=True)[:-1],
        AssistantMessage(content=[TextContent(text="Answer")], cacheable=True),
    ]
    next_turn = _sent(
        "openai",
        "gpt-5.6-luna",
        [*history, UserMessage(content="Follow-up", cacheable=True)],
    )

    question = 1 if first_turn["messages"][0]["role"] == "system" else 0
    assert (
        next_turn["messages"][: question + 1] == first_turn["messages"][: question + 1]
    )
    assert _user_contents(next_turn) == [
        _MARKED_QUESTION,
        [{**_MARKED_QUESTION[0], "text": "Follow-up"}],
    ]


def test_markers_survive_transforms_that_add_messages() -> None:
    """A Mistral-named deployment gets a bridge message between a tool result
    and the next user message. The flag travels on the message, so the user
    messages after the inserted bridge keep their markers."""
    sent = _sent(
        "azure",
        "gpt-5.6-luna",
        [
            *_turn(_RESULTS[:1], cacheable=True)[:-1],
            UserMessage(content="Follow-up", cacheable=True),
        ],
        api_base="https://test.openai.azure.com",
        deployment_name="mistral-router",
    )

    roles = [message["role"] for message in sent["messages"]]
    assert roles[roles.index("tool") + 1] == "assistant"
    assert sent["prompt_cache_options"] == {"mode": "explicit"}
    assert _user_contents(sent) == [
        _MARKED_QUESTION,
        [{**_MARKED_QUESTION[0], "text": "Follow-up"}],
    ]
    assert all("cache_breakpoint" not in message for message in sent["messages"])


def test_marking_a_text_part_keeps_its_fields() -> None:
    part: dict[str, JsonValue] = {
        "type": "text",
        "text": "Question",
        "cache_control": {"type": "ephemeral"},
    }
    marked, options = explicit_cache_breakpoints(
        [{"role": "user", "content": [part], CACHE_BREAKPOINT_FLAG: True}]
    )
    assert options == {"mode": "explicit"}
    assert marked == [
        {
            "role": "user",
            "content": [{**part, "prompt_cache_breakpoint": {"mode": "explicit"}}],
        }
    ]


def test_prefix_mark_stays_off_requests_without_explicit_caching() -> None:
    sent = _sent("openai", "gpt-4.1", _turn([], cacheable=True))
    assert "prompt_cache_options" not in sent
    assert _user_contents(sent)[0] == "Question"
    assert all("cache_breakpoint" not in message for message in sent["messages"])


def test_no_tool_result_keeps_implicit_caching() -> None:
    sent = _sent("openai", "gpt-5.6-luna", [UserMessage(content="Hello")])
    assert "prompt_cache_options" not in sent


@pytest.mark.parametrize("source", ["custom_config", "api_base", "base_url"])
def test_proxy_overrides_keep_plain_tool_results(source: str) -> None:
    proxy = "https://proxy.example.com/v1"
    sent = _sent(
        "openai",
        "gpt-5.6-luna",
        _turn(),
        custom_config={"OPENAI_API_BASE": proxy} if source == "custom_config" else None,
        model_kwargs={source: proxy} if source != "custom_config" else None,
    )
    assert all(isinstance(content, str) for content in _tool_contents(sent))
    assert "prompt_cache_options" not in sent
    assert sent.get("api_base") == proxy or sent["base_url"] == proxy


def test_cache_options_merge_without_mutating_configuration() -> None:
    configured: dict[str, JsonValue] = {"prompt_cache_options": {"ttl": "30m"}}
    client = get_llm(
        provider="openai",
        model="gpt-5.6-luna",
        deployment_name=None,
        max_input_tokens=100_000,
        model_kwargs=configured,
    )
    request = GenerationRequest(messages=_turn())
    original = request.model_dump()
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion", return_value=_RESPONSE) as completion,
    ):
        client.invoke(request)
        sent = completion.call_args.kwargs
        assert sent["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
        sent["prompt_cache_options"]["mode"] = "changed"
        _tool_contents(sent)[0][0]["prompt_cache_breakpoint"]["mode"] = "changed"
        client.invoke(request)
        again = completion.call_args.kwargs
        assert again["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
        assert _tool_contents(again)[0][0]["prompt_cache_breakpoint"] == {
            "mode": "explicit"
        }
        client.invoke(GenerationRequest(messages=[UserMessage(content="Hello")]))
        assert completion.call_args.kwargs["prompt_cache_options"] == {"ttl": "30m"}
    assert configured == {"prompt_cache_options": {"ttl": "30m"}}
    assert request.model_dump() == original


def test_endpoint_gate_waits_for_other_requests_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_BASE_URL", "https://proxy.example.com/v1")
    monkeypatch.setattr(litellm, "api_base", None)
    monkeypatch.setattr(multi_llm, "_env_injection_enabled", lambda: True)
    waiting = Event()
    lock = multi_llm.temporary_env_and_lock

    @contextmanager
    def observed_lock(
        env: dict[str, str],
        *,
        deadline: float | None = None,
    ) -> Iterator[None]:
        waiting.set()
        with lock(env, deadline=deadline):
            yield

    client = get_llm(
        provider="openai",
        model="gpt-5.6-luna",
        deployment_name=None,
        max_input_tokens=100_000,
    )
    monkeypatch.setattr(multi_llm, "temporary_env_and_lock", observed_lock)
    with patch("litellm.completion", return_value=_RESPONSE) as completion:
        with ThreadPoolExecutor(max_workers=1) as pool:
            with lock({"OPENAI_BASE_URL": "https://api.openai.com/v1"}):
                future = pool.submit(client.invoke, GenerationRequest(messages=_turn()))
                assert waiting.wait(10)
            future.result(timeout=10)
    sent = completion.call_args.kwargs
    assert "prompt_cache_options" not in sent
    assert _tool_contents(sent) == _RESULTS


def test_cache_retry_releases_environment_lock_and_keeps_caching_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CACHE_LOCK_TEST", raising=False)
    monkeypatch.setattr(multi_llm, "_env_injection_enabled", lambda: True)
    primary = get_llm(
        provider="openai",
        model="gpt-5.6-luna",
        deployment_name=None,
        max_input_tokens=100_000,
        custom_config={"CACHE_LOCK_TEST": "primary"},
        model_kwargs={"prompt_cache_options": {"ttl": "30m"}},
    )
    other = get_llm(
        provider="openai",
        model="gpt-4.1",
        deployment_name=None,
        max_input_tokens=100_000,
    )
    attempts: list[dict[str, Any]] = []
    traced: list[GenerationRequestParams] = []
    concurrent: Future[AssistantMessage] | None = None
    rejection_names = multi_llm._rejection_names_strippable_kwargs

    def classify(error: Exception, strippable: set[str]) -> bool:
        # Run another request before retry handling can dispatch the next attempt.
        assert concurrent is not None
        assert concurrent.result(timeout=5).text == "done"
        return rejection_names(error, strippable)

    def complete(
        **kwargs: Any,
    ) -> LiteLLMModelResponse | Iterator[ModelResponseStream]:
        nonlocal concurrent
        if not kwargs["stream"]:
            assert "CACHE_LOCK_TEST" not in os.environ
            return _RESPONSE
        assert os.environ["CACHE_LOCK_TEST"] == "primary"
        attempts.append(kwargs)
        if len(attempts) == 1:
            concurrent = pool.submit(
                other.invoke,
                GenerationRequest(messages=[UserMessage(content="Other")]),
            )
            raise BadRequestError(
                message="Unsupported prompt_cache_options",
                model="gpt-5.6-luna",
                llm_provider="openai",
            )
        return iter(
            [
                ModelResponseStream(
                    choices=[
                        StreamingChoices(
                            index=0,
                            delta=Delta(role="assistant", content="done"),
                            finish_reason="stop",
                        )
                    ]
                )
            ]
        )

    with (
        patch("litellm.completion", side_effect=complete),
        patch.object(
            multi_llm, "_rejection_names_strippable_kwargs", side_effect=classify
        ),
        patch.object(multi_llm, "record_llm_request_params", side_effect=traced.append),
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        assert primary.invoke(GenerationRequest(messages=_turn())).text == "done"

    assert len(attempts) == 2
    assert attempts[0]["prompt_cache_options"] == {"mode": "explicit", "ttl": "30m"}
    assert "prompt_cache_options" not in attempts[1]
    assert _tool_contents(attempts[1]) == _RESULTS
    primary_traces = [
        item.sent_kwargs for item in traced if item.model_name == "gpt-5.6-luna"
    ]
    assert (
        primary_traces[0]["prompt_cache_options"] == attempts[0]["prompt_cache_options"]
    )
    assert "prompt_cache_options" not in primary_traces[1]
    assert "CACHE_LOCK_TEST" not in os.environ


@pytest.mark.parametrize("provider", ["openai", "azure"])
@pytest.mark.parametrize("stream", [False, True])
@pytest.mark.parametrize(
    "rejected", [None, "prompt_cache_options", "prompt_cache_breakpoint"]
)
def test_real_bridge_preserves_breakpoints_in_responses_body(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    stream: bool,
    rejected: str | None,
) -> None:
    bodies: list[dict[str, Any]] = []

    def send(
        _client: httpx.Client, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        assert request.url.host == (
            "api.openai.com" if provider == "openai" else "test.openai.azure.com"
        )
        assert request.url.path.endswith("/responses")
        body = json.loads(request.content)
        bodies.append(body)
        if rejected and "prompt_cache_options" in body:
            return httpx.Response(
                400,
                request=request,
                json={
                    "error": {
                        "message": f"Unsupported {rejected}",
                        "type": "invalid_request_error",
                        "param": rejected,
                        "code": "unsupported_parameter",
                    }
                },
            )
        response = {
            "id": "resp_test",
            "object": "response",
            "created_at": 1,
            "model": "gpt-5.6-luna",
            "status": "completed",
            "output": [
                {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "done", "annotations": []}
                    ],
                }
            ],
            "usage": {"input_tokens": 10, "output_tokens": 1, "total_tokens": 11},
        }
        if stream:
            events = [
                {
                    "type": "response.output_text.delta",
                    "item_id": "msg_test",
                    "output_index": 0,
                    "content_index": 0,
                    "delta": "done",
                },
                {"type": "response.completed", "response": response},
            ]
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/event-stream"},
                content="".join(
                    f"event: {event['type']}\ndata: {json.dumps(event)}\n\n"
                    for event in events
                ),
            )
        return httpx.Response(200, request=request, json=response)

    monkeypatch.setattr(httpx.Client, "send", send)
    client = get_llm(
        provider=provider,
        model="gpt-5.6-luna",
        deployment_name="my-deployment" if provider == "azure" else None,
        api_base="https://test.openai.azure.com" if provider == "azure" else None,
        api_key="test-key",
        max_input_tokens=100_000,
    )
    with patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False):
        request = GenerationRequest(
            messages=_turn(cacheable=True),
            options=GenerationOptions(reasoning_effort=ReasoningEffort.HIGH),
        )
        if stream:
            assert (
                "".join(
                    event.text
                    for event in client.stream(request)
                    if isinstance(event, TextDeltaEvent)
                )
                == "done"
            )
        else:
            assert client.invoke(request).text == "done"
    if rejected:
        assert len(bodies) == 2
        assert bodies[-1]["reasoning"] == bodies[0]["reasoning"]
        assert bodies[-1]["reasoning"]["effort"] == "high"
        assert bodies[-1].get("temperature") == bodies[0].get("temperature")
        assert "prompt_cache_options" not in bodies[-1]
        assert [
            item["output"]
            for item in bodies[-1]["input"]
            if item["type"] == "function_call_output"
        ] == [[{"type": "input_text", "text": text}] for text in _RESULTS]
    else:
        assert len(bodies) == 1
    assert bodies[0]["prompt_cache_options"] == {"mode": "explicit"}
    outputs = [
        item["output"]
        for item in bodies[0]["input"]
        if item["type"] == "function_call_output"
    ]
    assert outputs == [
        [
            {
                "type": "input_text",
                "text": text,
                "prompt_cache_breakpoint": {"mode": "explicit"},
            }
        ]
        for text in _RESULTS
    ]

    assert bodies[0]["input"][0]["content"] == [
        {**_MARKED_QUESTION[0], "type": "input_text"}
    ]
    assert bodies[0]["input"][-1]["content"] == [
        {
            "type": "input_text",
            "text": "<system-reminder>Cite sources.</system-reminder>",
        }
    ]


@pytest.mark.parametrize("source", ["environment", "custom_config"])
def test_azure_endpoint_sources(
    monkeypatch: pytest.MonkeyPatch,
    source: str,
) -> None:
    endpoint = "https://test.openai.azure.com"
    monkeypatch.setattr(litellm, "api_base", None)
    if source == "environment":
        monkeypatch.setenv("AZURE_API_BASE", endpoint)
    sent = _sent(
        "azure",
        "gpt-5.6-luna",
        _turn(),
        custom_config={"AZURE_API_BASE": endpoint}
        if source == "custom_config"
        else None,
    )
    assert sent["prompt_cache_options"] == {"mode": "explicit"}


def test_invalid_cache_configuration_fails_before_dispatch() -> None:
    client = get_llm(
        provider="openai",
        model="gpt-5.6-luna",
        deployment_name=None,
        max_input_tokens=100_000,
        model_kwargs={"prompt_cache_options": "explicit"},
    )
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch("litellm.completion") as completion,
        pytest.raises(ValueError, match="prompt_cache_options must be a JSON object"),
    ):
        client.invoke(GenerationRequest(messages=_turn()))
    completion.assert_not_called()
