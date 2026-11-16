import json
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

from onyx.llm.constants import WELL_KNOWN_PROVIDER_NAMES, LlmProviderNames
from onyx.llm.model_capabilities import find_model_obj, get_model_map
from onyx.llm.model_catalog import find_model_cost
from onyx.llm.model_request import UserMessage
from onyx.llm.models import ReasoningEffort
from onyx.llm.multi_llm import LitellmLLM
from onyx.llm.well_known_providers.llm_provider_options import (
    _get_provider_to_models_map,
    _load_bundled_recommendations,
)


@contextmanager
def _capture_api(suffix: str) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    captured: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            content_length = int(self.headers.get("Content-Length", "0"))
            body = json.loads(self.rfile.read(content_length))
            captured.append({"path": self.path, "body": body})

            if self.path.endswith("/messages"):
                response = {
                    "id": "msg_test",
                    "type": "message",
                    "role": "assistant",
                    "model": body["model"],
                    "content": [{"type": "text", "text": "ok"}],
                    "stop_reason": "end_turn",
                    "stop_sequence": None,
                    "usage": {"input_tokens": 1, "output_tokens": 1},
                }
            else:
                response = {
                    "id": "chatcmpl-test",
                    "object": "chat.completion",
                    "created": 0,
                    "model": body["model"],
                    "choices": [
                        {
                            "index": 0,
                            "message": {"role": "assistant", "content": "ok"},
                            "finish_reason": "stop",
                        }
                    ],
                    "usage": {
                        "prompt_tokens": 1,
                        "completion_tokens": 1,
                        "total_tokens": 2,
                    },
                }

            encoded = json.dumps(response).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002, ARG002
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}{suffix}", captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_minimax_registry_includes_both_target_models() -> None:
    assert LlmProviderNames.MINIMAX in WELL_KNOWN_PROVIDER_NAMES
    assert _get_provider_to_models_map()[LlmProviderNames.MINIMAX] == [
        "MiniMax-M3.1-Flash",
        "MiniMax-M3",
    ]

    recommendations = _load_bundled_recommendations()
    default_model = recommendations.get_default_model("minimax")
    assert default_model is not None
    assert default_model.name == "MiniMax-M3.1-Flash"
    assert [model.name for model in recommendations.get_visible_models("minimax")] == [
        "MiniMax-M3.1-Flash",
        "MiniMax-M3",
    ]


def test_minimax_model_metadata_matches_official_limits_and_pricing() -> None:
    get_model_map.cache_clear()
    try:
        model_map = get_model_map()
        m31 = find_model_obj(model_map, LlmProviderNames.MINIMAX, "MiniMax-M3.1-Flash")
        m3 = find_model_obj(model_map, LlmProviderNames.MINIMAX, "MiniMax-M3")
        m31_cost = find_model_cost("minimax", "MiniMax-M3.1-Flash")
        m3_cost = find_model_cost("minimax", "MiniMax-M3")

        assert m31 is not None
        assert m31_cost is not None
        assert m31["max_input_tokens"] == 1_000_000
        assert m31["max_output_tokens"] == 524_288
        assert m31_cost["input"] == 0.15
        assert m31_cost["output"] == 0.6
        assert m31_cost["cache_read"] == 0.015
        assert m31["supports_reasoning"] is True
        assert m31["supports_vision"] is True

        assert m3 is not None
        assert m3_cost is not None
        assert m3["max_input_tokens"] == 1_000_000
        assert m3["max_output_tokens"] == 524_288
        assert m3_cost["input"] == 0.3
        assert m3_cost["output"] == 1.2
        assert m3_cost["cache_read"] == 0.06
        assert m3_cost["tiers"] == [
            {
                "cache_read": 0.12,
                "input": 0.6,
                "output": 2.4,
                "tier": {"size": 512_000, "type": "context"},
            }
        ]
        assert m3["supports_reasoning"] is True
        assert m3["supports_vision"] is True
    finally:
        get_model_map.cache_clear()


def test_minimax_anthropic_base_url_omits_v1() -> None:
    llm = LitellmLLM(
        api_key="test-key",
        api_base="https://api.minimax.io/anthropic/v1",
        model_provider=LlmProviderNames.MINIMAX,
        model_name="MiniMax-M3",
        max_input_tokens=1_000_000,
    )

    assert llm.config.api_base == "https://api.minimax.io/anthropic"


@pytest.mark.parametrize(
    ("suffix", "model_name", "reasoning_effort", "expected_path", "thinking"),
    [
        (
            "/anthropic",
            "MiniMax-M3",
            ReasoningEffort.AUTO,
            "/anthropic/v1/messages",
            {"type": "disabled"},
        ),
        (
            "/anthropic",
            "MiniMax-M3.1-Flash",
            ReasoningEffort.AUTO,
            "/anthropic/v1/messages",
            {"type": "adaptive"},
        ),
        (
            "/v1",
            "MiniMax-M3",
            ReasoningEffort.OFF,
            "/v1/chat/completions",
            {"type": "disabled"},
        ),
        (
            "/v1",
            "MiniMax-M3.1-Flash",
            ReasoningEffort.OFF,
            "/v1/chat/completions",
            {"type": "adaptive"},
        ),
    ],
)
def test_minimax_client_request_capture(
    suffix: str,
    model_name: str,
    reasoning_effort: ReasoningEffort,
    expected_path: str,
    thinking: dict[str, str] | None,
) -> None:
    with _capture_api(suffix) as (api_base, captured):
        llm = LitellmLLM(
            api_key="test-key",
            api_base=api_base,
            model_provider=LlmProviderNames.MINIMAX,
            model_name=model_name,
            max_input_tokens=1_000_000,
        )

        llm._completion(
            prompt=[UserMessage(content="Hello")],
            tools=None,
            tool_choice=None,
            stream=False,
            parallel_tool_calls=False,
            reasoning_effort=reasoning_effort,
            max_tokens=8,
        )

    assert len(captured) == 1
    request = captured[0]
    assert request["path"] == expected_path
    assert request["body"]["model"] == model_name
    assert request["body"].get("thinking") == thinking
    if suffix == "/v1":
        assert request["body"]["reasoning_split"] is True
