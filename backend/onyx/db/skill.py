"""DB operations for skill rows.

Management authorization:
- `VIEW` includes associated custom rows but excludes associated built-in
  provider rows, applies normal ownership and sharing visibility, and lets
  admins view all remaining skills.
- `EDIT` is the skill mutation policy. It excludes built-in rows and only
  returns custom rows the user can modify.

Runtime selection is deliberately separate from authorization. It applies
visibility without an admin bypass, user enablement for custom skills, app
readiness for associated skills, validity, and built-in availability.

Delete is a hard delete: `delete_skill` removes the row and its versions and
returns their bundle file ids. Callers delete those files after commit with
`delete_unreferenced_skill_bundles`; the orphan cleanup task retries failures.

Mutation helpers do not commit unless their docstring explicitly says otherwise.
Callers normally control the transaction boundary so multi-step operations can
roll back atomically.
"""

from collections.abc import Callable, Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, IntEnum
from typing import Literal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Integer,
    Select,
    String,
    and_,
    any_,
    bindparam,
    case,
    cast,
    column,
    delete,
    exists,
    false,
    func,
    literal,
    null,
    or_,
    select,
    true,
    type_coerce,
    union_all,
    update,
)
from sqlalchemy.dialects.postgresql import ARRAY, array, insert
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import (
    InstrumentedAttribute,
    Session,
    contains_eager,
    selectinload,
)
from sqlalchemy.sql.selectable import CTE, Subquery

