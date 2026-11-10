"""Management against migrated PostgreSQL; provider validation belongs to the caller."""

import sys
from collections.abc import Generator
from datetime import datetime, timezone
from threading import Event
from time import monotonic, sleep
from types import FrameType
from uuid import uuid4

import pytest
from sqlalchemy import delete, event, func, select, text, update
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db import marketplace_management as management
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ExternalAppType, Permission
from onyx.db.enums import SkillSharePermission as Share
from onyx.db.marketplace_sync import (
    MarketplaceSyncLeaseLost,
    claim_marketplace_sync,
    fence_marketplace_sync,
    finish_marketplace_sync,
)
from onyx.db.models import (
    ExternalApp,
    ExternalAppUserCredential,
    FileRecord,
    Marketplace,
    Sandbox,
    Skill,
    SkillVersion,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.resource_access import ResourceAccessChange, mutate_resource_access
from onyx.db.skill import SkillAccessAdapter
from onyx.db.skill_version import delete_unreferenced_skill_bundles
from onyx.db.user_preferences import deactivate_user
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.settings.models import Tier
from onyx.skills.ingest import ingest_skill_bundle, save_skill_bundle_bytes
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    MarketplaceProvider,
    MarketplaceRetirementProposal,
    MarketplaceSyncStatus,
)
from onyx.skills.marketplace.read_models import ReadySkill
from onyx.utils.threadpool_concurrency import start_thread_future
from tests.external_dependency_unit.craft.db_helpers import (
    make_sandbox,
    make_skill,
    make_user,
    make_user_credential,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply,
    catalog,
    skills,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import bundle

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")
CONFIG = GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main")


@pytest.fixture(autouse=True)
def no_management_io() -> Generator[None, None, None]:
    depth = 0

    def guard(frame: FrameType, event: str, _arg: object) -> None:
        nonlocal depth
        path = frame.f_code.co_filename
        if path.endswith("/onyx/db/marketplace_management.py"):
            depth += 1 if event == "call" else -1 if event == "return" else 0
        if depth and event == "call":
            assert not any(
                part in path
                for part in (
                    "/onyx/file_store/file_store.py",
                    "/requests/",
                    "/httpx/",
                    "/urllib/",
                    "/socket.py",
                    "/kombu/",
                )
            ), f"Management attempted I/O: {path}"

    previous = sys.getprofile()
    sys.setprofile(guard)
    try:
        yield
    finally:
        sys.setprofile(previous)


def connect(session: Session, user: User) -> ExternalApp:
    app = session.scalar(
        select(ExternalApp).where(ExternalApp.app_type == ExternalAppType.GITHUB)
    )
    if app is None:
        app = ExternalApp(name="GitHub", app_type=ExternalAppType.GITHUB, enabled=True)
        session.add(app)
        session.flush()
    make_user_credential(
        session, app=app, user=user, user_credentials={"access_token": "fixture"}
    )
    return app


def create(session: Session, user: User, *, personal: bool = True) -> Marketplace:
    return management.create_marketplace__no_commit(
        name="Catalog",
        provider=MarketplaceProvider.GITHUB,
        config=CONFIG,
        personal=personal,
        user=user,
        db_session=session,
    )


@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize("actor_kind", ["owner", "other", "scoped", "global"])
def test_source_authority(session: Session, personal: bool, actor_kind: str) -> None:
    owner, _ = manager(session, global_access=True)
    connect(session, owner)
    row = create(session, owner, personal=personal)
    actor = (
        owner
        if actor_kind == "owner"
        else (
            manager(session, global_access=actor_kind == "global")[0]
            if actor_kind in ("scoped", "global")
            else make_user(session, standard_account=True)
        )
    )
    if actor != owner:
        connect(session, actor)
    allowed = actor_kind in ("owner", "global")
    listed = {item.id for item in management.list_managed_marketplaces(actor, session)}
    assert (row.id in listed) == allowed
    for operation in (
        management.fetch_managed_marketplace,
        management.request_managed_marketplace_sync__no_commit,
        management.replace_marketplace_login__no_commit,
    ):
        if allowed:
            operation(row.id, actor, session)
        else:
            with pytest.raises(OnyxError):
                operation(row.id, actor, session)
    if allowed:
        management.remove_marketplace__no_commit(row.id, actor, session)
    else:
        with pytest.raises(OnyxError):
            management.remove_marketplace__no_commit(row.id, actor, session)


@pytest.mark.parametrize("enterprise", [False, True])
def test_create_defaults_and_rollback(
    session: Session, monkeypatch: pytest.MonkeyPatch, enterprise: bool
) -> None:
    monkeypatch.setattr("onyx.db.marketplace_access.IS_ENTERPRISE_BUILD", enterprise)
    owner = make_user(session, standard_account=True)
    connect(session, owner)
    session.commit()
    personal = create(session, owner)
    personal_id = personal.id
    assert personal.owner_user_id == personal.login_user_id == owner.id
    assert personal.public_permission is None and personal.sync_requested
    session.rollback()
    assert session.get(Marketplace, personal_id) is None
    with pytest.raises(OnyxError):
        create(session, owner, personal=False)
    scoped, _ = manager(session, global_access=False)
    connect(session, scoped)
    with pytest.raises(OnyxError):
        create(session, scoped, personal=False)
    admin, _ = manager(session, global_access=True)
    connect(session, admin)
    company = create(session, admin, personal=False)
    assert company.owner_user_id is None and company.login_user_id == admin.id
    assert company.public_permission == (None if enterprise else Share.VIEWER)


@pytest.mark.parametrize(
    "status", [MarketplaceSyncStatus.APPLIED, MarketplaceSyncStatus.FAILED]
)
def test_pending_status_covers_claimed_work(
    session: Session, status: MarketplaceSyncStatus
) -> None:
    user = make_user(session, standard_account=True)
    connect(session, user)
    row = create(session, user)
    session.commit()

    def snapshot() -> None:
        detail = management.fetch_managed_marketplace(row.id, user, session).marketplace
        listed = next(
            item
            for item in management.list_managed_marketplaces(user, session)
            if item.id == row.id
        )
        assert detail.sync_pending and listed.sync_pending
        assert "sync_owner" not in detail.model_dump()

    snapshot()
    worker = claim_marketplace_sync(row.id, session)
    assert worker is not None
    assert not row.sync_requested
    snapshot()
    finish_marketplace_sync(row.id, worker, session, status=status)
    detail = management.fetch_managed_marketplace(row.id, user, session).marketplace
    assert not detail.sync_pending and detail.sync_status == status
    assert not management.list_managed_marketplaces(user, session)[0].sync_pending


def test_safe_batched_reads_include_retired(session: Session) -> None:
    owner = make_user(session, standard_account=True)
    connect(session, owner)
    first = create(session, owner)
    second = create(session, owner)
    apply(session, first, catalog("first", "retired"))
    apply(session, first, catalog("first"), revision="next")
    session.execute(
        update(Marketplace)
        .where(Marketplace.id == first.id)
        .values(webhook_secret="fixture-webhook")
    )
    first.blocked_entries = {"broken": "invalid bundle"}
    first.retirement_proposal = MarketplaceRetirementProposal(
        revision="proposal", skill_ids=(uuid4(),)
    )
    session.flush()
    statements: list[str] = []

    def capture(
        _conn: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _many: bool,
    ) -> None:
        statements.append(statement)

    event.listen(session.get_bind(), "before_cursor_execute", capture)
    try:
        snapshots = management.list_managed_marketplaces(owner, session)
    finally:
        event.remove(session.get_bind(), "before_cursor_execute", capture)
    assert sum("count(" in query.lower() for query in statements) == 1
    by_id = {item.id: item for item in snapshots}
    assert (by_id[first.id].live_skill_count, by_id[first.id].retired_skill_count) == (
        1,
        1,
    )
    assert (
        by_id[second.id].live_skill_count == by_id[second.id].retired_skill_count == 0
    )
    detail = management.fetch_managed_marketplace(first.id, owner, session)
    assert (
        len(detail.skills) == 2
        and sum(item.retired_at is not None for item in detail.skills) == 1
    )
    assert detail.marketplace.blocked_entries == first.blocked_entries
    assert detail.marketplace.retirement_proposal == first.retirement_proposal
    assert (
        "webhook_secret" not in detail.model_dump_json()
        and "credential" not in detail.model_dump_json()
    )


@pytest.mark.parametrize(
    "operation", ["create", "sync", "replace", "defaults", "remove", "list", "fetch"]
)
@pytest.mark.parametrize("revocation", ["basic", "global", "inactive"])
def test_refresh_separate_auth_actor(
    db_session: Session, operation: str, revocation: str
) -> None:
    actor, _ = manager(db_session, global_access=True)
    connect(db_session, actor)
    row = create(db_session, actor, personal=False)
    row.sync_requested = False
    db_session.commit()
    actor_id, row_id = actor.id, row.id
    with get_session_with_current_tenant() as auth:
        stale = auth.get(User, actor_id)
        assert stale is not None and has_global_permission(
            stale, Permission.MANAGE_SKILLS
        )
        with get_session_with_current_tenant() as writer:
            lock_group_membership(writer)
            current = writer.get(User, actor_id)
            assert current is not None
            if revocation == "inactive":
                current.is_active = False
            else:
                basic_id = writer.scalar(
                    select(UserGroup.id).where(UserGroup.name == "Basic")
                )
                predicate = (
                    User__UserGroup.user_group_id == basic_id
                    if revocation == "basic"
                    else User__UserGroup.user_group_id != basic_id
                )
                writer.execute(
                    delete(User__UserGroup).where(
                        User__UserGroup.user_id == actor_id, predicate
                    )
                )
                recompute_user_permissions__no_commit(actor_id, writer)
            writer.commit()
        if operation == "list" and revocation == "global":
            assert management.list_managed_marketplaces(stale, db_session) == []
        else:
            with pytest.raises(OnyxError):
                if operation == "create":
                    create(db_session, stale, personal=False)
                elif operation == "defaults":
                    management.set_marketplace_default_access__no_commit(
                        row_id,
                        ResourceAccessChange(),
                        stale,
                        db_session,
                        tier=Tier.BUSINESS,
                    )
                elif operation == "list":
                    management.list_managed_marketplaces(stale, db_session)
                else:
                    operations = {
                        "sync": management.request_managed_marketplace_sync__no_commit,
                        "replace": management.replace_marketplace_login__no_commit,
                        "remove": management.remove_marketplace__no_commit,
                        "fetch": management.fetch_managed_marketplace,
                    }
                    operations[operation](row_id, stale, db_session)
        db_session.commit()
        assert not row.sync_requested and row.login_user_id == actor_id


@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize("locked_resource", ["marketplace", "skill"])
def test_deactivated_actor_cannot_remove_after_resource_lock_wait(
    db_session: Session, personal: bool, locked_resource: str
) -> None:
    actor, _ = manager(db_session, global_access=True)
    connect(db_session, actor)
    row = create(db_session, actor, personal=personal)
    skill = make_skill(db_session, author_user_id=actor.id)
    skill.marketplace_id = row.id
    skill.marketplace_entry_key = skill.name
    db_session.commit()
    actor_id, row_id, skill_id = actor.id, row.id, skill.id
    entered = Event()
    backend_pids: list[int] = []

    def remove() -> OnyxErrorCode | None:
        with get_session_with_current_tenant() as writer:
            current = writer.get(User, actor_id)
            assert current is not None and current.is_active
            pid = writer.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            backend_pids.append(pid)
            entered.set()
            try:
                management.remove_marketplace__no_commit(row_id, current, writer)
                writer.commit()
            except OnyxError as exc:
                writer.rollback()
                return exc.error_code
            return None

    with get_session_with_current_tenant() as holder:
        if locked_resource == "marketplace":
            holder.scalar(
                select(Marketplace).where(Marketplace.id == row_id).with_for_update()
            )
        else:
            holder.scalar(
                select(Skill.id).where(Skill.id == skill_id).with_for_update()
            )
        future = start_thread_future(remove, name="marketplace-deactivation-test")
        try:
            assert entered.wait(5)
            deadline = monotonic() + 5
            blocked = False
            while monotonic() < deadline:
                blocked = bool(
                    holder.scalar(
                        text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks "
                            "WHERE pid = :pid AND NOT granted)"
                        ),
                        {"pid": backend_pids[0]},
                    )
                )
                if blocked:
                    break
                sleep(0.01)
            assert blocked, "Removal must wait on the held resource lock"
            with get_session_with_current_tenant() as revoker:
                current = revoker.get(User, actor_id)
                assert current is not None
                deactivate_user(current, revoker)
        finally:
            holder.rollback()
    assert future.result(timeout=15) == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    db_session.expire_all()
    assert db_session.get(Marketplace, row_id) is not None
    assert db_session.get(Skill, skill_id) is not None


