"""Who can see, edit and run a plugin, as SQL expressions.

The rule, once:

- Visible: the plugin is in the Organization library and the install setting
  for the user is not NOT_AVAILABLE; or the user is its author; or a
  plugin__user row; or a plugin__user_group row with a permission for one of
  the user's groups. A group row with no permission holds only a group install
  setting and grants nothing. A row with a permission cannot be NOT_AVAILABLE.
- Editable: the author, or EDITOR through plugin__user or plugin__user_group.
  There is no organization-wide edit.
- Install setting for a user: the company setting is the plugin's own setting,
  else its marketplace default. Each of the user's groups gives its own setting,
  else the company setting. The most open one wins; a user in no group gets the
  company setting. Default groups do not count. The author and a share (user
  or group) get at least AVAILABLE.
- Enabled: REQUIRED is on. DEFAULT is on unless the user turned it off.
  AVAILABLE is on only when the user turned it on. A hidden plugin is off; its
  saved choice stays.
- Name order: when two enabled plugins of a user hold one skill name, a
  built-in skill keeps it, then a plugin REQUIRED for the user, then a
  published plugin, then the user's own, then a shared one. The older plugin
  wins a tie.
- Version a user runs: the author and share recipients run current_version_id.
  Users who see the plugin only through the organization run
  published_version_id, or current_version_id when it is empty.

Each expression takes the plugin and marketplace entities (the classes or
aliases of them) and a user id, which can be a value or a column, so one query
can compute access for many users or many plugins.
"""

from collections.abc import Collection, Iterable
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import cast
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    ColumnElement,
    and_,
    case,
    func,
    literal,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql.elements import KeyedColumnElement
from sqlalchemy.sql.selectable import Select, Subquery

from onyx.db.enums import (
    AccountType,
    MarketplaceKind,
    PluginInstallationPolicy,
    SandboxStatus,
    SkillSharePermission,
)
from onyx.db.external_app_readiness import app_dependency_states, waits_for_app
from onyx.db.models import (
    Marketplace,
    Plugin,
    Plugin__User,
    Plugin__UserGroup,
    PluginSkill,
    PluginVersion,
    Sandbox,
    User,
    User__UserGroup,
    UserGroup,
    UserPluginPreference,
)
from onyx.db.scoped_permissions import (
    managed_group_member_ids_subquery,
    scoped_group_ids_subquery,
)
from onyx.skills.models import SkillUsage

# user__user_group.user_id is typed nullable but never NULL in a join.
UserIdExpr = (
    UUID
    | ColumnElement[UUID]
    | InstrumentedAttribute[UUID]
    | InstrumentedAttribute[UUID | None]
)

# Most open first. The only ranking of install settings.
_POLICY_RANK: dict[PluginInstallationPolicy, int] = {
    PluginInstallationPolicy.REQUIRED: 3,
    PluginInstallationPolicy.DEFAULT: 2,
    PluginInstallationPolicy.AVAILABLE: 1,
    PluginInstallationPolicy.NOT_AVAILABLE: 0,
}


def policy_rank(policy: PluginInstallationPolicy) -> int:
    return _POLICY_RANK[policy]


def _rank_of(
    policy: ColumnElement[PluginInstallationPolicy]
    | ColumnElement[PluginInstallationPolicy | None]
    | InstrumentedAttribute[PluginInstallationPolicy | None],
) -> ColumnElement[int]:
    return case(_POLICY_RANK, value=policy)


def company_installation_policy(
    plugin: type[Plugin], marketplace: type[Marketplace]
) -> ColumnElement[PluginInstallationPolicy]:
    return func.coalesce(
        plugin.installation_policy, marketplace.default_installation_policy
    )


