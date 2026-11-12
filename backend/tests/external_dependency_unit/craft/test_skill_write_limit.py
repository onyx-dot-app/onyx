"""The skill limit check on writes (G7a), at the database level: the warning
for users already past the limit, app connections, backfilled versions and the
wait on the tenant-wide lock."""

from __future__ import annotations

import contextvars
import statistics
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from onyx.db import skill_limit
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import PluginInstallationPolicy, SkillInstallationPolicy
from onyx.db.external_app import (
    replace_custom_skill_associations__no_commit,
    upsert_external_app_user_credential__no_commit,
)
from onyx.db.models import Plugin, PluginVersion, Skill, User, UserPluginPreference
from onyx.db.plugin import set_plugin_preferences__no_commit
from onyx.db.plugin_access import active_skill_user, plugin_usage_by_user
from onyx.db.skill import (
    connect_external_app_within_skill_limit__no_commit,
    set_skill_enabled_for_user,
    set_skill_installation_policy,
)
from onyx.db.skill_limit import SkillLimitCheck, built_in_skill_usage
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES, SkillUsage
from onyx.utils.logger import setup_logger
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
    make_user,
)

logger = setup_logger()

_MB = 1024 * 1024


def _set_size(db_session: Session, plugin_id: UUID, size: int, files: int) -> None:
    current = select(Plugin.current_version_id).where(Plugin.id == plugin_id)
    db_session.execute(
        update(PluginVersion)
        .where(PluginVersion.id == current.scalar_subquery())
        .values(unpacked_size_bytes=size, file_count=files)
    )
    db_session.flush()


def _own_enabled_skill(
    db_session: Session, user: User, size: int, files: int = 1
) -> UUID:
    skill = make_skill(db_session, author_user_id=user.id)
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    _set_size(db_session, skill.id, size, files)
    return skill.id


def _fill(db_session: Session, user: User, free_bytes: int) -> UUID:
    built_ins = built_in_skill_usage(db_session)
    return _own_enabled_skill(
        db_session, user, SKILL_WRITE_MAX_BYTES - built_ins.bytes - free_bytes
    )


def _usage(db_session: Session, user: User, plugin_id: UUID) -> int:
    return (
        plugin_usage_by_user(User.__table__.c.id == user.id, db_session, [plugin_id])
        .get(user.id, SkillUsage())
        .bytes
    )


def test_backfilled_version_counts_as_zero(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=user.id)
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    assert (
        db_session.scalar(
            select(PluginVersion.unpacked_size_bytes)
            .join(Plugin, Plugin.current_version_id == PluginVersion.id)
            .where(Plugin.id == skill.id)
        )
        is None
    )
    assert _usage(db_session, user, skill.id) == 0

    _set_size(db_session, skill.id, 3 * _MB, 7)
    assert _usage(db_session, user, skill.id) == 3 * _MB


