"""Locust user that drives the Onyx chat streaming endpoint.

Each turn POSTs /api/chat/send-chat-message with stream=True and consumes the
NDJSON response line by line, firing a named pseudo-request the moment each
milestone packet arrives:

    chat:first_packet       — time to first stream line (server accepted + began work)
    chat:first_search_doc   — time to first search-tool document batch
    chat:first_answer_token — time to first answer content (TTFT)
    chat:total_turn         — full turn wall time (success/failure recorded here)

Configuration is via environment variables; see README.md.
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

    wait_time = constant(_env_float("ONYX_WAIT_SECONDS", 15.0))
    # Read timeout is between chunks, not total; chat_heartbeat keepalives in
    # the stream mean a healthy turn never goes silent this long.
    stream_read_timeout = _env_float("ONYX_STREAM_READ_TIMEOUT", 180.0)
    deep_research = os.environ.get("ONYX_DEEP_RESEARCH", "").lower() == "true"

    def on_start(self) -> None:
        api_key = os.environ.get("ONYX_API_KEY")
        if not api_key:
            raise RuntimeError("ONYX_API_KEY env var is required")
        self.client.headers["Authorization"] = f"Bearer {api_key}"

        self.llm_override: dict[str, Any] | None = None
        provider = os.environ.get("ONYX_LLM_PROVIDER")
        model = os.environ.get("ONYX_LLM_MODEL")
        if provider and model:
            self.llm_override = {"model_provider": provider, "model_version": model}

        self.messages = DEFAULT_MESSAGES
        self.turn_index = 0

    def _fire(
        self,
        name: str,
        start: float,
        response_length: int = 0,
        exception: Exception | None = None,
    ) -> None:
        self.environment.events.request.fire(
            request_type="CHAT",
            name=name,
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
                name="chat:send (headers)",
                timeout=(30, self.stream_read_timeout),
                catch_response=True,
            ) as response:
                if response.status_code != 200:
                    response.failure(f"HTTP {response.status_code}")
                    self._fire(
                        "chat:total_turn",
                        start,
                        exception=Exception(
                            f"HTTP {response.status_code}: {response.text[:200]}"
                        ),
                    )
                    return

                for line in response.iter_lines(decode_unicode=True):
                    for milestone in analyzer.feed(line):
                        self._fire(f"chat:{milestone}", start)
                response.success()
        except Exception as exc:
            self._fire("chat:total_turn", start, exception=exc)
            return

        summary = analyzer.summary
        if analyzer.completed_ok():
            self._fire("chat:total_turn", start, response_length=summary.answer_chars)
        else:
            reason = summary.error or (
                "stream ended without message_start/answer content "
                f"(packets={summary.packets}, saw_stop={summary.saw_stop})"
            )
            self._fire("chat:total_turn", start, exception=Exception(reason))


class BasicChatUser(OnyxChatUser):
    """Single-turn basic chat, new session each turn."""

    abstract = False
