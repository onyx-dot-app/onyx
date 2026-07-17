"""Skill-push fault-injection: one failing sandbox must not abort pushes to others."""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import BuildSessionStatus
from onyx.db.enums import SandboxStatus
from onyx.db.models import BuildSession
from onyx.db.models import Skill
from onyx.db.models import User
from onyx.server.features.build.sandbox.models import FatalWriteError
from onyx.skills.push import compute_skills_hash
from onyx.skills.push import push_skills_for_users
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox
from tests.external_dependency_unit.craft.db_helpers import make_user


def test_one_failing_sandbox_does_not_abort_push_to_others(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    seeded_skill: Callable[..., Skill],
    failing_sandbox_manager: Callable[..., StubSandboxManager],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    user_a = make_user(db_session)
    user_b = make_user(db_session)
    user_c = make_user(db_session)
    sandbox_a = make_sandbox(db_session, user_a, status=SandboxStatus.RUNNING)
    sandbox_b = make_sandbox(db_session, user_b, status=SandboxStatus.RUNNING)
    sandbox_c = make_sandbox(db_session, user_c, status=SandboxStatus.RUNNING)
    sessions = {
        user.id: BuildSession(
            user_id=user.id,
            status=BuildSessionStatus.ACTIVE,
            opencode_session_id=(
                None if user.id == user_c.id else f"opencode-{user.id}"
            ),
        )
        for user in (user_a, user_b, user_c)
    }
    idle_session = BuildSession(
        user_id=user_a.id,
        status=BuildSessionStatus.IDLE,
        opencode_session_id="stopped-opencode",
    )
    db_session.add_all(sessions.values())
    db_session.add(idle_session)
    db_session.commit()

    stub = failing_sandbox_manager(
        fail_on={sandbox_b.id: FatalWriteError("Pod not found")}
    )

    monkeypatch.setattr(
        "onyx.skills.push.get_sandbox_manager",
        lambda: stub,
    )

    seeded_skill(
        slug=f"partial-{uuid4().hex[:6]}",
        public=True,
        bundle_files={"SKILL.md": "p\n"},
    )

    with caplog.at_level(logging.WARNING):
        push_skills_for_users({user_a.id, user_b.id, user_c.id}, db_session)

    assert stub.write_files_to_sandbox_count == 3
    for session in sessions.values():
        db_session.refresh(session)
    assert sessions[user_a.id].skills_stale is True
    assert sessions[user_b.id].skills_stale is False
    assert sessions[user_c.id].skills_stale is False
    assert idle_session.skills_stale is False
    assert sandbox_a.skills_hash is not None
    assert sandbox_b.skills_hash is None
    assert sandbox_c.skills_hash is not None

    warning_messages = [
        r.getMessage() for r in caplog.records if r.levelno == logging.WARNING
    ]
    assert any("1/3 targets failed" in m for m in warning_messages), (
        f"Expected a '1/3 targets failed' partial-failure warning; got: {warning_messages!r}"
    )

    db_session.rollback()
    for session in sessions.values():
        db_session.refresh(session)
        assert session.skills_stale is False
    for sandbox in (sandbox_a, sandbox_b, sandbox_c):
        db_session.refresh(sandbox)
        assert sandbox.skills_hash is None


def test_unchanged_skill_files_are_not_pushed_or_marked_stale(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unchanged_user = make_user(db_session)
    changed_user = make_user(db_session)
    unchanged_sandbox = make_sandbox(
        db_session, unchanged_user, status=SandboxStatus.RUNNING
    )
    changed_sandbox = make_sandbox(
        db_session, changed_user, status=SandboxStatus.RUNNING
    )
    unchanged_session = BuildSession(
        user_id=unchanged_user.id,
        status=BuildSessionStatus.ACTIVE,
        opencode_session_id="unchanged-runtime",
    )
    changed_session = BuildSession(
        user_id=changed_user.id,
        status=BuildSessionStatus.ACTIVE,
        opencode_session_id="changed-runtime",
    )

    def files_for(user: User, _db_session: Session) -> dict[str, bytes]:
        return {f"{user.id}/SKILL.md": b"content"}

    unchanged_sandbox.skills_hash = compute_skills_hash(
        files_for(unchanged_user, db_session)
    )
    changed_sandbox.skills_hash = "outdated"
    db_session.add_all([unchanged_session, changed_session])
    db_session.commit()

    stub = StubSandboxManager()
    stub.write_files_to_sandbox_silent = True
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: stub)
    monkeypatch.setattr("onyx.skills.push.build_skills_fileset_for_user", files_for)

    push_skills_for_users({unchanged_user.id, changed_user.id}, db_session)

    db_session.refresh(unchanged_session)
    db_session.refresh(changed_session)
    assert stub.write_files_to_sandbox_count == 1
    assert stub.last_write_files_to_sandbox_payload is not None
    assert stub.last_write_files_to_sandbox_payload["sandbox_id"] == changed_sandbox.id
    assert unchanged_session.skills_stale is False
    assert changed_session.skills_stale is True
