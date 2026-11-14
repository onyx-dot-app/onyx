"""The skill limit at the database level: backfilled versions and the lock
order of a user's own writes. The write check itself is covered through the
API in ``tests/integration/tests/skills/test_skill_write_limit.py``."""

from __future__ import annotations

import contextvars
import io
import threading
import time
import zipfile
from uuid import UUID

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import PluginInstallationPolicy
from onyx.db.models import Plugin, PluginVersion, Skill, User
from onyx.db.plugin import set_plugin_preferences__no_commit
from onyx.db.plugin_access import load_user_plugin_states, skill_usage_by_user
from onyx.db.skill import (
    replace_skill_bundle,
    set_skill_enabled_for_user,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.file_store.file_store import get_default_file_store
from onyx.server.features.skill import api as skill_api
from onyx.skills.ingest import IngestedBundle, delete_bundle_blob, ingest_skill_bundle
from onyx.skills.limits import SKILL_WRITE_MAX_BYTES
from onyx.skills.models import SkillUsage
from tests.external_dependency_unit.craft.db_helpers import (
    make_skill,
    make_skillless_plugin,
    make_user,
)

_MB = 1024 * 1024


def _set_size(db_session: Session, plugin_id: UUID, size: int, files: int) -> None:
    current = select(Plugin.current_version_id).where(Plugin.id == plugin_id)
    db_session.execute(
        update(PluginVersion)
        .where(PluginVersion.id == current.scalar_subquery())
        .values(unpacked_size_bytes=size, file_count=files)
    )
    db_session.flush()


def _usage(db_session: Session, user: User, plugin_id: UUID) -> int:
    return (
        skill_usage_by_user(load_user_plugin_states([user.id], db_session, [plugin_id]))
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


def test_plugin_with_no_skills_counts_as_zero(db_session: Session) -> None:
    """A Required plugin with no skills and no recorded size runs for the user
    and adds nothing to the user's usage."""
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=user.id)
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    _set_size(db_session, skill.id, 3 * _MB, 7)
    plugin = make_skillless_plugin(
        db_session,
        published=True,
        installation_policy=PluginInstallationPolicy.REQUIRED,
    )

    states = load_user_plugin_states(
        [user.id], db_session, [skill.id, plugin.id], runnable_only=True
    )
    assert {state.plugin_id for state in states} == {skill.id, plugin.id}
    assert skill_usage_by_user(states)[user.id] == SkillUsage(bytes=3 * _MB, files=7)

    # Each NULL counts as 0 on its own: a known file count still counts.
    current = select(Plugin.current_version_id).where(Plugin.id == skill.id)
    db_session.execute(
        update(PluginVersion)
        .where(PluginVersion.id == current.scalar_subquery())
        .values(unpacked_size_bytes=None)
    )
    db_session.flush()
    states = load_user_plugin_states(
        [user.id], db_session, [skill.id, plugin.id], runnable_only=True
    )
    assert skill_usage_by_user(states)[user.id] == SkillUsage(bytes=0, files=7)


def _wait_for_lock_waiter(blocker_pid: int, timeout: float = 10.0) -> bool:
    """Wait until a connection waits on a lock that ``blocker_pid`` holds."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with get_session_with_current_tenant() as session:
            if session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' "
                    "AND :blocker = ANY(pg_blocking_pids(pid))"
                ),
                {"blocker": blocker_pid},
            ):
                return True
        time.sleep(0.05)
    return False


def test_toggle_does_not_wait_for_a_save_that_is_still_ingesting(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A save reads the skill without a lock while it ingests the bundle, so
    the same user's toggle finishes at once. The save then takes the user's
    lock and the skill row, in the toggle's order, and finishes too."""
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=user.id)
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    db_session.commit()
    user_id, skill_id = user.id, skill.id
    file_store = get_default_file_store()
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as bundle_zip:
        bundle_zip.writestr(
            "SKILL.md", f"---\nname: {skill.name}\ndescription: Saved\n---\n"
        )
    ingested = ingest_skill_bundle(
        bundle.getvalue(), "save.zip", file_store, expected_name=skill.name
    )
    errors: list[BaseException] = []
    save_read_skill = threading.Event()
    toggle_done = threading.Event()

    def save() -> None:
        try:
            with get_session_with_current_tenant() as session:
                saver = session.get(User, user_id)
                assert saver is not None
                skill_to_save = session.get(Skill, skill_id)
                assert skill_to_save is not None
                save_read_skill.set()
                toggle_done.wait(timeout=30)
                replace_skill_bundle(
                    skill=skill_to_save,
                    ingested=ingested,
                    base_version_id=None,
                    user=saver,
                    skip_if_unchanged=False,
                    db_session=session,
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    def toggle() -> None:
        try:
            save_read_skill.wait(timeout=30)
            with get_session_with_current_tenant() as session:
                toggler = session.get(User, user_id)
                assert toggler is not None
                set_skill_enabled_for_user(
                    skill_id=skill_id, enabled=False, user=toggler, db_session=session
                )
                session.commit()
            toggle_done.set()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(target,))
        for target in (save, toggle)
    ]
    try:
        for thread in threads:
            thread.start()
        assert toggle_done.wait(timeout=10)
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
    finally:
        delete_bundle_blob(file_store, ingested.bundle_file_id)


