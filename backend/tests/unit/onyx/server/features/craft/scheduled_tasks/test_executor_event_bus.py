"""A scheduled run must release its session's ``PodEventBus`` when it ends.

Scheduled sessions are never deleted and the sandbox outlives the run, so
neither ``cleanup_session_workspace`` nor ``terminate`` closes the bus. If the
executor does not close it, the scheduled-tasks worker keeps one ``/event``
stream to opencode serve per run until the worker restarts.
"""

from __future__ import annotations

from collections.abc import Generator, Iterator
from contextlib import nullcontext
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest

from onyx.db.enums import ScheduledTaskRunStatus
from onyx.server.features.build.sandbox import serve_transport
from onyx.server.features.build.sandbox.event_schema import (
    TURN_ERROR_CODE_SESSION,
    Error,
    PromptResponse,
)
from onyx.server.features.build.sandbox.kubernetes.kubernetes_sandbox_manager import (
    KubernetesSandboxManager,
)
from onyx.server.features.build.sandbox.serve_transport import (
    PromptSlot,
    ServeConnectionInfo,
)
from onyx.server.features.build.scheduled_tasks import executor
from onyx.server.features.build.session.manager import SessionManager


@pytest.fixture
def mgr(
    monkeypatch: pytest.MonkeyPatch,
) -> Generator[KubernetesSandboxManager, None, None]:
    """Manager with only the serve-transport state, so buses can be created
    without a cluster or a database."""
    monkeypatch.setattr(
        serve_transport,
        "get_session_with_current_tenant",
        lambda: nullcontext(MagicMock()),
    )
    monkeypatch.setattr(serve_transport, "get_sandbox_by_id", lambda *_: None)

    m: KubernetesSandboxManager = object.__new__(KubernetesSandboxManager)
    m._init_serve_state()
    m._load_serve_connection_info = (  # ty: ignore[invalid-assignment]
        lambda sandbox_id: ServeConnectionInfo(
            base_url=f"http://{sandbox_id}.invalid:4096",
            password=None,
        )
    )

    try:
        yield m
    finally:
        with m._event_buses_lock:
            buses = list(m._event_buses.values())
            m._event_buses.clear()
        for bus in buses:
            bus.close()


def _ok() -> Iterator[Any]:
    yield PromptResponse(stop_reason="end_turn")


def _error_event() -> Iterator[Any]:
    yield Error.model_validate({"code": TURN_ERROR_CODE_SESSION, "message": "boom"})


def _raises() -> Iterator[Any]:
    raise RuntimeError("stream broke")
    yield  # pragma: no cover


@pytest.mark.parametrize(
    ("events", "expected_status"),
    [
        (_ok, ScheduledTaskRunStatus.SUCCEEDED),
        (_error_event, ScheduledTaskRunStatus.FAILED),
        (_raises, ScheduledTaskRunStatus.FAILED),
    ],
    ids=["succeeded", "error_event", "exception"],
)
def test_scheduled_run_closes_its_session_event_bus(
    mgr: KubernetesSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
    events: Any,
    expected_status: ScheduledTaskRunStatus,
) -> None:
    sandbox_id = uuid4()
    session_id = uuid4()
    directory = mgr._session_directory(session_id)
    opened: list[Any] = []

    def yield_sandbox_events(
        run_sandbox_id: UUID,
        run_session_id: UUID,
        *_args: Any,
        **_kwargs: Any,
    ) -> Iterator[Any]:
        # The real send path opens the session's bus before streaming.
        opened.append(
            mgr._get_or_create_event_bus(
                run_sandbox_id, mgr._session_directory(run_session_id)
            )
        )
        yield from events()

    session_manager: SessionManager = object.__new__(SessionManager)
    session_manager._sandbox_manager = mgr
    monkeypatch.setattr(
        session_manager,
        "create_session",
        lambda **_: MagicMock(id=session_id),
    )
    monkeypatch.setattr(
        session_manager,
        "prompt_slot",
        lambda *_: nullcontext(PromptSlot(acquired=True)),
    )
    monkeypatch.setattr(session_manager, "yield_sandbox_events", yield_sandbox_events)
    monkeypatch.setattr(session_manager, "stamp_turn_deadline", MagicMock())
    monkeypatch.setattr(session_manager, "clear_turn_deadline", MagicMock())
    monkeypatch.setattr(session_manager, "persist_sandbox_event", MagicMock())
    monkeypatch.setattr(session_manager, "finalize_persist", MagicMock())

    mark_run_status = MagicMock()
    monkeypatch.setattr(executor, "SessionManager", lambda _db: session_manager)
    monkeypatch.setattr(
        executor, "get_session_with_current_tenant", lambda: nullcontext(MagicMock())
    )
    monkeypatch.setattr(executor, "session_creation_lock", lambda _: nullcontext())
    monkeypatch.setattr(executor, "create_message", MagicMock())
    monkeypatch.setattr(executor, "get_session_messages", lambda **_: [])
    monkeypatch.setattr(executor, "mark_run_status", mark_run_status)
    monkeypatch.setattr(executor, "update_sandbox_heartbeat", MagicMock())
    monkeypatch.setattr(executor, "_notify", MagicMock())
    monkeypatch.setattr(executor, "get_sandbox_manager", lambda: mgr)
    monkeypatch.setattr(executor, "capture_turn_outputs", lambda *_: None)
    monkeypatch.setattr(executor, "persist_turn_outputs", MagicMock())

    executor._drive_agent(
        run_id=uuid4(),
        task_id=uuid4(),
        task_user_id=uuid4(),
        task_name="nightly-report",
        task_prompt="Summarise yesterday's events",
        sandbox_id=sandbox_id,
        budget_seconds=60,
    )

    assert mark_run_status.call_args.kwargs["status"] == expected_status
    assert len(opened) == 1
    assert opened[0].closed
    with mgr._event_buses_lock:
        assert (sandbox_id, directory) not in mgr._event_buses
