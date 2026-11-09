"""Skill-push fault-injection: one failing sandbox must not abort pushes to others."""

from __future__ import annotations

import logging
from collections.abc import Callable
from uuid import UUID, uuid4
from weakref import ReferenceType, ref

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import BuildSessionStatus, SandboxStatus, SessionOrigin
from onyx.db.models import BuildSession, Skill, User
from onyx.server.features.build.db.build_session import session_runtime_stale
from onyx.server.features.build.sandbox.models import (
    FatalWriteError,
    FileSet,
    PushResult,
)
from onyx.skills import push as skill_push
from onyx.skills.push import (
    UserSkillsPayload,
    compute_skill_runtime_hash,
    push_skills_for_users,
)
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user


@pytest.mark.parametrize("failure_stage", ["result", "build", "send"])
def test_one_failing_sandbox_does_not_abort_push_to_others(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    seeded_skill: Callable[..., Skill],
    failing_sandbox_manager: Callable[..., StubSandboxManager],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    failure_stage: str,
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
    scheduled_session = BuildSession(
        user_id=user_a.id,
        status=BuildSessionStatus.ACTIVE,
        origin=SessionOrigin.SCHEDULED,
        opencode_session_id="scheduled-opencode",
    )
    db_session.add_all(sessions.values())
    db_session.add_all([idle_session, scheduled_session])
    db_session.commit()

    stub = failing_sandbox_manager(
        fail_on={sandbox_b.id: FatalWriteError("Pod not found")}
    )

    monkeypatch.setattr(
        "onyx.skills.push.get_sandbox_manager",
        lambda: stub,
    )

    seeded_skill(
        name=f"partial-{uuid4().hex[:6]}",
        public=True,
        bundle_files={"SKILL.md": "p\n"},
    )

    monkeypatch.setattr(
        skill_push,
        "get_sandbox_user_map",
        lambda _ids, _session: {
            sandbox_a.id: user_a,
            sandbox_b.id: user_b,
            sandbox_c.id: user_c,
        },
    )
    build_payload = skill_push.build_user_skills_payload

    def build(user: User, session: Session) -> UserSkillsPayload:
        if failure_stage == "build" and user.id == user_b.id:
            raise ValueError("Unreadable saved credential")
        return build_payload(user, session)

    send_payload = stub.push_to_sandbox

    def send(*, sandbox_id: UUID, mount_path: str, files: FileSet) -> PushResult:
        if failure_stage == "send" and sandbox_id == sandbox_b.id:
            raise RuntimeError("Unexpected transport failure")
        return send_payload(sandbox_id=sandbox_id, mount_path=mount_path, files=files)

    monkeypatch.setattr(skill_push, "build_user_skills_payload", build)
    monkeypatch.setattr(stub, "push_to_sandbox", send)

    with caplog.at_level(logging.WARNING):
        push_skills_for_users({user_a.id, user_b.id, user_c.id}, db_session)

    assert stub.write_files_to_sandbox_count == (3 if failure_stage == "result" else 2)
    assert session_runtime_stale(sessions[user_a.id], sandbox_a)
    assert not session_runtime_stale(sessions[user_b.id], sandbox_b)
    assert not session_runtime_stale(sessions[user_c.id], sandbox_c)
    assert not session_runtime_stale(idle_session, sandbox_a)
    assert not session_runtime_stale(scheduled_session, sandbox_a)
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
    for sandbox in (sandbox_a, sandbox_b, sandbox_c):
        db_session.refresh(sandbox)
        assert sandbox.skills_hash is None
    for session, sandbox in (
        (sessions[user_a.id], sandbox_a),
        (sessions[user_b.id], sandbox_b),
        (sessions[user_c.id], sandbox_c),
    ):
        assert not session_runtime_stale(session, sandbox)


def test_connectable_app_change_pushes_and_hashes_self_heal(
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

    connectable_apps_sections = {
        unchanged_user.id: "",
        changed_user.id: "new apps",
    }

    # Seed the runtime hash exactly as push_skills_for_users computes it, so the
    # "unchanged" sandbox is genuinely up to date.
    unchanged_sandbox.skills_hash = compute_skill_runtime_hash(
        files_for(unchanged_user, db_session),
        "",
    )
    changed_sandbox.skills_hash = compute_skill_runtime_hash(
        files_for(changed_user, db_session),
        "old apps",
    )
    unchanged_session.skills_hash = unchanged_sandbox.skills_hash
    changed_session.skills_hash = changed_sandbox.skills_hash
    db_session.add_all([unchanged_session, changed_session])
    db_session.commit()

    stub = StubSandboxManager()
    stub.write_files_to_sandbox_silent = True
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: stub)
    monkeypatch.setattr(
        "onyx.skills.push.build_user_skills_payload",
        lambda user, session: UserSkillsPayload(
            files=files_for(user, session),
            omissions=(),
            connectable_apps_section=connectable_apps_sections[user.id],
        ),
    )

    push_skills_for_users({unchanged_user.id, changed_user.id}, db_session)

    db_session.refresh(unchanged_sandbox)
    db_session.refresh(changed_sandbox)
    assert stub.write_files_to_sandbox_count == 1
    assert stub.last_write_files_to_sandbox_payload is not None
    assert stub.last_write_files_to_sandbox_payload["sandbox_id"] == changed_sandbox.id
    assert not session_runtime_stale(unchanged_session, unchanged_sandbox)
    assert session_runtime_stale(changed_session, changed_sandbox)

    connectable_apps_sections[changed_user.id] = "old apps"
    push_skills_for_users({changed_user.id}, db_session)

    db_session.refresh(changed_sandbox)
    assert stub.write_files_to_sandbox_count == 2
    assert not session_runtime_stale(changed_session, changed_sandbox)


@pytest.mark.parametrize("unchanged", [False, True])
def test_push_releases_each_payload_before_building_the_next(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    unchanged: bool,
) -> None:
    class TrackedFiles(dict[str, bytes]):
        pass

    users = [make_user(db_session) for _ in range(3)]
    sandboxes = [
        make_sandbox(db_session, user, status=SandboxStatus.RUNNING) for user in users
    ]
    if unchanged:
        for sandbox in sandboxes:
            sandbox.skills_hash = compute_skill_runtime_hash(
                {"demo/SKILL.md": b"demo"}, ""
            )
    db_session.commit()
    payload_refs: list[ReferenceType[object]] = []
    live_at_build: list[int] = []
    sent: list[UUID] = []

    def build(_user: User, _session: Session) -> UserSkillsPayload:
        live_at_build.append(sum(reference() is not None for reference in payload_refs))
        files = TrackedFiles({"demo/SKILL.md": b"demo"})
        payload = UserSkillsPayload(
            files=files, omissions=(), connectable_apps_section=""
        )
        # Track the container itself, not only an alias to its files.
        payload_refs.extend([ref(files), ref(payload)])
        return payload

    def send(
        *, sandbox_id: UUID, mount_path: str, files: FileSet, timeout_s: float = 30.0
    ) -> PushResult:
        assert mount_path == "/workspace/managed/skills"
        assert timeout_s > 0
        assert files == {"demo/SKILL.md": b"demo"}
        sent.append(sandbox_id)
        return PushResult(targets=1, succeeded=1, failures=[])

    manager = StubSandboxManager()
    monkeypatch.setattr(manager, "push_to_sandbox", send)
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: manager)
    monkeypatch.setattr("onyx.skills.push.build_user_skills_payload", build)
    push_skills_for_users({user.id for user in users}, db_session)

    assert live_at_build == [0, 0, 0]
    assert all(reference() is None for reference in payload_refs)
    assert set(sent) == (set() if unchanged else {sandbox.id for sandbox in sandboxes})
    for sandbox in sandboxes:
        db_session.refresh(sandbox)
        assert sandbox.skills_hash == compute_skill_runtime_hash(
            {"demo/SKILL.md": b"demo"}, ""
        )
