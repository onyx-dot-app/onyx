"""Skill runtime omissions: recorded with delivered content, read by the owner."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID, uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.configs.constants import MessageType
from onyx.db.enums import BuildSessionStatus, SandboxStatus, SessionOrigin
from onyx.db.models import BuildMessage, BuildSession, Sandbox, User
from onyx.db.skill_runtime_models import SkillRuntimeLimit, SkillRuntimeOmission
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.build.sandbox.models import (
    FatalWriteError,
    FileSet,
    PushResult,
)
from onyx.server.features.build.sandbox.util.mcp_config import (
    craft_mcp_fingerprint,
    resolve_craft_mcp_servers,
)
from onyx.server.features.build.session.api import (
    get_session_details,
    list_sessions,
    reload_session_skills,
)
from onyx.server.features.build.session.models import SkillRuntimeNoticeResponse
from onyx.server.features.build.session.sandbox_lifecycle import (
    ManagedContentPayload,
    push_managed_skills,
    record_managed_content_hashes__no_commit,
)
from onyx.skills.push import (
    SKILL_RUNTIME_MAX_BYTES,
    SKILL_RUNTIME_MAX_FILES,
    UserSkillsPayload,
    compute_skill_runtime_hash,
    push_skills_for_users,
)
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import make_sandbox, make_user

FILES: FileSet = {"kept/SKILL.md": b"kept"}


def _omission(
    name: str, limit: SkillRuntimeLimit = SkillRuntimeLimit.BYTES
) -> SkillRuntimeOmission:
    return SkillRuntimeOmission(
        skill_id=uuid4(),
        name=name,
        charged_bytes=950 * 1024 * 1024,
        file_count=12,
        failed_limit=limit,
    )


class _Push:
    """Serve one payload per user and count the files sent to sandboxes."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self.files: FileSet = FILES
        self.omissions: tuple[SkillRuntimeOmission, ...] = ()
        self.fail = False
        self.sent: list[UUID] = []
        manager = StubSandboxManager()
        monkeypatch.setattr(manager, "push_to_sandbox", self._send)
        monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: manager)
        monkeypatch.setattr("onyx.skills.push.build_user_skills_payload", self._payload)

    def _payload(self, _user: User, _db_session: Session) -> UserSkillsPayload:
        return UserSkillsPayload(
            files=self.files,
            omissions=self.omissions,
            connectable_apps_section="",
        )

    def _send(
        self,
        *,
        sandbox_id: UUID,
        mount_path: str,  # noqa: ARG002
        files: FileSet,  # noqa: ARG002
        timeout_s: float = 30.0,  # noqa: ARG002
    ) -> PushResult:
        self.sent.append(sandbox_id)
        if self.fail:
            raise FatalWriteError("Pod not found")
        return PushResult(targets=1, succeeded=1, failures=[])


def _stored(db_session: Session, sandbox: Sandbox) -> tuple[str | None, list]:
    db_session.refresh(sandbox)
    return sandbox.skills_hash, sandbox.skill_runtime_omissions


# =============================================================================
# Skill push
# =============================================================================


