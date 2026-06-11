"""Locust user that drives the Onyx chat streaming endpoint.

Each turn POSTs /api/chat/send-chat-message with stream=True and consumes the
NDJSON response line by line, firing a named pseudo-request the moment each
milestone packet arrives:

    <prefix>:first_packet         — time to first stream line
    <prefix>:first_search_doc     — time to first search-tool document batch
    <prefix>:first_answer_token   — time to first answer content (TTFT)
    <prefix>:first_dr_plan        — deep research plan started
    <prefix>:first_research_agent — first DR research agent spawned
    <prefix>:total_turn           — full turn wall time (success/failure here)

Scenario subclasses (see scenarios/) set `scenario_prefix`, `mock_model`,
`deep_research`, and timeouts. Configuration is via environment variables;
see README.md.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from locust import constant
from locust import HttpUser
from locust import task

from onyx_client.stream_parser import ChatStreamAnalyzer

DEFAULT_MESSAGES = [
    "What are the key features of the product?",
    "How does the search functionality work?",
    "What deployment options are available?",
    "Explain the security and access control model.",
    "What integrations and connectors are supported?",
    "Summarize how background indexing works.",
]


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    return float(raw) if raw else default


class OnyxChatUser(HttpUser):
    abstract = True

    scenario_prefix: str = "chat"
    # Model name sent as llm_override (mock knobs ride in the name). None =
    # persona default. Requires ONYX_LLM_PROVIDER when the target provider
    # is not the deployment default.
    mock_model: str | None = None
    deep_research: bool = False

    wait_time = constant(_env_float("ONYX_WAIT_SECONDS", 15.0))
    # Read timeout is between chunks, not total; chat_heartbeat keepalives in
    # the stream mean a healthy turn never goes silent this long.
    stream_read_timeout: float = _env_float("ONYX_STREAM_READ_TIMEOUT", 180.0)

    def on_start(self) -> None:
        api_key = os.environ.get("ONYX_API_KEY")
        if not api_key:
            raise RuntimeError("ONYX_API_KEY env var is required")
        self.client.headers["Authorization"] = f"Bearer {api_key}"

        provider = os.environ.get("ONYX_LLM_PROVIDER")
        model = self.mock_model or os.environ.get("ONYX_LLM_MODEL")
        self.llm_override: dict[str, Any] | None = None
        if model:
            self.llm_override = {"model_version": model}
            if provider:
                self.llm_override["model_provider"] = provider

        self.messages: list[str] = DEFAULT_MESSAGES
        self.turn_index: int = 0

    def _fire(
        self,
        name: str,
        start: float,
        response_length: int = 0,
        exception: Exception | None = None,
    ) -> None:
        self.environment.events.request.fire(
            request_type="CHAT",
            name=f"{self.scenario_prefix}:{name}",
            response_time=(time.perf_counter() - start) * 1000,
            response_length=response_length,
            exception=exception,
            context={},
        )

    @task
    def chat_turn(self) -> None:
        message = self.messages[self.turn_index % len(self.messages)]
        self.turn_index += 1

        payload: dict[str, Any] = {
            "message": message,
            "stream": True,
            # Omitting chat_session_id auto-creates a session with the
            # default persona (SendMessageRequest validator).
            "chat_session_info": {
                "description": f"loadtest-{uuid.uuid4().hex[:8]}",
            },
        }
        if self.llm_override:
            payload["llm_override"] = self.llm_override
        if self.deep_research:
            payload["deep_research"] = True

        analyzer = ChatStreamAnalyzer()
        start = time.perf_counter()
        try:
            # name= groups the auto-recorded HTTP metric; with stream=True its
            # response_time is time-to-headers only — the real signal is in
            # the CHAT milestone rows.
            with self.client.post(
                "/api/chat/send-chat-message",
                json=payload,
                stream=True,
                name=f"{self.scenario_prefix}:send (headers)",
                timeout=(30, self.stream_read_timeout),
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    self._fire(
                        "total_turn",
                        start,
                        exception=Exception(
                            f"HTTP {response.status_code}: {response.text[:200]}"
                        ),
                    )
                    return

                for line in response.iter_lines(decode_unicode=True):
                    for milestone in analyzer.feed(line):
                        self._fire(milestone, start)
                response.success()
        except Exception as exc:
            self._fire("total_turn", start, exception=exc)
            return

        summary = analyzer.summary
        if analyzer.completed_ok():
            self._fire("total_turn", start, response_length=summary.answer_chars)
        else:
            self._fire(
                "total_turn",
                start,
                exception=Exception(analyzer.failure_reason()),
            )


class BasicChatUser(OnyxChatUser):
    """Single-turn basic chat, new session each turn."""

    abstract = False
