"""Who can see, edit and run a plugin, as SQL expressions.

The rule, once:

- Visible: the plugin is in the Organization library and the install setting
  for the user is not NOT_AVAILABLE; or the user is its author; or a
  plugin__user row; or a plugin__user_group row with a permission for one of
  the user's groups. A group row with no permission holds only a group install
  setting and grants nothing. A group row whose own setting is NOT_AVAILABLE
  grants nothing either.
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
from datetime import datetime, timezone
from enum import Enum, IntEnum
from typing import Literal
from uuid import UUID

from sqlalchemy import (
    ColumnElement,
    and_,
    case,
    func,
    or_,
    select,
    true,
)
from sqlalchemy.dialects.postgresql import aggregate_order_by
from sqlalchemy.orm import InstrumentedAttribute, Session, aliased
from sqlalchemy.sql.elements import KeyedColumnElement
from sqlalchemy.sql.selectable import Subquery

from onyx.db.enums import (
    AccountType,
    MarketplaceKind,
    PluginInstallationPolicy,
    PluginReviewStatus,
    SandboxStatus,
    SkillSharePermission,
)
from onyx.db.external_app_readiness import ready_app_skill_pairs
from onyx.db.models import (
    ExternalApp__Skill,
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
from onyx.skills.limits import SkillUsage

UserIdExpr = UUID | ColumnElement[UUID] | InstrumentedAttribute[UUID]

PluginKind = Literal["skill", "plugin"]


def plugin_version_kind(skill_paths: Iterable[str]) -> PluginKind:
    """The kind of a version, from the paths of its plugin_skill rows. A
    version is a skill when it holds exactly one skill, with SKILL.md at the
    bundle root; otherwise it is a plugin. No column stores the result, so a
    later version can change it."""
    return "skill" if list(skill_paths) == [""] else "plugin"


# Most open first. The only ranking of install settings.
_POLICY_RANK: dict[PluginInstallationPolicy, int] = {
    PluginInstallationPolicy.REQUIRED: 3,
    PluginInstallationPolicy.DEFAULT: 2,
    PluginInstallationPolicy.AVAILABLE: 1,
    PluginInstallationPolicy.NOT_AVAILABLE: 0,
}


def policy_rank(policy: PluginInstallationPolicy) -> int:
    return _POLICY_RANK[policy]


def _rank_of(policy: ColumnElement[PluginInstallationPolicy]) -> ColumnElement[int]:
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
    one of the user's groups and a setting other than NOT_AVAILABLE. With
    ``permission``, only rows at that level."""
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
            Plugin__UserGroup.installation_policy.is_distinct_from(
                PluginInstallationPolicy.NOT_AVAILABLE
            ),
        )
        .correlate_except(Plugin__UserGroup, User__UserGroup)
    )
    if permission is not None:
        user_share = user_share.where(Plugin__User.permission == permission)
        group_share = group_share.where(Plugin__UserGroup.permission == permission)
    return or_(user_share.exists(), group_share.exists())


def _setting_rank_for_user(
    plugin: type[Plugin], marketplace: type[Marketplace], user_id: UserIdExpr
) -> ColumnElement[int]:
    """Rank of the install setting before the share floor. Default groups
    (Basic, Admin) do not count: Basic holds the whole organization, so it
    would always give the company setting. Plugins cannot be shared with them
    either."""
    company = company_installation_policy(plugin, marketplace)
    group_setting = (
        select(Plugin__UserGroup.installation_policy)
        .where(
            Plugin__UserGroup.plugin_id == plugin.id,
            Plugin__UserGroup.user_group_id == User__UserGroup.user_group_id,
        )
        .correlate_except(Plugin__UserGroup)
        .scalar_subquery()
    )
    most_open_group = (
        select(func.max(_rank_of(func.coalesce(group_setting, company))))
        .select_from(User__UserGroup)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        .where(User__UserGroup.user_id == user_id, UserGroup.is_default.is_(False))
        .correlate_except(User__UserGroup, UserGroup)
        .scalar_subquery()
    )
    return func.coalesce(most_open_group, _rank_of(company))


