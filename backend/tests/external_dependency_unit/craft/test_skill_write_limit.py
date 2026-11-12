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

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Plugin, PluginVersion, User
from onyx.db.plugin import set_plugin_preferences__no_commit
from onyx.db.plugin_access import load_user_plugin_states, skill_usage_by_user
from onyx.db.skill import (
    fetch_skill_to_save,
    replace_skill_bundle,
    set_skill_enabled_for_user,
)
from onyx.file_store.file_store import get_default_file_store
from onyx.skills.ingest import delete_bundle_blob, ingest_skill_bundle
from onyx.skills.limits import SkillUsage
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user

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


def _wait_for_lock_waiter(timeout: float = 10.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with get_session_with_current_tenant() as session:
            if session.scalar(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
            ):
                return True
        time.sleep(0.05)
    return False


def test_bundle_save_and_toggle_of_one_user_do_not_deadlock(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """A save holds the skill row while the same user's toggle of that skill
    waits. Both take the user's lock first, so the save then finishes."""
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
    save_holds_skill = threading.Event()
    toggle_waits = threading.Event()

    def save() -> None:
        try:
            with get_session_with_current_tenant() as session:
                saver = session.get(User, user_id)
                assert saver is not None
                locked = fetch_skill_to_save(skill_id, saver, session)
                save_holds_skill.set()
                toggle_waits.wait(timeout=30)
                replace_skill_bundle(
                    skill=locked,
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
            save_holds_skill.wait(timeout=30)
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
        for target in (save, toggle)
    ]
    try:
        for thread in threads:
            thread.start()
        assert save_holds_skill.wait(timeout=30)
        assert _wait_for_lock_waiter()
        toggle_waits.set()
        for thread in threads:
            thread.join(timeout=60)
        assert errors == []
    finally:
        delete_bundle_blob(file_store, ingested.bundle_file_id)
