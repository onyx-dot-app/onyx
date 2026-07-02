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

from onyx_client.env import env_float
from onyx_client.env import env_int
from onyx_client.stream_parser import ChatStreamAnalyzer

DEFAULT_MESSAGES = [
    "What are the key features of the product?",
    "How does the search functionality work?",
    "What deployment options are available?",
    "Explain the security and access control model.",
    "What integrations and connectors are supported?",
    "Summarize how background indexing works.",
]

_PAD = "Please consider the full context of the conversation so far in detail. "


def _sized_message(question: str, target_chars: int) -> str:
    """Pad a question with filler up to ~target_chars so histories grow fast
    enough to cross the summarization threshold (compression testing)."""
    if target_chars <= len(question):
        return question
    filler = _PAD * (target_chars // len(_PAD) + 1)
    return (question + " " + filler)[:target_chars]


class OnyxChatUser(HttpUser):
    abstract = True

    scenario_prefix: str = "chat"
    # Model name sent as llm_override (mock knobs ride in the name). None =
    # persona default. Requires ONYX_LLM_PROVIDER when the target provider
    # is not the deployment default.
    mock_model: str | None = None
    deep_research: bool = False

    # >1 keeps one session alive for N turns, chaining parent_message_id so
    # history grows; 1 (default) = a fresh session per turn.
    max_session_turns: int = env_int("ONYX_SESSION_TURNS", 1)

    # Per-message size in chars (ONYX_MSG_CHARS overrides). 0 = the short
    # default questions. Scenarios that need history to grow fast (compression)
    # raise this default; larger messages cross the summarization threshold in
    # fewer turns.
    default_msg_chars: int = 0

    # If set to a milestone name, drop the stream the instant it arrives
    # (client disconnect). Recorded as <prefix>:disconnected, not a failure.
    disconnect_after_milestone: str | None = None

    wait_time = constant(env_float("ONYX_WAIT_SECONDS", 15.0))
    # Read timeout is between chunks, not total; chat_heartbeat keepalives in
    # the stream mean a healthy turn never goes silent this long.
    stream_read_timeout: float = env_float("ONYX_STREAM_READ_TIMEOUT", 180.0)

    def on_start(self) -> None:
        api_key = os.environ.get("ONYX_API_KEY")
        if not api_key:
            raise RuntimeError("ONYX_API_KEY env var is required")
        self.client.headers["Authorization"] = f"Bearer {api_key}"

        # When LOCUST_HOST points at an internal Service (to bypass an external
        # ALB/WAF rate limit for high-rps runs), set ONYX_HOST_HEADER to the
        # real domain so the in-cluster nginx routes by Host as usual.
        host_header = os.environ.get("ONYX_HOST_HEADER")
        if host_header:
            self.client.headers["Host"] = host_header

        provider = os.environ.get("ONYX_LLM_PROVIDER")
        model = self.mock_model or os.environ.get("ONYX_LLM_MODEL")
        self.llm_override: dict[str, Any] | None = None
        if model:
            self.llm_override = {"model_version": model}
            if provider:
                self.llm_override["model_provider"] = provider

        msg_chars = env_int("ONYX_MSG_CHARS", self.default_msg_chars)
        self.messages: list[str] = (
            [_sized_message(q, msg_chars) for q in DEFAULT_MESSAGES]
            if msg_chars > 0
            else DEFAULT_MESSAGES
        )
        self.turn_index: int = 0

        # Multi-turn session state (only used when max_session_turns > 1).
        self._session_id: str | None = None
        self._parent_message_id: int | None = None
        self._session_turn: int = 0

        # File attachments to include on every turn (populated by scenarios
        # that exercise the file path; empty for plain chat).
        self.file_descriptors: list[dict[str, Any]] = []
        self.setup_files()

    def setup_files(self) -> None:
        """Hook for scenarios to upload files and populate file_descriptors.
        No-op by default."""

    def _create_session(self) -> str | None:
        """Open a session for a multi-turn conversation; None on failure."""
        with self.client.post(
            "/api/chat/create-chat-session",
            json={"persona_id": 0, "description": f"loadtest-{uuid.uuid4().hex[:8]}"},
            name=f"{self.scenario_prefix}:create-session",
            catch_response=True,
        ) as response:
            if response.status_code != 200:
                response.failure(f"HTTP {response.status_code}")
                return None
            session_id = response.json().get("chat_session_id")
            if not session_id:
                # A 200 with no id would otherwise be counted a success while
                # silently dropping the turn — fail it explicitly instead.
                response.failure("create-chat-session: missing chat_session_id")
                return None
            response.success()
            return session_id

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

    def _next_payload(self, message: str) -> dict[str, Any] | None:
        """Build the send payload, managing session reuse. None = skip turn
        (a multi-turn session was needed but couldn't be created)."""
        payload: dict[str, Any] = {"message": message, "stream": True}

        if self.max_session_turns > 1:
            if self._session_id is None or self._session_turn >= self.max_session_turns:
                self._session_id = self._create_session()
                self._parent_message_id = None
                self._session_turn = 0
                if self._session_id is None:
                    return None
            payload["chat_session_id"] = self._session_id
            if self._parent_message_id is not None:
                payload["parent_message_id"] = self._parent_message_id
        else:
            # Omitting chat_session_id auto-creates a session with the
            # default persona (SendMessageRequest validator).
            payload["chat_session_info"] = {
                "description": f"loadtest-{uuid.uuid4().hex[:8]}",
            }

        if self.llm_override:
            payload["llm_override"] = self.llm_override
        if self.deep_research:
            payload["deep_research"] = True
        if self.file_descriptors:
            payload["file_descriptors"] = self.file_descriptors
        return payload

    @task
    def chat_turn(self) -> None:
        message = self.messages[self.turn_index % len(self.messages)]
        self.turn_index += 1

        payload = self._next_payload(message)
        if payload is None:
            return

        analyzer = ChatStreamAnalyzer()
        disconnect_target = self.disconnect_after_milestone
        disconnected = False
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
                    # Abandon a multi-turn session that just errored so the
                    # next turn starts fresh rather than reusing a bad session.
                    self._session_id = None
                    return

                for line in response.iter_lines(decode_unicode=True):
                    for milestone in analyzer.feed(line):
                        self._fire(milestone, start)
                        if disconnect_target and milestone == disconnect_target:
                            disconnected = True
                            break
                    if disconnected:
                        break
                # On disconnect, exiting the `with` unconsumed closes the
                # socket so the server sees the client drop; the sample is ok.
                response.success()
        except Exception as exc:
            self._fire("total_turn", start, exception=exc)
            self._session_id = None  # don't reuse a session after a failure
            return

        if disconnected:
            self._fire(
                "disconnected", start, response_length=analyzer.summary.answer_chars
            )
            # A mid-stream disconnect abandons this conversation; the next turn
            # starts a fresh session.
            self._session_id = None
            return

        if self.max_session_turns > 1:
            self._session_turn += 1
            rid = analyzer.summary.reserved_assistant_message_id
            if rid is not None:
                self._parent_message_id = rid

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
    """Single-turn basic chat, new session each turn.

    The bulk of the default weighted mix (see README "Scenario mix").
    """

    abstract = False
    weight = 70