def plugin_shared_with_user(
    plugin: type[Plugin],
    user_id: UserIdExpr,
    permission: SkillSharePermission | None = None,
) -> ColumnElement[bool]:
    """A plugin__user row, or a plugin__user_group row with a permission for
    one of the user's groups. With ``permission``, only rows at that level."""
    user_share = (
        select(Plugin__User.plugin_id)
        .where(Plugin__User.plugin_id == plugin.id, Plugin__User.user_id == user_id)
        .correlate_except(Plugin__User)
    )
    group_share = (
        select(Plugin__UserGroup.plugin_id)
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Plugin__UserGroup.user_group_id,
        )
        .where(
            Plugin__UserGroup.plugin_id == plugin.id,
            User__UserGroup.user_id == user_id,
            Plugin__UserGroup.permission.is_not(None),
        )
        .correlate_except(Plugin__UserGroup, User__UserGroup)
    )
    if permission is not None:
        user_share = user_share.where(Plugin__User.permission == permission)
        group_share = group_share.where(Plugin__UserGroup.permission == permission)
    return or_(user_share.exists(), group_share.exists())


def _granted(plugin: type[Plugin], user_id: UserIdExpr) -> ColumnElement[bool]:
    return or_(
        plugin.author_user_id == user_id, plugin_shared_with_user(plugin, user_id)
    )


def _with_share_floor(
    rank: ColumnElement[int], granted: ColumnElement[bool]
) -> ColumnElement[int]:
    """The author and a share (``granted``) get at least AVAILABLE."""
    return case(
        (granted, func.greatest(rank, policy_rank(PluginInstallationPolicy.AVAILABLE))),
        else_=rank,
    )


def _visible(
    granted: ColumnElement[bool],
    published: ColumnElement[bool],
    setting_rank: ColumnElement[int],
) -> ColumnElement[bool]:
    return or_(
        granted,
        and_(
            published,
            setting_rank > policy_rank(PluginInstallationPolicy.NOT_AVAILABLE),
        ),
    )


def _version_for(
    granted: ColumnElement[bool],
    current_version_id: ColumnElement[UUID] | InstrumentedAttribute[UUID],
    published_version_id: ColumnElement[UUID | None]
    | InstrumentedAttribute[UUID | None],
) -> ColumnElement[UUID]:
    return case(
        (granted, current_version_id),
        else_=func.coalesce(published_version_id, current_version_id),
    )


def plugin_editable_by_user(
    plugin: type[Plugin], user_id: UserIdExpr
) -> ColumnElement[bool]:
    return or_(
        plugin.author_user_id == user_id,
        plugin_shared_with_user(plugin, user_id, SkillSharePermission.EDITOR),
    )


def plugin_in_managed_scope(
    plugin: type[Plugin], marketplace: type[Marketplace], manager: User
) -> ColumnElement[bool]:
    """H6 and R17: a group manager acts on a plugin that is not published, is
    shared with a group they manage, and is shared with no other group and no
    user outside their groups. Fails closed for a user who manages no group."""
    managed = scoped_group_ids_subquery(manager)
    group_share = select(Plugin__UserGroup.plugin_id).where(
        Plugin__UserGroup.plugin_id == plugin.id,
        Plugin__UserGroup.permission.is_not(None),
    )
    user_share_outside = select(Plugin__User.plugin_id).where(
        Plugin__User.plugin_id == plugin.id,
        Plugin__User.user_id.not_in(managed_group_member_ids_subquery(manager)),
    )
    return and_(
        marketplace.kind != MarketplaceKind.ORGANIZATION_LIBRARY,
        group_share.where(Plugin__UserGroup.user_group_id.in_(managed)).exists(),
        ~group_share.where(Plugin__UserGroup.user_group_id.not_in(managed)).exists(),
        ~user_share_outside.exists(),
    )