from onyx.auth.permissions import has_global_permission, has_permission
from onyx.auth.scoped_permissions import assert_within_scope
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import (
    AccountType,
    Permission,
    PermissionAuthority,
    SandboxStatus,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.external_app import (
    SkillExternalAppDependencyState,
    get_ready_external_app_ids_for_users,
    get_skill_external_app_dependencies,
)
from onyx.db.models import (
    ExternalApp,
    ExternalApp__Skill,
    Marketplace,
    Sandbox,
    Skill,
    Skill__User,
    Skill__UserGroup,
    SkillVersion,
    User,
    User__UserGroup,
    UserSkillLimitBlock,
    UserSkillPreference,
)
from onyx.db.resource_access import (
    ResourceAccessAdapter,
    ResourceAccessState,
    lock_resource_access_user,
    mutate_resource_access,
)
from onyx.db.resource_access import (
    ResourceAccessChange as SkillSharingChange,
)
from onyx.db.scoped_permissions import (
    scoped_group_ids_subquery,
    within_managed_scope_clause,
)
from onyx.db.skill_library import (
    assert_new_skill_name_available,
    skill_library_owner,
)
from onyx.db.skill_mutation import (
    assert_skill_content_editable,
    assert_skill_deletable,
    assert_skill_mutable,
    is_company_marketplace_skill,
)
from onyx.db.skill_version import (
    PreparedSkillVersionWrite,
    persist_skill_version_validity,
    save_skill_version,
    skill_bundle_file_ids,
)
from onyx.db.user_group import assert_not_shared_with_default_group
from onyx.db.users import lock_group_membership
from onyx.db.utils import is_fk_violation, uuid_array
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.built_in import BUILT_IN_SKILLS, get_builtin_skill_footprints
from onyx.skills.ingest import IngestedBundle
from onyx.skills.limits import (
    SKILL_WRITE_MAX_BYTES,
    SKILL_WRITE_MAX_FILES,
    SkillLimit,
    SkillLimitBaseline,
    SkillLimitViolation,
    SkillUsage,
    SkillUsageSummary,
    failed_skill_limit,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Past these sizes, a usage query finds each name's shared winner once.
# Smaller queries cost less to expand each user over each name.
PER_USER_WINNER_MAX_NAME_PAIRS = 5_000
PER_USER_WINNER_MAX_FULL_TOTAL_USERS = 20


class SkillManagementPolicy(str, Enum):
    VIEW = "view"
    EDIT = "edit"


@dataclass(frozen=True)
class SkillValidityUpdate:
    skill_id: UUID
    version_id: UUID
    bundle_file_id: str | None
    is_valid: bool


@dataclass(frozen=True)
class SkillUserState:
    enabled: bool
    can_toggle: bool
    external_app_dependency: SkillExternalAppDependencyState | None
    effective_installation_policy: SkillInstallationPolicy
    hidden_by_skill_id: UUID | None = None
    # Set when connecting the skill's app would have passed the write limit.
    skill_limit_block: SkillLimit | None = None


class SkillRuntimePriority(IntEnum):
    """Keep classes under the runtime limit; a lower value stays first."""

    BUILT_IN = 0
    REQUIRED = 1
    ENABLED = 2
    DEFAULT = 3


@dataclass(frozen=True)
class RuntimeSkillCandidate:
    skill: Skill
    priority: SkillRuntimePriority
    # Explicit enable time, or the newest grant that reaches the user.
    granted_at: datetime | None
    # Unique position in the runtime keep order across all candidates.
    keep_rank: int


@dataclass(frozen=True)
class SkillMarketplaceSource:
    id: UUID
    name: str
    personal: bool


def skill_marketplace_sources(
    marketplace_ids: Collection[UUID], db_session: Session
) -> dict[UUID, SkillMarketplaceSource]:
    """Load display fields only, for sources of already authorized skills."""
    if not marketplace_ids:
        return {}
    return {
        source_id: SkillMarketplaceSource(source_id, name, personal)
        for source_id, name, personal in db_session.execute(
            select(
                Marketplace.id,
                Marketplace.name,
                Marketplace.owner_user_id.is_not(None),
            ).where(Marketplace.id.in_(marketplace_ids))
        )
    }


# A literal user, or a user column of an enclosing multi-user query.
UserIdRef = UUID | ColumnElement[UUID] | InstrumentedAttribute[UUID]


def _is_shared_with_user(
    user_id: UserIdRef,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    stmt = (
        select(Skill__User.skill_id)
        .where(Skill__User.skill_id == Skill.id)
        .where(Skill__User.user_id == user_id)
    )
    if permission is not None:
        stmt = stmt.where(Skill__User.permission == permission)
    return stmt.exists()


def _is_shared_with_user_group(
    user_id: UserIdRef,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    stmt = (
        select(Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id == Skill.id)
        .where(User__UserGroup.user_id == user_id)
    )
    if permission is not None:
        stmt = stmt.where(Skill__UserGroup.permission == permission)
    return stmt.exists()


def _is_group_shared_only_within_managed_scope(user: User) -> ColumnElement[bool]:
    """A scoped manager may edit a skill only when every group it is shared with
    is one they manage, and it isn't published org-wide. Delegates to the shared
    read-side helper so this can't drift from the write-side GATE 2."""
    return within_managed_scope_clause(
        resource_id_col=Skill.id,
        junction_resource_col=Skill__UserGroup.skill_id,
        junction_group_col=Skill__UserGroup.user_group_id,
        non_public_clause=Skill.public_permission.is_(None),
        managed_subq=scoped_group_ids_subquery(user),
    )


def _is_owned_custom_skill(user_id: UserIdRef) -> ColumnElement[bool]:
    return and_(
        Skill.author_user_id.is_not(None),
        Skill.author_user_id == user_id,
        Skill.built_in_skill_id.is_(None),
    )


def skill_visible_to_user(
    user_id: UserIdRef,
    *,
    include_retired: bool = False,
    installation_policy: ColumnElement[str] | None = None,
) -> ColumnElement[bool]:
    policy = (
        installation_policy
        if installation_policy is not None
        else _effective_skill_policy(user_id)
    )
    visible = or_(
        _is_shared_with_user(user_id),
        _is_owned_custom_skill(user_id),
        and_(
            policy != SkillInstallationPolicy.NOT_AVAILABLE,
            or_(
                Skill.public_permission.is_not(None),
                _is_shared_with_user_group(user_id),
            ),
        ),
    )

    return visible if include_retired else and_(Skill.retired_at.is_(None), visible)


def _is_editable_by_user(
    user: User, *, allow_management: bool = True
) -> ColumnElement[bool]:
    editable = or_(
        _is_owned_custom_skill(user.id),
        _is_shared_with_user(user.id, SkillSharePermission.EDITOR),
        _is_shared_with_user_group(user.id, SkillSharePermission.EDITOR),
        Skill.public_permission == SkillSharePermission.EDITOR,
    )
    if (
        allow_management
        and has_permission(user, Permission.MANAGE_SKILLS) is PermissionAuthority.SCOPED
    ):
        editable = or_(editable, _is_group_shared_only_within_managed_scope(user))
    return editable


def _group_skill_policy_rank() -> ColumnElement[int]:
    policy = func.coalesce(
        Skill__UserGroup.installation_policy, Skill.installation_policy
    )
    return case(
        (policy == SkillInstallationPolicy.REQUIRED, 3),
        (policy == SkillInstallationPolicy.DEFAULT, 2),
        (policy == SkillInstallationPolicy.AVAILABLE, 1),
        else_=0,
    )


def _skill_policy_from_rank(rank: ColumnElement[int]) -> ColumnElement[str]:
    return case(
        {
            3: SkillInstallationPolicy.REQUIRED.value,
            2: SkillInstallationPolicy.DEFAULT.value,
            1: SkillInstallationPolicy.AVAILABLE.value,
            0: SkillInstallationPolicy.NOT_AVAILABLE.value,
        },
        value=rank,
        else_=Skill.installation_policy,
    )


def _effective_skill_policy(user_id: UserIdRef) -> ColumnElement[str]:
    group_rank = (
        select(func.max(_group_skill_policy_rank()))
        .select_from(Skill__UserGroup)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(
            Skill__UserGroup.skill_id == Skill.id, User__UserGroup.user_id == user_id
        )
        .correlate_except(Skill__UserGroup, User__UserGroup)
        .scalar_subquery()
    )
    return _skill_policy_from_rank(group_rank)


def _group_policy_ranks(
    user_ids: Collection[UUID],
    skill_ids: Collection[UUID] | None = None,
    *,
    names: Collection[str] | None = None,
) -> Subquery:
    """The strongest group policy rank per user and group-shared Skill."""
    groups = (
        select(
            User__UserGroup.user_id,
            Skill__UserGroup.skill_id,
            func.max(_group_skill_policy_rank()).label("rank"),
        )
        .select_from(Skill__UserGroup)
        .join(Skill, Skill.id == Skill__UserGroup.skill_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(User__UserGroup.user_id == any_(uuid_array(user_ids)))
        .group_by(User__UserGroup.user_id, Skill__UserGroup.skill_id)
    )
    if skill_ids is not None:
        groups = groups.where(Skill.id.in_(skill_ids))
    if names is not None:
        groups = groups.where(Skill.name.in_(names))
    return groups.subquery()


def _skill_installation_policy_rows(
    user_ids: Collection[UUID],
    skill_ids: Collection[UUID] | None = None,
    *,
    names: Collection[str] | None = None,
) -> CTE:
    group_rows = _group_policy_ranks(user_ids, skill_ids, names=names)
    user_id = User.__table__.c.id
    rows = (
        select(
            user_id.label("user_id"),
            Skill.id.label("skill_id"),
            _skill_policy_from_rank(group_rows.c.rank).label("installation_policy"),
        )
        .select_from(User)
        .join(Skill, true())
        .outerjoin(
            group_rows,
            and_(group_rows.c.user_id == user_id, group_rows.c.skill_id == Skill.id),
        )
        .where(user_id.in_(user_ids))
    )
    if skill_ids is not None:
        rows = rows.where(Skill.id.in_(skill_ids))
    if names is not None:
        rows = rows.where(Skill.name.in_(names))
    return rows.cte()


def resolve_skill_installation_policies(
    user_ids: Collection[UUID],
    skill_ids: Collection[UUID],
    db_session: Session,
) -> dict[tuple[UUID, UUID], SkillInstallationPolicy]:
    """Resolve requested live user/skill pairs in one query, without changing preferences."""
    if not user_ids or not skill_ids:
        return {}
    policies = _skill_installation_policy_rows(user_ids, skill_ids)
    rows = db_session.execute(
        select(policies.c.user_id, policies.c.skill_id, policies.c.installation_policy)
        .join(Skill, Skill.id == policies.c.skill_id)
        .where(Skill.retired_at.is_(None))
    )
    return {
        (user_id, skill_id): SkillInstallationPolicy(policy)
        for user_id, skill_id, policy in rows
    }


def _is_required_for_user(
    user_id: UserIdRef, installation_policy: ColumnElement[str] | None = None
) -> ColumnElement[bool]:
    policy = (
        installation_policy
        if installation_policy is not None
        else _effective_skill_policy(user_id)
    )
    return and_(
        policy == SkillInstallationPolicy.REQUIRED,
        skill_visible_to_user(user_id, installation_policy=policy),
    )


def _is_enabled_for_user(
    user_id: UserIdRef,
    installation_policy: ColumnElement[str] | None = None,
    *,
    preference: ColumnElement[bool] | None = None,
) -> ColumnElement[bool]:
    """``preference`` is the user's saved choice when the caller already joins it."""
    policy = (
        installation_policy
        if installation_policy is not None
        else _effective_skill_policy(user_id)
    )
    if preference is None:
        preference = (
            select(UserSkillPreference.enabled)
            .where(
                UserSkillPreference.user_id == user_id,
                UserSkillPreference.skill_id == Skill.id,
            )
            # Also correlates a user column of a multi-user query.
            .correlate_except(UserSkillPreference)
            .scalar_subquery()
        )
    visible = skill_visible_to_user(user_id, installation_policy=policy)
    enabled = or_(
        Skill.built_in_skill_id.isnot(None),
        policy == SkillInstallationPolicy.REQUIRED,
        preference.is_(True),
        and_(
            policy == SkillInstallationPolicy.DEFAULT,
            preference.is_(None),
        ),
    )

    return and_(
        Skill.retired_at.is_(None),
        policy != SkillInstallationPolicy.NOT_AVAILABLE,
        visible,
        enabled,
    )


def available_built_in_skills(db_session: Session) -> ColumnElement[bool]:
    """Keep custom rows and known built-ins whose ``is_available(db)`` is true.
    User-facing reads use this; admin reads don't (admins see all rows)."""
    available = [
        d.built_in_skill_id
        for d in BUILT_IN_SKILLS.values()
        if d.is_available(db_session)
    ]
    return or_(
        Skill.built_in_skill_id.is_(None),
        Skill.built_in_skill_id.in_(available),
    )


def _skill_select_with_eager_load(*, order_by_name: bool) -> Select[tuple[Skill]]:
    stmt = (
        select(Skill)
        .outerjoin(Skill.current_version)
        .options(
            contains_eager(Skill.current_version),
            selectinload(Skill.author),
            selectinload(Skill.user_shares).selectinload(Skill__User.user),
            selectinload(Skill.group_shares).selectinload(Skill__UserGroup.user_group),
        )
    )
    if order_by_name:
        stmt = stmt.order_by(Skill.name, Skill.id)
    return stmt


def _skill_select_for_management_policy(
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
    order_by_name: bool,
    include_retired: bool = False,
    allow_management: bool = True,
) -> Select[tuple[Skill]]:
    stmt = _skill_select_with_eager_load(order_by_name=order_by_name)
    if not include_retired:
        stmt = stmt.where(Skill.retired_at.is_(None))
    if policy == SkillManagementPolicy.VIEW:
        # Associated custom skills are first-class; provider-owned built-ins
        # remain represented only through the Apps surfaces.
        stmt = stmt.where(
            or_(
                Skill.built_in_skill_id.is_(None),
                ~exists().where(ExternalApp__Skill.skill_id == Skill.id),
            )
        )
        if allow_management and has_global_permission(user, Permission.MANAGE_SKILLS):
            return stmt
        policies = _skill_installation_policy_rows([user.id])
        stmt = stmt.join(policies, policies.c.skill_id == Skill.id).where(
            skill_visible_to_user(
                user.id,
                include_retired=include_retired,
                installation_policy=policies.c.installation_policy,
            )
        )
        return stmt.where(available_built_in_skills(db_session))

    if policy == SkillManagementPolicy.EDIT:
        stmt = stmt.where(Skill.built_in_skill_id.is_(None))
        if allow_management and has_global_permission(user, Permission.MANAGE_SKILLS):
            return stmt
        return stmt.where(_is_editable_by_user(user, allow_management=allow_management))

    raise ValueError(f"Unknown skill management policy: {policy}")


def get_group_ids_for_skill(skill_id: UUID, db_session: Session) -> list[int]:
    """Group ids a skill is shared with — the scope input for GATE 2 checks."""
    return list(
        db_session.scalars(
            select(Skill__UserGroup.user_group_id).where(
                Skill__UserGroup.skill_id == skill_id
            )
        )
    )


def _skill_reaches_user(
    user_id: UserIdRef, *, shared: ColumnElement[bool] | None = None
) -> ColumnElement[bool]:
    """Any grant that can show the skill to the user, before installation policy."""
    return or_(
        Skill.public_permission.is_not(None),
        Skill.author_user_id == user_id,
        shared
        if shared is not None
        else or_(_is_shared_with_user(user_id), _is_shared_with_user_group(user_id)),
    )


def skill_audience_user_ids(
    skill_ids: Collection[UUID], db_session: Session
) -> set[UUID]:
    """Users who can sign in and reach any of the skills, with or without a sandbox."""
    if not skill_ids:
        return set()
    audience = skill_audience_rows(skill_ids).subquery()
    return set(db_session.scalars(select(audience.c.user_id).distinct()))


def skill_audience_rows(skill_ids: Collection[UUID]) -> Select[tuple[UUID, UUID]]:
    """Skill/user pairs at the executing statement's snapshot, including no sandbox."""
    user_id = User.__table__.c.id
    # Join grant edges once instead of running correlated subplans per user/Skill.
    shares = union_all(
        select(Skill__User.skill_id, Skill__User.user_id).where(
            Skill__User.skill_id.in_(skill_ids)
        ),
        select(Skill__UserGroup.skill_id, User__UserGroup.user_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(Skill__UserGroup.skill_id.in_(skill_ids)),
    ).subquery()
    shared = select(shares.c.skill_id, shares.c.user_id).distinct().subquery()
    return (
        select(Skill.id.label("skill_id"), user_id.label("user_id"))
        .select_from(User)
        .join(Skill, true())
        .outerjoin(
            shared, and_(shared.c.skill_id == Skill.id, shared.c.user_id == user_id)
        )
        .where(
            Skill.id.in_(skill_ids),
            _skill_reaches_user(user_id, shared=shared.c.user_id.is_not(None)),
            User.__table__.c.is_active.is_(True),
            User.account_type.not_in([AccountType.BOT, AccountType.EXT_PERM_USER]),
        )
    )


def affected_user_ids_for_skill(skill: Skill, db_session: Session) -> set[UUID]:
    return affected_user_ids_for_skills([skill.id], db_session).get(skill.id, set())


def affected_user_ids_for_skills(
    skill_ids: Collection[UUID], db_session: Session
) -> dict[UUID, set[UUID]]:
    recipients: dict[UUID, set[UUID]] = {}
    if not skill_ids:
        return recipients
    rows = db_session.execute(
        select(Skill.id, Sandbox.user_id)
        .join(
            Sandbox,
            and_(
                Sandbox.status == SandboxStatus.RUNNING,
                _skill_reaches_user(Sandbox.user_id),
            ),
        )
        .where(Skill.id.in_(skill_ids))
    )
    for skill_id, user_id in rows:
        recipients.setdefault(skill_id, set()).add(user_id)
    return recipients


def list_skills(
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
    allow_management: bool = True,
) -> list[Skill]:
    stmt = _skill_select_for_management_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=True,
        allow_management=allow_management,
    )
    return list(db_session.scalars(stmt))


def _runtime_candidate_order(
    user_id: UserIdRef,
) -> tuple[
    ColumnElement[int], InstrumentedAttribute[datetime], InstrumentedAttribute[UUID]
]:
    """Company library, the user's library, then others; the caller joins Marketplace."""
    library_owner = skill_library_owner()
    priority = case(
        (library_owner.is_(None), 0),
        (library_owner == user_id, 1),
        else_=2,
    )
    return priority, Skill.created_at, Skill.id


def _runtime_eligibility(
    user_id: UserIdRef,
    policy: ColumnElement[str],
    *,
    app_ready: ColumnElement[bool],
    built_in_available: ColumnElement[bool],
    include_skill_id: UUID | None = None,
    preference: ColumnElement[bool] | None = None,
) -> list[ColumnElement[bool]]:
    """Runtime gate for one user or a user column; the caller joins current versions.

    ``app_ready`` is true for an app-linked skill whose app the user can use.
    ``built_in_available`` is ``available_built_in_skills``.
    ``preference`` is the user's joined saved choice, read per row otherwise.
    """
    return [
        skill_visible_to_user(user_id, installation_policy=policy),
        policy != SkillInstallationPolicy.NOT_AVAILABLE,
        or_(
            _is_enabled_for_user(user_id, policy, preference=preference),
            Skill.id == include_skill_id,
        ),
        or_(~exists().where(ExternalApp__Skill.skill_id == Skill.id), app_ready),
        or_(
            Skill.built_in_skill_id.isnot(None),
            and_(SkillVersion.id.is_not(None), SkillVersion.is_valid.is_not(False)),
        ),
        built_in_available,
        ~exists().where(
            UserSkillLimitBlock.user_id == user_id,
            UserSkillLimitBlock.skill_id == Skill.id,
        ),
    ]


def _runtime_name_winners(
    user: User,
    db_session: Session,
    *,
    include_skill_id: UUID | None = None,
    required_only: bool = False,
    dependencies: Mapping[UUID, SkillExternalAppDependencyState] | None = None,
) -> Select[tuple[UUID, UUID, int]]:
    """Select each eligible skill, its name winner and its resolution position."""
    external_app_dependencies = (
        dependencies
        if dependencies is not None
        else get_skill_external_app_dependencies(db_session, user)
    )
    ready_external_app_skill_ids = [
        skill_id
        for skill_id, dependency in external_app_dependencies.items()
        if dependency.ready
    ]
    policies = _skill_installation_policy_rows([user.id])
    policy = policies.c.installation_policy
    candidate_order = _runtime_candidate_order(user.id)
    stmt = (
        select(
            Skill.id.label("skill_id"),
            func.first_value(Skill.id)
            .over(partition_by=Skill.name, order_by=candidate_order)
            .label("winner_id"),
            func.row_number()
            .over(order_by=(Skill.name, *candidate_order))
            .label("position"),
        )
        .outerjoin(Skill.current_version)
        .outerjoin(Marketplace, Skill.marketplace_id == Marketplace.id)
        .join(policies, policies.c.skill_id == Skill.id)
        .where(
            *_runtime_eligibility(
                user.id,
                policy,
                app_ready=Skill.id.in_(ready_external_app_skill_ids),
                built_in_available=available_built_in_skills(db_session),
                include_skill_id=include_skill_id,
            )
        )
    )
    if required_only:
        stmt = stmt.where(
            or_(_is_required_for_user(user.id, policy), Skill.id == include_skill_id)
        )
    return stmt


def resolve_skill_runtime_names(
    user: User,
    db_session: Session,
    *,
    include_skill_id: UUID | None = None,
    required_only: bool = False,
    dependencies: Mapping[UUID, SkillExternalAppDependencyState] | None = None,
) -> dict[UUID, UUID]:
    """Map each eligible skill to its name winner, including hidden duplicates.

    Entries follow name, library priority, creation time, then UUID order.
    An explicit enable can include one not-yet-enabled skill for conflict checks.
    """
    winners = _runtime_name_winners(
        user,
        db_session,
        include_skill_id=include_skill_id,
        required_only=required_only,
        dependencies=dependencies,
    ).subquery()
    rows = db_session.execute(
        select(winners.c.skill_id, winners.c.winner_id).order_by(winners.c.position)
    )
    return dict(rows.tuples().all())


def list_runtime_skills_for_user(
    *,
    db_session: Session,
    user: User,
    include_fallbacks: bool = False,
) -> list[Skill]:
    """Return database-known winners, or all ordered candidates for delivery.

    Delivery can discover unreadable bundles; it must try the next candidate.
    """
    # One statement, so a concurrent revoke cannot ship a version it did not check.
    winners = _runtime_name_winners(user, db_session).subquery()
    stmt = (
        _skill_select_with_eager_load(order_by_name=False)
        .join(winners, winners.c.skill_id == Skill.id)
        .order_by(winners.c.position)
    )
    if not include_fallbacks:
        stmt = stmt.where(winners.c.winner_id == Skill.id)
    return list(db_session.scalars(stmt))


def _runtime_skill_priorities(
    user: User, skill_ids: Collection[UUID], db_session: Session
) -> dict[UUID, tuple[SkillRuntimePriority, datetime | None, int]]:
    """Rank already-eligible skills for the runtime limit in one query.

    Order: class, newest date first, unknown dates last, then name and id.
    """
    if not skill_ids:
        return {}
    policies = _skill_installation_policy_rows([user.id], skill_ids)
    priority = case(
        (Skill.built_in_skill_id.is_not(None), int(SkillRuntimePriority.BUILT_IN)),
        (
            policies.c.installation_policy == SkillInstallationPolicy.REQUIRED,
            int(SkillRuntimePriority.REQUIRED),
        ),
        (UserSkillPreference.enabled.is_(True), int(SkillRuntimePriority.ENABLED)),
        else_=int(SkillRuntimePriority.DEFAULT),
    )
    direct_shared_at = (
        select(Skill__User.created_at)
        .where(Skill__User.skill_id == Skill.id, Skill__User.user_id == user.id)
        .correlate(Skill)
        .scalar_subquery()
    )
    group_shared_at = (
        select(func.max(Skill__UserGroup.created_at))
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Skill__UserGroup.user_group_id,
        )
        .where(
            Skill__UserGroup.skill_id == Skill.id,
            User__UserGroup.user_id == user.id,
        )
        .correlate(Skill)
        .scalar_subquery()
    )
    granted_at = case(
        (priority == int(SkillRuntimePriority.BUILT_IN), null()),
        (
            priority == int(SkillRuntimePriority.ENABLED),
            UserSkillPreference.enabled_at,
        ),
        # GREATEST ignores NULL, so one known grant date is enough.
        else_=func.greatest(direct_shared_at, group_shared_at),
    )
    keep_rank = func.row_number().over(
        order_by=(priority, granted_at.desc().nulls_last(), Skill.name, Skill.id)
    )
    rows = db_session.execute(
        select(Skill.id, priority, granted_at, keep_rank)
        .join(policies, policies.c.skill_id == Skill.id)
        .outerjoin(
            UserSkillPreference,
            and_(
                UserSkillPreference.user_id == user.id,
                UserSkillPreference.skill_id == Skill.id,
            ),
        )
        .where(Skill.id.in_(skill_ids))
    )
    return {
        skill_id: (SkillRuntimePriority(rank_class), date, rank)
        for skill_id, rank_class, date, rank in rows
    }


def list_runtime_skill_candidates_for_user(
    *, db_session: Session, user: User
) -> list[RuntimeSkillCandidate]:
    """Return every delivery candidate in name-resolution order with its keep rank.

    Name precedence and fallback order come from ``resolve_skill_runtime_names``;
    the keep rank only orders whole Skills under the runtime limit.
    """
    skills = list_runtime_skills_for_user(
        db_session=db_session, user=user, include_fallbacks=True
    )
    priorities = _runtime_skill_priorities(
        user, [skill.id for skill in skills], db_session
    )
    return [
        RuntimeSkillCandidate(skill, *priorities[skill.id])
        for skill in skills
        if skill.id in priorities
    ]


def _user_specific_skill_names(
    user_ids: Collection[UUID],
    names: Collection[str] | None,
    app_overrides: Collection[tuple[UUID, int]],
) -> CTE:
    """Each user and Skill name whose winner can differ from the generic winner.

    Lists every row that ties a user to a Skill: preference, direct or group
    share, limit block, app readiness, authorship or marketplace ownership.
    Without one, a name has the same winner as for a user with no rows. Extra
    pairs are safe: they get a full per-user winner.
    """
    apps = (
        func.unnest(
            uuid_array([user_id for user_id, _ in app_overrides]),
            bindparam(
                None, [app_id for _, app_id in app_overrides], type_=ARRAY(Integer)
            ),
        )
        .table_valued(
            column("user_id", PGUUID(as_uuid=True)),
            column("external_app_id", Integer),
        )
        .render_derived(name="app_overrides")
    )
    links = union_all(
        select(UserSkillPreference.user_id, UserSkillPreference.skill_id),
        select(Skill__User.user_id, Skill__User.skill_id),
        select(User__UserGroup.user_id, Skill__UserGroup.skill_id).join(
            Skill__UserGroup,
            Skill__UserGroup.user_group_id == User__UserGroup.user_group_id,
        ),
        select(UserSkillLimitBlock.user_id, UserSkillLimitBlock.skill_id),
        select(apps.c.user_id, ExternalApp__Skill.skill_id).join(
            ExternalApp__Skill,
            ExternalApp__Skill.external_app_id == apps.c.external_app_id,
        ),
        select(Skill.author_user_id, Skill.id),
        select(Marketplace.owner_user_id, Skill.id).join(
            Skill, Skill.marketplace_id == Marketplace.id
        ),
    ).subquery()
    stmt = (
        select(links.c.user_id, Skill.name)
        .join(Skill, Skill.id == links.c.skill_id)
        .where(links.c.user_id == any_(uuid_array(user_ids)))
        .distinct()
    )
    if names is not None:
        stmt = stmt.where(Skill.name.in_(names))
    return stmt.cte()


def _skill_name_winners(
    policies: Subquery,
    ready_apps: Collection[tuple[UUID, int]],
    *,
    built_in_available: ColumnElement[bool],
    exclude_skill_ids: Collection[UUID],
    version_overrides: Mapping[UUID, UUID | None],
) -> Select[tuple[UUID, str, Sequence[int]]]:
    """Each policy row's user and name with the runtime winner and its size.

    ``policies`` has ``user_id``, ``skill_id`` and ``installation_policy``.
    """
    user_id = policies.c.user_id
    app_ready = false()
    if ready_apps:
        ready = (
            func.unnest(
                uuid_array([user_id for user_id, _ in ready_apps]),
                bindparam(
                    None, [app_id for _, app_id in ready_apps], type_=ARRAY(Integer)
                ),
            )
            .table_valued(
                column("user_id", PGUUID(as_uuid=True)),
                column("external_app_id", Integer),
            )
            .render_derived(name="ready_apps")
        )
        app_ready = exists().where(
            ExternalApp__Skill.skill_id == Skill.id,
            ready.c.external_app_id == ExternalApp__Skill.external_app_id,
            ready.c.user_id == user_id,
        )
    unknown = and_(
        Skill.built_in_skill_id.is_(None),
        or_(
            SkillVersion.unpacked_size_bytes.is_(None),
            SkillVersion.file_count.is_(None),
        ),
    )
    footprints = get_builtin_skill_footprints().items()
    built_in_bytes = case(
        {skill_id: footprint.bytes for skill_id, footprint in footprints},
        value=Skill.built_in_skill_id,
        else_=0,
    )
    built_in_files = case(
        {skill_id: footprint.files for skill_id, footprint in footprints},
        value=Skill.built_in_skill_id,
        else_=0,
    )
    library_priority, *creation_order = _runtime_candidate_order(user_id)
    name_positions = (
        select(
            Skill.id.label("skill_id"),
            func.row_number()
            .over(partition_by=Skill.name, order_by=creation_order)
            .label("position"),
        )
        .cte("skill_name_positions", nesting=True)
        .prefix_with("MATERIALIZED")
    )
    # The smallest array per name is the runtime winner, followed by its size.
    winner = func.min(
        array(
            [
                cast(value, BigInteger)
                for value in (
                    library_priority,
                    name_positions.c.position,
                    case(
                        (unknown, 0),
                        else_=func.coalesce(
                            SkillVersion.unpacked_size_bytes, built_in_bytes
                        ),
                    ),
                    case(
                        (unknown, 0),
                        else_=func.coalesce(SkillVersion.file_count, built_in_files),
                    ),
                    case((unknown, 1), else_=0),
                )
            ]
        )
    )
    version_id = (
        case(
            {
                skill_id: literal(version, PGUUID(as_uuid=True))
                for skill_id, version in version_overrides.items()
            },
            value=Skill.id,
            else_=Skill.current_version_id,
        )
        if version_overrides
        else Skill.current_version_id
    )
    return (
        select(
            user_id.label("user_id"),
            Skill.name.label("name"),
            type_coerce(winner, ARRAY(BigInteger)).label("winner"),
        )
        .select_from(policies)
        .join(Skill, Skill.id == policies.c.skill_id)
        .join(name_positions, name_positions.c.skill_id == Skill.id)
        .outerjoin(SkillVersion, SkillVersion.id == version_id)
        .outerjoin(Marketplace, Skill.marketplace_id == Marketplace.id)
        .outerjoin(
            UserSkillPreference,
            and_(
                UserSkillPreference.user_id == user_id,
                UserSkillPreference.skill_id == Skill.id,
            ),
        )
        .where(
            *_runtime_eligibility(
                user_id,
                policies.c.installation_policy,
                app_ready=app_ready,
                built_in_available=built_in_available,
                preference=UserSkillPreference.__table__.c.enabled,
            ),
            Skill.id.not_in(exclude_skill_ids),
        )
        .group_by(user_id, Skill.name)
    )


def skill_usage_for_users(
    user_ids: Collection[UUID],
    db_session: Session,
    *,
    exclude_skill_ids: Collection[UUID] = (),
    names: Collection[str] | None = None,
) -> dict[UUID, SkillUsage]:
    """Total each user's runtime name winners from current-version metadata.

    Uses one query for any number of users, plus two app-readiness queries.
    Reads no bundles. Users without Skills get zero usage. ``names`` limits
    the total to those names; their winners are the same as in a full total.

    Most names have the same winner for every user. For many users, the query
    finds each name's winner once for a user with no rows of their own, then
    replaces it for each user and name from ``_user_specific_skill_names``.
    Fewer users take every name through the per-user winner instead.
    """
    usage = {user_id: SkillUsage() for user_id in user_ids}
    if not usage:
        return usage
    # No row can reference this id: every per-user table has a user foreign key.
    generic_user_id = uuid4()
    shared = (
        len(usage) * len(names) > PER_USER_WINNER_MAX_NAME_PAIRS
        if names is not None
        else len(usage) > PER_USER_WINNER_MAX_FULL_TOTAL_USERS
    )
    ready = get_ready_external_app_ids_for_users(
        db_session, [*usage, generic_user_id] if shared else usage, skill_names=names
    )
    stmt = skill_usage_statement(
        user_ids,
        ready,
        generic_user_id,
        built_in_available=available_built_in_skills(db_session),
        exclude_skill_ids=exclude_skill_ids,
        names=names,
    )
    for user_id, _, total_bytes, total_files, unknown_count, _ in db_session.execute(
        stmt
    ):
        usage[user_id] = SkillUsage(
            int(total_bytes), int(total_files), int(unknown_count)
        )
    return usage


def skill_usage_statement(
    user_ids: Collection[UUID],
    ready: Mapping[UUID, Collection[int]],
    generic_user_id: UUID,
    *,
    built_in_available: ColumnElement[bool],
    exclude_skill_ids: Collection[UUID] = (),
    names: Collection[str] | None = None,
    version_overrides: Mapping[UUID, UUID | None] = {},
    per_name: bool = False,
) -> Select[tuple[UUID, str | None, int, int, int, Sequence[int] | None]]:
    """Build usage at the caller's statement snapshot, with explicit readiness.

    A None override makes a staged custom Skill absent. Per-name rows contain
    generic winners plus exact replacements (including zero) for user/name
    exceptions. The generic id must have no user row and must be in ``ready``.
    Per-name rows also retain the ranked winner; totals return None for it.
    Totals contain only existing users. Neither mode executes a query.
    """
    shared = (
        len(user_ids) * len(names) > PER_USER_WINNER_MAX_NAME_PAIRS
        if names is not None
        else len(user_ids) > PER_USER_WINNER_MAX_FULL_TOTAL_USERS
    )
    if not shared:
        users = (
            func.unnest(uuid_array(user_ids))
            .table_valued(column("user_id", PGUUID(as_uuid=True)))
            .render_derived(name="users")
        )
        every_name = select(users.c.user_id, Skill.name).join(Skill, true()).distinct()
        if names is not None:
            every_name = every_name.where(Skill.name.in_(names))
        return _skill_usage_from_winners(
            user_ids,
            every_name.cte(),
            None,
            ready,
            built_in_available=built_in_available,
            exclude_skill_ids=exclude_skill_ids,
            names=names,
            version_overrides=version_overrides,
            per_name=per_name,
        )
    generic_policies = select(
        literal(generic_user_id, PGUUID(as_uuid=True)).label("user_id"),
        Skill.id.label("skill_id"),
        _skill_policy_from_rank(cast(null(), Integer)).label("installation_policy"),
    )
    if names is not None:
        generic_policies = generic_policies.where(Skill.name.in_(names))
    generic_ready = set(ready[generic_user_id])
    ready = {user: apps for user, apps in ready.items() if user != generic_user_id}
    generic = _skill_name_winners(
        generic_policies.subquery(),
        [(generic_user_id, app_id) for app_id in generic_ready],
        built_in_available=built_in_available,
        exclude_skill_ids=exclude_skill_ids,
        version_overrides=version_overrides,
    ).cte()
    return _skill_usage_from_winners(
        user_ids,
        _user_specific_skill_names(
            user_ids,
            names,
            [
                (user_id, app_id)
                for user_id, app_ids in ready.items()
                for app_id in set(app_ids).symmetric_difference(generic_ready)
            ],
        ),
        generic,
        ready,
        built_in_available=built_in_available,
        exclude_skill_ids=exclude_skill_ids,
        names=names,
        version_overrides=version_overrides,
        per_name=per_name,
    )


def _skill_usage_from_winners(
    user_ids: Collection[UUID],
    pairs: CTE,
    generic: CTE | None,
    ready: Mapping[UUID, Collection[int]],
    *,
    built_in_available: ColumnElement[bool],
    exclude_skill_ids: Collection[UUID],
    names: Collection[str] | None,
    version_overrides: Mapping[UUID, UUID | None],
    per_name: bool,
) -> Select[tuple[UUID, str | None, int, int, int, Sequence[int] | None]]:
    """Each user's total: the ``generic`` winners, with ``pairs`` replaced.

    Without ``generic``, ``pairs`` must hold every user and name.
    """
    groups = _group_policy_ranks(user_ids, names=names)
    specific = _skill_name_winners(
        select(
            pairs.c.user_id,
            Skill.id.label("skill_id"),
            _skill_policy_from_rank(groups.c.rank).label("installation_policy"),
        )
        .select_from(pairs)
        .join(Skill, Skill.name == pairs.c.name)
        .outerjoin(
            groups,
            and_(groups.c.user_id == pairs.c.user_id, groups.c.skill_id == Skill.id),
        )
        .subquery(),
        [(user_id, app_id) for user_id, app_ids in ready.items() for app_id in app_ids],
        built_in_available=built_in_available,
        exclude_skill_ids=exclude_skill_ids,
        version_overrides=version_overrides,
    ).subquery()
    amount_names = ("bytes", "files", "unknown_skill_count")
    if per_name:
        replacements_by_name = (
            select(
                pairs.c.user_id,
                pairs.c.name,
                *(
                    func.coalesce(specific.c.winner[index], 0).label(name)
                    for index, name in zip((3, 4, 5), amount_names, strict=True)
                ),
                specific.c.winner,
            )
            .select_from(pairs)
            .outerjoin(
                specific,
                and_(
                    specific.c.user_id == pairs.c.user_id,
                    specific.c.name == pairs.c.name,
                ),
            )
        )
        if generic is None:
            return replacements_by_name
        rows = union_all(
            select(
                generic.c.user_id,
                generic.c.name,
                *(
                    generic.c.winner[index].label(name)
                    for index, name in zip((3, 4, 5), amount_names, strict=True)
                ),
                generic.c.winner,
            ),
            replacements_by_name,
        ).subquery()
        return select(*rows.c)
    replacements = (
        select(
            pairs.c.user_id,
            *(
                func.sum(
                    func.coalesce(specific.c.winner[index], 0)
                    - (
                        func.coalesce(generic.c.winner[index], 0)
                        if generic is not None
                        else 0
                    )
                ).label(name)
                for index, name in zip((3, 4, 5), amount_names, strict=True)
            ),
        )
        .select_from(pairs)
        .outerjoin(
            specific,
            and_(
                specific.c.user_id == pairs.c.user_id,
                specific.c.name == pairs.c.name,
            ),
        )
        .group_by(pairs.c.user_id)
    )
    if generic is not None:
        replacements = replacements.outerjoin(generic, generic.c.name == pairs.c.name)
    deltas = replacements.subquery()
    base = (
        select(
            *(
                func.coalesce(func.sum(generic.c.winner[index]), 0).label(name)
                for index, name in zip((3, 4, 5), amount_names, strict=True)
            )
        ).subquery()
        if generic is not None
        else None
    )
    # One statement includes existing users, generic winners and replacements.
    user_id = User.__table__.c.id
    stmt = (
        select(
            user_id.label("user_id"),
            literal(None, String).label("name"),
            *(
                (
                    func.coalesce(deltas.c[name], 0)
                    + (base.c[name] if base is not None else 0)
                ).label(name)
                for name in amount_names
            ),
            literal(None, ARRAY(BigInteger)).label("winner"),
        )
        .outerjoin(deltas, deltas.c.user_id == user_id)
        .where(user_id == any_(uuid_array(user_ids)))
    )
    if base is not None:
        stmt = stmt.join(base, true())
    return stmt


def lock_skill_limit_users(user_ids: Collection[UUID], db_session: Session) -> None:
    """Take the preference lock on many users, after membership and skill locks."""
    if not user_ids:
        return
    lock_group_membership(db_session)
    user_id = User.__table__.c.id
    db_session.execute(
        select(user_id)
        .where(user_id == any_(uuid_array(user_ids)))
        .order_by(user_id)
        .with_for_update(key_share=True)
    )


def capture_skill_limit_baseline(
    skill_ids: Collection[UUID],
    db_session: Session,
    *,
    user_ids: Collection[UUID] | None = None,
) -> SkillLimitBaseline:
    """Lock and measure users who can reach the skills before a write changes them.

    Pass ``user_ids`` when only those users' Skills change, such as an enable.
    """
    lock_group_membership(db_session)
    users = (
        set(user_ids)
        if user_ids is not None
        else skill_audience_user_ids(skill_ids, db_session)
    )
    lock_skill_limit_users(users, db_session)
    names = _skill_names(skill_ids, db_session)
    return SkillLimitBaseline(
        skill_ids=frozenset(skill_ids),
        user_ids=frozenset(user_ids) if user_ids is not None else None,
        names=names,
        before=skill_usage_for_users(users, db_session, names=names),
    )


def _skill_names(skill_ids: Collection[UUID], db_session: Session) -> frozenset[str]:
    if not skill_ids:
        return frozenset()
    return frozenset(
        db_session.scalars(select(Skill.name).where(Skill.id.in_(skill_ids)))
    )


def skill_limit_violations(
    baseline: SkillLimitBaseline, db_session: Session
) -> dict[UUID, tuple[SkillUsage, SkillLimit]]:
    """Return users the write puts over a limit, with proposed usage and failed limit.

    Locks users who gained access in stable order. Users already over may keep
    or reduce their usage. Only the changed names are measured, and only users
    whose usage grows get a full total.
    """
    db_session.flush()
    users = (
        set(baseline.user_ids)
        if baseline.user_ids is not None
        else skill_audience_user_ids(baseline.skill_ids, db_session)
        | baseline.before.keys()
    )
    new_users = users - baseline.before.keys()
    lock_skill_limit_users(new_users, db_session)
    names = baseline.names | _skill_names(baseline.skill_ids, db_session)
    after = skill_usage_for_users(users, db_session, names=names)
    before = {user_id: baseline.before.get(user_id, SkillUsage()) for user_id in users}
    # The changed Skills had none of these names or users before, so the
    # current usage without them is the baseline.
    for missing_users, missing_names in (
        (new_users, names),
        (users - new_users, names - baseline.names),
    ):
        if missing_users and missing_names:
            for user_id, usage in skill_usage_for_users(
                missing_users,
                db_session,
                exclude_skill_ids=baseline.skill_ids,
                names=missing_names,
            ).items():
                before[user_id] += usage
    deltas = {user_id: after[user_id] - before[user_id] for user_id in users}
    totals = skill_usage_for_users(
        [
            user_id
            for user_id, delta in deltas.items()
            if delta.charged_bytes > 0 or delta.charged_files > 0
        ],
        db_session,
    )
    violations: dict[UUID, tuple[SkillUsage, SkillLimit]] = {}
    for user_id, usage in totals.items():
        failed = failed_skill_limit(usage, usage - deltas[user_id])
        if failed is not None:
            violations[user_id] = (usage, failed)
    return violations


def skill_limit_violation(
    violations: Mapping[UUID, tuple[SkillUsage, SkillLimit]], actor_id: UUID | None
) -> SkillLimitViolation:
    actor = violations.get(actor_id) if actor_id is not None else None
    return SkillLimitViolation(
        failed_limit=(
            SkillLimit.BYTES
            if any(limit == SkillLimit.BYTES for _, limit in violations.values())
            else SkillLimit.FILES
        ),
        affected_user_count=len(violations),
        usage=SkillUsageSummary.from_usage(actor[0]) if actor is not None else None,
    )


def skill_limit_error(
    violations: Mapping[UUID, tuple[SkillUsage, SkillLimit]], actor_id: UUID | None
) -> OnyxError:
    actor = violations.get(actor_id) if actor_id is not None else None
    if actor is not None and len(violations) == 1:
        usage = actor[0]
        detail = (
            "This would put your skills at "
            f"{usage.charged_bytes / (1024 * 1024):.1f} MB in {usage.charged_files:,} "
            f"files. The limit is {SKILL_WRITE_MAX_BYTES // (1024 * 1024)} MB and "
            f"{SKILL_WRITE_MAX_FILES:,} files."
        )
    else:
        count = len(violations)
        detail = (
            f"This change would put {count} {'user' if count == 1 else 'users'} "
            f"past the {SKILL_WRITE_MAX_BYTES // (1024 * 1024)} MB or "
            f"{SKILL_WRITE_MAX_FILES:,}-file skill limit."
        )
    violation = skill_limit_violation(violations, actor_id)
    return OnyxError(
        OnyxErrorCode.PAYLOAD_TOO_LARGE,
        detail,
        extra={"skill_limit": violation.model_dump(mode="json")},
    )


def assert_skill_limit(
    baseline: SkillLimitBaseline, db_session: Session, *, actor_id: UUID | None
) -> None:
    """Raise 413 if the write since ``baseline`` puts any affected user over a limit."""
    violations = skill_limit_violations(baseline, db_session)
    if violations:
        raise skill_limit_error(violations, actor_id)


def skill_limit_blocks(
    user_id: UUID, skill_ids: Collection[UUID], db_session: Session
) -> dict[UUID, SkillLimit]:
    if not skill_ids:
        return {}
    return dict(
        db_session.execute(
            select(
                UserSkillLimitBlock.skill_id, UserSkillLimitBlock.failed_limit
            ).where(
                UserSkillLimitBlock.user_id == user_id,
                UserSkillLimitBlock.skill_id.in_(skill_ids),
            )
        )
        .tuples()
        .all()
    )


def connect_external_app_within_skill_limit__no_commit(
    external_app_id: int,
    user_id: UUID,
    connect: Callable[[], object],
    db_session: Session,
) -> dict[UUID, SkillLimit]:
    """Run ``connect`` and keep it; leave off the app's skills that do not fit.

    Earlier blocks for the app's skills are retried. Skills are tried in name
    order. A skill left off is tried again after a later one turns on, because
    that skill can replace a larger one of its name. The limit check never
    discards the connection: if it fails, the app connects without blocks and
    the runtime limit applies.
    """
    app_skill_ids = (
        select(Skill.id)
        .join(ExternalApp__Skill, ExternalApp__Skill.skill_id == Skill.id)
        .where(ExternalApp__Skill.external_app_id == external_app_id)
        .order_by(Skill.name, Skill.id)
    )
    skill_ids: list[UUID] | None = None
    baseline: SkillLimitBaseline | None = None
    try:
        with db_session.begin_nested():
            lock_group_membership(db_session)
            # Association writers lock the app row; this holds them off until commit.
            db_session.execute(
                select(ExternalApp.id)
                .where(ExternalApp.id == external_app_id)
                .with_for_update(key_share=True)
            )
            skill_ids = list(db_session.scalars(app_skill_ids))
            baseline = capture_skill_limit_baseline(
                skill_ids, db_session, user_ids=[user_id]
            )
    except Exception:
        logger.exception("Skill limit baseline failed for app %s", external_app_id)
    connect()
    db_session.flush()
    if skill_ids is None:
        skill_ids = list(db_session.scalars(app_skill_ids))
    if not skill_ids:
        return {}
    blocked: dict[UUID, SkillLimit] = {}
    try:
        with db_session.begin_nested():
            db_session.execute(
                delete(UserSkillLimitBlock).where(
                    UserSkillLimitBlock.user_id == user_id,
                    UserSkillLimitBlock.skill_id.in_(skill_ids),
                )
            )
        # A failed usage check must not restore blocks from an earlier connection.
        if baseline is None:
            return {}
        with db_session.begin_nested():
            if not skill_limit_violations(baseline, db_session):
                return {}
            db_session.execute(
                insert(UserSkillLimitBlock).values(
                    [
                        {
                            "user_id": user_id,
                            "skill_id": skill_id,
                            "failed_limit": SkillLimit.BYTES,
                        }
                        for skill_id in skill_ids
                    ]
                )
            )
            pending = list(skill_ids)
            failures = 0
            # Stop when every skill left off fails with no turn-on in between.
            while failures < len(pending):
                skill_id = pending.pop(0)
                block = (
                    UserSkillLimitBlock.user_id == user_id,
                    UserSkillLimitBlock.skill_id == skill_id,
                )
                db_session.execute(delete(UserSkillLimitBlock).where(*block))
                violation = skill_limit_violations(baseline, db_session).get(user_id)
                if violation is None:
                    blocked.pop(skill_id, None)
                    failures = 0
                    continue
                blocked[skill_id] = violation[1]
                pending.append(skill_id)
                failures += 1
                db_session.execute(
                    insert(UserSkillLimitBlock).values(
                        user_id=user_id,
                        skill_id=skill_id,
                        failed_limit=violation[1],
                    )
                )
    except Exception:
        logger.exception("Skill limit check failed for app %s", external_app_id)
        return {}
    return blocked


def fetch_skill(
    skill_id: UUID,
    *,
    policy: SkillManagementPolicy,
    db_session: Session,
    user: User,
    lock_for_update: bool = False,
    allow_retired: bool = False,
    allow_management: bool = True,
) -> Skill | None:
    stmt = _skill_select_for_management_policy(
        policy=policy,
        db_session=db_session,
        user=user,
        order_by_name=False,
        include_retired=lock_for_update or allow_retired,
        allow_management=allow_management,
    ).where(Skill.id == skill_id)
    if lock_for_update:
        stmt = stmt.with_for_update(of=Skill).execution_options(populate_existing=True)
    skill = db_session.scalars(stmt).one_or_none()
    if skill is not None and lock_for_update:
        db_session.refresh(skill, ["current_version"])
        if not allow_retired:
            assert_skill_mutable(skill)
    return skill


def add_new_skill__no_commit(
    skill: Skill,
    db_session: Session,
    *,
    intended_public_permission: SkillSharePermission | None = None,
) -> Skill:
    lock_group_membership(db_session)
    if skill.built_in_skill_id is None:
        public = skill.public_permission or intended_public_permission
        owner_id = skill.author_user_id if public is None else None
        if skill.marketplace_id is not None:
            owner_id = db_session.execute(
                select(Marketplace.owner_user_id).where(
                    Marketplace.id == skill.marketplace_id
                )
            ).scalar_one()
        assert_new_skill_name_available(owner_id, skill.name, db_session)
    db_session.add(skill)
    db_session.flush()
    return skill


def _lock_user_skill_preferences(user_id: UUID, db_session: Session) -> None:
    lock_group_membership(db_session)
    # Serialize preference changes without blocking foreign-key reads from sharing.
    db_session.execute(
        select(User.__table__.c.id)
        .where(User.__table__.c.id == user_id)
        .with_for_update(key_share=True)
    )


def enable_new_skill_if_name_available__no_commit(
    skill: Skill,
    user_id: UUID,
    db_session: Session,
) -> bool:
    """Enable a newly inserted skill under the same user lock as toggles."""
    _lock_user_skill_preferences(user_id, db_session)
    user = lock_resource_access_user(user_id, db_session)
    baseline = capture_skill_limit_baseline([skill.id], db_session, user_ids=[user_id])
    policy = resolve_skill_installation_policies([user.id], [skill.id], db_session).get(
        (user.id, skill.id)
    )
    if policy is None or policy == SkillInstallationPolicy.NOT_AVAILABLE:
        return False
    if policy == SkillInstallationPolicy.REQUIRED:
        return True
    if (
        db_session.scalar(
            select(Skill.id).where(
                Skill.name == skill.name,
                Skill.id != skill.id,
                _is_enabled_for_user(user.id),
            )
        )
        is not None
    ):
        return False
    inserted_user_id = db_session.scalar(
        insert(UserSkillPreference)
        .values(
            user_id=user_id,
            skill_id=skill.id,
            name=skill.name,
            enabled=True,
            enabled_at=func.clock_timestamp(),
        )
        .on_conflict_do_nothing()
        .returning(UserSkillPreference.user_id)
    )
    if inserted_user_id is None:
        return False
    assert_skill_limit(baseline, db_session, actor_id=user_id)
    return True


def clear_enabled_skill_preferences__no_commit(
    skill_ids: Collection[UUID], db_session: Session, *, user_id: UUID | None = None
) -> None:
    """App removal preserves opt-outs and choices hidden by Not available."""
    lock_group_membership(db_session)
    users = select(UserSkillPreference.user_id).where(
        UserSkillPreference.skill_id.in_(skill_ids),
        UserSkillPreference.enabled.is_(True),
    )
    if user_id is not None:
        users = users.where(UserSkillPreference.user_id == user_id)
    user_ids = list(
        db_session.scalars(users.distinct().order_by(UserSkillPreference.user_id))
    )
    for affected_user_id in user_ids:
        _lock_user_skill_preferences(affected_user_id, db_session)
    policies = _skill_installation_policy_rows(user_ids, skill_ids)
    db_session.execute(
        delete(UserSkillPreference)
        .where(
            UserSkillPreference.enabled.is_(True),
            exists().where(
                policies.c.user_id == UserSkillPreference.user_id,
                policies.c.skill_id == UserSkillPreference.skill_id,
                policies.c.installation_policy != SkillInstallationPolicy.NOT_AVAILABLE,
            ),
        )
        .execution_options(synchronize_session=False)
    )


def replace_skill_bundle(
    *,
    skill: Skill,
    ingested: IngestedBundle,
    creator_id: UUID,
    db_session: Session,
    prepared: PreparedSkillVersionWrite,
) -> list[str]:
    """Replace with content prepared before write locks; return post-commit cleanup."""
    if not skill.is_custom:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Built-in skills have no bundle.")
    baseline = capture_skill_limit_baseline([skill.id], db_session)
    stale_file_ids = save_skill_version(
        skill, ingested, creator_id, db_session, prepared=prepared
    )
    assert_skill_limit(baseline, db_session, actor_id=creator_id)
    return stale_file_ids


def create_skill_from_ingested_bundle(
    ingested: IngestedBundle,
    creator_id: UUID,
    db_session: Session,
    *,
    intended_public_permission: SkillSharePermission | None = None,
) -> Skill:
    skill = add_new_skill__no_commit(
        Skill(
            name=ingested.canonical_name,
            description=ingested.description,
            current_version_id=uuid4(),
            author_user_id=creator_id,
        ),
        db_session,
        intended_public_permission=intended_public_permission,
    )
    save_skill_version(skill, ingested, creator_id, db_session, initial=True)
    return skill


def set_skill_public_permission(
    *,
    skill: Skill,
    public_permission: SkillSharePermission | None,
    db_session: Session,
) -> None:
    assert_skill_mutable(skill)
    is_associated = db_session.scalar(
        select(
            exists().where(
                ExternalApp__Skill.skill_id == skill.id,
            )
        )
    )
    if (
        is_associated
        and not is_company_marketplace_skill(skill, db_session)
        and public_permission != SkillSharePermission.VIEWER
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Skills associated with an external app must remain visible to the "
            "organization with viewer access.",
        )
    if (
        public_permission is None
        and skill.is_custom
        and skill.author_user_id is None
        and skill.marketplace_id is None
    ):
        raise OnyxError(
            OnyxErrorCode.CONFLICT,
            "Assign an owner before making this skill private.",
        )
    skill.public_permission = public_permission
    db_session.flush()


def skill_user_states(
    user: User,
    skill_ids: Iterable[UUID],
    db_session: Session,
) -> dict[UUID, SkillUserState]:
    requested_ids = set(skill_ids)
    if not requested_ids:
        return {}

    external_app_dependencies = get_skill_external_app_dependencies(
        db_session,
        user,
    )
    winners = resolve_skill_runtime_names(
        user, db_session, dependencies=external_app_dependencies
    )
    policies = _skill_installation_policy_rows([user.id], requested_ids)
    policy = policies.c.installation_policy
    rows = db_session.execute(
        select(
            Skill.id,
            policy,
            _is_enabled_for_user(user.id, policy).label("enabled"),
            skill_visible_to_user(user.id, installation_policy=policy).label("visible"),
            and_(
                Skill.built_in_skill_id.is_(None),
                SkillVersion.id.is_not(None),
                SkillVersion.is_valid.is_not(False),
                policy.not_in(
                    [
                        SkillInstallationPolicy.REQUIRED,
                        SkillInstallationPolicy.NOT_AVAILABLE,
                    ]
                ),
            ).label("supports_preference"),
        )
        .outerjoin(Skill.current_version)
        .join(policies, policies.c.skill_id == Skill.id)
        .where(Skill.id.in_(requested_ids), Skill.retired_at.is_(None))
    )
    blocks = skill_limit_blocks(user.id, requested_ids, db_session)
    return {
        skill_id: SkillUserState(
            enabled=enabled
            and skill_id not in blocks
            and winners.get(skill_id, skill_id) == skill_id,
            can_toggle=visible
            and supports_preference
            and (
                enabled
                or skill_id not in external_app_dependencies
                or external_app_dependencies[skill_id].ready
            ),
            external_app_dependency=external_app_dependencies.get(skill_id),
            effective_installation_policy=SkillInstallationPolicy(effective_policy),
            hidden_by_skill_id=(
                winners[skill_id]
                if skill_id in winners and winners[skill_id] != skill_id
                else None
            ),
            skill_limit_block=blocks.get(skill_id),
        )
        for skill_id, effective_policy, enabled, visible, supports_preference in rows
    }


def set_skill_enabled_for_user(
    *,
    skill_id: UUID,
    enabled: bool,
    replace_conflict: bool = False,
    user: User,
    db_session: Session,
    allow_management: bool = True,
) -> Skill:
    _lock_user_skill_preferences(user.id, db_session)
    user = lock_resource_access_user(user.id, db_session)
    skill = fetch_skill(
        skill_id,
        policy=SkillManagementPolicy.VIEW,
        user=user,
        db_session=db_session,
        lock_for_update=True,
        allow_management=allow_management,
    )
    if skill is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            "Skill is not visible.",
        )

    state = skill_user_states(user, [skill.id], db_session)[skill.id]
    if not state.can_toggle:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This skill cannot be enabled or disabled.",
        )
    # A disable can also grow usage when it reveals a larger skill of that name.
    baseline = capture_skill_limit_baseline([skill.id], db_session, user_ids=[user.id])
    # An explicit choice retries a skill that an app connection left off.
    db_session.execute(
        delete(UserSkillLimitBlock).where(
            UserSkillLimitBlock.user_id == user.id,
            UserSkillLimitBlock.skill_id == skill.id,
        )
    )

    if enabled:
        required_names = resolve_skill_runtime_names(
            user, db_session, include_skill_id=skill.id, required_only=True
        )
        if required_names.get(skill.id, skill.id) != skill.id:
            raise OnyxError(
                OnyxErrorCode.SKILL_NAME_CONFLICT,
                "A required skill already uses this name.",
            )
        current_names = resolve_skill_runtime_names(user, db_session)
        current_winners = set(current_names.values())
        conflicts = db_session.scalars(
            select(Skill.id).where(
                Skill.name == skill.name,
                Skill.id != skill.id,
                _is_enabled_for_user(user.id),
                _effective_skill_policy(user.id) != SkillInstallationPolicy.REQUIRED,
            )
        ).all()
        if conflicts:
            if not replace_conflict and current_winners.intersection(conflicts):
                raise OnyxError(
                    OnyxErrorCode.SKILL_NAME_CONFLICT,
                    f"Another skill named '{skill.name}' is already enabled.",
                )
            db_session.execute(
                insert(UserSkillPreference)
                .values(
                    [
                        {
                            "user_id": user.id,
                            "skill_id": conflict,
                            "name": skill.name,
                            "enabled": False,
                        }
                        for conflict in conflicts
                    ]
                )
                .on_conflict_do_update(
                    index_elements=[
                        UserSkillPreference.user_id,
                        UserSkillPreference.skill_id,
                    ],
                    set_={"enabled": False},
                )
            )
        db_session.execute(
            update(UserSkillPreference)
            .where(
                UserSkillPreference.user_id == user.id,
                UserSkillPreference.name == skill.name,
                UserSkillPreference.skill_id != skill.id,
                UserSkillPreference.enabled.is_(True),
            )
            .values(enabled=False)
        )
    db_session.execute(
        insert(UserSkillPreference)
        .values(
            user_id=user.id,
            skill_id=skill.id,
            name=skill.name,
            enabled=enabled,
            enabled_at=func.clock_timestamp() if enabled else None,
        )
        .on_conflict_do_update(
            index_elements=[UserSkillPreference.user_id, UserSkillPreference.skill_id],
            set_={
                "enabled": enabled,
                "enabled_at": func.clock_timestamp()
                if enabled
                else UserSkillPreference.enabled_at,
            },
        )
    )
    assert_skill_limit(baseline, db_session, actor_id=user.id)
    return skill


def set_skill_installation_policy(
    skill: Skill,
    policy: SkillInstallationPolicy,
    db_session: Session,
) -> None:
    assert_skill_mutable(skill)
    if policy != SkillInstallationPolicy.AVAILABLE and not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Installation policies apply only to custom skills.",
        )
    skill.installation_policy = policy
    db_session.flush()


def _flush_shares(db_session: Session, fk_violation_detail: str) -> None:
    try:
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, fk_violation_detail) from e
        raise


