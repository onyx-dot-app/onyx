"""A group membership change that revokes a Skill must reach the pod before the
next admission, even when the push after the commit fails."""

import io
import zipfile
from collections.abc import Generator
from dataclasses import dataclass
from threading import Event, Lock, Thread, current_thread
from typing import Literal
from unittest.mock import MagicMock
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import delete, select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import fetch_user_group_member_ids
from ee.onyx.server.scim.api import (
    delete_group,
    register_scim_exception_handlers,
    replace_group,
    scim_router,
)
from ee.onyx.server.scim.auth import verify_scim_token
from ee.onyx.server.scim.models import ScimGroupMember, ScimGroupResource
from ee.onyx.server.scim.providers.base import get_default_provider
from ee.onyx.server.user_group import api as user_group_api
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session, get_session_with_current_tenant
from onyx.db.enums import BuildSessionStatus, SandboxStatus, SessionOrigin
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.models import (
    BuildSession,
    Sandbox,
    ScimToken,
    Skill__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.skill import list_runtime_skills_for_user
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.file_store.file_store import FileStore
from onyx.server.features.build.db.build_session import session_runtime_stale
from onyx.server.features.build.db.sandbox import (
    begin_provisioning_attempt__no_commit,
    mark_user_sandbox_skills_pending__no_commit,
)
from onyx.server.features.build.sandbox.models import (
    FatalWriteError,
    FileSet,
    SandboxInfo,
)
from onyx.server.features.build.session import streaming
from onyx.server.features.build.session.errors import StaleProvisioningAttemptError
from onyx.server.features.build.session.manager import SessionManager
from onyx.server.features.build.session.sandbox_lifecycle import (
    ProvisioningPolicy,
    ensure_sandbox_ready,
    sync_managed_content,
)
from onyx.server.features.build.session.session_ready import (
    ensure_session_ready,
    session_runtime_intact,
)
from onyx.skills import push
from onyx.skills.push import SKILLS_MOUNT_PATH
from tests.common.craft.stubs import StubSandboxManager
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_sandbox,
    make_skill,
    make_user,
    share_skill_with_group,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")

Route = Literal["admin_patch", "admin_delete", "scim_replace", "scim_delete"]


class RecordingSandboxManager(StubSandboxManager):
    """Records each Skill push and proves it runs after the membership commit."""

    def __init__(self, failing: set[UUID]) -> None:
        super().__init__()
        self.failing = failing
        self.skill_pushes: list[tuple[UUID, FileSet]] = []
        self._probe = Lock()
        self.regenerate_session_config_silent = True
        self.dispose_opencode_instance_silent = True
        self.health_check_returns = True
        self.session_workspace_exists_returns = True

    def write_files_to_sandbox(
        self, *, sandbox_id: UUID, mount_path: str, files: FileSet
    ) -> None:
        if mount_path != SKILLS_MOUNT_PATH:
            return
        # Parallel pushes share one probe so they do not see each other's lock.
        with self._probe, get_session_with_current_tenant() as other:
            # Raises if the caller still holds the membership lock.
            lock_group_membership(other, nowait=True)
            other.rollback()
            self.skill_pushes.append((sandbox_id, files))
        if sandbox_id in self.failing:
            raise FatalWriteError("pod unreachable")


@dataclass
class World:
    admin: User
    member: User
    stayer: User
    joiner: User
    group_id: int
    skill_name: str
    sandboxes: dict[UUID, Sandbox]
    session: BuildSession


@pytest.mark.parametrize("method", ["PUT", "PATCH", "DELETE"])
def test_scim_delivery_contention_returns_transient_error_and_allows_retry(
    db_session: Session,
    world: "World",
    monkeypatch: pytest.MonkeyPatch,
    method: str,
) -> None:
    """SCIM retries a rolled-back membership update after delivery releases its row."""
    token = ScimToken(
        name="delivery-contention",
        hashed_token=uuid4().hex,
        token_display="onyx_scim_****test",
        created_by_id=world.admin.id,
    )
    db_session.add(token)
    db_session.commit()
    manager = RecordingSandboxManager(set())
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)

    def route_session() -> Generator[Session, None, None]:
        with get_session_with_current_tenant() as session:
            yield session

    app = FastAPI()
    app.include_router(scim_router)
    register_onyx_exception_handlers(app)
    register_scim_exception_handlers(app)
    app.dependency_overrides[get_session] = route_session
    app.dependency_overrides[verify_scim_token] = lambda: token
    group = db_session.get(UserGroup, world.group_id)
    assert group is not None
    original_name = group.name
    old_hash = world.sandboxes[world.member.id].skills_hash
    payload: dict[str, object] | None = None
    if method == "PUT":
        payload = {
            "displayName": original_name + "-changed",
            "members": [{"value": str(world.stayer.id)}],
        }
    elif method == "PATCH":
        payload = {
            "schemas": ["urn:ietf:params:scim:api:messages:2.0:PatchOp"],
            "Operations": [
                {"op": "remove", "path": f'members[value eq "{world.member.id}"]'}
            ],
        }

    client = TestClient(app)
    path = f"/scim/v2/Groups/{world.group_id}"
    with get_session_with_current_tenant() as delivery:
        delivery.execute(
            select(Sandbox)
            .where(Sandbox.id == world.sandboxes[world.member.id].id)
            .with_for_update()
        ).scalar_one()
        response = client.request(method, path, json=payload)
        assert response.status_code == 503, response.text
        assert response.headers["content-type"] == "application/scim+json"
        assert response.headers["retry-after"] == "1"
        body = response.json()
        assert body["schemas"] == ["urn:ietf:params:scim:api:messages:2.0:Error"]
        assert body["status"] == "503"
        assert "Retry" in body["detail"]
        assert "error_code" not in body
        with get_session_with_current_tenant() as check:
            lock_group_membership(check, nowait=True)
            assert fetch_user_group_member_ids(check, world.group_id) == {
                world.member.id,
                world.stayer.id,
            }
            assert (
                check.scalar(
                    select(UserGroup.name).where(UserGroup.id == world.group_id)
                )
                == original_name
            )
            assert (
                check.scalar(
                    select(Sandbox.skills_hash).where(
                        Sandbox.id == world.sandboxes[world.member.id].id
                    )
                )
                == old_hash
            )
        assert manager.skill_pushes == []
        delivery.rollback()

    response = client.request(method, path, json=payload)
    assert response.status_code == (204 if method == "DELETE" else 200), response.text
    with get_session_with_current_tenant() as check:
        assert world.member.id not in fetch_user_group_member_ids(check, world.group_id)