def plugin_required_for_anyone(
    plugin: type[Plugin], marketplace: type[Marketplace]
) -> ColumnElement[bool]:
    """The company setting is REQUIRED, or a group row is REQUIRED for a member
    who can see the plugin. REQUIRED is the most open setting, so that member
    gets REQUIRED."""
    required = PluginInstallationPolicy.REQUIRED
    group_row = aliased(Plugin__UserGroup)
    membership = aliased(User__UserGroup)
    member_required = (
        select(membership.user_id)
        .join(group_row, group_row.user_group_id == membership.user_group_id)
        .where(
            group_row.plugin_id == plugin.id,
            group_row.installation_policy == required,
            _visible(
                _granted(plugin, membership.user_id),
                marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY,
                literal(policy_rank(required)),
            ),
        )
        .correlate_except(group_row, membership)
    )
    return or_(
        company_installation_policy(plugin, marketplace) == required,
        member_required.exists(),
    )


def plugin_ids_in_managed_scope(
    plugin_ids: Iterable[UUID], manager: User, db_session: Session
) -> set[UUID]:
    ids = sorted(set(plugin_ids))
    if not ids:
        return set()
    return set(
        db_session.scalars(
            select(Plugin.id)
            .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
            .where(
                Plugin.id.in_(ids),
                plugin_in_managed_scope(Plugin, Marketplace, manager),
            )
        )
    )


def version_user_runs(plugin: type[Plugin], user_id: UserIdExpr) -> ColumnElement[UUID]:
    return _version_for(
        _granted(plugin, user_id),
        plugin.current_version_id,
        plugin.published_version_id,
    )


def frontmatter_in_version(
    key: str, version_id: ColumnElement[UUID]
) -> ColumnElement[str]:
    """A frontmatter value of the version's first skill, by path. A skill
    plugin has one skill, at the bundle root."""
    return (
        select(PluginSkill.frontmatter[key].astext)
        .where(PluginSkill.plugin_version_id == version_id)
        .order_by(PluginSkill.path)
        .limit(1)
        .correlate_except(PluginSkill)
        .scalar_subquery()
    )


def version_is_valid(version_id: ColumnElement[UUID]) -> ColumnElement[bool | None]:
    """Lazy validity of a version. NULL while the push has not classified it."""
    return (
        select(PluginVersion.is_valid)
        .where(PluginVersion.id == version_id)
        .correlate_except(PluginVersion)
        .scalar_subquery()
    )


# --- Install settings and choices of many users -----------------------------

_POLICY_OF_RANK: dict[int, PluginInstallationPolicy] = {
    rank: policy for policy, rank in _POLICY_RANK.items()
}


class SkillNameRank(IntEnum):
    """Who keeps a skill name that two enabled skills of a user hold. Lower
    wins."""

    REQUIRED = 0
    PUBLISHED = 1
    OWN = 2
    SHARED = 3


class KeepGroup(IntEnum):
    """Run-time keep order: a lower group stays first."""

    REQUIRED = 0
    TURNED_ON = 1
    INSTALLED_BY_DEFAULT = 2