def replace_skill_shares(
    *,
    skill: Skill,
    db_session: Session,
    user_shares: Mapping[UUID, SkillSharePermission] | None = None,
    group_shares: Mapping[int, SkillSharePermission] | None = None,
    group_installation_policies: Mapping[int, SkillInstallationPolicy | None]
    | None = None,
) -> None:
    assert_skill_mutable(skill)
    if user_shares is not None:
        shared_at = {share.user_id: share.created_at for share in skill.user_shares}
        db_session.execute(delete(Skill__User).where(Skill__User.skill_id == skill.id))
        for user_id, permission in user_shares.items():
            share = Skill__User(
                skill_id=skill.id, user_id=user_id, permission=permission
            )
            if user_id in shared_at:
                share.created_at = shared_at[user_id]
            db_session.add(share)
        _flush_shares(db_session, "One or more user share targets do not exist.")
        db_session.expire(skill, ["user_shares"])

    if group_shares is not None:
        group_shared_at = {
            share.user_group_id: share.created_at for share in skill.group_shares
        }
        policies = {
            share.user_group_id: share.installation_policy
            for share in skill.group_shares
        }
        if group_installation_policies is not None:
            policies.update(group_installation_policies)
        assert_not_shared_with_default_group(db_session, list(group_shares))
        db_session.execute(
            delete(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill.id)
        )
        for group_id, permission in group_shares.items():
            group_share = Skill__UserGroup(
                skill_id=skill.id,
                user_group_id=group_id,
                permission=permission,
                installation_policy=policies.get(group_id),
            )
            if group_id in group_shared_at:
                group_share.created_at = group_shared_at[group_id]
            db_session.add(group_share)
        _flush_shares(db_session, "One or more group share targets do not exist.")
        db_session.expire(skill, ["group_shares"])


