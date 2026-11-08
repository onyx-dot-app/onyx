"""Preserve provider cache writes through LiteLLM, generation, tracing, and cost."""

import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest

from onyx.llm.cost import compute_cost_cents
from onyx.llm.factory import get_llm
from onyx.llm.models import GenerationRequest, UserMessage
from onyx.tracing.llm_utils import record_llm_response, record_llm_span_output
from tests.unit.onyx.agents.fakes import collect_generation


@pytest.mark.parametrize("streaming", [False, True], ids=["invoke", "stream"])
def test_responses_cache_writes_reach_generation_cost_and_trace(
    monkeypatch: pytest.MonkeyPatch, streaming: bool
) -> None:
    # Raw usage from a GPT-6 Luna request with an explicit tool-result breakpoint.
    response = {
        "id": "resp_cached",
        "object": "response",
        "created_at": 1,
        "model": "gpt-6-luna",
        "status": "completed",
        "output": [
            {
                "id": "msg_answer",
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": "OK", "annotations": []}],
            }
        ],
        "usage": {
            "input_tokens": 6410,
            "input_tokens_details": {
                "cached_tokens": 0,
                "cache_write_tokens": 6327,
                "cache_write_tokens_details": {
                    "ttl_30m_tokens": 6327,
                    "ttl_12h_tokens": 0,
                },
            },
            "output_tokens": 5,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 6415,
        },
    }

    def send(
        _client: httpx.Client, request: httpx.Request, **_kwargs: Any
    ) -> httpx.Response:
        assert request.url.path.endswith("/responses")
        if streaming:
            event = {
                "type": "response.completed",
                "sequence_number": 0,
                "response": response,
            }
            return httpx.Response(
                200,
                request=request,
                headers={"content-type": "text/event-stream"},
                content=f"event: response.completed\ndata: {json.dumps(event)}\n\n",
            )
        return httpx.Response(200, request=request, json=response)

    monkeypatch.setattr(httpx.Client, "send", send)
    client = get_llm(
        provider="openai",
        model="gpt-6-luna",
        deployment_name=None,
        api_key="test-key",
        max_input_tokens=10000,
    )
    request = GenerationRequest(messages=[UserMessage(content="Acknowledge.")])
    record_name = "record_llm_span_output" if streaming else "record_llm_response"
    record_function = record_llm_span_output if streaming else record_llm_response
    with (
        patch("onyx.llm.multi_llm._env_injection_enabled", return_value=False),
        patch.object(client, "_track_llm_cost") as track_cost,
        patch(f"onyx.llm.multi_llm.{record_name}", wraps=record_function) as record,
    ):
        message = (
            collect_generation(list(client.stream(request)))
            if streaming
            else client.invoke(request)
        )
    usage = message.usage
    assert usage is not None
    assert usage.prompt_tokens == 6410
    assert usage.cache_creation_input_tokens == 6327
    assert usage.cache_read_input_tokens == 0
    assert usage.completion_tokens == 5
    assert track_cost.call_args.args[0] == usage
    span = record.call_args.args[0]
    assert span.span_data.usage["cache_creation_input_tokens"] == 6327
    assert span.span_data.usage["input_tokens"] == 6410

    with patch(
        "onyx.llm.cost.find_model_cost",
        return_value={
            "input": 0.10,
            "cache_read": 0.01,
            "cache_write": 0.125,
            "output": 0.50,
        },
    ):
        input_cents, output_cents = compute_cost_cents(
            model="gpt-6-luna",
            provider="openai",
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cache_read_tokens=usage.cache_read_input_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens,
        )
    assert input_cents == pytest.approx(0.0799175)
    assert output_cents == pytest.approx(0.00025)