class UserPluginState(BaseModel):
    """One plugin that one user can see, as that user gets it."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    plugin_id: UUID
    # The install setting for the user, with the author and share floor.
    installation_policy: PluginInstallationPolicy
    published: bool
    is_author: bool
    # The version the user runs, its bundle and its lazy validity.
    version_id: UUID
    bundle_file_id: str | None
    version_is_valid: bool | None
    # The user's choice under the setting, before the name order.
    enabled: bool
    # Enabled, the version is not invalid, and the app it needs, if any, is
    # ready for the user. Only these plugins count for the skill limits.
    can_run: bool
    created_at: datetime
    # Names from the plugin_skill rows of the version the user runs, by path.
    skill_names: tuple[str, ...]
    # Recorded size of the version the user runs; a NULL size or file count
    # is 0. None when both are NULL: a backfilled version before the repair
    # task measures it, or a version with no bundle.
    usage: SkillUsage | None
    # The user turned the plugin on (a saved choice, not the default).
    turned_on: bool
    enabled_at: datetime | None
    # The latest share or group row the user gets the plugin through, else
    # when the plugin was created.
    shared_at: datetime

    @property
    def name_rank(self) -> SkillNameRank:
        if self.installation_policy == PluginInstallationPolicy.REQUIRED:
            return SkillNameRank.REQUIRED
        if self.published:
            return SkillNameRank.PUBLISHED
        if self.is_author:
            return SkillNameRank.OWN
        return SkillNameRank.SHARED

    @property
    def keep_key(self) -> tuple[KeepGroup, float, UUID]:
        """Run-time keep order: Required, then turned on, then Installed by
        default; the most recent first inside each, then the plugin id."""
        group = KeepGroup.INSTALLED_BY_DEFAULT
        order_time = self.shared_at
        if self.installation_policy == PluginInstallationPolicy.REQUIRED:
            group = KeepGroup.REQUIRED
        elif self.turned_on:
            group = KeepGroup.TURNED_ON
            # A backfilled choice has no enabled_at.
            order_time = self.enabled_at or self.shared_at
        return (group, -order_time.timestamp(), self.plugin_id)


def _user_plugin_pairs(
    user_filter: ColumnElement[bool], plugin_ids: list[UUID] | None
) -> Subquery:
    """Each user (``user_filter`` on the user table) with each plugin the user
    can see, or only those of ``plugin_ids``. The one place that applies the
    install setting rule to users.

    Reads the share rows and group settings once for each pair, through joins.
    Correlated subqueries repeat for each column that uses them; on tables with
    no statistics, that plan costs more than ``jit_above_cost``, and each
    backend that JIT-compiles it keeps about 30 MB."""
    user_id: KeyedColumnElement[UUID] = User.__table__.c.id
    company = company_installation_policy(Plugin, Marketplace)
    company_rank = _rank_of(company)
    # Group rows are aggregated once for the filtered users and joined to each
    # pair by hash, so a call for many users stays under jit_above_cost on
    # tables with no statistics.
    filtered_users = select(user_id).where(user_filter).correlate(None)
    group_policy_rank = case(
        (
            and_(
                UserGroup.is_default.is_(False),
                Plugin__UserGroup.installation_policy.is_not(None),
            ),
            _rank_of(Plugin__UserGroup.installation_policy),
        )
    )
    group_rows = (
        select(
            User__UserGroup.user_id.label("user_id"),
            Plugin__UserGroup.plugin_id.label("plugin_id"),
            func.bool_or(Plugin__UserGroup.permission.is_not(None)).label("shared"),
            # Most open setting of the non-default groups that give their own.
            func.max(group_policy_rank).label("max_rank"),
            func.count(group_policy_rank).label("setting_groups"),
            func.max(Plugin__UserGroup.created_at).label("shared_at"),
        )
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == Plugin__UserGroup.user_group_id,
        )
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(User__UserGroup.user_id.in_(filtered_users))
        .group_by(User__UserGroup.user_id, Plugin__UserGroup.plugin_id)
        .subquery("group_rows")
    )
    user_groups = (
        select(
            User__UserGroup.user_id.label("user_id"),
            func.count().label("groups"),
        )
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(
            User__UserGroup.user_id.in_(filtered_users),
            UserGroup.is_default.is_(False),
        )
        .group_by(User__UserGroup.user_id)
        .subquery("user_groups")
    )
    # A non-default group with no setting of its own gives the company one.
    setting_rank = case(
        (func.coalesce(user_groups.c.groups, 0) == 0, company_rank),
        (
            func.coalesce(group_rows.c.setting_groups, 0) < user_groups.c.groups,
            func.greatest(group_rows.c.max_rank, company_rank),
        ),
        else_=group_rows.c.max_rank,
    )
    grants = (
        select(
            user_id.label("user_id"),
            Plugin.id.label("plugin_id"),
            Plugin.created_at.label("created_at"),
            (Marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY).label(
                "published"
            ),
            func.coalesce(Plugin.author_user_id == user_id, False).label("is_author"),
            or_(
                Plugin__User.plugin_id.is_not(None),
                func.coalesce(group_rows.c.shared, False),
            ).label("shared"),
            setting_rank.label("setting_rank"),
            Plugin.current_version_id.label("current_version_id"),
            Plugin.published_version_id.label("published_version_id"),
            Plugin__User.created_at.label("user_shared_at"),
            group_rows.c.shared_at.label("group_shared_at"),
        )
        .select_from(User.__table__)
        .join(Plugin, true())
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .outerjoin(
            Plugin__User,
            and_(Plugin__User.plugin_id == Plugin.id, Plugin__User.user_id == user_id),
        )
        .outerjoin(
            group_rows,
            and_(group_rows.c.user_id == user_id, group_rows.c.plugin_id == Plugin.id),
        )
        .outerjoin(user_groups, user_groups.c.user_id == user_id)
        .where(user_filter)
    )
    if plugin_ids is not None:
        grants = grants.where(Plugin.id.in_(plugin_ids))
    g = grants.subquery("pair_grants")
    granted = or_(g.c.is_author, g.c.shared)
    return (
        select(
            g.c.user_id,
            g.c.plugin_id,
            g.c.created_at,
            g.c.published,
            g.c.is_author,
            _with_share_floor(g.c.setting_rank, granted).label("rank"),
            _version_for(
                granted, g.c.current_version_id, g.c.published_version_id
            ).label("version_id"),
            g.c.user_shared_at,
            g.c.group_shared_at,
        )
        .where(_visible(granted, g.c.published, g.c.setting_rank))
        .subquery("pairs")
    )


def _enabled_in_pairs(pairs: Subquery) -> ColumnElement[bool]:
    """The user's choice under the setting. Needs an outer join of
    user_plugin_preference on the pair."""
    choice = UserPluginPreference.enabled
    rank = pairs.c.rank
    return case(
        (rank == policy_rank(PluginInstallationPolicy.REQUIRED), True),
        (
            rank == policy_rank(PluginInstallationPolicy.DEFAULT),
            func.coalesce(choice, True),
        ),
        (
            rank == policy_rank(PluginInstallationPolicy.AVAILABLE),
            func.coalesce(choice, False),
        ),
        else_=False,
    )


def _shared_at(pairs: Subquery) -> ColumnElement[datetime]:
    return func.coalesce(
        func.greatest(pairs.c.user_shared_at, pairs.c.group_shared_at),
        pairs.c.created_at,
    )


def load_user_plugin_states(
    users: Iterable[UUID] | ColumnElement[bool],
    db_session: Session,
    plugin_ids: Iterable[UUID] | None = None,
    *,
    runnable_only: bool = False,
) -> list[UserPluginState]:
    """The state of each plugin each user can see (only those of
    ``plugin_ids``, when given), in one query, then one query for app
    connections. ``users`` is a list of ids or a filter on the user table.
    ``runnable_only`` keeps only the plugins that can run."""
    user_filter: ColumnElement[bool]
    if isinstance(users, ColumnElement):
        user_filter = cast(ColumnElement[bool], users)
    else:
        user_ids = sorted(set(users))
        if not user_ids:
            return []
        user_filter = User.__table__.c.id.in_(user_ids)
    plugins = sorted(set(plugin_ids)) if plugin_ids is not None else None
    if plugins is not None and not plugins:
        return []
    pairs = _user_plugin_pairs(user_filter, plugins)
    enabled = _enabled_in_pairs(pairs)
    skill_names = (
        select(
            func.array_agg(
                aggregate_order_by(
                    PluginSkill.frontmatter["name"].astext, PluginSkill.path
                )
            )
        )
        .where(PluginSkill.plugin_version_id == pairs.c.version_id)
        .correlate(pairs)
        .scalar_subquery()
    )
    stmt = (
        select(
            pairs.c.user_id,
            pairs.c.plugin_id,
            pairs.c.rank,
            pairs.c.published,
            pairs.c.is_author,
            pairs.c.version_id,
            PluginVersion.bundle_file_id,
            PluginVersion.is_valid,
            enabled.label("enabled"),
            pairs.c.created_at,
            skill_names.label("skill_names"),
            PluginVersion.unpacked_size_bytes,
            PluginVersion.file_count,
            UserPluginPreference.enabled.label("choice"),
            UserPluginPreference.enabled_at,
            _shared_at(pairs).label("shared_at"),
        )
        .join(PluginVersion, PluginVersion.id == pairs.c.version_id)
        .outerjoin(
            UserPluginPreference,
            and_(
                UserPluginPreference.user_id == pairs.c.user_id,
                UserPluginPreference.plugin_id == pairs.c.plugin_id,
            ),
        )
        .order_by(pairs.c.user_id, pairs.c.plugin_id)
    )
    if runnable_only:
        stmt = stmt.where(enabled, PluginVersion.is_valid.is_not(False))
    rows = db_session.execute(stmt).all()
    apps = app_dependency_states(
        {row.user_id for row in rows},
        db_session,
        {row.plugin_id for row in rows if row.enabled},
    )
    states: list[UserPluginState] = []
    for row in rows:
        can_run = (
            bool(row.enabled)
            and row.is_valid is not False
            and not waits_for_app(apps.get((row.user_id, row.plugin_id)))
        )
        if runnable_only and not can_run:
            continue
        states.append(
            UserPluginState(
                user_id=row.user_id,
                plugin_id=row.plugin_id,
                installation_policy=_POLICY_OF_RANK[row.rank],
                published=bool(row.published),
                is_author=bool(row.is_author),
                version_id=row.version_id,
                bundle_file_id=row.bundle_file_id,
                version_is_valid=row.is_valid,
                enabled=bool(row.enabled),
                can_run=can_run,
                created_at=row.created_at,
                skill_names=tuple(row.skill_names or ()),
                usage=(
                    None
                    if row.unpacked_size_bytes is None and row.file_count is None
                    else SkillUsage(
                        bytes=row.unpacked_size_bytes or 0, files=row.file_count or 0
                    )
                ),
                turned_on=row.choice is True,
                enabled_at=row.enabled_at,
                shared_at=row.shared_at,
            )
        )
    return states


def skill_usage_by_user(states: Iterable[UserPluginState]) -> dict[UUID, SkillUsage]:
    """Usage of the plugins each user can run, before the name order. A
    version with no recorded size counts as 0. Built-in skills are not
    plugins and are not counted."""
    usage: dict[UUID, SkillUsage] = {}
    for state in states:
        if state.can_run:
            usage[state.user_id] = usage.get(state.user_id, SkillUsage()) + (
                state.usage or SkillUsage()
            )
    return usage


def users_with_usage_past(
    user_filter: ColumnElement[bool], usage: SkillUsage
) -> Select[tuple[UUID]]:
    """Users whose enabled, not invalid plugins add up past ``usage`` in bytes
    or files. App readiness is not checked, so this is an upper bound of
    ``skill_usage_by_user``: it narrows the users that need the full read."""
    pairs = _user_plugin_pairs(user_filter, None)
    return (
        select(pairs.c.user_id)
        .join(PluginVersion, PluginVersion.id == pairs.c.version_id)
        .outerjoin(
            UserPluginPreference,
            and_(
                UserPluginPreference.user_id == pairs.c.user_id,
                UserPluginPreference.plugin_id == pairs.c.plugin_id,
            ),
        )
        .where(_enabled_in_pairs(pairs), PluginVersion.is_valid.is_not(False))
        .group_by(pairs.c.user_id)
        .having(
            or_(
                func.sum(func.coalesce(PluginVersion.unpacked_size_bytes, 0))
                > usage.bytes,
                func.sum(func.coalesce(PluginVersion.file_count, 0)) > usage.files,
            )
        )
    )


def visible_plugin_ids(user_id: UUID) -> Select[tuple[UUID]]:
    """The plugins the user can see, as a subquery for ``in_``."""
    pairs = _user_plugin_pairs(User.__table__.c.id == user_id, None)
    return select(pairs.c.plugin_id)


_NO_SKILL_DISK_ACCOUNTS = (
    AccountType.BOT,
    AccountType.EXT_PERM_USER,
    AccountType.ANONYMOUS,
)


def active_skill_user() -> ColumnElement[bool]:
    """Users the skill limit counts: active accounts that can get a skill
    disk."""
    user = User.__table__.c
    return and_(
        user.is_active.is_(True), user.account_type.not_in(_NO_SKILL_DISK_ACCOUNTS)
    )


def affected_user_ids_for_plugins(
    plugin_ids: Iterable[UUID], db_session: Session
) -> set[UUID]:
    """Users with a running sandbox who can see at least one of the plugins.
    Ignores user choices, so a change that removes access still reaches the
    users who had it (read it before and after the change)."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return set()
    running = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
    pairs = _user_plugin_pairs(User.__table__.c.id.in_(running), ids)
    return set(db_session.scalars(select(pairs.c.user_id).distinct()))


