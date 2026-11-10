"""One decision snapshot for an atomic marketplace publication."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass, field
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    String,
    cast,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.dialects.postgresql import ARRAY, aggregate_order_by
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Session
from sqlalchemy.sql.selectable import CompoundSelect

from onyx.db.external_app import get_ready_external_app_ids_for_users
from onyx.db.skill import (
    available_built_in_skills,
    lock_skill_limit_users,
    skill_audience_rows,
    skill_audience_user_ids,
    skill_limit_violation,
    skill_usage_statement,
)
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.limits import (
    SkillLimit,
    SkillLimitViolation,
    SkillUsage,
    failed_skill_limit,
)


@dataclass(frozen=True)
class MarketplaceVersionProposal:
    skill_id: UUID
    name: str
    version_id: UUID
    is_new: bool


_ZERO_USAGE = SkillUsage()


@dataclass(frozen=True)
class _NameWinner:
    rank: tuple[int, int]
    usage: SkillUsage


@dataclass
class _NameUsage:
    shared: dict[str, _NameWinner | None] = field(default_factory=dict)
    specific: dict[str, dict[UUID, _NameWinner | None]] = field(default_factory=dict)

    def winner(self, name: str, user: UUID | None) -> _NameWinner | None:
        return (
            self.shared.get(name)
            if user is None
            else self.specific.get(name, {}).get(user, self.shared.get(name))
        )

    def deltas(
        self, before: "_NameUsage", name: str, accepted: Sequence["_NameUsage"]
    ) -> tuple[SkillUsage, dict[UUID, SkillUsage]]:
        def delta(user: UUID | None) -> SkillUsage:
            original = before.winner(name, user)
            winner = previous = original
            # Staged versions are valid. An update can change a winner's size
            # or expose an older candidate, but cannot remove eligibility.
            for state in (*accepted, self):
                candidate = state.winner(name, user)
                previous = winner
                if candidate != original and candidate is not None:
                    if winner is None or candidate.rank <= winner.rank:
                        winner = candidate
            return (winner.usage if winner else _ZERO_USAGE) - (
                previous.usage if previous else _ZERO_USAGE
            )

        users = {
            user
            for state in (before, *accepted, self)
            for user in state.specific.get(name, {})
        }
        return delta(None), {user: delta(user) for user in users}


@dataclass
class _DecisionSnapshot:
    audience: dict[UUID, Collection[UUID]] = field(default_factory=dict)
    totals: dict[UUID, SkillUsage] = field(default_factory=dict)
    before: _NameUsage = field(default_factory=_NameUsage)
    after: dict[int, _NameUsage] = field(default_factory=dict)


def _decision_statement(
    proposals: Sequence[MarketplaceVersionProposal],
    variants: Sequence[Sequence[MarketplaceVersionProposal]],
    users: Collection[UUID],
    ready: Mapping[UUID, Collection[int]],
    generic: UUID,
    available: ColumnElement[bool],
) -> CompoundSelect:
    absent = {p.skill_id: None for p in proposals if p.is_new}
    names = {p.name for p in proposals}
    audience = skill_audience_rows([p.skill_id for p in proposals]).subquery()
    # Public entries often have identical audiences. Transfer each user set once.
    audiences = (
        select(
            audience.c.skill_id,
            func.array_agg(
                aggregate_order_by(audience.c.user_id, audience.c.user_id)
            ).label("users"),
        )
        .group_by(audience.c.skill_id)
        .subquery()
    )
    parts = [
        select(
            literal(-2).label("variant"),
            func.string_agg(cast(audiences.c.skill_id, String), ",").label("name"),
            literal(generic, PGUUID(as_uuid=True)).label("user_id"),
            literal(0, BigInteger).label("bytes"),
            literal(0, BigInteger).label("files"),
            literal(0, BigInteger).label("unknown_skill_count"),
            audiences.c.users.label("audience"),
            literal(None, ARRAY(BigInteger)).label("winner"),
        ).group_by(audiences.c.users)
    ]
    for variant, entries in [(-1, ()), (0, ()), *enumerate(variants, 1)]:
        overrides: dict[UUID, UUID | None] = {
            **absent,
            **{p.skill_id: p.version_id for p in entries},
        }
        usage = skill_usage_statement(
            users,
            ready,
            generic,
            built_in_available=available,
            version_overrides=overrides,
            names=None
            if variant == -1
            else ({p.name for p in entries} if variant > 0 else names),
            per_name=variant != -1,
        ).subquery()
        parts.append(
            select(
                literal(variant),
                usage.c.name,
                usage.c.user_id,
                usage.c.bytes,
                usage.c.files,
                usage.c.unknown_skill_count,
                literal(None, ARRAY(PGUUID(as_uuid=True))),
                usage.c.winner,
            )
        )
    return union_all(*parts)


def _capture_decision(
    proposals: Sequence[MarketplaceVersionProposal],
    variants: Sequence[Sequence[MarketplaceVersionProposal]],
    db_session: Session,
) -> _DecisionSnapshot:
    """Readiness precedes SQL; all SQL decision inputs come from one statement.

    Readiness (including built-in availability) can change outside membership
    locks. It stays fixed for this statement. SQL audience changes can add users
    without those locks: discard that entire snapshot, capture their readiness
    and user locks, then retry. Repeated growth aborts for a worker retry.
    No replay step reads refreshed decision inputs.
    This boundary does not provide serializable isolation for unchecked writers.
    """
    generic = uuid4()
    for _ in range(3):
        users = skill_audience_user_ids([p.skill_id for p in proposals], db_session)
        lock_skill_limit_users(users, db_session)
        ready = get_ready_external_app_ids_for_users(db_session, [*users, generic])
        available = available_built_in_skills(db_session)
        snapshot = _DecisionSnapshot()
        rows = db_session.execute(
            _decision_statement(proposals, variants, users, ready, generic, available)
        )
        for variant, name, user, size, files, unknown, audience, winner in rows:
            if variant == -2:
                for skill_id in name.split(","):
                    snapshot.audience[UUID(skill_id)] = audience
                continue
            usage = SkillUsage(int(size), int(files), int(unknown))
            if variant == -1:
                snapshot.totals[user] = usage
                continue
            values = (
                snapshot.before
                if variant == 0
                else snapshot.after.setdefault(variant, _NameUsage())
            )
            ranked = _NameWinner((winner[0], winner[1]), usage) if winner else None
            if user == generic:
                values.shared[name] = ranked
            else:
                values.specific.setdefault(name, {})[user] = ranked
        observed = {
            user for audience in snapshot.audience.values() for user in audience
        }
        if observed <= users:
            return snapshot
    raise OnyxError(
        OnyxErrorCode.SERVICE_UNAVAILABLE,
        "Skill audience keeps changing. Retry the marketplace sync.",
    )


def marketplace_version_decisions(
    proposals: Sequence[MarketplaceVersionProposal],
    existing_names: Collection[str],
    db_session: Session,
) -> dict[UUID, SkillLimitViolation | str]:
    """Return refusals; absent keys are accepted, in proposal order.

    Each variant updates one candidate per name. Replay selects the winner
    across accepted variants from the same snapshot. New entries reserve their
    names only after acceptance; saved duplicate names remain supported.
    """
    if not proposals:
        return {}
    by_name: dict[str, list[MarketplaceVersionProposal]] = {}
    variants: list[list[MarketplaceVersionProposal]] = []
    variant_for: dict[UUID, int] = {}
    for proposal in proposals:
        siblings = by_name.setdefault(proposal.name, [])
        if len(variants) == len(siblings):
            variants.append([])
        variants[len(siblings)].append(proposal)
        variant_for[proposal.skill_id] = len(siblings) + 1
        siblings.append(proposal)
    snapshot = _capture_decision(proposals, variants, db_session)
    totals = dict(snapshot.totals)
    names = set(existing_names)
    refusals: dict[UUID, SkillLimitViolation | str] = {}
    for index, proposal in enumerate(proposals):
        if proposal.is_new and proposal.name in names:
            refusals[proposal.skill_id] = "name taken"
            continue
        after = snapshot.after.get(variant_for[proposal.skill_id], _NameUsage())
        accepted = [
            snapshot.after.get(variant_for[prior.skill_id], _NameUsage())
            for prior in proposals[:index]
            if prior.name == proposal.name and prior.skill_id not in refusals
        ]
        shared_delta, specific_deltas = after.deltas(
            snapshot.before, proposal.name, accepted
        )
        proposed: dict[UUID, SkillUsage] = {}
        violations: dict[UUID, tuple[SkillUsage, SkillLimit]] = {}
        for user in snapshot.audience.get(proposal.skill_id, ()):
            delta = specific_deltas.get(user, shared_delta)
            if delta == _ZERO_USAGE:
                continue
            usage = totals[user] + delta
            proposed[user] = usage
            failed = failed_skill_limit(usage, totals[user])
            if failed is not None:
                violations[user] = (usage, failed)
        if violations:
            refusals[proposal.skill_id] = skill_limit_violation(violations, None)
            continue
        names.add(proposal.name)
        totals.update(proposed)
    return refusals
