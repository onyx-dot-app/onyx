"""Interactive message API tests in the Craft k8s integration lane."""

from __future__ import annotations

import os
import time
from typing import cast
from uuid import UUID, uuid4

import pytest
from kubernetes import client

from onyx.configs.constants import MessageType
from onyx.server.features.build.interactive_turns.models import InteractiveTurnResponse
from onyx.server.features.build.sandbox.manager import (
    SandboxManager,
)
from onyx.server.features.build.session.models import (
    MessageInterruptResponse,
    MessageResponse,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client as http_client
from tests.integration.common_utils.managers.build_session import BuildSessionManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.tests.craft.k8s.k8s_fixtures import (
    cleanup_api_user_sandbox,
    kubernetes_runtime,
    register_suite_sandbox,
)

pytestmark = [
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
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    api_user = UserManager.create(name=f"craft-k8s-message-{uuid4().hex[:8]}")
    sandbox_id: UUID | None = None
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
        register_suite_sandbox(sandbox_id)

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
        cleanup_api_user_sandbox(k8s_manager, k8s_client, UUID(api_user.id), sandbox_id)


def test_interrupt_running_bash_turn_stops_work_and_allows_follow_up(
    k8s_manager: SandboxManager,
    k8s_client: client.CoreV1Api,
) -> None:
    nonce = uuid4().hex
    api_user = UserManager.create(name=f"craft-k8s-cancel-{nonce[:8]}")
    sandbox_id: UUID | None = None
    try:
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
        register_suite_sandbox(sandbox_id)
        runtime = kubernetes_runtime(k8s_manager)
        started_name = f"cancel-started-{nonce}.txt"
        final_name = f"cancel-finished-{nonce}.txt"
        follow_up_name = f"cancel-follow-up-{nonce}.txt"

        def get_turn(turn_id: str) -> InteractiveTurnResponse:
            response = http_client.get(
                f"{API_SERVER_URL}/build/sessions/{session_id}/turns/{turn_id}",
                headers=api_user.headers,
                cookies=api_user.cookies,
            )
            response.raise_for_status()
            result = InteractiveTurnResponse.model_validate(response.json())
            assert result.turn_id == turn_id
            assert result.session_id == str(session_id)
            return result

        def output_names() -> set[str]:
            return {
                entry.name
                for entry in BuildSessionManager.list_files(
                    api_user, session_id, "outputs"
                ).entries
            }

        command = (
            "mkdir -p outputs; sleep 120 & work_pid=$!; "
            f"printf '%s %s %s' \"$$\" \"$work_pid\" '{nonce}' "
            f"> outputs/{started_name}.tmp; "
            f"mv outputs/{started_name}.tmp outputs/{started_name}; "
            'wait "$work_pid"; '
            f"printf '%s' '{nonce}' > outputs/{final_name}"
        )
        turn = BuildSessionManager.start_turn(
            api_user,
            session_id,
            "Run this exact command in one foreground Bash tool call with a "
            "180000 millisecond timeout. Do not shorten the sleep, create the "
            "files separately, or background the tool call. It is a cancellation "
            f"check.\n{command}",
            client_request_id=f"req-{uuid4()}",
        )
        deadline = time.monotonic() + 180
        while started_name not in output_names():
            current = get_turn(turn.turn_id)
            assert current.status not in _TERMINAL_TURN_STATUSES, current
            assert time.monotonic() < deadline, (
                f"Bash did not create its start marker; last turn={current!r}"
            )
            time.sleep(1)

        started = (
            BuildSessionManager.download_artifact(
                api_user, session_id, f"outputs/{started_name}"
            )
            .decode()
            .split()
        )
        assert len(started) == 3 and started[2] == nonce
        work_pids = {int(value) for value in started[:2]}
        assert len(work_pids) == 2 and min(work_pids) > 1

        def living_work_pids() -> set[int]:
            result = runtime.helper(
                sandbox_id,
                "run",
                {
                    "argv": [
                        "python3",
                        "-c",
                        "import os,sys\n"
                        "for value in sys.argv[1:]:\n"
                        " try: os.kill(int(value), 0)\n"
                        " except ProcessLookupError: continue\n"
                        " print(value)\n",
                        *(str(pid) for pid in sorted(work_pids)),
                    ],
                    "timeout_seconds": 5,
                },
                timeout=15,
            )
            assert result.returncode == 0, result.stderr
            return {int(value) for value in result.stdout.split()}

        assert get_turn(turn.turn_id).status == "RUNNING"
        assert living_work_pids() == work_pids
        assert final_name not in output_names()
        response = http_client.post(
            f"{API_SERVER_URL}/build/sessions/{session_id}/interrupt",
            params={"turn_id": turn.turn_id},
            headers=api_user.headers,
            cookies=api_user.cookies,
        )
        response.raise_for_status()
        assert MessageInterruptResponse.model_validate(response.json()).interrupted

        deadline = time.monotonic() + 90
        while True:
            current = get_turn(turn.turn_id)
            remaining_pids = living_work_pids()
            assert final_name not in output_names(), (
                "Canceled Bash wrote its final file"
            )
            if current.status == "CANCELLED" and not remaining_pids:
                break
            assert current.status not in {"SUCCEEDED", "FAILED"}, current
            assert time.monotonic() < deadline, (
                f"Cancellation did not settle; turn={current!r}, "
                f"live work PIDs={remaining_pids!r}"
            )
            time.sleep(1)

        follow_up = BuildSessionManager.start_turn(
            api_user,
            session_id,
            "The prior task was canceled. Do not resume it or touch its files. "
            "Run exactly this Bash command, then finish your reply.\n"
            f"printf '%s' '{nonce}' > outputs/{follow_up_name}",
            client_request_id=f"req-{uuid4()}",
        )
        assert follow_up.turn_id != turn.turn_id
        deadline = time.monotonic() + 180
        while True:
            current = get_turn(follow_up.turn_id)
            names = output_names()
            assert final_name not in names, "Canceled Bash wrote its final file later"
            assert current.status not in {"FAILED", "CANCELLED"}, current
            if current.status == "SUCCEEDED" and follow_up_name in names:
                break
            assert time.monotonic() < deadline, (
                f"Follow-up did not finish with its output file; turn={current!r}"
            )
            time.sleep(1)
        assert (
            BuildSessionManager.download_artifact(
                api_user, session_id, f"outputs/{follow_up_name}"
            )
            == nonce.encode()
        )
        assert get_turn(turn.turn_id).status == "CANCELLED"
        assert living_work_pids() == set()
    finally:
        cleanup_api_user_sandbox(k8s_manager, k8s_client, UUID(api_user.id), sandbox_id)