def order_skill_names(
    states: Iterable[UserPluginState],
    reserved_names: Collection[str] = (),
) -> frozenset[UUID]:
    """The plugins that lose a skill name to another plugin one user can run,
    or to one of ``reserved_names`` (the user's built-in skills, which always
    win). A plugin that loses any of its names does not load, and shows as off.
    Only plugins that can run take part."""
    contenders: dict[str, list[UserPluginState]] = {}
    for state in states:
        if not state.can_run:
            continue
        for name in state.skill_names:
            contenders.setdefault(name, []).append(state)

    hidden: set[UUID] = set()
    for name, named in contenders.items():
        ordered = sorted(
            named,
            key=lambda state: (state.name_rank, state.created_at, state.plugin_id),
        )
        if name not in reserved_names:
            ordered = ordered[1:]
        hidden.update(state.plugin_id for state in ordered)
    return frozenset(hidden)


# --- Access of plugins for responses ----------------------------------------


@dataclass(frozen=True)
class PluginUserShare:
    user_id: UUID
    email: str
    permission: SkillSharePermission


@dataclass(frozen=True)
class PluginGroupShare:
    group_id: int
    group_name: str
    permission: SkillSharePermission


class PluginGroupRowAccess(BaseModel):
    """One plugin__user_group row. A row with no permission holds only a
    setting."""

    model_config = ConfigDict(frozen=True)

    group_id: int
    group_name: str
    permission: SkillSharePermission | None
    installation_policy: PluginInstallationPolicy | None


