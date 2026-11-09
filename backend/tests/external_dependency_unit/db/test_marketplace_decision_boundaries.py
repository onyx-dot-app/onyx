"""Readiness and audience boundaries of atomic marketplace budget decisions."""

import time
from collections.abc import Collection
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import timedelta
from queue import Queue
from typing import Any
from uuid import UUID

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CompoundSelect

from onyx.db import marketplace_limits as limit_db
from onyx.db import skill as skill_db
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import ExternalAppType, SkillInstallationPolicy, SkillSharePermission
from onyx.db.external_app import update_external_app
from onyx.db.marketplace import reconcile_marketplace__no_commit
from onyx.db.models import (
    Marketplace,
    Marketplace__UserGroup,
    Skill,
    User,
    User__UserGroup,
)
from onyx.db.skill import skill_usage_for_users
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.limits import SKILL_LIMIT_BLOCK_REASON, SKILL_WRITE_MAX_BYTES
from onyx.skills.marketplace.read_models import CompleteMarketplace, ReadySkill
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_external_app,
    make_group,
    make_user,
    make_user_credential,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    catalog,
    stage,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_marketplace_sync import GitHub, run
from tests.external_dependency_unit.db.test_marketplace_sync import github as github
from tests.external_dependency_unit.db.test_skill_limit_marketplace_sync import (
    ROOM,
    _catalog_archive,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user
from tests.external_dependency_unit.db.test_skill_write_limit import sized_skill


@pytest.fixture(autouse=True, params=[0, 1_000_000])
def query_shape(
    request: pytest.FixtureRequest, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(skill_db, "PER_USER_WINNER_MAX_NAME_PAIRS", request.param)
    monkeypatch.setattr(skill_db, "PER_USER_WINNER_MAX_FULL_TOTAL_USERS", request.param)


@pytest.mark.parametrize("disable_before_read", [True, False])
def test_readiness_is_fixed_before_the_decision_statement(
    disable_before_read: bool,
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    small = sized_skill(session, size=ROOM, name="app-fallback")
    sized_skill(session, size=8 * ROOM, name="app-fallback", author=user)
    app = make_external_app(
        session, skill=small, auth_template={"Authorization": "Bearer {token}"}
    )
    make_user_credential(session, app=app, user=user, user_credentials={"token": "x"})
    session.commit()
    github.archive = _catalog_archive(beta=b"")
    run(marketplace, tenant)
    usage = skill_usage_for_users([user.id], session)[user.id]
    sized_skill(
        session,
        size=SKILL_WRITE_MAX_BYTES - usage.charged_bytes - 2 * ROOM,
        author=user,
    )
    session.commit()
    app_id = app.id
    read = limit_db.get_ready_external_app_ids_for_users
    reads = []

    def disable() -> None:
        with get_session_with_current_tenant() as other:
            update_external_app(other, app_id, ExternalAppType.CUSTOM, enabled=False)
            other.commit()

    def readiness(
        db_session: Session, user_ids: Collection[UUID]
    ) -> dict[UUID, set[int]]:
        if disable_before_read:
            disable()
        ready = read(db_session, user_ids)
        reads.append(ready)
        if not disable_before_read:
            disable()
        return ready

    monkeypatch.setattr(limit_db, "get_ready_external_app_ids_for_users", readiness)
    github.revision = "f" * 40
    github.archive = _catalog_archive(alpha=b"x" * ROOM, beta=b"")
    run(marketplace, tenant)
    session.refresh(marketplace)
    assert len(reads) == 1
    assert bool(marketplace.blocked_entries) == disable_before_read
    assert set(marketplace.blocked_entries.values()) <= {SKILL_LIMIT_BLOCK_REASON}
    # A later app disable can put the user over. It must not refresh just one
    # side of a delta or the totals during replay.
    excess = (5 if disable_before_read else 6) * ROOM
    assert (
        skill_usage_for_users([user.id], session)[user.id].charged_bytes
        == SKILL_WRITE_MAX_BYTES + excess
    )


@pytest.mark.parametrize("newcomer_can_fit", [False, True])
def test_new_audience_user_gets_fresh_readiness_and_totals(
    newcomer_can_fit: bool,
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = make_group(session)
    marketplace.public_permission = None
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    session.add(
        Marketplace__UserGroup(
            marketplace_id=marketplace.id,
            user_group_id=group.id,
            permission=SkillSharePermission.VIEWER,
        )
    )
    add_user_to_group(session, user, group)
    newcomer = make_user(session, standard_account=True)
    # Only the newcomer has this ready app. A missing readiness capture would
    # reveal its larger fallback and incorrectly refuse the fitting case.
    small = sized_skill(session, size=ROOM, name="newcomer-app")
    sized_skill(session, size=8 * ROOM, name="newcomer-app", author=newcomer)
    app = make_external_app(
        session, skill=small, auth_template={"Authorization": "Bearer {token}"}
    )
    make_user_credential(
        session, app=app, user=newcomer, user_credentials={"token": "x"}
    )
    session.commit()
    github.archive = _catalog_archive(beta=b"")
    run(marketplace, tenant)
    usage = skill_usage_for_users([newcomer.id], session)[newcomer.id]
    room = 2 * ROOM if newcomer_can_fit else ROOM // 2
    sized_skill(
        session,
        size=SKILL_WRITE_MAX_BYTES - usage.charged_bytes - room,
        author=newcomer,
    )
    session.commit()
    group_id, newcomer_id = group.id, newcomer.id
    read = limit_db.get_ready_external_app_ids_for_users
    captured: list[set[UUID]] = []

    def readiness(
        db_session: Session, user_ids: Collection[UUID]
    ) -> dict[UUID, set[int]]:
        ready = read(db_session, user_ids)
        captured.append(set(user_ids))
        if len(captured) == 1:
            with get_session_with_current_tenant() as other:
                other.add(User__UserGroup(user_id=newcomer_id, user_group_id=group_id))
                other.commit()
        return ready

    monkeypatch.setattr(limit_db, "get_ready_external_app_ids_for_users", readiness)
    github.revision = "e" * 40
    github.archive = _catalog_archive(alpha=b"x" * ROOM, beta=b"")
    run(marketplace, tenant)
    session.refresh(marketplace)
    assert bool(marketplace.blocked_entries) != newcomer_can_fit
    assert len(captured) == 2
    assert newcomer_id not in captured[0] and newcomer_id in captured[1]
    assert set(marketplace.blocked_entries.values()) <= {SKILL_LIMIT_BLOCK_REASON}


@pytest.mark.parametrize("first_fits", [True, False])
def test_duplicate_new_name_reserves_only_an_accepted_entry(
    first_fits: bool, session: Session, marketplace: Marketplace, user: User
) -> None:
    """A larger first proposal may fail while a later same-name proposal fits."""
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    # The company proposal replaces this personal fallback. Its refusal must
    # retain the fallback, not make the name cost zero for the next proposal.
    sized_skill(session, size=ROOM, author=user, name="hello")
    sized_skill(session, size=SKILL_WRITE_MAX_BYTES - 2 * ROOM, author=user)
    session.commit()
    first = catalog("hello", body=b"x" * (ROOM if first_fits else 3 * ROOM)).entries[0]
    second = (
        catalog("hello", body=b"y" * ROOM)
        .entries[0]
        .model_copy(update={"entry_key": "second/hello"})
    )
    read = CompleteMarketplace(entries=[first, second])
    staged = stage(read)
    result = reconcile_marketplace__no_commit(
        marketplace.id,
        read,
        revision="duplicate",
        staged=staged,
        db_session=session,
    )
    session.commit()
    expected = (
        {"second/hello": "name taken"}
        if first_fits
        else {"tools/hello": SKILL_LIMIT_BLOCK_REASON}
    )
    assert result.blocked_entries == expected
    kept = "tools/hello" if first_fits else "second/hello"
    assert list(
        session.scalars(
            select(Skill.marketplace_entry_key).where(
                Skill.marketplace_id == marketplace.id
            )
        )
    ) == [kept]
    assert result.cleanup_file_ids == {
        bundle.bundle_file_id for key, bundle in staged.items() if key != kept
    }
    assert (
        skill_usage_for_users([user.id], session)[user.id].charged_bytes
        < SKILL_WRITE_MAX_BYTES
    )


def test_accepted_shrink_funds_later_growth(
    session: Session, marketplace: Marketplace, user: User
) -> None:
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    initial = catalog("alpha", "beta", body=b"x" * 2 * ROOM)
    reconcile_marketplace__no_commit(
        marketplace.id,
        initial,
        revision="r1",
        staged=stage(initial),
        db_session=session,
    )
    session.commit()
    usage = skill_usage_for_users([user.id], session)[user.id]
    sized_skill(
        session,
        size=SKILL_WRITE_MAX_BYTES - usage.charged_bytes - ROOM // 2,
        author=user,
    )
    session.commit()
    read = CompleteMarketplace(
        entries=[
            catalog("alpha").entries[0],
            catalog("beta", body=b"y" * 3 * ROOM).entries[0],
        ]
    )
    result = reconcile_marketplace__no_commit(
        marketplace.id, read, revision="r2", staged=stage(read), db_session=session
    )
    session.commit()
    assert result.blocked_entries == {}
    assert len(result.changed_skill_ids) == 2
    assert (
        skill_usage_for_users([user.id], session)[user.id].charged_bytes
        == SKILL_WRITE_MAX_BYTES - ROOM - ROOM // 2
    )


def test_membership_writer_waits_for_atomic_publication(
    session: Session,
    marketplace: Marketplace,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    initial = catalog("alpha", "beta")
    reconcile_marketplace__no_commit(
        marketplace.id,
        initial,
        revision="r1",
        staged=stage(initial),
        db_session=session,
    )
    session.commit()
    marketplace_id, user_id = marketplace.id, user.id
    old = dict(
        session.execute(
            select(Skill.id, Skill.current_version_id).where(
                Skill.marketplace_id == marketplace_id
            )
        )
        .tuples()
        .all()
    )
    group_id = make_group(session).id
    session.commit()
    waiting: Queue[int] = Queue()
    publisher_pid = session.scalar(select(func.pg_backend_pid()))
    assert isinstance(publisher_pid, int)

    def writer() -> None:
        with get_session_with_current_tenant() as other:
            other.execute(text("SET LOCAL statement_timeout = '10s'"))
            pid = other.scalar(select(func.pg_backend_pid()))
            assert isinstance(pid, int)
            waiting.put(pid)
            lock_group_membership(other)
            other.add(User__UserGroup(user_id=user_id, user_group_id=group_id))
            other.commit()

    with ThreadPoolExecutor(max_workers=1) as executor:
        statement = limit_db._decision_statement
        futures = []

        def start_writer(*args: Any, **kwargs: Any) -> CompoundSelect:
            futures.append(executor.submit(copy_context().run, writer))
            pid = waiting.get(timeout=5)
            with get_session_with_current_tenant() as observer:
                deadline = time.monotonic() + 5
                while (
                    publisher_pid
                    not in observer.execute(
                        select(func.pg_blocking_pids(pid))
                    ).scalar_one()
                ):
                    assert time.monotonic() < deadline, (
                        "Writer did not wait on publication"
                    )
                    time.sleep(0.01)
            return statement(*args, **kwargs)

        monkeypatch.setattr(limit_db, "_decision_statement", start_writer)
        read = catalog("alpha", "beta", body=b"grown")
        try:
            reconcile_marketplace__no_commit(
                marketplace_id,
                read,
                revision="r2",
                staged=stage(read),
                db_session=session,
            )
            assert len(futures) == 1 and not futures[0].done()
            with get_session_with_current_tenant() as observer:
                assert (
                    dict(
                        observer.execute(
                            select(Skill.id, Skill.current_version_id).where(
                                Skill.marketplace_id == marketplace_id
                            )
                        )
                        .tuples()
                        .all()
                    )
                    == old
                )
            session.commit()
        finally:
            session.rollback()
        futures[0].result(timeout=5)
    assert (
        session.scalar(
            select(User__UserGroup.user_id).where(
                User__UserGroup.user_id == user_id,
                User__UserGroup.user_group_id == group_id,
            )
        )
        == user_id
    )


def test_continuous_audience_growth_aborts_without_partial_publication(
    session: Session,
    marketplace: Marketplace,
    user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    group = make_group(session)
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    session.add(
        Marketplace__UserGroup(
            marketplace_id=marketplace.id,
            user_group_id=group.id,
            permission=SkillSharePermission.VIEWER,
        )
    )
    add_user_to_group(session, user, group)
    newcomers = [make_user(session, standard_account=True).id for _ in range(3)]
    group_id = group.id
    session.commit()
    initial = catalog("alpha", "beta")
    reconcile_marketplace__no_commit(
        marketplace.id,
        initial,
        revision="r1",
        staged=stage(initial),
        db_session=session,
    )
    session.commit()
    old = dict(
        session.execute(
            select(Skill.id, Skill.current_version_id).where(
                Skill.marketplace_id == marketplace.id
            )
        )
        .tuples()
        .all()
    )
    statement = limit_db._decision_statement
    observed = []

    def join_before_statement(*args: Any, **kwargs: Any) -> CompoundSelect:
        with get_session_with_current_tenant() as other:
            newcomer_id = newcomers[len(observed)]
            other.add(User__UserGroup(user_id=newcomer_id, user_group_id=group_id))
            other.commit()
        observed.append(newcomer_id)
        return statement(*args, **kwargs)

    monkeypatch.setattr(limit_db, "_decision_statement", join_before_statement)
    read = catalog("alpha", "beta", body=b"grown")
    with pytest.raises(OnyxError) as error:
        reconcile_marketplace__no_commit(
            marketplace.id, read, revision="r2", staged=stage(read), db_session=session
        )
    assert error.value.error_code == OnyxErrorCode.SERVICE_UNAVAILABLE
    session.commit()
    assert observed == newcomers
    assert (
        dict(
            session.execute(
                select(Skill.id, Skill.current_version_id).where(
                    Skill.marketplace_id == marketplace.id
                )
            )
            .tuples()
            .all()
        )
        == old
    )
    assert marketplace.last_synced_revision == "r1"


def test_accepted_growth_counts_against_later_entries(
    session: Session, marketplace: Marketplace, user: User
) -> None:
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    initial = catalog("alpha", "beta")
    reconcile_marketplace__no_commit(
        marketplace.id,
        initial,
        revision="r1",
        staged=stage(initial),
        db_session=session,
    )
    session.commit()
    usage = skill_usage_for_users([user.id], session)[user.id]
    sized_skill(
        session,
        size=SKILL_WRITE_MAX_BYTES - usage.charged_bytes - 3 * ROOM // 2,
        author=user,
    )
    session.commit()
    read = catalog("alpha", "beta", body=b"x" * ROOM)
    result = reconcile_marketplace__no_commit(
        marketplace.id, read, revision="r2", staged=stage(read), db_session=session
    )
    session.commit()
    assert result.blocked_entries == {"tools/beta": SKILL_LIMIT_BLOCK_REASON}
    assert len(result.changed_skill_ids) == 1
    assert (
        skill_usage_for_users([user.id], session)[user.id].charged_bytes
        == SKILL_WRITE_MAX_BYTES - ROOM // 2
    )


@pytest.mark.parametrize("false_refusal", [False, True])
def test_existing_duplicate_updates(
    session: Session, marketplace: Marketplace, false_refusal: bool, user: User
) -> None:
    member = user
    marketplace.public_permission = SkillSharePermission.VIEWER
    marketplace.installation_policy = SkillInstallationPolicy.REQUIRED
    old = sized_skill(
        session, name="duplicate", size=100, policy=SkillInstallationPolicy.REQUIRED
    )
    current = sized_skill(
        session,
        name="duplicate",
        size=1000 if false_refusal else 8000,
        policy=SkillInstallationPolicy.REQUIRED,
    )
    first = catalog(
        "duplicate", folder="older", body=b"x" * (1500 if false_refusal else 2000)
    )
    second_read = catalog(
        "duplicate", folder="newer", body=b"x" * (2000 if false_refusal else 6000)
    )
    second = CompleteMarketplace(
        entries=[
            second_read.entries[0].model_copy(update={"entry_key": "other/duplicate"})
        ]
    )
    for skill, read in ((old, first), (current, second)):
        entry = read.entries[0]
        assert isinstance(entry, ReadySkill)
        skill.marketplace_id = marketplace.id
        skill.marketplace_entry_key = entry.entry_key
        skill.marketplace_path = entry.path
    assert old.current_version is not None
    old.current_version.is_valid = False
    # Ensure creation order is independent of PostgreSQL's transaction timestamp.
    old.created_at = current.created_at - timedelta(days=1)
    sized_skill(
        session,
        size=SKILL_WRITE_MAX_BYTES - (2000 if false_refusal else 8000),
        author=member,
    )
    session.flush()
    before = {s.id: s.current_version_id for s in (old, current)}
    entries = [*first.entries, *second.entries]
    if not false_refusal:
        entries.extend(catalog("tail", body=b"x" * 7000).entries)
    read = CompleteMarketplace(entries=entries)
    result = reconcile_marketplace__no_commit(
        marketplace.id, read, revision="review", staged=stage(read), db_session=session
    )
    session.flush()
    assert old.current_version_id != before[old.id]
    assert current.current_version_id != before[current.id], result.blocked_entries
    if false_refusal:
        assert result.blocked_entries == {}
    else:
        assert len(result.blocked_entries) == 1, result.blocked_entries
        assert next(iter(result.blocked_entries)).endswith("tail")