def transfer_skill_ownership(
    *,
    skill: Skill,
    new_owner_user_id: UUID,
    db_session: Session,
) -> None:
    assert_skill_content_editable(skill)
    if not skill.is_custom:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Skill '{skill.name}' is a built-in and cannot have its ownership transferred.",
        )

    previous_owner_user_id = skill.author_user_id
    if new_owner_user_id == previous_owner_user_id:
        return

    baseline = capture_skill_limit_baseline([skill.id], db_session)
    try:
        skill.author_user_id = new_owner_user_id
        db_session.execute(
            delete(Skill__User).where(
                Skill__User.skill_id == skill.id,
                Skill__User.user_id == new_owner_user_id,
            )
        )
        if previous_owner_user_id is not None:
            share_upsert = (
                insert(Skill__User)
                .values(
                    skill_id=skill.id,
                    user_id=previous_owner_user_id,
                    permission=SkillSharePermission.EDITOR,
                )
                .on_conflict_do_update(
                    index_elements=[Skill__User.skill_id, Skill__User.user_id],
                    set_={"permission": SkillSharePermission.EDITOR},
                )
                .returning(Skill__User)
            )
            db_session.scalars(
                share_upsert,
                execution_options={"populate_existing": True},
            ).one()
        db_session.flush()
    except IntegrityError as e:
        if is_fk_violation(e):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "New owner user does not exist.",
            ) from e
        raise
    assert_skill_limit(baseline, db_session, actor_id=None)


