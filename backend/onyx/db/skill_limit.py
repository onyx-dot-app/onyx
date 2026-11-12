"""The per-user skill limit check on writes.

A write may not move an active user from within the limits in
``onyx.skills.limits`` to past them. A user who is already past them gets a
warning, not a refusal.

The check measures change, not a copy of the access rules. A plugin's share of
a user's total depends only on that plugin's rows, the user's choice for it,
the user's groups and the user's app connection. A write changes a known set
of plugins, so:

1. Before the write, ``track`` measures those plugins for every user.
2. After the write, ``finish`` takes the tenant-wide lock, measures the same
   plugins again, and reads the full total of each user whose share grew.
   The total before is the total after minus that growth.

The lock is taken after every row lock of the write, and nothing waits for a
row lock while it is held, so it cannot deadlock with them. It serializes the
measure and the commit: a second write measures after the first one commits
and sees it.
"""

import time
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import ColumnElement, and_, select
from sqlalchemy.orm import Session

from onyx.db.models import Skill, User
from onyx.db.plugin_access import (
    RuntimePluginCharge,
    active_skill_user,
    plugin_usage_by_user,
    runtime_plugin_charges,
)
from onyx.db.utils import acquire_advisory_xact_lock, advisory_lock_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills import limits
from onyx.skills.built_in import (
    BUILT_IN_SKILL_RUNTIME_USAGE,
    BUILT_IN_SKILL_USAGE,
    BUILT_IN_SKILLS,
)
from onyx.skills.limits import (
    SkillLimitRefusal,
    SkillUsage,
    SkillUsageModel,
    runtime_keep_key,
    runtime_omission_reason,
)
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

_LOCK_NAMESPACE = "onyx_skill_limit"
_SESSION_KEY = "onyx_skill_limit_check"
_MB = 1024 * 1024


@dataclass(frozen=True)
class SkillLimitOutcome:
    # Users the write moves past a limit, with their usage after it.
    users_over: dict[UUID, SkillUsage] = field(default_factory=dict)
    # Users already past a limit whose usage grows.
    users_already_over: int = 0
    lock_wait_ms: float = 0.0


def lock_skill_limit(db_session: Session) -> float:
    """Take the tenant-wide skill limit lock until the transaction ends.
    Returns the wait in milliseconds."""
    started = time.perf_counter()
    acquire_advisory_xact_lock(
        db_session, advisory_lock_id(_LOCK_NAMESPACE, get_current_tenant_id())
    )
    wait_ms = (time.perf_counter() - started) * 1000
    logger.info("Skill limit lock wait: %.1f ms", wait_ms)
    return wait_ms


def built_in_skill_usage(
    db_session: Session, usage_table: Mapping[str, SkillUsage] = BUILT_IN_SKILL_USAGE
) -> SkillUsage:
    """Usage of the built-in skills the tenant has and offers. Every user
    counts all of them. ``usage_table`` gives each built-in's usage."""
    usage = SkillUsage()
    for built_in_skill_id in set(
        db_session.scalars(
            select(Skill.built_in_skill_id).where(Skill.built_in_skill_id.is_not(None))
        )
    ):
        definition = BUILT_IN_SKILLS.get(built_in_skill_id or "")
        if definition is not None and definition.is_available(db_session):
            usage += usage_table[definition.built_in_skill_id]
    return usage


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


def skill_limit_refusal(exc: OnyxError) -> SkillLimitRefusal | None:
    """The ``skill_limit`` of a SKILL_LIMIT_EXCEEDED error, for a response
    that reports one failed item rather than the whole request."""
    if exc.error_code is not OnyxErrorCode.SKILL_LIMIT_EXCEEDED or not exc.extra:
        return None
    return SkillLimitRefusal.model_validate(exc.extra["skill_limit"])