@pytest.fixture
def world(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> Generator[World, None, None]:
    admin = make_user(db_session, is_admin=True)
    member, stayer, joiner = (
        make_user(db_session, standard_account=True) for _ in range(3)
    )
    group = make_group(db_session)
    group.is_up_to_date = True
    user_ids = [admin.id, member.id, stayer.id, joiner.id]
    try:
        yield _seed_world(db_session, monkeypatch, admin, member, stayer, joiner, group)
    finally:
        db_session.rollback()
        db_session.execute(
            delete(BuildSession).where(BuildSession.user_id.in_(user_ids))
        )
        db_session.execute(delete(Sandbox).where(Sandbox.user_id.in_(user_ids)))
        db_session.execute(delete(ScimToken).where(ScimToken.created_by_id == admin.id))
        db_session.execute(
            delete(Skill__UserGroup).where(Skill__UserGroup.user_group_id == group.id)
        )
        db_session.execute(
            delete(User__UserGroup).where(User__UserGroup.user_id.in_(user_ids))
        )
        db_session.execute(delete(UserGroup).where(UserGroup.id == group.id))
        db_session.execute(delete(User).where(User.__table__.c.id.in_(user_ids)))
        db_session.commit()


def _seed_world(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    admin: User,
    member: User,
    stayer: User,
    joiner: User,
    group: UserGroup,
) -> World:
    add_user_to_group(db_session, member, group)
    add_user_to_group(db_session, stayer, group)
    # The company default hides the Skill; only the group policy installs it.
    skill = make_skill(db_session, is_public=True)
    skill.installation_policy = Policy.AVAILABLE
    assert skill.current_version is not None
    skill.current_version.is_valid = True
    share_skill_with_group(
        db_session, skill, group
    ).installation_policy = Policy.REQUIRED
    sandboxes = {
        user.id: make_sandbox(db_session, user) for user in (member, stayer, joiner)
    }
    for user_id, sandbox in sandboxes.items():
        sandbox.skills_hash = f"delivered-{user_id.hex}"
    session = BuildSession(
        user_id=member.id,
        status=BuildSessionStatus.ACTIVE,
        opencode_session_id="opencode-live",
        skills_hash=sandboxes[member.id].skills_hash,
    )
    db_session.add(session)
    db_session.commit()
    assert skill.id in {
        row.id
        for row in list_runtime_skills_for_user(user=member, db_session=db_session)
    }

    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("SKILL.md", f"---\nname: {skill.name}\n---\n")
    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = lambda *_, **__: io.BytesIO(archive.getvalue())
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    # Deletion is finished later by the sync task, as in the default deployment.
    monkeypatch.setattr(user_group_api, "DISABLE_VECTOR_DB", False)

    return World(
        admin=admin,
        member=member,
        stayer=stayer,
        joiner=joiner,
        group_id=group.id,
        skill_name=skill.name,
        sandboxes=sandboxes,
        session=session,
    )


def _change_membership(db_session: Session, world: World, route: Route) -> None:
    """Drop ``member`` from the group; the replace routes also add ``joiner``."""
    path = f"/manage/admin/user-group/{world.group_id}"
    if route.startswith("admin"):
        app = FastAPI()
        app.include_router(user_group_api.router)
        register_onyx_exception_handlers(app)
        app.dependency_overrides[current_user] = lambda: world.admin
        app.dependency_overrides[get_session] = lambda: db_session
        client = TestClient(app)
        if route == "admin_patch":
            response = client.patch(
                path, json={"user_ids": [str(world.stayer.id), str(world.joiner.id)]}
            )
        else:
            response = client.delete(path)
        assert response.status_code == 200, response.text
        return

    token = ScimToken(
        name="revocation-test",
        hashed_token=uuid4().hex,
        token_display="onyx_scim_****test",
        created_by_id=world.admin.id,
    )
    db_session.add(token)
    db_session.commit()
    if route == "scim_replace":
        group = db_session.get(UserGroup, world.group_id)
        assert group is not None
        resource = ScimGroupResource(
            displayName=group.name,
            members=[
                ScimGroupMember(value=str(user.id))
                for user in (world.stayer, world.joiner)
            ],
        )
        replace_group(
            str(world.group_id), resource, token, get_default_provider(), db_session
        )
    else:
        delete_group(str(world.group_id), token, db_session)


@pytest.mark.parametrize(
    "route", ["admin_patch", "admin_delete", "scim_replace", "scim_delete"]
)
def test_failed_push_after_membership_commit_blocks_dispatch_until_delivery(
    db_session: Session,
    world: World,
    route: Route,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    member_sandbox = world.sandboxes[world.member.id]
    manager = RecordingSandboxManager(failing=set())
    for target in (
        "onyx.skills.push.get_sandbox_manager",
        "onyx.server.features.build.session.manager.get_sandbox_manager",
    ):
        monkeypatch.setattr(target, lambda: manager)
    manager.failing = {sandbox.id for sandbox in world.sandboxes.values()}
    replaces = route in ("admin_patch", "scim_replace")
    recipients = (
        {world.member.id, world.joiner.id}
        if replaces
        else {world.member.id, world.stayer.id}
    )

    _change_membership(db_session, world, route)

    # The membership commits and every recipient's push fails.
    with get_session_with_current_tenant() as other:
        assert world.member.id not in fetch_user_group_member_ids(other, world.group_id)
    assert {sandbox_id for sandbox_id, _ in manager.skill_pushes} == {
        world.sandboxes[user_id].id for user_id in recipients
    }
    for user_id, sandbox in world.sandboxes.items():
        db_session.refresh(sandbox)
        expected = None if user_id in recipients else f"delivered-{user_id.hex}"
        assert sandbox.skills_hash == expected, user_id
    db_session.refresh(world.session)
    assert session_runtime_stale(world.session, member_sandbox)
    assert not session_runtime_intact(world.session, member_sandbox)

    # The next turn retries delivery and refuses to dispatch while it fails.
    manager.skill_pushes.clear()
    session_manager = SessionManager(db_session)
    with pytest.raises(OnyxError) as reload_error:
        session_manager.reload_session_skills(world.session.id, world.member)
    assert reload_error.value.error_code == OnyxErrorCode.BAD_GATEWAY
    with pytest.raises(OnyxError) as ready_error:
        ensure_session_ready(db_session, manager, world.session, world.member)
    assert ready_error.value.error_code == OnyxErrorCode.BAD_GATEWAY
    assert [sandbox_id for sandbox_id, _ in manager.skill_pushes] == [
        member_sandbox.id,
        member_sandbox.id,
    ]
    assert manager.dispose_opencode_instance_count == 0
    db_session.refresh(member_sandbox)
    assert member_sandbox.skills_hash is None

    # A successful retry removes the revoked Skill, then records and reloads.
    manager.failing = set()
    manager.skill_pushes.clear()
    assert session_manager.reload_session_skills(world.session.id, world.member) is (
        False
    )
    [(pushed_sandbox_id, delivered)] = manager.skill_pushes
    assert pushed_sandbox_id == member_sandbox.id
    assert not any(path.startswith(f"{world.skill_name}/") for path in delivered)
    db_session.refresh(member_sandbox)
    db_session.refresh(world.session)
    assert member_sandbox.skills_hash is not None
    assert world.session.skills_hash == member_sandbox.skills_hash
    assert manager.regenerate_session_config_count == 1
    assert manager.dispose_opencode_instance_count == 1
    assert not session_runtime_stale(world.session, member_sandbox)
    assert session_runtime_intact(world.session, member_sandbox)


class DeliveryRaceManager(RecordingSandboxManager):
    """Holds the delivery thread's Skill push open until the test releases it;
    every other Skill push (the membership route's) fails."""

    DELIVERY_THREAD = "managed-content-delivery"

    def __init__(self, sandbox_id: UUID) -> None:
        super().__init__(failing={sandbox_id})
        self.in_delivery = Event()
        self.release = Event()
        self.delivered: FileSet | None = None
        self.batch_delivery = False
        self.provision_returns = SandboxInfo(
            sandbox_id=sandbox_id,
            directory_path="/tmp/sandbox",
            status=SandboxStatus.RUNNING,
            last_heartbeat=None,
        )

    def write_files_to_sandbox(
        self, *, sandbox_id: UUID, mount_path: str, files: FileSet
    ) -> None:
        if current_thread().name != self.DELIVERY_THREAD and not self.batch_delivery:
            super().write_files_to_sandbox(
                sandbox_id=sandbox_id, mount_path=mount_path, files=files
            )
            return
        if mount_path != SKILLS_MOUNT_PATH:
            return
        self.delivered = files
        self.in_delivery.set()
        assert self.release.wait(timeout=30)


@pytest.mark.parametrize("delivery", ["sync", "provision", "batch"])
@pytest.mark.parametrize("pending_before", [False, True])
def test_in_flight_delivery_cannot_clear_membership_invalidation(
    db_session: Session,
    world: World,
    delivery: Literal["sync", "provision", "batch"],
    pending_before: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A contended membership mutation rolls back; a later retry's pending
    marker survives the older delivery and a failed postcommit push."""
    member_sandbox = world.sandboxes[world.member.id]
    sandbox_id = member_sandbox.id
    if pending_before:
        member_sandbox.skills_hash = None
    if delivery == "provision":
        member_sandbox.status = SandboxStatus.SLEEPING
    db_session.commit()
    manager = DeliveryRaceManager(sandbox_id)
    manager.batch_delivery = delivery == "batch"
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: manager)
    errors: list[BaseException] = []

    def deliver() -> None:
        try:
            with get_session_with_current_tenant() as session:
                user = session.get(User, world.member.id)
                assert user is not None
                if delivery == "sync":
                    sync_managed_content(session, manager, sandbox_id, user)
                elif delivery == "batch":
                    push.push_skills_for_users({user.id}, session)
                    session.commit()
                else:
                    ensure_sandbox_ready(
                        session, manager, user.id, policy=ProvisioningPolicy.FAIL
                    )
        except BaseException as exc:
            errors.append(exc)

    def route_session() -> Generator[Session, None, None]:
        with get_session_with_current_tenant() as session:
            yield session

    app = FastAPI()
    app.include_router(user_group_api.router)
    register_onyx_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: world.admin
    app.dependency_overrides[get_session] = route_session
    responses: list[tuple[int, dict[str, str]]] = []

    def remove_member() -> None:
        try:
            response = TestClient(app).patch(
                f"/manage/admin/user-group/{world.group_id}",
                json={"user_ids": [str(world.stayer.id)]},
            )
            responses.append((response.status_code, response.json()))
        except BaseException as exc:
            errors.append(exc)

    delivery_thread = Thread(target=deliver, name=manager.DELIVERY_THREAD)
    membership_thread = Thread(target=remove_member)
    delivery_thread.start()
    try:
        assert manager.in_delivery.wait(timeout=30)
        membership_thread.start()
        membership_thread.join(timeout=5)
        # The response arrives before releasing the Skill transport barrier.
        assert not membership_thread.is_alive()
        assert responses == [
            (
                409,
                {
                    "error_code": "CONFLICT",
                    "detail": "Skills are being delivered. Retry this membership request.",
                },
            )
        ]
        with get_session_with_current_tenant() as other:
            # A second membership caller can proceed while delivery is stalled.
            lock_group_membership(other, nowait=True)
            assert world.member.id in fetch_user_group_member_ids(other, world.group_id)
            for original in world.sandboxes.values():
                current = other.get(Sandbox, original.id)
                assert current is not None
                expected = (
                    None
                    if pending_before and current.id == sandbox_id
                    else f"delivered-{current.user_id.hex}"
                )
                assert current.skills_hash == expected
            other.rollback()
        second_response = TestClient(app).patch(
            f"/manage/admin/user-group/{world.group_id}",
            json={"user_ids": [str(world.member.id), str(world.stayer.id)]},
        )
        assert second_response.status_code == 200, second_response.text
    finally:
        manager.release.set()
        delivery_thread.join(timeout=60)
        if membership_thread.is_alive() or membership_thread.ident is not None:
            membership_thread.join(timeout=60)

    assert not errors, errors
    manager.batch_delivery = False
    # Retry the full mutation after the older delivery has recorded its hash.
    # Its failing postcommit push must leave the newer marker pending.
    with get_session_with_current_tenant() as retry:
        _change_membership(retry, world, "admin_patch")
    # The delivery read the old roster, so it carried the revoked Skill.
    assert manager.delivered is not None
    assert any(path.startswith(f"{world.skill_name}/") for path in manager.delivered)
    db_session.expire_all()
    sandbox = db_session.get(Sandbox, sandbox_id)
    assert sandbox is not None
    # The membership push failed, so the change must still be pending.
    assert sandbox.skills_hash is None
    session = db_session.get(BuildSession, world.session.id)
    assert session is not None
    assert session_runtime_stale(session, sandbox)


def test_resumed_scheduled_session_reloads_after_pending_delivery(
    db_session: Session,
    world: World,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A scheduled session's live runtime loaded the revoked Skill too; a later
    turn on it must reload after the retried delivery, not reuse it."""
    member_sandbox = world.sandboxes[world.member.id]
    member_sandbox.skills_hash = None
    world.session.origin = SessionOrigin.SCHEDULED
    db_session.commit()
    manager = RecordingSandboxManager(failing=set())
    monkeypatch.setattr("onyx.skills.push.get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: manager,
    )

    assert not session_runtime_intact(world.session, member_sandbox)
    ensure_session_ready(db_session, manager, world.session, world.member)

    db_session.refresh(member_sandbox)
    db_session.refresh(world.session)
    assert member_sandbox.skills_hash is not None
    assert manager.dispose_opencode_instance_count == 1
    assert world.session.skills_hash == member_sandbox.skills_hash


@pytest.mark.parametrize("origin", [SessionOrigin.INTERACTIVE, SessionOrigin.SCHEDULED])
def test_prompt_send_refuses_pending_delivery(
    db_session: Session,
    world: World,
    origin: SessionOrigin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Pending delivery refuses admission before session preparation."""
    member_sandbox = world.sandboxes[world.member.id]
    world.session.origin = origin
    db_session.commit()
    manager = RecordingSandboxManager(failing=set())
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: manager,
    )
    session_manager = SessionManager(db_session)
    with get_session_with_current_tenant() as other:
        mark_user_sandbox_skills_pending__no_commit(other, {world.member.id})
        other.commit()

    with pytest.raises(OnyxError) as error:
        next(
            session_manager.yield_sandbox_events(
                member_sandbox.id, world.session.id, "hello"
            )
        )
    assert error.value.error_code == OnyxErrorCode.BAD_GATEWAY
    assert manager.ensure_opencode_session_count == 0
    assert manager.send_message_count == 0


@pytest.mark.parametrize("origin", [SessionOrigin.INTERACTIVE, SessionOrigin.SCHEDULED])
@pytest.mark.parametrize("stage", ["session_loading", "heartbeat"])
def test_membership_commit_during_preparation_refuses_admission(
    db_session: Session,
    world: World,
    origin: SessionOrigin,
    stage: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = world.sandboxes[world.member.id]
    world.session.origin = origin
    db_session.commit()
    manager = RecordingSandboxManager(failing={sandbox.id})
    manager.send_message_events = []
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: manager,
    )
    original_load = streaming.load_turn_session
    original_heartbeat = streaming._refresh_sandbox_heartbeat_best_effort

    def revoke() -> None:
        with get_session_with_current_tenant() as other:
            _change_membership(other, world, "admin_patch")

    def load_then_revoke(
        session: Session,
        transport: StubSandboxManager,
        sandbox_id: UUID,
        session_id: UUID,
    ) -> BuildSession | None:
        result = original_load(session, transport, sandbox_id, session_id)
        revoke()
        return result

    def heartbeat_then_revoke(sandbox_id: UUID) -> None:
        original_heartbeat(sandbox_id)
        revoke()

    if stage == "session_loading":
        monkeypatch.setattr(streaming, "load_turn_session", load_then_revoke)
    else:
        monkeypatch.setattr(
            streaming, "_refresh_sandbox_heartbeat_best_effort", heartbeat_then_revoke
        )
    with pytest.raises(OnyxError) as error:
        list(
            SessionManager(db_session).yield_sandbox_events(
                sandbox.id, world.session.id, "hello"
            )
        )
    assert error.value.error_code == OnyxErrorCode.BAD_GATEWAY
    with get_session_with_current_tenant() as other:
        assert world.member.id not in fetch_user_group_member_ids(other, world.group_id)
        committed = other.get(Sandbox, sandbox.id)
        assert committed is not None and committed.skills_hash is None
    assert manager.send_message_count == 0


class LibraryBarrierManager(DeliveryRaceManager):
    def write_files_to_sandbox(
        self, *, sandbox_id: UUID, mount_path: str, files: FileSet
    ) -> None:
        if current_thread().name == self.DELIVERY_THREAD:
            if mount_path != SKILLS_MOUNT_PATH:
                self.in_delivery.set()
                assert self.release.wait(timeout=30)
            return
        super().write_files_to_sandbox(
            sandbox_id=sandbox_id, mount_path=mount_path, files=files
        )


@pytest.mark.parametrize(
    "delivery,supersede", [("sync", False), ("provision", False), ("provision", True)]
)
def test_library_push_holds_no_skill_delivery_lock(
    db_session: Session,
    world: World,
    delivery: str,
    supersede: bool,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sandbox = world.sandboxes[world.member.id]
    if delivery == "provision":
        sandbox.status = SandboxStatus.SLEEPING
    db_session.commit()
    manager = LibraryBarrierManager(sandbox.id)
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)
    errors: list[BaseException] = []

    def deliver() -> None:
        try:
            with get_session_with_current_tenant() as other:
                user = other.get(User, world.member.id)
                assert user is not None
                if delivery == "sync":
                    sync_managed_content(other, manager, sandbox.id, user)
                else:
                    ensure_sandbox_ready(
                        other, manager, user.id, policy=ProvisioningPolicy.FAIL
                    )
        except BaseException as exc:
            errors.append(exc)

    thread = Thread(target=deliver, name=manager.DELIVERY_THREAD)
    thread.start()
    try:
        assert manager.in_delivery.wait(timeout=30)
        with get_session_with_current_tenant() as other:
            # NOWAIT proves the stalled library transport owns no sandbox row lock.
            current = other.scalar(
                select(Sandbox)
                .where(Sandbox.id == sandbox.id)
                .with_for_update(nowait=True)
            )
            assert current is not None
            if delivery == "provision":
                assert current.status == SandboxStatus.PROVISIONING
            other.rollback()
        with get_session_with_current_tenant() as other:
            _change_membership(other, world, "admin_patch")
            lock_group_membership(other, nowait=True)
            other.rollback()
        if supersede:
            with get_session_with_current_tenant() as other:
                newer = other.get(Sandbox, sandbox.id)
                assert newer is not None
                begin_provisioning_attempt__no_commit(other, newer)
                newer.skills_hash = "newer-attempt"
                other.commit()
    finally:
        manager.release.set()
        thread.join(timeout=60)
    assert not thread.is_alive()
    if supersede:
        assert len(errors) == 1 and isinstance(errors[0], StaleProvisioningAttemptError)
    else:
        assert not errors, errors
    with get_session_with_current_tenant() as other:
        current = other.get(Sandbox, sandbox.id)
        assert current is not None
        if supersede:
            assert current.status == SandboxStatus.PROVISIONING
            assert current.skills_hash == "newer-attempt"
            assert current.provisioning_attempt_number == 2
        else:
            assert current.skills_hash is None
            assert current.status == SandboxStatus.RUNNING


def test_pending_mark_rolls_back_multiple_rows_and_preserves_timeouts(
    world: World,
    isolated_engine: Engine,
) -> None:
    ordered = sorted(world.sandboxes.values(), key=lambda row: row.id)
    with (
        get_session_with_current_tenant() as blocker,
        isolated_engine.connect() as connection,
        Session(bind=connection) as request,
    ):
        blocker.scalar(
            select(Sandbox).where(Sandbox.id == ordered[-1].id).with_for_update()
        )
        request.execute(text("SET lock_timeout = '731ms'"))
        request.execute(text("SET statement_timeout = '4s'"))
        request.commit()
        before = tuple(
            request.execute(
                text(
                    "SELECT current_setting('lock_timeout'), current_setting('statement_timeout')"
                )
            ).one()
        )
        request.commit()
        try:
            lock_group_membership(request, nowait=True)
            group = request.get(UserGroup, world.group_id)
            assert group is not None
            group.name = "must-roll-back"
            request.flush()
            with pytest.raises(OnyxError) as error:
                mark_user_sandbox_skills_pending__no_commit(
                    request, set(world.sandboxes)
                )
            assert error.value.error_code == OnyxErrorCode.CONFLICT
            assert (
                tuple(
                    request.execute(
                        text(
                            "SELECT current_setting('lock_timeout'), current_setting('statement_timeout')"
                        )
                    ).one()
                )
                == before
            )
            request.rollback()
            with get_session_with_current_tenant() as observer:
                lock_group_membership(observer, nowait=True)
                unchanged = observer.get(UserGroup, world.group_id)
                assert unchanged is not None and unchanged.name != "must-roll-back"
                first = observer.scalar(
                    select(Sandbox)
                    .where(Sandbox.id == ordered[0].id)
                    .with_for_update(nowait=True)
                )
                assert first is not None and first.skills_hash == ordered[0].skills_hash
                observer.rollback()
            blocker.rollback()
            mark_user_sandbox_skills_pending__no_commit(request, set(world.sandboxes))
            assert (
                tuple(
                    request.execute(
                        text(
                            "SELECT current_setting('lock_timeout'), current_setting('statement_timeout')"
                        )
                    ).one()
                )
                == before
            )
            request.rollback()
        finally:
            request.rollback()
            request.execute(text("RESET lock_timeout"))
            request.execute(text("RESET statement_timeout"))
            request.commit()


@pytest.mark.parametrize("origin", [SessionOrigin.INTERACTIVE, SessionOrigin.SCHEDULED])
def test_membership_commit_after_final_admission_can_still_send(
    db_session: Session,
    world: World,
    origin: SessionOrigin,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Admission is a database read, not an atomic database/network protocol."""
    sandbox = world.sandboxes[world.member.id]
    world.session.origin = origin
    db_session.commit()
    manager = RecordingSandboxManager(failing={sandbox.id})
    manager.send_message_events = []
    monkeypatch.setattr(push, "get_sandbox_manager", lambda: manager)
    monkeypatch.setattr(
        "onyx.server.features.build.session.manager.get_sandbox_manager",
        lambda: manager,
    )
    original = streaming.sandbox_skills_delivery_pending

    def admit_then_commit(session: Session, sandbox_id: UUID) -> bool:
        pending = original(session, sandbox_id)
        assert not pending
        with get_session_with_current_tenant() as other:
            _change_membership(other, world, "admin_patch")
        return pending

    monkeypatch.setattr(streaming, "sandbox_skills_delivery_pending", admit_then_commit)
    assert (
        list(
            SessionManager(db_session).yield_sandbox_events(
                sandbox.id, world.session.id, "already admitted"
            )
        )
        == []
    )
    assert manager.send_message_count == 1
    assert manager.last_send_message_payload is not None
    assert manager.last_send_message_payload["message"] == "already admitted"
    with get_session_with_current_tenant() as other:
        committed = other.get(Sandbox, sandbox.id)
        assert committed is not None and committed.skills_hash is None