def delete_skill(skill: Skill, db_session: Session) -> list[str]:
    """Hard-delete a locked skill and its versions. Returns every bundle file id
    for cleanup after commit."""
    file_ids = skill_bundle_file_ids(skill, db_session)
    db_session.delete(skill)
    db_session.flush()
    return sorted(file_ids)


def persist_skill_validity(
    updates: Iterable[SkillValidityUpdate],
) -> None:
    """Persist classifications if each skill still references the observed bundle."""
    if not updates:
        return

    with get_session_with_current_tenant() as db_session:
        for validity_update in updates:
            persist_skill_version_validity(
                skill_id=validity_update.skill_id,
                version_id=validity_update.version_id,
                bundle_file_id=validity_update.bundle_file_id,
                is_valid=validity_update.is_valid,
                db_session=db_session,
            )
        db_session.commit()


SkillBulkAction = Literal["enable", "disable", "delete"]


def ensure_can_edit_org_visibility(
    skill: Skill, user: User, *, allow_management: bool = True
) -> None:
    assert_skill_mutable(skill)
    if skill.marketplace_id is not None and skill.author_user_id == user.id:
        return
    if not (allow_management and has_global_permission(user, Permission.MANAGE_SKILLS)):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Company access changes require global manage-skills permission.",
        )