class SkillLimitCheck:
    """One check for one transaction. ``user_ids`` None checks every active
    user; otherwise only those users can change."""

    def __init__(
        self,
        db_session: Session,
        actor_id: UUID | None,
        user_ids: Iterable[UUID] | None,
    ) -> None:
        self._db_session = db_session
        self.actor_id = actor_id
        self.user_ids = frozenset(user_ids) if user_ids is not None else None
        self._plugin_ids: set[UUID] = set()
        self._before: dict[UUID, SkillUsage] = {}

    def _user_filter(self) -> ColumnElement[bool]:
        if self.user_ids is None:
            return active_skill_user()
        return and_(active_skill_user(), User.__table__.c.id.in_(self.user_ids))

    def covers(self, user_ids: Iterable[UUID] | None) -> bool:
        if self.user_ids is None:
            return True
        return user_ids is not None and set(user_ids) <= self.user_ids

    def track(self, plugin_ids: Iterable[UUID]) -> None:
        """Measure plugins the write is about to change. Call before any write
        to them."""
        new = set(plugin_ids) - self._plugin_ids
        if not new:
            return
        self._db_session.flush()
        for user_id, usage in plugin_usage_by_user(
            self._user_filter(), self._db_session, new
        ).items():
            self._before[user_id] = self._before.get(user_id, SkillUsage()) + usage
        self._plugin_ids |= new

    def track_new(self, plugin_ids: Iterable[UUID]) -> None:
        """Plugins this transaction created. Nobody had them before."""
        self._plugin_ids |= set(plugin_ids)

    def measure(self) -> SkillLimitOutcome:
        """Take the lock and compare each user's usage after the write with the
        usage before it."""
        if not self._plugin_ids:
            return SkillLimitOutcome()
        self._db_session.flush()
        wait_ms = lock_skill_limit(self._db_session)
        user_filter = self._user_filter()
        after = plugin_usage_by_user(user_filter, self._db_session, self._plugin_ids)
        grown = sorted(
            user_id
            for user_id, usage in after.items()
            if usage.grew_from(self._before.get(user_id, SkillUsage()))
        )
        if not grown:
            return SkillLimitOutcome(lock_wait_ms=wait_ms)
        totals = plugin_usage_by_user(
            and_(user_filter, User.__table__.c.id.in_(grown)), self._db_session
        )
        built_ins = built_in_skill_usage(self._db_session)
        users_over: dict[UUID, SkillUsage] = {}
        already_over = 0
        for user_id in grown:
            total_after = totals.get(user_id, SkillUsage()) + built_ins
            if not total_after.is_over_write_limit:
                continue
            total_before = (
                total_after - after[user_id] + self._before.get(user_id, SkillUsage())
            )
            if total_before.is_over_write_limit:
                already_over += 1
            else:
                users_over[user_id] = total_after
        return SkillLimitOutcome(
            users_over=users_over,
            users_already_over=already_over,
            lock_wait_ms=wait_ms,
        )

    def finish(self) -> SkillLimitOutcome:
        """Raise 413 when the write moves a user past a limit."""
        outcome = self.measure()
        if outcome.users_over:
            raise skill_limit_error(outcome.users_over, self.actor_id)
        if outcome.users_already_over:
            logger.warning(
                "Skill write grows %d users who are already past the skill limit",
                outcome.users_already_over,
            )
        return outcome


@contextmanager
def skill_limit_check(
    db_session: Session,
    plugin_ids: Iterable[UUID] = (),
    *,
    actor_id: UUID | None,
    user_ids: Iterable[UUID] | None = None,
) -> Iterator[SkillLimitCheck]:
    """Check the skill limit for the write in the block. ``plugin_ids`` are the
    plugins it changes; plugins it creates go to ``track_new``. A check inside
    another check of the same session joins it, and the outer one finishes."""
    outer = db_session.info.get(_SESSION_KEY)
    if isinstance(outer, SkillLimitCheck):
        if not outer.covers(user_ids):
            raise ValueError("A nested skill limit check covers more users.")
        outer.track(plugin_ids)
        yield outer
        return
    check = SkillLimitCheck(db_session, actor_id, user_ids)
    check.track(plugin_ids)
    db_session.info[_SESSION_KEY] = check
    try:
        yield check
    finally:
        db_session.info.pop(_SESSION_KEY, None)
    check.finish()


# --- Users past the write limit ------------------------------------------------


@dataclass(frozen=True)
class UserPastWriteLimit:
    user_id: UUID
    email: str
    usage: SkillUsage
    # Plugins the run-time limit leaves out for the user.
    skills_not_loaded: int


def runtime_omission_count(
    charges: Iterable[RuntimePluginCharge], built_ins: SkillUsage
) -> int:
    """How many plugins the run-time limit leaves out, by sizes alone. A
    version with no recorded size counts as 0."""
    used = built_ins
    count = 0
    for charge in sorted(
        charges,
        key=lambda item: runtime_keep_key(item.group, item.order_time, item.plugin_id),
    ):
        usage = charge.usage or SkillUsage()
        if runtime_omission_reason(used, usage) is not None:
            count += 1
        else:
            used += usage
    return count


def users_past_write_limit(db_session: Session) -> list[UserPastWriteLimit]:
    """Active users past the write limit (500 MB or 5,000 files), largest
    first, with how many of their plugins the run-time limit leaves out. One
    usage query for every user, then one charge query for those users."""
    built_ins = built_in_skill_usage(db_session)
    over = {
        user_id: usage + built_ins
        for user_id, usage in plugin_usage_by_user(
            active_skill_user(), db_session
        ).items()
        if (usage + built_ins).is_over_write_limit
    }
    if not over:
        return []
    charges = runtime_plugin_charges(over, db_session)
    runtime_built_ins = built_in_skill_usage(db_session, BUILT_IN_SKILL_RUNTIME_USAGE)
    emails: dict[UUID, str] = {  # noqa: C416  # unpacking types the SQLAlchemy Row
        user_id: email
        for user_id, email in db_session.execute(
            select(User.__table__.c.id, User.__table__.c.email).where(
                User.__table__.c.id.in_(over)
            )
        )
    }
    return sorted(
        (
            UserPastWriteLimit(
                user_id=user_id,
                email=emails[user_id],
                usage=usage,
                skills_not_loaded=runtime_omission_count(
                    charges.get(user_id, []), runtime_built_ins
                ),
            )
            for user_id, usage in over.items()
        ),
        key=lambda item: (-item.usage.bytes, item.email),
    )
