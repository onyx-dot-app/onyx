"""The per-user skill limit check on the acting user's own writes.

A user's own write (turning a skill on, an upload or import, a new version of
a skill they run) may not move them from within the limits in
``onyx.skills.limits`` to past them. A user who is already past them is not
refused. Writes that change what other users get (settings, shares,
publishing, membership) are not checked.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import User
from onyx.db.plugin_access import (
    load_user_plugin_states,
    skill_usage_by_user,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills import limits
from onyx.skills.built_in import built_in_skills_usage
from onyx.skills.models import SkillLimitRefusal, SkillUsage

_MB = 1024 * 1024


def lock_user_skill_preferences(user_id: UUID, db_session: Session) -> None:
    """Serialize one user's skill writes on the user row, without blocking the
    foreign-key reads of sharing writes."""
    db_session.execute(
        select(User.__table__.c.id)
        .where(User.__table__.c.id == user_id)
        .with_for_update(key_share=True)
    )


def skill_limit_error(usage: SkillUsage) -> OnyxError:
    """413 with ``skill_limit``: the user's usage after the write, and the
    limits."""
    detail = (
        f"This would put your skills at {usage.bytes / _MB:.1f} MB in "
        f"{usage.files:,} files. The limit is "
        f"{limits.SKILL_WRITE_MAX_BYTES // _MB} MB and "
        f"{limits.SKILL_WRITE_MAX_FILES:,} files."
    )
    refusal = SkillLimitRefusal(
        usage=usage,
        max_bytes=limits.SKILL_WRITE_MAX_BYTES,
        max_files=limits.SKILL_WRITE_MAX_FILES,
    )
    return OnyxError(
        OnyxErrorCode.SKILL_LIMIT_EXCEEDED,
        detail,
        extra={"skill_limit": refusal.model_dump(mode="json")},
    )


def _usage(
    users: Iterable[UUID],
    db_session: Session,
    plugin_ids: Iterable[UUID] | None = None,
) -> dict[UUID, SkillUsage]:
    return skill_usage_by_user(
        load_user_plugin_states(users, db_session, plugin_ids, runnable_only=True)
    )


@contextmanager
def check_skill_limit(
    db_session: Session, plugin_ids: Iterable[UUID], user_id: UUID
) -> Iterator[None]:
    """Refuse with 413 when the user's own write in the block moves them past
    the write limit. ``plugin_ids`` are the plugins it changes or creates.
    Holds the user's lock, so two writes of one user check one at a time."""
    ids = set(plugin_ids)
    lock_user_skill_preferences(user_id, db_session)
    db_session.flush()
    before = _usage([user_id], db_session, ids).get(user_id, SkillUsage())
    yield
    db_session.flush()
    after = _usage([user_id], db_session, ids).get(user_id, SkillUsage())
    if not after.grew_from(before):
        return
    total_after = (
        _usage([user_id], db_session).get(user_id, SkillUsage())
        + built_in_skills_usage()
    )
    total_before = total_after - after + before
    if limits.is_over_write_limit(total_after) and not limits.is_over_write_limit(
        total_before
    ):
        raise skill_limit_error(total_after)