class SkillAccessAdapter(ResourceAccessAdapter[Skill]):
    permission = Permission.MANAGE_SKILLS

    def load(
        self,
        resource_id: UUID,
        user: User,
        db_session: Session,
        *,
        allow_management: bool,
    ) -> Skill:
        skill = fetch_skill(
            resource_id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
            allow_management=allow_management,
        )
        if skill is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        if is_company_marketplace_skill(skill, db_session):
            if not allow_management:
                raise OnyxError(
                    OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                    "API token lacks manage-skills scope.",
                )
            assert_within_scope(
                user,
                db_session,
                permission=self.permission,
                current_group_ids=[share.user_group_id for share in skill.group_shares],
                requested_group_ids=[],
                is_non_public=skill.public_permission is None,
            )
        return skill

    def state(self, resource: Skill) -> ResourceAccessState:
        return ResourceAccessState(
            owner_user_id=resource.author_user_id,
            public_permission=resource.public_permission,
            user_shares={
                share.user_id: share.permission for share in resource.user_shares
            },
            group_shares={
                share.user_group_id: share.permission for share in resource.group_shares
            },
            group_installation_policies={
                share.user_group_id: share.installation_policy
                for share in resource.group_shares
            },
            sharing_owner_id=(
                resource.author_user_id if resource.marketplace_id is not None else None
            ),
        )

    def write(
        self, resource: Skill, change: SkillSharingChange, db_session: Session
    ) -> None:
        before = self.state(resource), resource.installation_policy
        if change.set_public_permission:
            set_skill_public_permission(
                skill=resource,
                public_permission=change.public_permission,
                db_session=db_session,
            )
        if change.installation_policy is not None:
            set_skill_installation_policy(
                resource, change.installation_policy, db_session
            )
        replace_skill_shares(
            skill=resource,
            user_shares=change.user_shares,
            group_shares=change.group_shares,
            group_installation_policies=change.group_installation_policies,
            db_session=db_session,
        )
        if before != (
            self.state(resource),
            resource.installation_policy,
        ) and is_company_marketplace_skill(resource, db_session):
            resource.follows_marketplace_access = False

    def affected_users(
        self, resource_ids: Collection[UUID], db_session: Session
    ) -> dict[UUID, set[UUID]]:
        return affected_user_ids_for_skills(resource_ids, db_session)