@pytest.mark.parametrize("invalid", ["disconnected", "disabled", "inactive"])
def test_stored_login_facts_are_rechecked(db_session: Session, invalid: str) -> None:
    owner = make_user(db_session, standard_account=True)
    app = connect(db_session, owner)
    row = create(db_session, owner)
    row.sync_requested = False
    db_session.commit()
    owner_id, app_id, row_id = owner.id, app.id, row.id
    with get_session_with_current_tenant() as writer:
        if invalid == "disconnected":
            writer.execute(
                delete(ExternalAppUserCredential).where(
                    ExternalAppUserCredential.user_id == owner_id
                )
            )
        elif invalid == "disabled":
            fresh_app = writer.get(ExternalApp, app_id)
            assert fresh_app is not None
            fresh_app.enabled = False
        else:
            fresh_user = writer.get(User, owner_id)
            assert fresh_user is not None
            fresh_user.is_active = False
        writer.commit()
    for operation in (
        management.request_managed_marketplace_sync__no_commit,
        management.replace_marketplace_login__no_commit,
    ):
        with pytest.raises(OnyxError):
            operation(row_id, owner, db_session)
    with pytest.raises(OnyxError):
        create(db_session, owner)
    db_session.rollback()
    # Restore the shared fixture app for later tests.
    app.enabled = True
    db_session.commit()