@dataclass(frozen=True)
class PluginAccess:
    """A plugin's grants and the values one user sees. User shares and
    ``group_shares`` hold only rows with a permission; ``group_rows`` holds
    every group row."""

    plugin_id: UUID
    author_user_id: UUID | None
    author_email: str | None
    author_is_active: bool
    published: bool
    installation_policy: PluginInstallationPolicy | None
    current_version_id: UUID
    current_version_number: int
    # None while the plugin is not published.
    published_version_number: int | None
    # The version waiting for review, if any.
    pending_version_number: int | None
    version_user_runs: UUID
    # From the frontmatter of the version the user runs.
    name: str | None
    description: str
    # Lazy validity of the version the user runs.
    is_valid: bool | None
    user_shares: tuple[PluginUserShare, ...]
    group_rows: tuple[PluginGroupRowAccess, ...]

    # The default of the plugin's marketplace.
    marketplace_default_policy: PluginInstallationPolicy
    # ``plugin_required_for_anyone``.
    required_for_anyone: bool

    @property
    def group_shares(self) -> tuple[PluginGroupShare, ...]:
        return tuple(
            PluginGroupShare(
                group_id=row.group_id,
                group_name=row.group_name,
                permission=row.permission,
            )
            for row in self.group_rows
            if row.permission is not None
        )