def share_skill__no_commit(
    skill: Skill,
    change: SkillSharingChange,
    user: User,
    db_session: Session,
    *,
    allow_management: bool = True,
) -> set[UUID]:
    return mutate_resource_access(
        [skill.id],
        change,
        user,
        db_session,
        SkillAccessAdapter(),
        allow_management=allow_management,
    ).affected


def delete_skill_for_user__no_commit(
    skill: Skill, user: User, db_session: Session, *, allow_global_management: bool
) -> tuple[set[UUID], list[str]]:
    """Delete a skill the user may edit. Returns the affected users and the
    bundle file ids for cleanup after commit."""
    assert_skill_deletable(skill)
    if (
        skill.marketplace_id is not None
        and skill.author_user_id != user.id
        and not (
            allow_global_management
            and has_global_permission(user, Permission.MANAGE_SKILLS)
        )
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Deleting retired synced skills requires the owner or global manage-skills permission.",
        )
    if (
        skill.retired_at is None
        and (
            skill.installation_policy == SkillInstallationPolicy.REQUIRED
            or any(
                share.installation_policy == SkillInstallationPolicy.REQUIRED
                for share in skill.group_shares
            )
        )
        and not (
            allow_global_management
            and has_global_permission(user, Permission.MANAGE_SKILLS)
        )
    ):
        raise OnyxError(
            OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
            "Deleting required skills requires global manage-skills permission.",
        )
    affected = affected_user_ids_for_skill(skill, db_session)
    return affected, delete_skill(skill, db_session)


