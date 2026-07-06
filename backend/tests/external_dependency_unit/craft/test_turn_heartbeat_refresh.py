"""``yield_sandbox_events`` must refresh ``sandbox.last_heartbeat`` — the idle
reaper's only activity signal — at turn start and periodically while events flow."""

from __future__ import annotations

import datetime
from uuid import UUID
from uuid import uuid4

import pytest
from acp.schema import AgentMessageChunk
from acp.schema import PromptResponse
from acp.schema import TextContentBlock
from sqlalchemy import update
from sqlalchemy.orm import Session

from onyx.db.models import Sandbox
from onyx.db.models import User
from onyx.server.features.build.session import streaming as streaming_module
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_user


def _agent_message_chunk(text: str) -> AgentMessageChunk:
    return AgentMessageChunk(
        content=TextContentBlock(type="text", text=text),
        session_update="agent_message_chunk",
    )


def _prompt_response() -> PromptResponse:
    return PromptResponse(stop_reason="end_turn")


def test_turn_start_refreshes_heartbeat(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub_sandbox_manager: StubSandboxManager,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)
    db_session.execute(
        update(Sandbox)
        .where(Sandbox.id == sandbox.id)
        .values(
            last_heartbeat=datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=2)
        )
    )
    db_session.commit()

    stub_sandbox_manager.send_message_events = [
        _agent_message_chunk("hello"),
        _prompt_response(),
    ]

    list(
        streaming_module.yield_sandbox_events(
            db_session,
            stub_sandbox_manager,
            sandbox.id,
            uuid4(),
            "hi",
            opencode_session_id="oc-test",
            agent_provider=None,
            agent_model=None,
        )
    )

    db_session.expire_all()
    refreshed = db_session.get(Sandbox, sandbox.id)
    assert refreshed is not None
    assert refreshed.last_heartbeat is not None
    age = datetime.datetime.now(datetime.timezone.utc) - refreshed.last_heartbeat
    assert age < datetime.timedelta(seconds=60)


def test_heartbeat_refreshed_per_event_when_interval_elapsed(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)

    recorded_calls: list[UUID] = []

    def _record_heartbeat(_db_session: Session, sandbox_id: UUID) -> Sandbox:
        recorded_calls.append(sandbox_id)
        return sandbox

    monkeypatch.setattr(streaming_module, "update_sandbox_heartbeat", _record_heartbeat)
    monkeypatch.setattr(
        streaming_module, "SANDBOX_HEARTBEAT_REFRESH_INTERVAL_SECONDS", 0.0
    )

    stub_sandbox_manager.send_message_events = [
        _agent_message_chunk("one"),
        _agent_message_chunk("two"),
        _prompt_response(),
    ]

    list(
        streaming_module.yield_sandbox_events(
            db_session,
            stub_sandbox_manager,
            sandbox.id,
            uuid4(),
            "hi",
            opencode_session_id="oc-test",
            agent_provider=None,
            agent_model=None,
        )
    )

    assert len(recorded_calls) == 1 + 3
    assert all(sandbox_id == sandbox.id for sandbox_id in recorded_calls)


def test_heartbeat_not_refreshed_per_event_within_default_interval(
    db_session: Session,
    test_user: User,  # noqa: ARG001
    stub_sandbox_manager: StubSandboxManager,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user)

    recorded_calls: list[UUID] = []

    def _record_heartbeat(_db_session: Session, sandbox_id: UUID) -> Sandbox:
        recorded_calls.append(sandbox_id)
        return sandbox

    monkeypatch.setattr(streaming_module, "update_sandbox_heartbeat", _record_heartbeat)

    stub_sandbox_manager.send_message_events = [
        _agent_message_chunk("one"),
        _agent_message_chunk("two"),
        _prompt_response(),
    ]

    list(
        streaming_module.yield_sandbox_events(
            db_session,
            stub_sandbox_manager,
            sandbox.id,
            uuid4(),
            "hi",
            opencode_session_id="oc-test",
            agent_provider=None,
            agent_model=None,
        )
    )

    assert len(recorded_calls) == 1
