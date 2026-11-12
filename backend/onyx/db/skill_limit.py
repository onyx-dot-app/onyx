"""The per-user skill limit check on the acting user's own writes.

A user's own write (turning a skill on, an upload or import, a new version of
a skill they run) may not move them from within the limits in
``onyx.skills.limits`` to past them. A user who is already past them is not
refused. Writes that change what other users get (settings, shares,
publishing, membership) are not checked: the run-time limit, the "did not
load" notice and the admin list cover those users.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from onyx.db.models import Sandbox, User
from onyx.db.plugin_access import (
    active_skill_user,
    load_user_plugin_states,
    skill_usage_by_user,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills import limits
from onyx.skills.built_in import BUILT_IN_SKILLS_USAGE
from onyx.skills.limits import SkillLimitRefusal, SkillUsage, SkillUsageModel

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
        usage=SkillUsageModel(bytes=usage.bytes, files=usage.files),
        max_bytes=limits.SKILL_WRITE_MAX_BYTES,
        max_files=limits.SKILL_WRITE_MAX_FILES,
    )
    return OnyxError(
        OnyxErrorCode.SKILL_LIMIT_EXCEEDED,
        detail,
        extra={"skill_limit": refusal.model_dump(mode="json")},
    )


def _usage(
    users: Iterable[UUID] | ColumnElement[bool],
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
        _usage([user_id], db_session).get(user_id, SkillUsage()) + BUILT_IN_SKILLS_USAGE
    )
    total_before = total_after - after + before
    if total_after.is_over_write_limit and not total_before.is_over_write_limit:
        raise skill_limit_error(total_after)


# --- Users past the write limit ------------------------------------------------


@dataclass(frozen=True)
class UserPastWriteLimit:
    user_id: UUID
    email: str
    usage: SkillUsage
    # Plugins the last push left out of the user's sandbox.
    skills_not_loaded: int


def users_past_write_limit(db_session: Session) -> list[UserPastWriteLimit]:
    """Active users past the write limit (500 MB or 5,000 files), largest
    first, with how many plugins the last push left out of their sandbox."""
    over = {
        user_id: total
        for user_id, usage in _usage(active_skill_user(), db_session).items()
        if (total := usage + BUILT_IN_SKILLS_USAGE).is_over_write_limit
    }
    if not over:
        return []
    user = User.__table__.c
    emails: dict[UUID, str] = {  # noqa: C416  # unpacking types the SQLAlchemy Row
        user_id: email
        for user_id, email in db_session.execute(
            select(user.id, user.email).where(user.id.in_(over))
        )
    }
    not_loaded: dict[UUID, int] = {  # noqa: C416  # unpacking types the SQLAlchemy Row
        user_id: count
        for user_id, count in db_session.execute(
            select(
                Sandbox.user_id,
                func.max(func.jsonb_array_length(Sandbox.skill_omissions)),
            )
            .where(Sandbox.user_id.in_(over))
            .group_by(Sandbox.user_id)
        )
    }
    return sorted(
        (
            UserPastWriteLimit(
                user_id=user_id,
                email=emails[user_id],
                usage=usage,
                skills_not_loaded=not_loaded.get(user_id) or 0,
            )
            for user_id, usage in over.items()
        ),
        key=lambda item: (-item.usage.bytes, item.email),
    )
