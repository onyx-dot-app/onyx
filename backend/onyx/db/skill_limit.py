"""The per-user skill limit check on writes.

A write may not move an active user from within the limits in
``onyx.skills.limits`` to past them. A user who is already past them is not
refused.

The check measures change: a plugin's share of a user's total depends only on
that plugin, so ``check_skill_limit`` measures the plugins the write changes
before and after it, and reads the full total only of the users whose share
grew. It takes the tenant-wide lock after the write's row locks, so the measure
after the write and the commit run one write at a time: a second write measures
after the first one commits.
"""

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import ColumnElement, and_, func, select
from sqlalchemy.orm import Session

from onyx.db.models import Sandbox, User
from onyx.db.plugin_access import (
    active_skill_user,
    load_user_plugin_states,
    skill_usage_by_user,
)
from onyx.db.utils import acquire_advisory_xact_lock, advisory_lock_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills import limits
from onyx.skills.built_in import BUILT_IN_SKILLS_USAGE
from onyx.skills.limits import SkillLimitRefusal, SkillUsage, SkillUsageModel
from shared_configs.contextvars import get_current_tenant_id

_LOCK_NAMESPACE = "onyx_skill_limit"
_MB = 1024 * 1024


def skill_limit_error(
    users_over: dict[UUID, SkillUsage], actor_id: UUID | None
) -> OnyxError:
    """413 with ``skill_limit``: the number of users the write puts over, the
    acting user's usage after the write when they are one of them, and the
    limits."""
    actor_usage = users_over.get(actor_id) if actor_id is not None else None
    max_mb = limits.SKILL_WRITE_MAX_BYTES // _MB
    if actor_usage is not None and len(users_over) == 1:
        detail = (
            f"This would put your skills at {actor_usage.bytes / _MB:.1f} MB in "
            f"{actor_usage.files:,} files. The limit is {max_mb} MB and "
            f"{limits.SKILL_WRITE_MAX_FILES:,} files."
        )
    else:
        count = len(users_over)
        detail = (
            f"This change would put {count} {'user' if count == 1 else 'users'} "
            f"past the skill limit of {max_mb} MB or "
            f"{limits.SKILL_WRITE_MAX_FILES:,} files."
        )
    refusal = SkillLimitRefusal(
        users_over=len(users_over),
        usage=(
            SkillUsageModel(bytes=actor_usage.bytes, files=actor_usage.files)
            if actor_usage is not None
            else None
        ),
        max_bytes=limits.SKILL_WRITE_MAX_BYTES,
        max_files=limits.SKILL_WRITE_MAX_FILES,
    )
    return OnyxError(
        OnyxErrorCode.SKILL_LIMIT_EXCEEDED,
        detail,
        extra={"skill_limit": refusal.model_dump(mode="json")},
    )


def _usage(
    user_filter: ColumnElement[bool],
    db_session: Session,
    plugin_ids: Iterable[UUID] | None = None,
) -> dict[UUID, SkillUsage]:
    return skill_usage_by_user(
        load_user_plugin_states(user_filter, db_session, plugin_ids, runnable_only=True)
    )


@contextmanager
def check_skill_limit(
    db_session: Session,
    plugin_ids: Iterable[UUID],
    actor_id: UUID | None,
    *,
    user_ids: Iterable[UUID] | None = None,
) -> Iterator[None]:
    """Refuse with 413 when the write in the block moves an active user past
    the write limit. ``plugin_ids`` are the plugins it changes or creates;
    ``user_ids`` limits the check to users the write can change."""
    ids = set(plugin_ids)
    user_filter = active_skill_user()
    if user_ids is not None:
        user_filter = and_(user_filter, User.__table__.c.id.in_(set(user_ids)))
    db_session.flush()
    before = _usage(user_filter, db_session, ids)
    yield
    db_session.flush()
    acquire_advisory_xact_lock(
        db_session, advisory_lock_id(_LOCK_NAMESPACE, get_current_tenant_id())
    )
    after = _usage(user_filter, db_session, ids)
    grown = sorted(
        user_id
        for user_id, usage in after.items()
        if usage.grew_from(before.get(user_id, SkillUsage()))
    )
    if not grown:
        return
    totals = _usage(and_(user_filter, User.__table__.c.id.in_(grown)), db_session)
    users_over: dict[UUID, SkillUsage] = {}
    for user_id in grown:
        total_after = totals.get(user_id, SkillUsage()) + BUILT_IN_SKILLS_USAGE
        total_before = total_after - after[user_id] + before.get(user_id, SkillUsage())
        if total_after.is_over_write_limit and not total_before.is_over_write_limit:
            users_over[user_id] = total_after
    if users_over:
        raise skill_limit_error(users_over, actor_id)


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
