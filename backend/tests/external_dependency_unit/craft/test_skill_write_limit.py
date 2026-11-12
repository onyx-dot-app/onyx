"""The skill limit usage at the database level: backfilled versions. The write
check itself is covered through the API in
``tests/integration/tests/skills/test_skill_write_limit.py``."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.models import Plugin, PluginVersion, User
from onyx.db.plugin import set_plugin_preferences__no_commit
from onyx.db.plugin_access import load_user_plugin_states, skill_usage_by_user
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