def test_request_and_login_rollback_preservation_and_fence(db_session: Session) -> None:
    session = db_session
    owner = make_user(session, standard_account=True)
    admin, _ = manager(session, global_access=True)
    connect(session, owner)
    connect(session, admin)
    row = create(session, owner)
    apply(session, row, catalog("first"))
    apply(session, row, catalog("first", body=b"changed"), revision="second")
    skill = skills(session, row)[0]
    mutate_resource_access(
        [skill.id],
        ResourceAccessChange(user_shares={admin.id: Share.VIEWER}),
        owner,
        session,
        SkillAccessAdapter(),
    )
    row.sync_requested = False
    session.commit()
    management.request_managed_marketplace_sync__no_commit(row.id, owner, session)
    session.rollback()
    assert not row.sync_requested
    management.request_managed_marketplace_sync__no_commit(row.id, admin, session)
    session.commit()
    old_worker = claim_marketplace_sync(row.id, session)
    assert old_worker is not None
    row.retirement_proposal = MarketplaceRetirementProposal(
        revision="third", skill_ids=(skill.id,), approved=True
    )
    session.commit()
    versions = set(
        session.scalars(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill.id)
        )
    )
    old_version = skill.current_version_id
    management.replace_marketplace_login__no_commit(row.id, admin, session)
    session.rollback()
    assert row.login_user_id == owner.id and row.sync_owner == old_worker
    assert row.retirement_proposal is not None and row.retirement_proposal.approved
    management.replace_marketplace_login__no_commit(row.id, admin, session)
    session.commit()
    assert row.login_user_id == admin.id and row.owner_user_id == owner.id
    assert (
        row.sync_requested
        and row.sync_owner is None
        and row.sync_lease_expires_at is None
    )
    assert row.retirement_proposal is None and row.last_synced_revision == "second"
    assert (
        skill.current_version_id == old_version
        and skill.user_shares[0].user_id == admin.id
    )
    assert (
        set(
            session.scalars(
                select(SkillVersion.id).where(SkillVersion.skill_id == skill.id)
            )
        )
        == versions
    )
    with get_session_with_current_tenant() as worker:
        with pytest.raises(MarketplaceSyncLeaseLost):
            fence_marketplace_sync(row.id, old_worker, worker)