def load_plugin_access(
    plugin_ids: Iterable[UUID], user_id: UUID, db_session: Session
) -> dict[UUID, PluginAccess]:
    """Read the access of many plugins in three queries. Selects columns, not
    entities, so a write earlier in the session is always seen."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return {}
    runs = version_user_runs(Plugin, user_id)
    current: type[PluginVersion] = aliased(PluginVersion)
    published: type[PluginVersion] = aliased(PluginVersion)
    pending: type[PluginVersion] = aliased(PluginVersion)
    author = User.__table__.alias("author")
    user_email: KeyedColumnElement[str] = User.__table__.c.email
    plugin_rows = db_session.execute(
        select(
            Plugin.id,
            Plugin.author_user_id,
            author.c.email,
            author.c.is_active,
            Marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY,
            Plugin.installation_policy,
            Marketplace.default_installation_policy,
            Plugin.current_version_id,
            current.version_number,
            published.version_number,
            pending.version_number,
            runs,
            frontmatter_in_version("name", runs),
            func.coalesce(
                frontmatter_in_version("description", runs), Plugin.description
            ),
            version_is_valid(runs),
            plugin_required_for_anyone(Plugin, Marketplace),
        )
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .join(current, current.id == Plugin.current_version_id)
        .outerjoin(published, published.id == Plugin.published_version_id)
        .outerjoin(pending, pending.id == Plugin.pending_version_id)
        .outerjoin(author, author.c.id == Plugin.author_user_id)
        .where(Plugin.id.in_(ids))
    ).all()

    user_shares: dict[UUID, list[PluginUserShare]] = {}
    for plugin_id, share_user_id, email, permission in db_session.execute(
        select(
            Plugin__User.plugin_id,
            Plugin__User.user_id,
            user_email,
            Plugin__User.permission,
        )
        .join(User.__table__, User.__table__.c.id == Plugin__User.user_id)
        .where(Plugin__User.plugin_id.in_(ids))
        .order_by(Plugin__User.plugin_id, user_email)
    ):
        user_shares.setdefault(plugin_id, []).append(
            PluginUserShare(user_id=share_user_id, email=email, permission=permission)
        )

    group_rows: dict[UUID, list[PluginGroupRowAccess]] = {}
    for plugin_id, group_id, group_name, permission, policy in db_session.execute(
        select(
            Plugin__UserGroup.plugin_id,
            Plugin__UserGroup.user_group_id,
            UserGroup.name,
            Plugin__UserGroup.permission,
            Plugin__UserGroup.installation_policy,
        )
        .join(UserGroup, UserGroup.id == Plugin__UserGroup.user_group_id)
        .where(Plugin__UserGroup.plugin_id.in_(ids))
        .order_by(Plugin__UserGroup.plugin_id, UserGroup.name, UserGroup.id)
    ):
        group_rows.setdefault(plugin_id, []).append(
            PluginGroupRowAccess(
                group_id=group_id,
                group_name=group_name,
                permission=permission,
                installation_policy=policy,
            )
        )

    return {
        row[0]: PluginAccess(
            plugin_id=row[0],
            author_user_id=row[1],
            author_email=row[2],
            author_is_active=bool(row[3]),
            published=bool(row[4]),
            installation_policy=row[5],
            marketplace_default_policy=row[6],
            current_version_id=row[7],
            current_version_number=row[8],
            published_version_number=row[9],
            pending_version_number=row[10],
            version_user_runs=row[11],
            name=row[12],
            description=row[13],
            is_valid=row[14],
            required_for_anyone=bool(row[15]),
            user_shares=tuple(user_shares.get(row[0], ())),
            group_rows=tuple(group_rows.get(row[0], ())),
        )
        for row in plugin_rows
    }
