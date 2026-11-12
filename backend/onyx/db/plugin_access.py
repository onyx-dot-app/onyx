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

from onyx.db.enums import (
    MarketplaceKind,
    PluginInstallationPolicy,
    PluginReviewStatus,
    SandboxStatus,
    SkillInstallationPolicy,
    SkillSharePermission,
)
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

UserIdExpr = UUID | ColumnElement[UUID] | InstrumentedAttribute[UUID]

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
        .where(user_id.in_(users))
    )
    if plugin_ids is not None:
        plugins = sorted(set(plugin_ids))
        if not plugins:
            return []
        access = access.where(Plugin.id.in_(plugins))
    else:
        access = access.where(plugin_visible_to_user(Plugin, Marketplace, user_id))
    pairs = access.subquery("pairs")

    choice = UserPluginPreference.enabled
    rank = pairs.c.rank
    enabled = case(
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
        .outerjoin(
            UserPluginPreference,
            and_(
                UserPluginPreference.user_id == pairs.c.user_id,
                UserPluginPreference.plugin_id == pairs.c.plugin_id,
            ),
        )
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
class PluginAccess:
    """A plugin's grants and the values one user sees. Shares hold only rows
    with a permission."""

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

    @property
    def skill_installation_policy(self) -> SkillInstallationPolicy:
        """The plugin's own company setting as the skills API shows it. No
        setting maps to AVAILABLE, as it did before plugins. The skills API
        cannot show NOT_AVAILABLE until group install settings ship."""
        if self.installation_policy in (
            PluginInstallationPolicy.DEFAULT,
            PluginInstallationPolicy.REQUIRED,
        ):
            return SkillInstallationPolicy(self.installation_policy.value)
        return SkillInstallationPolicy.AVAILABLE


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
    for plugin_id, group_id, group_name, permission in db_session.execute(
        select(
            Plugin__UserGroup.plugin_id,
            Plugin__UserGroup.user_group_id,
            UserGroup.name,
            Plugin__UserGroup.permission,
        )
        .join(UserGroup, UserGroup.id == Plugin__UserGroup.user_group_id)
        .where(
            Plugin__UserGroup.plugin_id.in_(ids),
            Plugin__UserGroup.permission.is_not(None),
        )
        .order_by(Plugin__UserGroup.plugin_id, UserGroup.name)
    ):
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
            current_version_id=row[6],
            current_version_number=row[7],
            published_version_number=row[8],
            pending_version_number=row[9],
            version_user_runs=row[10],
            name=row[11],
            description=row[12],
            is_valid=row[13],
            user_shares=tuple(user_shares.get(row[0], ())),
            group_shares=tuple(group_shares.get(row[0], ())),
        )
        for row in plugin_rows
    }


def plugin_is_in_user_uploads_of(user_id: UUID) -> ColumnElement[bool]:
    """A plugin in the user's "My uploads"."""
    return Plugin.marketplace_id.in_(
        select(Marketplace.id).where(
            Marketplace.kind == MarketplaceKind.USER_UPLOADS,
            Marketplace.owner_user_id == user_id,
        )
    )