def test_global_defaults_preserve_overrides_and_audience(session: Session) -> None:
    admin, old_group = manager(session, global_access=True)
    scoped, new_group = manager(session, global_access=False)
    connect(session, admin)
    row = create(session, admin, personal=False)
    for user in (admin, scoped):
        make_sandbox(session, user)
    management.set_marketplace_default_access__no_commit(
        row.id,
        ResourceAccessChange(group_shares={old_group: Share.VIEWER}),
        admin,
        session,
        tier=Tier.BUSINESS,
    )
    apply(session, row, catalog("follower", "override"))
    override = next(skill for skill in skills(session, row) if skill.name == "override")
    mutate_resource_access(
        [override.id],
        ResourceAccessChange(user_shares={admin.id: Share.VIEWER}),
        admin,
        session,
        SkillAccessAdapter(),
    )
    change = ResourceAccessChange(group_shares={new_group: Share.VIEWER})
    with pytest.raises(OnyxError):
        management.set_marketplace_default_access__no_commit(
            row.id, change, scoped, session, tier=Tier.BUSINESS
        )
    affected = management.set_marketplace_default_access__no_commit(
        row.id, change, admin, session, tier=Tier.BUSINESS
    )
    assert affected == {admin.id, scoped.id}
    session.expire_all()
    follower = next(skill for skill in skills(session, row) if skill.name == "follower")
    assert (
        follower.group_shares[0].user_group_id == new_group
        and follower.follows_marketplace_access
    )
    assert (
        override.group_shares[0].user_group_id == old_group
        and not override.follows_marketplace_access
    )
    assert override.user_shares[0].user_id == admin.id
    personal = create(session, admin)
    with pytest.raises(OnyxError):
        management.set_marketplace_default_access__no_commit(
            personal.id, change, admin, session, tier=Tier.BUSINESS
        )