def installation_rank_for_user(
    plugin: type[Plugin], marketplace: type[Marketplace], user_id: UserIdExpr
) -> ColumnElement[int]:
    """Rank (see ``policy_rank``) of the install setting that applies to the
    user. The author and a share get at least AVAILABLE."""
    rank = _setting_rank_for_user(plugin, marketplace, user_id)
    return case(
        (
            or_(
                plugin.author_user_id == user_id,
                plugin_shared_with_user(plugin, user_id),
            ),
            func.greatest(rank, policy_rank(PluginInstallationPolicy.AVAILABLE)),
        ),
        else_=rank,
    )


def plugin_visible_to_user(
    plugin: type[Plugin], marketplace: type[Marketplace], user_id: UserIdExpr
) -> ColumnElement[bool]:
    return or_(
        plugin.author_user_id == user_id,
        plugin_shared_with_user(plugin, user_id),
        and_(
            marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY,
            _setting_rank_for_user(plugin, marketplace, user_id)
            > policy_rank(PluginInstallationPolicy.NOT_AVAILABLE),
        ),
    )


def affected_user_ids_for_plugins(
    plugin_ids: Iterable[UUID], db_session: Session
) -> set[UUID]:
    """Users with a running sandbox who can see at least one of the plugins, in
    one query. Ignores user choices, so a change that removes access still
    reaches the users who had it."""
    ids = sorted(set(plugin_ids))
    if not ids:
        return set()
    plugin: type[Plugin] = aliased(Plugin)
    marketplace: type[Marketplace] = aliased(Marketplace)
    visible = (
        select(plugin.id)
        .join(marketplace, marketplace.id == plugin.marketplace_id)
        .where(
            plugin.id.in_(ids),
            plugin_visible_to_user(plugin, marketplace, Sandbox.user_id),
        )
        .correlate_except(plugin, marketplace)
        .exists()
    )
    return set(
        db_session.scalars(
            select(Sandbox.user_id).where(
                Sandbox.status == SandboxStatus.RUNNING, visible
            )
        )
    )


def plugin_editable_by_user(
    plugin: type[Plugin], user_id: UserIdExpr
) -> ColumnElement[bool]:
    return or_(
        plugin.author_user_id == user_id,
        plugin_shared_with_user(plugin, user_id, SkillSharePermission.EDITOR),
    )


def plugin_is_published(marketplace: type[Marketplace]) -> ColumnElement[bool]:
    return marketplace.kind == MarketplaceKind.ORGANIZATION_LIBRARY


def version_user_runs(plugin: type[Plugin], user_id: UserIdExpr) -> ColumnElement[UUID]:
    return case(
        (
            or_(
                plugin.author_user_id == user_id,
                plugin_shared_with_user(plugin, user_id),
            ),
            plugin.current_version_id,
        ),
        else_=func.coalesce(plugin.published_version_id, plugin.current_version_id),
    )