def test_successful_push_records_omissions_and_failed_push_keeps_them(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
    db_session.commit()
    push = _Push(monkeypatch)
    delivered = _omission("too-large")
    push.omissions = (delivered,)

    push_skills_for_users({user.id}, db_session)

    delivered_hash = compute_skill_runtime_hash(FILES, "")
    assert push.sent == [sandbox.id]
    assert _stored(db_session, sandbox) == (delivered_hash, [delivered])

    push.files = {"changed/SKILL.md": b"changed"}
    push.omissions = (_omission("never-delivered", SkillRuntimeLimit.FILES),)
    push.fail = True
    push_skills_for_users({user.id}, db_session)

    assert push.sent == [sandbox.id, sandbox.id]
    assert _stored(db_session, sandbox) == (delivered_hash, [delivered])


def test_unchanged_files_update_and_clear_omissions_without_a_push(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
    sandbox.skills_hash = compute_skill_runtime_hash(FILES, "")
    db_session.commit()
    push = _Push(monkeypatch)
    # A new oversized Skill leaves the delivered files unchanged.
    first = _omission("first-large")
    second = _omission("second-large")
    push.omissions = (first, second)

    push_skills_for_users({user.id}, db_session)

    assert push.sent == []
    assert _stored(db_session, sandbox) == (sandbox.skills_hash, [first, second])

    push.omissions = ()
    push_skills_for_users({user.id}, db_session)

    assert push.sent == []
    assert _stored(db_session, sandbox) == (sandbox.skills_hash, [])


def test_failed_push_after_no_delivery_records_nothing(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(db_session)
    sandbox = make_sandbox(db_session, user, status=SandboxStatus.RUNNING)
    db_session.commit()
    push = _Push(monkeypatch)
    push.omissions = (_omission("too-large"),)
    push.fail = True

    push_skills_for_users({user.id}, db_session)

    assert push.sent == [sandbox.id]
    assert _stored(db_session, sandbox) == (None, [])


# =============================================================================
# Session start
# =============================================================================


@pytest.mark.parametrize("hydrated", [True, False])
def test_session_start_records_omissions_only_with_delivered_content(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    stub_sandbox_manager: StubSandboxManager,
    hydrated: bool,
) -> None:
    sandbox_row = sandbox(user=test_user, status=SandboxStatus.RUNNING)
    previous = _omission("previous")
    sandbox_row.skills_hash = "previous"
    sandbox_row.skill_runtime_omissions = [previous]
    db_session.commit()
    omission = _omission("not-loaded")
    payload = ManagedContentPayload(
        connectable_apps_section="",
        skills_files=FILES,
        skill_omissions=(omission,),
        skills_hash=compute_skill_runtime_hash(FILES, ""),
        mcp_fingerprint=craft_mcp_fingerprint(
            resolve_craft_mcp_servers(db_session, test_user)
        ),
    )
    db_session.commit()
    stub_sandbox_manager.write_files_to_sandbox_silent = True
    if not hydrated:
        stub_sandbox_manager.write_files_to_sandbox_raises_for = {
            sandbox_row.id: FatalWriteError("Pod not found")
        }

    skills_hydrated = push_managed_skills(stub_sandbox_manager, sandbox_row.id, payload)
    record_managed_content_hashes__no_commit(
        db_session, sandbox_row.id, payload, skills_hydrated
    )
    db_session.commit()

    assert skills_hydrated is hydrated
    assert _stored(db_session, sandbox_row) == (
        (payload.skills_hash, [omission]) if hydrated else ("previous", [previous])
    )


# =============================================================================
# Session responses
# =============================================================================


@pytest.mark.usefixtures("session_manager_with_stub")
def test_owner_session_responses_carry_the_runtime_notice(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
) -> None:
    sandbox_row = sandbox(user=test_user, status=SandboxStatus.SLEEPING)
    omission = _omission("too-large")
    sandbox_row.skills_hash = "delivered"
    sandbox_row.skill_runtime_omissions = [omission]
    session_row = BuildSession(user_id=test_user.id, status=BuildSessionStatus.IDLE)
    db_session.add(session_row)
    db_session.flush()
    # The session list shows only sessions with a message.
    db_session.add(
        BuildMessage(
            session_id=session_row.id,
            turn_index=0,
            type=MessageType.USER,
            message_metadata={
                "type": "user_message",
                "content": {"type": "text", "text": "hi"},
            },
        )
    )
    db_session.commit()
    expected = SkillRuntimeNoticeResponse(
        max_bytes=SKILL_RUNTIME_MAX_BYTES,
        max_files=SKILL_RUNTIME_MAX_FILES,
        omissions=[omission],
    )

    details = get_session_details(session_row.id, test_user, db_session)
    listed = list_sessions(test_user, db_session)
    reloaded = reload_session_skills(session_row.id, test_user, db_session)

    assert details.skill_runtime_notice == expected
    assert [s.skill_runtime_notice for s in listed.sessions] == [expected]
    assert reloaded.skill_runtime_notice == expected
    assert details.model_dump(mode="json")["skill_runtime_notice"] == {
        "max_bytes": 900 * 1024 * 1024,
        "max_files": 10_000,
        "max_directories": 10_000,
        "max_path_bytes": 4021,
        "max_path_component_bytes": 255,
        "omissions": [
            {
                "skill_id": str(omission.skill_id),
                "name": "too-large",
                "charged_bytes": omission.charged_bytes,
                "file_count": 12,
                "failed_limit": "bytes",
            }
        ],
    }

    sandbox_row.skill_runtime_omissions = []
    db_session.commit()
    assert (
        get_session_details(session_row.id, test_user, db_session).skill_runtime_notice
        is None
    )


@pytest.mark.usefixtures("session_manager_with_stub")
def test_runtime_notice_never_reaches_another_user(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
) -> None:
    owner_sandbox = sandbox(user=test_user, status=SandboxStatus.SLEEPING)
    owner_sandbox.skills_hash = "delivered"
    owner_sandbox.skill_runtime_omissions = [_omission("private-skill")]
    owner_session = BuildSession(user_id=test_user.id, status=BuildSessionStatus.IDLE)
    db_session.add(owner_session)
    other = make_user(db_session)
    db_session.commit()

    with pytest.raises(HTTPException):
        get_session_details(owner_session.id, other, db_session)
    with pytest.raises(OnyxError):
        reload_session_skills(owner_session.id, other, db_session)
    assert SkillRuntimeNoticeResponse.for_owner(other.id, owner_sandbox) is None
    assert SkillRuntimeNoticeResponse.for_owner(None, owner_sandbox) is None


@pytest.mark.parametrize("loaded_hash", [None, "older", "delivered"])
@pytest.mark.usefixtures("session_manager_with_stub")
def test_scheduled_notice_describes_only_its_loaded_skills(
    db_session: Session,
    test_user: User,
    sandbox: Callable[..., Sandbox],
    loaded_hash: str | None,
) -> None:
    sandbox_row = sandbox(user=test_user, status=SandboxStatus.SLEEPING)
    sandbox_row.skills_hash = "delivered"
    sandbox_row.skill_runtime_omissions = [_omission("too-large")]
    session_row = BuildSession(
        user_id=test_user.id,
        status=BuildSessionStatus.IDLE,
        origin=SessionOrigin.SCHEDULED,
        skills_hash=loaded_hash,
    )
    db_session.add(session_row)
    db_session.commit()
    response = get_session_details(session_row.id, test_user, db_session)
    assert not response.skills_stale
    assert (response.skill_runtime_notice is not None) == (loaded_hash == "delivered")