@pytest.mark.usefixtures("initialize_file_store")
def test_remove_cascades_cleanup_audience_rollback_and_fence(
    db_session: Session,
) -> None:
    owner = make_user(db_session, standard_account=True)
    recipient = make_user(db_session, standard_account=True)
    outsider = make_user(db_session, standard_account=True)
    connect(db_session, owner)
    row = create(db_session, owner)
    db_session.commit()
    store = get_default_file_store()
    read = catalog("retained")
    entry = read.entries[0]
    assert isinstance(entry, ReadySkill)
    staged = ingest_skill_bundle(entry.bundle_bytes, "retained.zip", store)
    apply(db_session, row, read, staged={"tools/retained": staged})
    db_session.commit()
    read = catalog("retained", body=b"new")
    entry = read.entries[0]
    assert isinstance(entry, ReadySkill)
    newer = ingest_skill_bundle(entry.bundle_bytes, "retained.zip", store)
    apply(
        db_session,
        row,
        read,
        revision="new",
        staged={"tools/retained": newer},
    )
    skill = skills(db_session, row)[0]
    mutate_resource_access(
        [skill.id],
        ResourceAccessChange(user_shares={recipient.id: Share.VIEWER}),
        owner,
        db_session,
        SkillAccessAdapter(),
    )
    skill.retired_at = datetime.now(timezone.utc)
    db_session.commit()
    legacy = save_skill_bundle_bytes(
        bundle("legacy"), display_name="legacy.zip", file_store=store
    )
    db_session.add(
        SkillVersion(skill_id=skill.id, version_number=3, bundle_file_id=legacy)
    )
    shared = make_skill(
        db_session, author_user_id=outsider.id, bundle_file_id=staged.bundle_file_id
    )
    for user in (owner, recipient, outsider):
        make_sandbox(db_session, user)
    db_session.commit()
    row_id, skill_id = row.id, skill.id
    versions = set(
        db_session.scalars(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill_id)
        )
    )
    old_worker = claim_marketplace_sync(row_id, db_session)
    assert old_worker is not None
    expected_files = {staged.bundle_file_id, newer.bundle_file_id, legacy}
    result = management.remove_marketplace__no_commit(row_id, owner, db_session)
    assert result.cleanup_file_ids == expected_files and result.affected_user_ids == {
        owner.id,
        recipient.id,
    }
    db_session.rollback()
    assert (
        db_session.get(Marketplace, row_id) is not None
        and db_session.get(Skill, skill_id) is not None
    )
    assert (
        set(
            db_session.scalars(
                select(SkillVersion.id).where(SkillVersion.skill_id == skill_id)
            )
        )
        == versions
    )
    assert (
        set(
            db_session.scalars(
                select(FileRecord.file_id).where(FileRecord.file_id.in_(expected_files))
            )
        )
        == expected_files
    )
    management.remove_marketplace__no_commit(row_id, owner, db_session)
    db_session.commit()
    db_session.expire_all()
    assert (
        db_session.get(Marketplace, row_id) is None
        and db_session.get(Skill, skill_id) is None
    )
    assert not list(
        db_session.scalars(
            select(SkillVersion.id).where(SkillVersion.skill_id == skill_id)
        )
    )
    with pytest.raises(MarketplaceSyncLeaseLost):
        fence_marketplace_sync(row_id, old_worker, db_session)
    db_session.rollback()
    delete_unreferenced_skill_bundles(list(result.cleanup_file_ids), db_session)
    assert set(
        db_session.scalars(
            select(FileRecord.file_id).where(FileRecord.file_id.in_(expected_files))
        )
    ) == {staged.bundle_file_id}

    db_session.execute(
        delete(Sandbox).where(
            Sandbox.user_id.in_([owner.id, recipient.id, outsider.id])
        )
    )
    db_session.execute(delete(Skill).where(Skill.id == shared.id))
    db_session.commit()
    delete_unreferenced_skill_bundles(list(expected_files), db_session)