def test_two_writes_of_one_user_cannot_both_pass_the_limit(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Two toggles that each fit but together pass the limit: the user's lock
    makes the second wait for the first to commit, so it sees the first and is
    refused with 413."""
    user = make_user(db_session, standard_account=True)
    first = make_skill(db_session, author_user_id=user.id)
    second = make_skill(db_session, author_user_id=user.id)
    for skill in (first, second):
        _set_size(db_session, skill.id, SKILL_WRITE_MAX_BYTES // 2 + _MB, 1)
    db_session.commit()
    user_id = user.id
    errors: list[BaseException] = []
    first_pids: list[int] = []
    first_toggled = threading.Event()
    first_may_commit = threading.Event()

    def toggle_first() -> None:
        try:
            with get_session_with_current_tenant() as session:
                toggler = session.get(User, user_id)
                assert toggler is not None
                set_skill_enabled_for_user(
                    skill_id=first.id, enabled=True, user=toggler, db_session=session
                )
                first_pids.append(session.scalar(text("SELECT pg_backend_pid()")))
                first_toggled.set()
                first_may_commit.wait(timeout=30)
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    def toggle_second() -> None:
        try:
            first_toggled.wait(timeout=30)
            with get_session_with_current_tenant() as session:
                toggler = session.get(User, user_id)
                assert toggler is not None
                set_skill_enabled_for_user(
                    skill_id=second.id, enabled=True, user=toggler, db_session=session
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(target,))
        for target in (toggle_first, toggle_second)
    ]
    for thread in threads:
        thread.start()
    assert first_toggled.wait(timeout=30)
    _wait_for_lock_waiter(first_pids[0], timeout=5)
    first_may_commit.set()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert len(errors) == 1
    (refusal,) = errors
    assert isinstance(refusal, OnyxError)
    assert refusal.error_code == OnyxErrorCode.SKILL_LIMIT_EXCEEDED


def _ingest_saved_bundle(name: str) -> IngestedBundle:
    bundle = io.BytesIO()
    with zipfile.ZipFile(bundle, "w") as bundle_zip:
        bundle_zip.writestr("SKILL.md", f"---\nname: {name}\ndescription: Saved\n---\n")
    file_store = get_default_file_store()
    ingested = ingest_skill_bundle(
        bundle.getvalue(), "save.zip", file_store, expected_name=name
    )
    return ingested


def test_a_save_rechecks_edit_access_under_its_locks(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """The routes check edit access before they ingest, without a lock. An
    editor whose share is removed meanwhile cannot save: the locked save checks
    again."""
    owner = make_user(db_session, standard_account=True)
    former_editor = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=owner.id)
    db_session.commit()
    ingested = _ingest_saved_bundle(skill.name)
    bundle_file_id = ingested.bundle_file_id
    try:
        try:
            replace_skill_bundle(
                skill=skill,
                ingested=ingested,
                base_version_id=None,
                user=former_editor,
                skip_if_unchanged=False,
                db_session=db_session,
            )
        except OnyxError as exc:
            assert exc.error_code is OnyxErrorCode.NOT_FOUND
        else:
            raise AssertionError("a user without edit access saved a version")
        db_session.rollback()
    finally:
        delete_bundle_blob(get_default_file_store(), bundle_file_id)


def test_a_file_edit_and_a_toggle_take_locks_in_one_order(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A file edit reads the bundle under the save locks (the user's lock,
    then the skill row, then the plugin). A toggle by the same user meanwhile
    waits for the edit and does not deadlock with it."""
    user = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=user.id)
    set_plugin_preferences__no_commit(user.id, [skill.id], True, db_session)
    db_session.commit()
    user_id, skill_id = user.id, skill.id
    ingested = _ingest_saved_bundle(skill.name)
    bundle_file_id = ingested.bundle_file_id
    # The helper skill has no stored blob; the locks are what this test checks.
    monkeypatch.setattr(skill_api, "read_skill_bundle_blob", lambda *_: b"")
    errors: list[BaseException] = []
    edit_read_bundle = threading.Event()

    def edit() -> None:
        try:
            with get_session_with_current_tenant() as session:
                editor = session.get(User, user_id)
                skill_to_edit = session.get(Skill, skill_id)
                assert editor is not None and skill_to_edit is not None
                skill_api._bundle_to_edit(skill_to_edit, editor, session)
                edit_read_bundle.set()
                time.sleep(1)
                replace_skill_bundle(
                    skill=skill_to_edit,
                    ingested=ingested,
                    base_version_id=None,
                    user=editor,
                    skip_if_unchanged=False,
                    db_session=session,
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    def toggle() -> None:
        try:
            edit_read_bundle.wait(timeout=30)
            with get_session_with_current_tenant() as session:
                toggler = session.get(User, user_id)
                assert toggler is not None
                set_skill_enabled_for_user(
                    skill_id=skill_id, enabled=False, user=toggler, db_session=session
                )
                session.commit()
        except BaseException as exc:
            errors.append(exc)

    threads = [
        threading.Thread(target=contextvars.copy_context().run, args=(target,))
        for target in (edit, toggle)
    ]
    try:
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert not any(thread.is_alive() for thread in threads)
        assert errors == []
    finally:
        delete_bundle_blob(get_default_file_store(), bundle_file_id)
