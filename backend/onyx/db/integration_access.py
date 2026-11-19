"""Who has access to an integration and who has it on, as SQL.

The rule, once:

- Access: the user is the owner; or an integration__user row; or an
  integration__user_group row with a permission for one of the user's groups;
  or the install setting for the user is above NOT_AVAILABLE. A group row
  with no permission holds only a group install setting. A plugin gives no
  access to an integration.
- Install setting for a user: the company setting is
  integration.installation_policy. Each non-default group of the user gives
  its own setting, else the company setting. The most open one wins; a user
  in no group gets the company setting. The owner and a share (user or group)
  get at least AVAILABLE. ``onyx.db.plugin_access`` holds this rule for
  plugins and integrations.
- Turned on: REQUIRED is on. DEFAULT is on unless the user turned it off.
  AVAILABLE is on only when the user turned it on. With no access, the
  integration is off; the saved choice stays.
- On: turned on, and an admin did not turn the integration off
  (integration.enabled). An integration that an admin turned off keeps its
  access.

The write functions flush and never commit.
"""

from collections.abc import Collection, Iterable, Mapping
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, and_, delete, func, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import KeyedColumnElement
from sqlalchemy.sql.selectable import Select, Subquery

from onyx.db.enums import (
    Permission,
    PluginInstallationPolicy,
    SandboxStatus,
    SkillSharePermission,
)
from onyx.db.models import (
    Integration,
    Integration__User,
    Integration__UserGroup,
    Sandbox,
    User,
    UserGroup,
    UserIntegrationPreference,
)
from onyx.db.plugin import (
    AccessRows,
    PluginAccessChange,
    PluginGroupGrant,
    PluginGroupRow,
    PluginGroupSetting,
    PluginUserGrant,
    check_access_change,
    new_group_rows,
)
from onyx.db.plugin_access import (
    POLICY_OF_RANK,
    PluginGroupShare,
    PluginUserShare,
    enabled_under_setting,
    group_rows_of_users,
    non_default_group_counts,
    policy_rank,
    rank_of,
    setting_rank_for_user,
    with_share_floor,
)
from onyx.db.utils import is_fk_violation
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError


class UserIntegrationState(BaseModel):
    """One integration that one user has access to, as that user gets it."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    integration_id: int
    # The install setting for the user, with the owner and share floor.
    installation_policy: PluginInstallationPolicy
    is_owner: bool
    # The company setting is above NOT_AVAILABLE, so each user has access.
    for_everyone: bool
    # The saved choice of the user. None: the user made no choice.
    choice: bool | None
    # The choice under the setting.
    turned_on: bool
    # False: an admin turned the integration off.
    integration_enabled: bool

    @property
    def on(self) -> bool:
        return self.turned_on and self.integration_enabled


def _user_integration_pairs(
    user_filter: ColumnElement[bool], integration_ids: list[int] | None
) -> Subquery:
    """Each user (``user_filter`` on the user table) with each integration
    the user has access to, or only those of ``integration_ids``. The one
    place that applies the access rule to the integrations of users.

    Reads the share rows and group settings once for each pair, through
    joins, for the reason that ``plugin_access._user_plugin_pairs`` gives."""
    user_id: KeyedColumnElement[UUID] = User.__table__.c.id
    company_rank = rank_of(Integration.installation_policy)
    filtered_users = select(user_id).where(user_filter).correlate(None)
    group_rows = group_rows_of_users(
        Integration__UserGroup, Integration__UserGroup.integration_id, filtered_users
    )
    user_groups = non_default_group_counts(filtered_users)
    grants = (
        select(
            user_id.label("user_id"),
            Integration.id.label("integration_id"),
            Integration.enabled.label("integration_enabled"),
            company_rank.label("company_rank"),
            func.coalesce(Integration.owner_user_id == user_id, False).label(
                "is_owner"
            ),
            or_(
                Integration__User.integration_id.is_not(None),
                func.coalesce(group_rows.c.shared, False),
            ).label("shared"),
            setting_rank_for_user(company_rank, group_rows, user_groups).label(
                "setting_rank"
            ),
        )
        .select_from(User.__table__)
        .join(Integration, true())
        .outerjoin(
            Integration__User,
            and_(
                Integration__User.integration_id == Integration.id,
                Integration__User.user_id == user_id,
            ),
        )
        .outerjoin(
            group_rows,
            and_(
                group_rows.c.user_id == user_id,
                group_rows.c.resource_id == Integration.id,
            ),
        )
        .outerjoin(user_groups, user_groups.c.user_id == user_id)
        .where(user_filter)
    )
    if integration_ids is not None:
        grants = grants.where(Integration.id.in_(integration_ids))
    g = grants.subquery("pair_grants")
    granted = or_(g.c.is_owner, g.c.shared)
    not_available = policy_rank(PluginInstallationPolicy.NOT_AVAILABLE)
    return (
        select(
            g.c.user_id,
            g.c.integration_id,
            g.c.integration_enabled,
            g.c.is_owner,
            (g.c.company_rank > not_available).label("for_everyone"),
            with_share_floor(g.c.setting_rank, granted).label("rank"),
        )
        .where(or_(granted, g.c.setting_rank > not_available))
        .subquery("pairs")
    )


def load_user_integration_states(
    user_ids: Iterable[UUID],
    db_session: Session,
    integration_ids: Iterable[int] | None = None,
) -> list[UserIntegrationState]:
    """The state of each integration each user has access to (only those of
    ``integration_ids``, when given), in one query."""
    users = sorted(set(user_ids))
    if not users:
        return []
    integrations = sorted(set(integration_ids)) if integration_ids is not None else None
    if integrations is not None and not integrations:
        return []
    pairs = _user_integration_pairs(User.__table__.c.id.in_(users), integrations)
    choice = UserIntegrationPreference.enabled
    stmt = (
        select(
            pairs.c.user_id,
            pairs.c.integration_id,
            pairs.c.rank,
            pairs.c.is_owner,
            pairs.c.for_everyone,
            choice.label("choice"),
            enabled_under_setting(pairs.c.rank, choice).label("turned_on"),
            pairs.c.integration_enabled,
        )
        .outerjoin(
            UserIntegrationPreference,
            and_(
                UserIntegrationPreference.user_id == pairs.c.user_id,
                UserIntegrationPreference.integration_id == pairs.c.integration_id,
            ),
        )
        .order_by(pairs.c.user_id, pairs.c.integration_id)
    )
    return [
        UserIntegrationState(
            user_id=row.user_id,
            integration_id=row.integration_id,
            installation_policy=POLICY_OF_RANK[row.rank],
            is_owner=bool(row.is_owner),
            for_everyone=bool(row.for_everyone),
            choice=row.choice,
            turned_on=bool(row.turned_on),
            integration_enabled=bool(row.integration_enabled),
        )
        for row in db_session.execute(stmt).all()
    ]


def accessible_integration_ids(user_id: UUID) -> Select[tuple[int]]:
    """The integrations the user has access to, as a subquery for ``in_``."""
    pairs = _user_integration_pairs(User.__table__.c.id == user_id, None)
    return select(pairs.c.integration_id)


def user_can_use_integration(
    db_session: Session, integration_id: int, user_id: UUID
) -> bool:
    """True when the user has access to the integration, also when the user
    or an admin turned it off."""
    pairs = _user_integration_pairs(User.__table__.c.id == user_id, [integration_id])
    return db_session.scalar(select(pairs.c.integration_id).limit(1)) is not None


def affected_user_ids_for_integrations(
    integration_ids: Iterable[int], db_session: Session
) -> set[UUID]:
    """Users with a running sandbox who have access to at least one of the
    integrations. Ignores user choices, so a change that removes access still
    reaches the users who had it (read it before and after the change)."""
    ids = sorted(set(integration_ids))
    if not ids:
        return set()
    running = select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
    pairs = _user_integration_pairs(User.__table__.c.id.in_(running), ids)
    return set(db_session.scalars(select(pairs.c.user_id).distinct()))


def set_integration_preferences__no_commit(
    user_id: UUID,
    integration_ids: Iterable[int],
    enabled: bool,
    db_session: Session,
) -> None:
    """Write the user's on/off choice. enabled_at is set each time the user
    turns an integration on."""
    ids = sorted(set(integration_ids))
    if not ids:
        return
    stmt = insert(UserIntegrationPreference).values(
        [
            {
                "user_id": user_id,
                "integration_id": integration_id,
                "enabled": enabled,
                "enabled_at": func.now() if enabled else None,
            }
            for integration_id in ids
        ]
    )
    db_session.execute(
        stmt.on_conflict_do_update(
            index_elements=[
                UserIntegrationPreference.user_id,
                UserIntegrationPreference.integration_id,
            ],
            set_={
                "enabled": stmt.excluded.enabled,
                "enabled_at": (
                    func.now() if enabled else UserIntegrationPreference.enabled_at
                ),
            },
        )
    )


class IntegrationShares(BaseModel):
    """The shares of one integration. A group row with no permission is not
    a share."""

    model_config = ConfigDict(frozen=True)

    user_shares: tuple[PluginUserShare, ...]
    group_shares: tuple[PluginGroupShare, ...]


def load_integration_shares(
    integration_id: int, db_session: Session
) -> IntegrationShares:
    user_email: KeyedColumnElement[str] = User.__table__.c.email
    return IntegrationShares(
        user_shares=tuple(
            PluginUserShare(user_id=user_id, email=email, permission=permission)
            for user_id, email, permission in db_session.execute(
                select(
                    Integration__User.user_id, user_email, Integration__User.permission
                )
                .join(User.__table__, User.__table__.c.id == Integration__User.user_id)
                .where(Integration__User.integration_id == integration_id)
                .order_by(user_email)
            )
        ),
        group_shares=tuple(
            PluginGroupShare(group_id=group_id, group_name=name, permission=permission)
            for group_id, name, permission in db_session.execute(
                select(
                    Integration__UserGroup.user_group_id,
                    UserGroup.name,
                    Integration__UserGroup.permission,
                )
                .join(UserGroup, UserGroup.id == Integration__UserGroup.user_group_id)
                .where(
                    Integration__UserGroup.integration_id == integration_id,
                    Integration__UserGroup.permission.is_not(None),
                )
                .order_by(UserGroup.name, UserGroup.id)
            )
        ),
    )


class IntegrationGroupSetting(BaseModel):
    model_config = ConfigDict(frozen=True)

    group_id: int
    group_name: str
    installation_policy: PluginInstallationPolicy


def load_integration_group_settings(
    integration_id: int, db_session: Session
) -> list[IntegrationGroupSetting]:
    """The groups with their own install setting for the integration."""
    return [
        IntegrationGroupSetting(
            group_id=group_id, group_name=name, installation_policy=policy
        )
        for group_id, name, policy in db_session.execute(
            select(
                Integration__UserGroup.user_group_id,
                UserGroup.name,
                Integration__UserGroup.installation_policy,
            )
            .join(UserGroup, UserGroup.id == Integration__UserGroup.user_group_id)
            .where(
                Integration__UserGroup.integration_id == integration_id,
                Integration__UserGroup.installation_policy.is_not(None),
            )
            .order_by(UserGroup.name, UserGroup.id)
        )
    ]


def group_limited_integration_ids(user_id: UUID, db_session: Session) -> list[int]:
    """The integrations an admin made available to some groups, which the
    user has no access to. Members see them as No access. A private
    integration (only the owner and the shares) stays hidden."""
    not_available = PluginInstallationPolicy.NOT_AVAILABLE
    return list(
        db_session.scalars(
            select(Integration__UserGroup.integration_id)
            .where(
                Integration__UserGroup.installation_policy.is_not(None),
                Integration__UserGroup.installation_policy != not_available,
                Integration__UserGroup.integration_id.notin_(
                    accessible_integration_ids(user_id)
                ),
            )
            .distinct()
            .order_by(Integration__UserGroup.integration_id)
        )
    )


def replace_integration_shares__no_commit(
    integration: Integration,
    user_ids: Collection[UUID],
    group_ids: Collection[int],
    actor: User,
    db_session: Session,
) -> None:
    """Make the shares of a locked integration equal the users and groups.
    Each share is a VIEWER row. A group keeps its install setting, and a kept
    share keeps its created_at. The share rules of plugins apply
    (``onyx.db.plugin.check_access_change``): the Sharing setting, the
    managed group scope, no default group, and no share for a group whose
    setting is NOT_AVAILABLE."""
    viewer = SkillSharePermission.VIEWER
    _apply_access_change__no_commit(
        integration,
        PluginAccessChange(
            user_grants=tuple(
                PluginUserGrant(user_id=user_id, permission=viewer)
                for user_id in sorted(set(user_ids))
            ),
            group_grants=tuple(
                PluginGroupGrant(group_id=group_id, permission=viewer)
                for group_id in sorted(set(group_ids))
            ),
        ),
        actor,
        db_session,
    )


def set_integration_group_settings__no_commit(
    integration: Integration,
    settings: Mapping[int, PluginInstallationPolicy | None],
    actor: User,
    db_session: Session,
) -> None:
    """Set the install setting of each group in ``settings`` on a locked
    integration. None removes the setting of the group. The shares stay. Only
    an organization-wide action manager sets a group setting."""
    _apply_access_change__no_commit(
        integration,
        PluginAccessChange(
            group_settings=tuple(
                PluginGroupSetting(group_id=group_id, installation_policy=policy)
                for group_id, policy in sorted(settings.items())
            )
        ),
        actor,
        db_session,
    )


def _apply_access_change__no_commit(
    integration: Integration,
    change: PluginAccessChange,
    actor: User,
    db_session: Session,
) -> None:
    viewer = SkillSharePermission.VIEWER
    group_rows = {
        group_id: PluginGroupRow(permission=permission, installation_policy=policy)
        for group_id, permission, policy in db_session.execute(
            select(
                Integration__UserGroup.user_group_id,
                Integration__UserGroup.permission,
                Integration__UserGroup.installation_policy,
            ).where(Integration__UserGroup.integration_id == integration.id)
        )
    }
    user_grants = dict.fromkeys(
        db_session.scalars(
            select(Integration__User.user_id).where(
                Integration__User.integration_id == integration.id
            )
        ),
        viewer,
    )
    rows = AccessRows(
        published=integration.installation_policy
        != PluginInstallationPolicy.NOT_AVAILABLE,
        user_grants=user_grants,
        group_rows=group_rows,
        new_user_grants=(
            None
            if change.user_grants is None
            else {grant.user_id: viewer for grant in change.user_grants}
        ),
        new_group_rows=new_group_rows(group_rows, change),
    )
    check_access_change(
        [rows], change, actor, db_session, manage_permission=Permission.MANAGE_ACTIONS
    )
    try:
        with db_session.begin_nested():
            _write_rows(integration.id, rows, db_session)
    except IntegrityError as exc:
        if is_fk_violation(exc):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "One or more share targets do not exist.",
            ) from exc
        raise


def _write_rows(integration_id: int, rows: AccessRows, db_session: Session) -> None:
    """Write the user and group rows after a change. A field that does not
    change is None and keeps its rows."""
    if rows.new_user_grants is not None:
        users = sorted(rows.new_user_grants)
        db_session.execute(
            delete(Integration__User).where(
                Integration__User.integration_id == integration_id,
                Integration__User.user_id.notin_(users),
            )
        )
        if users:
            db_session.execute(
                insert(Integration__User)
                .values(
                    [
                        {"integration_id": integration_id, "user_id": user_id}
                        for user_id in users
                    ]
                )
                .on_conflict_do_nothing()
            )
    if rows.new_group_rows is None:
        db_session.flush()
        return
    groups = rows.new_group_rows
    db_session.execute(
        delete(Integration__UserGroup).where(
            Integration__UserGroup.integration_id == integration_id,
            Integration__UserGroup.user_group_id.notin_(list(groups)),
        )
    )
    if groups:
        stmt = insert(Integration__UserGroup).values(
            [
                {
                    "integration_id": integration_id,
                    "user_group_id": group_id,
                    "permission": row.permission,
                    "installation_policy": row.installation_policy,
                }
                for group_id, row in sorted(groups.items())
            ]
        )
        db_session.execute(
            stmt.on_conflict_do_update(
                index_elements=[
                    Integration__UserGroup.integration_id,
                    Integration__UserGroup.user_group_id,
                ],
                set_={
                    "permission": stmt.excluded.permission,
                    "installation_policy": stmt.excluded.installation_policy,
                },
            )
        )
    db_session.flush()