@pytest.mark.parametrize("change", ["basic", "inactive", "owner"])
def test_personal_owner_rechecked_after_io(db_session: Session, change: str) -> None:
    owner = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    connect(db_session, owner)
    row = create(db_session, owner)
    row.sync_requested = False
    db_session.commit()
    row_id, owner_id, other_id = row.id, owner.id, other.id
    with get_session_with_current_tenant() as auth:
        stale = auth.get(User, owner_id)
        assert stale is not None
        with get_session_with_current_tenant() as writer:
            lock_group_membership(writer)
            if change == "owner":
                writer.execute(
                    update(Marketplace)
                    .where(Marketplace.id == row_id)
                    .values(owner_user_id=other_id)
                )
            elif change == "basic":
                writer.execute(
                    delete(User__UserGroup).where(User__UserGroup.user_id == owner_id)
                )
                recompute_user_permissions__no_commit(owner_id, writer)
            else:
                current = writer.get(User, owner_id)
                assert current is not None
                current.is_active = False
            writer.commit()
        for operation in (
            management.request_managed_marketplace_sync__no_commit,
            management.replace_marketplace_login__no_commit,
            management.remove_marketplace__no_commit,
            management.fetch_managed_marketplace,
        ):
            with pytest.raises(OnyxError):
                operation(row_id, stale, db_session)
        db_session.commit()
        assert not row.sync_requested and row.login_user_id == owner_id
