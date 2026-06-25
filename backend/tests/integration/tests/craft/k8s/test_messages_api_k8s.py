"""Interactive message API tests in the Craft k8s integration lane."""

from __future__ import annotations

import os
import time
from contextlib import suppress
from typing import cast
from uuid import UUID
from uuid import uuid4

import pytest
from kubernetes import client

from onyx.configs.constants import MessageType
from onyx.server.features.build.configs import SANDBOX_BACKEND
from onyx.server.features.build.configs import SandboxBackend
from onyx.server.features.build.interactive_turns.models import InteractiveTurnResponse
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.session.models import MessageResponse
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.tests.craft.k8s.k8s_fixtures import cleanup_api_user_sandbox_rows
from tests.integration.tests.craft.k8s.k8s_fixtures import wait_for_pod_deletion

pytestmark = [
    pytest.mark.skipif(
        SANDBOX_BACKEND != SandboxBackend.KUBERNETES,
        reason="K8s tests require SANDBOX_BACKEND=kubernetes; run in the dedicated K8s CI job.",
    ),
    pytest.mark.skipif(
        not os.environ.get("OPENAI_API_KEY"),
        reason="message-turn k8s test needs a real OPENAI_API_KEY",
    ),
]

_TERMINAL_TURN_STATUSES = {"SUCCEEDED", "FAILED", "CANCELLED"}


def _assistant_text(messages: list[MessageResponse]) -> str:
    chunks: list[str] = []
    for message in messages:
        if message.type != MessageType.ASSISTANT:
            continue
        metadata = message.message_metadata
        if metadata.get("type") != "agent_message":
            continue
        content = metadata.get("content")
        if isinstance(content, dict):
            text = cast(dict[str, object], content).get("text")
            if isinstance(text, str):
                chunks.append(text)
    return "".join(chunks)


def _turn_status(turn: InteractiveTurnResponse | None) -> str | None:
    if turn is None:
        return None
    return turn.status


def test_send_message_api_runs_real_celery_turn(
    k8s_manager: KubernetesSandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    api_user = UserManager.create(name=f"craft-k8s-message-{uuid4().hex[:8]}")
    sandbox_id: UUID | None = None
    pod_name: str | None = None
    try:
        # Pin the cheap model; the Build path defaults to gpt-5.5 otherwise.
        session = BuildSessionManager.create(
            api_user,
            headless=True,
            llm_provider_type="openai",
            llm_model_name="gpt-5-mini",
        )
        session_id = UUID(session.id)
        sandbox = session.sandbox
        assert sandbox is not None
        sandbox_id = UUID(sandbox.id)
        pod_name = k8s_manager._get_pod_name(sandbox_id)

        turn = BuildSessionManager.start_turn(
            api_user,
            session_id,
            "Reply with a short greeting.",
            client_request_id=f"req-{uuid4()}",
        )
        assert turn.session_id == str(session_id)
        assert turn.status in {"QUEUED", "RUNNING"}

        deadline = time.monotonic() + 180
        last_messages: list[MessageResponse] = []
        last_turn: InteractiveTurnResponse | None = None
        saw_assistant_text = False
        while time.monotonic() < deadline:
            last_messages = BuildSessionManager.list_messages(api_user, session_id)
            text = _assistant_text(last_messages)
            if text.strip():
                assert "Reply with a short greeting" not in text
                saw_assistant_text = True
            last_turn = BuildSessionManager.get_active_turn(api_user, session_id)
            status = _turn_status(last_turn)
            if status in {"FAILED", "CANCELLED"}:
                raise AssertionError(
                    f"Craft turn ended with status={status}: {last_turn!r}; "
                    f"messages={last_messages!r}"
                )
            if saw_assistant_text and (
                last_turn is None or status in _TERMINAL_TURN_STATUSES
            ):
                return
            time.sleep(3)

        raise AssertionError(
            "Timed out waiting for an assistant message from the deployed "
            f"Craft turn. Last turn: {last_turn!r}. "
            f"Last messages: {last_messages!r}"
        )
    finally:
        if sandbox_id is not None:
            with suppress(Exception):
                k8s_manager.terminate(sandbox_id)
            # Wait for pod deletion before removing DB rows: the egress proxy resolves
            # sandbox identity via Sandbox.user_id, so deleting the row while the pod
            # is still alive would leave an unattributable orphaned pod.
            if pod_name is not None:
                with suppress(Exception):
                    wait_for_pod_deletion(k8s_client, pod_name)
        cleanup_api_user_sandbox_rows(UUID(api_user.id))