def create_skill_from_bundle__no_commit(
    ingested: IngestedBundle,
    change: SkillSharingChange | None,
    auto_enable: bool,
    user: User,
    db_session: Session,
    *,
    allow_management: bool = True,
) -> tuple[Skill, bool, set[UUID]]:
    """Create a skill from a stored bundle inside a savepoint, so a name
    conflict or a rejected access change rolls back this skill only. Returns
    the skill, whether it was enabled for the user, and the affected users."""
    with db_session.begin_nested():
        user = lock_resource_access_user(user.id, db_session)
        skill = create_skill_from_ingested_bundle(
            ingested,
            user.id,
            db_session,
            intended_public_permission=change.public_permission
            if change is not None
            else None,
        )
        baseline = capture_skill_limit_baseline([skill.id], db_session)
        affected: set[UUID] = set()
        if change is not None:
            affected = share_skill__no_commit(
                skill, change, user, db_session, allow_management=allow_management
            )
        enabled = auto_enable and enable_new_skill_if_name_available__no_commit(
            skill, user.id, db_session
        )
        assert_skill_limit(baseline, db_session, actor_id=user.id)
        if enabled:
            affected.add(user.id)
    return skill, enabled, affected


def bulk_update_skill__no_commit(
    skill_id: UUID,
    action: SkillBulkAction,
    user: User,
    db_session: Session,
    *,
    allow_global_management: bool,
) -> tuple[set[UUID], list[str]]:
    """Apply one bulk action to one skill inside a savepoint, so a failure
    rolls back this skill only. Returns the affected users and, for a delete,
    the bundle file ids for cleanup after commit."""
    with db_session.begin_nested():
        if action in ("enable", "disable"):
            set_skill_enabled_for_user(
                skill_id=skill_id,
                enabled=action == "enable",
                user=user,
                db_session=db_session,
                allow_management=allow_global_management,
            )
            return {user.id}, []
        user = lock_resource_access_user(user.id, db_session)
        skill = fetch_skill(
            skill_id,
            policy=SkillManagementPolicy.EDIT,
            user=user,
            db_session=db_session,
            lock_for_update=True,
            allow_retired=action == "delete",
            allow_management=allow_global_management,
        )
        if skill is None:
            raise OnyxError(OnyxErrorCode.NOT_FOUND, "Skill not found")
        return delete_skill_for_user__no_commit(
            skill, user, db_session, allow_global_management=allow_global_management
        )
