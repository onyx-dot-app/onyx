"""Timeout settings must reach `OpencodeServeClient.send_message`."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Generator
from typing import Any
from uuid import uuid4

from onyx.server.features.build.configs import (
    OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS,
)
from onyx.server.features.build.configs import PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS
from onyx.server.features.build.sandbox.event_schema import PromptResponse
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)


class _FakeServeClient:
    def __init__(self) -> None:
        self.captured_timeout: float | None = None
        self.captured_absolute_timeout: float | None = None

    def ensure_session(
        self,
        opencode_session_id: str | None,  # noqa: ARG002
        *,
        directory: str,  # noqa: ARG002
        title: str | None = None,  # noqa: ARG002
    ) -> str:
        return "ses_fake"

    def send_message(
        self,
        opencode_session_id: str,  # noqa: ARG002
        message: str,  # noqa: ARG002
        *,
        directory: str,  # noqa: ARG002
        model_provider: str | None = None,  # noqa: ARG002
        model_id: str | None = None,  # noqa: ARG002
        timeout: float = OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS,
        absolute_timeout: float | None = None,
        should_interrupt: Callable[[], bool] | None = None,  # noqa: ARG002
    ) -> Generator[Any, None, None]:
        self.captured_timeout = timeout
        self.captured_absolute_timeout = absolute_timeout
        yield PromptResponse.model_validate({"stopReason": "end_turn"})

    def close(self) -> None:
        pass


def _manager_with(client: _FakeServeClient) -> KubernetesSandboxManager:
    manager: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    manager._init_serve_state()

    def build_client(*_: Any, **__: Any) -> _FakeServeClient:
        return client

    manager._build_serve_client = build_client  # type: ignore[method-assign]
    return manager


def test_send_message_threads_turn_timeout_as_absolute_budget() -> None:
    client = _FakeServeClient()
    manager = _manager_with(client)

    events = list(
        manager.send_message(uuid4(), uuid4(), "hi", turn_timeout_seconds=1234.0)
    )

    assert client.captured_timeout == OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS
    assert client.captured_absolute_timeout == 1234.0
    assert any(isinstance(e, PromptResponse) for e in events)


def test_send_message_defaults_to_prompt_timeout() -> None:
    client = _FakeServeClient()
    manager = _manager_with(client)

    list(manager.send_message(uuid4(), uuid4(), "hi"))

    assert client.captured_timeout == OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS
    assert client.captured_absolute_timeout is None


def test_subagent_message_has_prompt_slot_hard_ceiling() -> None:
    client = _FakeServeClient()
    manager = _manager_with(client)

    list(manager.send_subagent_message(uuid4(), uuid4(), "ses_child", "hi"))

    assert client.captured_timeout == OPENCODE_PROMPT_INACTIVITY_TIMEOUT_SECONDS
    assert client.captured_absolute_timeout == PROMPT_SLOT_KEEP_ALIVE_MAX_SECONDS