def test_already_over_user_gets_a_warning(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    _fill(db_session, user, free_bytes=-1 * _MB)
    skill = make_skill(db_session, author_user_id=user.id)
    _set_size(db_session, skill.id, 1 * _MB, 1)

    check = SkillLimitCheck(db_session, user.id, [user.id])
    check.track([skill.id])
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    outcome = check.finish()
    assert outcome.users_over == {}
    assert outcome.users_already_over == 1


def test_inactive_user_does_not_count(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    _fill(db_session, user, free_bytes=1 * _MB)
    skill = make_skill(db_session, author_user_id=user.id)
    _set_size(db_session, skill.id, 2 * _MB, 1)
    user.is_active = False
    db_session.flush()

    check = SkillLimitCheck(db_session, None, None)
    check.track([skill.id])
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    assert check.finish().users_over == {}
    assert (
        db_session.scalar(
            select(active_skill_user())
            .select_from(User.__table__)
            .where(User.__table__.c.id == user.id)
        )
        is False
    )


def test_app_connect_leaves_the_skill_off(db_session: Session) -> None:
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    db_session.execute(
        update(Plugin)
        .where(Plugin.id == skill.id)
        .values(installation_policy=PluginInstallationPolicy.DEFAULT)
    )
    _set_size(db_session, skill.id, 2 * _MB, 1)
    app = make_external_app(
        db_session, skill=skill, auth_template={"Authorization": "Bearer {token}"}
    )
    filler = _fill(db_session, user, free_bytes=1 * _MB)

    def connect() -> object:
        return upsert_external_app_user_credential__no_commit(
            db_session,
            external_app_id=app.id,
            user_id=user.id,
            user_credentials={"token": "t"},
        )

    left_off = connect_external_app_within_skill_limit__no_commit(
        app.id, user, connect, db_session
    )
    assert left_off == [skill.id]
    preference = db_session.get(UserPluginPreference, (user.id, skill.id))
    assert preference is not None and preference.enabled is False

    # With room, a new connection keeps it on.
    db_session.delete(preference)
    _set_size(db_session, filler, 0, 0)
    assert (
        connect_external_app_within_skill_limit__no_commit(
            app.id, user, connect, db_session
        )
        == []
    )


def test_concurrent_writes_wait_for_the_lock(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ten users turn on a skill at the same time. Each write waits in line
    for the tenant-wide lock. The waits are logged for the PR. Ten writers fit
    the test engine's pool next to the test session."""
    writers = 10
    users = [make_user(db_session, standard_account=True) for _ in range(writers)]
    skills = [make_skill(db_session, author_user_id=user.id) for user in users]
    for skill in skills:
        _set_size(db_session, skill.id, 1 * _MB, 3)
    db_session.commit()

    waits: list[float] = []
    real_lock = skill_limit.lock_skill_limit

    def recorded_lock(session: Session) -> float:
        wait_ms = real_lock(session)
        waits.append(wait_ms)
        return wait_ms

    monkeypatch.setattr(skill_limit, "lock_skill_limit", recorded_lock)
    barrier = threading.Barrier(writers)
    errors: list[BaseException] = []

    def toggle(user_id: UUID, skill_id: UUID) -> None:
        try:
            with get_session_with_current_tenant() as session:
                user = session.get(User, user_id)
                assert user is not None
                barrier.wait(timeout=60)
                set_skill_enabled_for_user(
                    skill_id=skill_id, enabled=True, user=user, db_session=session
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(
            target=contextvars.copy_context().run,
            args=(toggle, user.id, skill.id),
        )
        for user, skill in zip(users, skills, strict=True)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert len(waits) == writers
    logger.info(
        "Skill limit lock wait over %d concurrent writes: min %.1f ms, "
        "median %.1f ms, max %.1f ms",
        writers,
        min(waits),
        statistics.median(waits),
        max(waits),
    )
    db_session.expire_all()
    for user, skill in zip(users, skills, strict=True):
        preference = db_session.get(UserPluginPreference, (user.id, skill.id))
        assert preference is not None and preference.enabled


def _wait_for_lock_waiter(timeout: float = 10.0) -> bool:
    """True once another backend waits on a row or advisory lock."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with get_session_with_current_tenant() as session:
            waiting = session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
            )
        if waiting:
            return True
        time.sleep(0.05)
    return False


@dataclass(frozen=True)
class _RaceIds:
    user_id: UUID
    skill_id: UUID
    app_id: int


def _race_with_app_connect(
    db_session: Session, other_write: Callable[[Session, _RaceIds], None]
) -> list[BaseException]:
    """Connect a near-limit user to an app whose Installed-by-default skill
    does not fit. While the connect holds its locks, run ``other_write`` in a
    second session. Returns the errors of both sessions."""
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, is_public=True)
    db_session.execute(
        update(Plugin)
        .where(Plugin.id == skill.id)
        .values(installation_policy=PluginInstallationPolicy.DEFAULT)
    )
    _set_size(db_session, skill.id, 2 * _MB, 1)
    app = make_external_app(
        db_session, skill=skill, auth_template={"Authorization": "Bearer {token}"}
    )
    _fill(db_session, user, free_bytes=1 * _MB)
    db_session.commit()
    ids = _RaceIds(user.id, skill.id, app.id)
    user_id, app_id = ids.user_id, ids.app_id

    connect_holds_locks = threading.Event()
    other_waits = threading.Event()
    errors: list[BaseException] = []

    def connect_app() -> None:
        try:
            with get_session_with_current_tenant() as session:
                connecting_user = session.get(User, user_id)
                assert connecting_user is not None

                def connect() -> object:
                    connect_holds_locks.set()
                    other_waits.wait(timeout=30)
                    return upsert_external_app_user_credential__no_commit(
                        session,
                        external_app_id=app_id,
                        user_id=user_id,
                        user_credentials={"token": "t"},
                    )

                connect_external_app_within_skill_limit__no_commit(
                    app_id, connecting_user, connect, session
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    def run_other() -> None:
        try:
            if not connect_holds_locks.wait(timeout=30):
                raise TimeoutError("The connect did not start.")
            with get_session_with_current_tenant() as session:
                other_write(session, ids)
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(target,))
        for target in (connect_app, run_other)
    ]
    for thread in threads:
        thread.start()
    assert connect_holds_locks.wait(timeout=30)
    # The second write now waits on a lock the connect holds.
    assert _wait_for_lock_waiter()
    other_waits.set()
    for thread in threads:
        thread.join(timeout=60)
    return errors


def test_app_connect_and_same_user_toggle_do_not_deadlock(
    db_session: Session,
) -> None:
    def toggle(session: Session, ids: _RaceIds) -> None:
        user = session.get(User, ids.user_id)
        assert user is not None
        set_skill_enabled_for_user(
            skill_id=ids.skill_id, enabled=False, user=user, db_session=session
        )

    assert _race_with_app_connect(db_session, toggle) == []


def test_app_connect_and_admin_setting_change_do_not_deadlock(
    db_session: Session,
) -> None:
    def change_setting(session: Session, ids: _RaceIds) -> None:
        skill = session.get(Skill, ids.skill_id)
        assert skill is not None
        set_skill_installation_policy(skill, SkillInstallationPolicy.AVAILABLE, session)

    assert _race_with_app_connect(db_session, change_setting) == []


def test_app_connect_and_app_skill_change_do_not_deadlock(
    db_session: Session,
) -> None:
    def relink(session: Session, ids: _RaceIds) -> None:
        replace_custom_skill_associations__no_commit(
            session, external_app_id=ids.app_id, skill_ids=[ids.skill_id]
        )

    assert _race_with_app_connect(db_session, relink) == []