def _frontmatter_in_version(
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


def skill_name_in_version(version_id: ColumnElement[UUID]) -> ColumnElement[str]:
    return _frontmatter_in_version("name", version_id)


def version_is_valid(version_id: ColumnElement[UUID]) -> ColumnElement[bool | None]:
    """Lazy validity of a version. NULL while the push has not classified it."""
    return (
        select(PluginVersion.is_valid)
        .where(PluginVersion.id == version_id)
        .correlate_except(PluginVersion)
        .scalar_subquery()
    )


def _pending_version_number() -> ColumnElement[int]:
    return (
        select(PluginVersion.version_number)
        .where(
            PluginVersion.plugin_id == Plugin.id,
            PluginVersion.review_status == PluginReviewStatus.PENDING,
        )
        .correlate_except(PluginVersion)
        .scalar_subquery()
    )


def get_version_user_runs(
    plugin_id: UUID, user_id: UUID, db_session: Session
) -> UUID | None:
    return db_session.scalar(
        select(version_user_runs(Plugin, user_id)).where(Plugin.id == plugin_id)
    )


# --- Install settings and choices of many users -----------------------------

_POLICY_OF_RANK: dict[int, PluginInstallationPolicy] = {
    rank: policy for policy, rank in _POLICY_RANK.items()
}


class SkillNameRank(IntEnum):
    """Who keeps a skill name that two enabled skills of a user hold. Lower
    wins."""

    BUILT_IN = 0
    REQUIRED = 1
    PUBLISHED = 2
    OWN = 3
    SHARED = 4


class NameHiddenReason(str, Enum):
    BUILT_IN = "built_in"
    REQUIRED = "required"
    PUBLISHED = "published"
    OWN = "own"
    SHARED = "shared"
    # The same rank: the older plugin kept the name.
    OLDER = "older"


@dataclass(frozen=True)
class UserPluginState:
    """One plugin as one user gets it."""

    user_id: UUID
    plugin_id: UUID
    # The install setting for the user, with the author and share floor.
    installation_policy: PluginInstallationPolicy
    visible: bool
    published: bool
    is_author: bool
    shared: bool
    # The version the user runs, and its lazy validity.
    version_id: UUID
    version_is_valid: bool | None
    # The user's choice under the setting, before the name order.
    enabled: bool
    created_at: datetime
    # Names from the plugin_skill rows of the version the user runs, by path.
    skill_names: tuple[str, ...]

    @property
    def name_rank(self) -> SkillNameRank:
        if self.installation_policy == PluginInstallationPolicy.REQUIRED:
            return SkillNameRank.REQUIRED
        if self.published:
            return SkillNameRank.PUBLISHED
        if self.is_author:
            return SkillNameRank.OWN
        return SkillNameRank.SHARED


def skill_name_order_key(
    rank: SkillNameRank, created_at: datetime | None, plugin_id: UUID
) -> tuple[int, datetime, UUID]:
    """Sort key of the name order: rank, then the older plugin, then id."""
    return (rank, created_at or datetime.min.replace(tzinfo=timezone.utc), plugin_id)


def _user_plugin_pairs(
    user_filter: ColumnElement[bool], plugin_ids: list[UUID] | None
) -> Subquery:
    """Each user (``user_filter`` on the user table) with each plugin: the given
    plugins, or else only the plugins the user can see."""
    user_id: KeyedColumnElement[UUID] = User.__table__.c.id
    access = (
        select(
            user_id.label("user_id"),
            Plugin.id.label("plugin_id"),
            Plugin.created_at.label("created_at"),
            plugin_is_published(Marketplace).label("published"),
            func.coalesce(Plugin.author_user_id == user_id, False).label("is_author"),
            plugin_shared_with_user(Plugin, user_id).label("shared"),
            installation_rank_for_user(Plugin, Marketplace, user_id).label("rank"),
            plugin_visible_to_user(Plugin, Marketplace, user_id).label("visible"),
            version_user_runs(Plugin, user_id).label("version_id"),
        )
        .select_from(User.__table__)
        .join(Plugin, true())
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .where(user_filter)
    )
    if plugin_ids is not None:
        access = access.where(Plugin.id.in_(plugin_ids))
    else:
        access = access.where(plugin_visible_to_user(Plugin, Marketplace, user_id))
    return access.subquery("pairs")


def _enabled_in_pairs(pairs: Subquery) -> ColumnElement[bool]:
    """The user's choice under the setting. Needs an outer join of
    user_plugin_preference on the pair."""
    choice = UserPluginPreference.enabled
    rank = pairs.c.rank
    return case(
        (pairs.c.visible.is_not(True), False),
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


def _preference_of_pair(pairs: Subquery) -> ColumnElement[bool]:
    return and_(
        UserPluginPreference.user_id == pairs.c.user_id,
        UserPluginPreference.plugin_id == pairs.c.plugin_id,
    )


def load_user_plugin_states(
    user_ids: Iterable[UUID],
    db_session: Session,
    plugin_ids: Iterable[UUID] | None = None,
) -> list[UserPluginState]:
    """The state of each plugin for each user, in one query. With
    ``plugin_ids``, every pair of the users and those plugins; without, only
    the plugins each user can see."""
    users = sorted(set(user_ids))
    if not users:
        return []
    plugins = sorted(set(plugin_ids)) if plugin_ids is not None else None
    if plugins is not None and not plugins:
        return []
    pairs = _user_plugin_pairs(User.__table__.c.id.in_(users), plugins)
    rank = pairs.c.rank
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
    rows = db_session.execute(
        select(
            pairs.c.user_id,
            pairs.c.plugin_id,
            rank,
            pairs.c.visible,
            pairs.c.published,
            pairs.c.is_author,
            pairs.c.shared,
            pairs.c.version_id,
            PluginVersion.is_valid,
            enabled,
            pairs.c.created_at,
            skill_names,
        )
        .join(PluginVersion, PluginVersion.id == pairs.c.version_id)
        .outerjoin(UserPluginPreference, _preference_of_pair(pairs))
        .order_by(pairs.c.user_id, pairs.c.plugin_id)
    ).all()
    return [
        UserPluginState(
            user_id=row[0],
            plugin_id=row[1],
            installation_policy=_POLICY_OF_RANK[row[2]],
            visible=bool(row[3]),
            published=bool(row[4]),
            is_author=bool(row[5]),
            shared=bool(row[6]),
            version_id=row[7],
            version_is_valid=row[8],
            enabled=bool(row[9]),
            created_at=row[10],
            skill_names=tuple(row[11] or ()),
        )
        for row in rows
    ]


# --- Skill usage of many users ------------------------------------------------

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


def _plugin_usage_rows(
    user_filter: ColumnElement[bool],
    plugin_ids: list[UUID] | None,
    by_plugin: bool,
    db_session: Session,
) -> list[tuple[UUID, UUID | None, SkillUsage]]:
    """Usage of the plugins each user gets, in one query, then one query for
    app connections. A plugin counts with the size of the version the user
    runs when it is enabled for the user (before the name order), its version
    is not invalid, and its app, if any, is connected. A backfilled version
    with no sizes counts as 0."""
    pairs = _user_plugin_pairs(user_filter, plugin_ids)
    app_plugin = pairs.c.plugin_id.in_(select(ExternalApp__Skill.skill_id))
    key = (
        pairs.c.plugin_id
        if by_plugin
        else case((app_plugin, pairs.c.plugin_id), else_=None)
    )
    rows = db_session.execute(
        select(
            pairs.c.user_id,
            key,
            app_plugin,
            func.sum(func.coalesce(PluginVersion.unpacked_size_bytes, 0)),
            func.sum(func.coalesce(PluginVersion.file_count, 0)),
        )
        .join(PluginVersion, PluginVersion.id == pairs.c.version_id)
        .outerjoin(UserPluginPreference, _preference_of_pair(pairs))
        .where(_enabled_in_pairs(pairs), PluginVersion.is_valid.is_not(False))
        .group_by(pairs.c.user_id, key, app_plugin)
    ).all()
    ready = ready_app_skill_pairs(
        ((user_id, plugin_id) for user_id, plugin_id, is_app, _, _ in rows if is_app),
        db_session,
    )
    return [
        (user_id, plugin_id, SkillUsage(bytes=int(size), files=int(files)))
        for user_id, plugin_id, is_app, size, files in rows
        if not is_app or (user_id, plugin_id) in ready
    ]


def plugin_usage_by_user(
    user_filter: ColumnElement[bool],
    db_session: Session,
    plugin_ids: Iterable[UUID] | None = None,
) -> dict[UUID, SkillUsage]:
    """Usage of the plugins each user gets (``plugin_ids``, or all), for the
    users that ``user_filter`` selects on the user table. Users with no usage
    are left out. Built-in skills are not plugins and are not counted."""
    plugins = sorted(set(plugin_ids)) if plugin_ids is not None else None
    if plugins is not None and not plugins:
        return {}
    usage: dict[UUID, SkillUsage] = {}
    for user_id, _, row_usage in _plugin_usage_rows(
        user_filter, plugins, False, db_session
    ):
        usage[user_id] = usage.get(user_id, SkillUsage()) + row_usage
    return usage


def plugin_usage_by_plugin(
    user_id: UUID, plugin_ids: Iterable[UUID], db_session: Session
) -> dict[UUID, SkillUsage]:
    """Usage of each of the plugins one user gets."""
    plugins = sorted(set(plugin_ids))
    if not plugins:
        return {}
    return {
        plugin_id: row_usage
        for _, plugin_id, row_usage in _plugin_usage_rows(
            User.__table__.c.id == user_id, plugins, True, db_session
        )
        if plugin_id is not None
    }


@dataclass(frozen=True)
class HiddenSkillName:
    plugin_id: UUID
    name: str
    # None when a built-in skill keeps the name.
    kept_by_plugin_id: UUID | None
    reason: NameHiddenReason


@dataclass(frozen=True)
class SkillNameOrder:
    # Skill name to the plugin that keeps it. Built-in names are not listed.
    kept: dict[str, UUID]
    hidden: tuple[HiddenSkillName, ...]

    def hides(self, plugin_id: UUID) -> bool:
        return any(entry.plugin_id == plugin_id for entry in self.hidden)


def _hidden_reason(
    kept_rank: SkillNameRank, hidden_rank: SkillNameRank
) -> NameHiddenReason:
    if kept_rank == hidden_rank:
        return NameHiddenReason.OLDER
    return NameHiddenReason(kept_rank.name.lower())


def order_skill_names(
    states: Iterable[UserPluginState],
    reserved_names: Collection[str] = (),
) -> SkillNameOrder:
    """Keep one plugin for each skill name of one user's enabled plugins.
    ``reserved_names`` are the built-in skill names, which always win."""
    contenders: dict[str, list[UserPluginState]] = {}
    for state in states:
        if not state.enabled:
            continue
        for name in state.skill_names:
            contenders.setdefault(name, []).append(state)

    kept: dict[str, UUID] = {}
    hidden: list[HiddenSkillName] = []
    for name in sorted(contenders):
        ordered = sorted(
            contenders[name],
            key=lambda state: skill_name_order_key(
                state.name_rank, state.created_at, state.plugin_id
            ),
        )
        if name in reserved_names:
            winner_id: UUID | None = None
            winner_rank = SkillNameRank.BUILT_IN
            losers = ordered
        else:
            winner_id = ordered[0].plugin_id
            winner_rank = ordered[0].name_rank
            kept[name] = winner_id
            losers = ordered[1:]
        hidden.extend(
            HiddenSkillName(
                plugin_id=loser.plugin_id,
                name=name,
                kept_by_plugin_id=winner_id,
                reason=_hidden_reason(winner_rank, loser.name_rank),
            )
            for loser in losers
        )
    return SkillNameOrder(kept=kept, hidden=tuple(hidden))


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


@dataclass(frozen=True)
class PluginGroupRowAccess:
    """One plugin__user_group row. A row with no permission holds only a
    setting."""

    group_id: int
    group_name: str
    permission: SkillSharePermission | None
    installation_policy: PluginInstallationPolicy | None


@dataclass(frozen=True)
class PluginAccess:
    """A plugin's grants and the values one user sees. Shares hold only rows
    with a permission; ``group_rows`` holds every group row."""

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
    group_shares: tuple[PluginGroupShare, ...]
    group_rows: tuple[PluginGroupRowAccess, ...]

    # The default of the plugin's marketplace.
    marketplace_default_policy: PluginInstallationPolicy

    @property
    def company_installation_policy(self) -> PluginInstallationPolicy:
        """The plugin's own setting, else its marketplace default."""
        return self.installation_policy or self.marketplace_default_policy


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
    author = User.__table__.alias("author")
    user_email: KeyedColumnElement[str] = User.__table__.c.email
    plugin_rows = db_session.execute(
        select(
            Plugin.id,
            Plugin.author_user_id,
            author.c.email,
            author.c.is_active,
            plugin_is_published(Marketplace),
            Plugin.installation_policy,
            Marketplace.default_installation_policy,
            Plugin.current_version_id,
            current.version_number,
            published.version_number,
            _pending_version_number(),
            runs,
            skill_name_in_version(runs),
            func.coalesce(
                _frontmatter_in_version("description", runs), Plugin.description
            ),
            version_is_valid(runs),
        )
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .join(current, current.id == Plugin.current_version_id)
        .outerjoin(published, published.id == Plugin.published_version_id)
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

    group_shares: dict[UUID, list[PluginGroupShare]] = {}
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
        if permission is not None:
            group_shares.setdefault(plugin_id, []).append(
                PluginGroupShare(
                    group_id=group_id, group_name=group_name, permission=permission
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
            user_shares=tuple(user_shares.get(row[0], ())),
            group_shares=tuple(group_shares.get(row[0], ())),
            group_rows=tuple(group_rows.get(row[0], ())),
        )
        for row in plugin_rows
    }


@dataclass(frozen=True)
class GroupPluginRow:
    """One plugin__user_group row of a group, for the group page. The name and
    description come from the version the group's members run: the current
    version through a share, else the published one."""

    plugin_id: UUID
    kind: PluginKind
    plugin_name: str
    # From the frontmatter of the version the group runs.
    skill_name: str | None
    description: str
    published: bool
    # None: the row holds only a group install setting.
    permission: SkillSharePermission | None
    # None: no group override.
    installation_policy: PluginInstallationPolicy | None
    company_installation_policy: PluginInstallationPolicy

    @property
    def name(self) -> str:
        """A plugin of kind skill shows as its skill."""
        if self.kind == "skill" and self.skill_name:
            return self.skill_name
        return self.plugin_name


def load_group_plugins(group_id: int, db_session: Session) -> list[GroupPluginRow]:
    """Every plugin__user_group row of the group, ordered by plugin name."""
    group_runs = case(
        (
            and_(
                Plugin__UserGroup.permission.is_not(None),
                Plugin__UserGroup.installation_policy.is_distinct_from(
                    PluginInstallationPolicy.NOT_AVAILABLE
                ),
            ),
            Plugin.current_version_id,
        ),
        else_=func.coalesce(Plugin.published_version_id, Plugin.current_version_id),
    )
    skill_paths = (
        select(func.array_agg(aggregate_order_by(PluginSkill.path, PluginSkill.path)))
        .where(PluginSkill.plugin_version_id == group_runs)
        .correlate_except(PluginSkill)
        .scalar_subquery()
    )
    rows = db_session.execute(
        select(
            Plugin.id,
            Plugin.name,
            skill_name_in_version(group_runs),
            func.coalesce(
                _frontmatter_in_version("description", group_runs),
                Plugin.description,
            ),
            skill_paths,
            plugin_is_published(Marketplace),
            Plugin__UserGroup.permission,
            Plugin__UserGroup.installation_policy,
            company_installation_policy(Plugin, Marketplace),
        )
        .join(Plugin, Plugin.id == Plugin__UserGroup.plugin_id)
        .join(Marketplace, Marketplace.id == Plugin.marketplace_id)
        .where(Plugin__UserGroup.user_group_id == group_id)
        .order_by(Plugin.name, Plugin.id)
    ).all()
    result = [
        GroupPluginRow(
            plugin_id=plugin_id,
            kind=plugin_version_kind(paths or ()),
            plugin_name=plugin_name,
            skill_name=skill_name,
            description=description,
            published=bool(published),
            permission=permission,
            installation_policy=policy,
            company_installation_policy=company,
        )
        for (
            plugin_id,
            plugin_name,
            skill_name,
            description,
            paths,
            published,
            permission,
            policy,
            company,
        ) in rows
    ]
    return sorted(result, key=lambda row: (row.name.lower(), row.plugin_id))


def plugin_is_in_user_uploads_of(user_id: UUID) -> ColumnElement[bool]:
    """A plugin in the user's "My uploads"."""
    return Plugin.marketplace_id.in_(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.USER_UPLOADS,
            Marketplace.owner_user_id == user_id,
        )
    )
