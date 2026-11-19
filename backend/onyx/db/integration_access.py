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
"""

from collections.abc import Iterable
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import ColumnElement, and_, func, or_, select, true
from sqlalchemy.orm import Session
from sqlalchemy.sql.elements import KeyedColumnElement
from sqlalchemy.sql.selectable import Select, Subquery

from onyx.db.enums import PluginInstallationPolicy
from onyx.db.models import (
    Integration,
    Integration__User,
    Integration__UserGroup,
    User,
    UserIntegrationPreference,
)
from onyx.db.plugin_access import (
    POLICY_OF_RANK,
    enabled_under_setting,
    group_rows_of_users,
    non_default_group_counts,
    policy_rank,
    rank_of,
    setting_rank_for_user,
    with_share_floor,
)


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
