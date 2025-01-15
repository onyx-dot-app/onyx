from collections.abc import Sequence

from sqlalchemy import exists
from sqlalchemy import Row
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import aliased
from sqlalchemy.orm import Session

from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserRole
from onyx.server.token_rate_limits.models import TokenRateLimitArgs


def _add_user_filters(
    stmt: Select, user: User | None, get_editable: bool = True
) -> Select:
    # If user is None and auth is disabled, assume the user is an admin
    if (user is None and DISABLE_AUTH) or (user and user.role == UserRole.ADMIN):
        return stmt

    stmt = stmt.distinct()
    TRLimit_UG = aliased(TokenRateLimit__UserGroup)
    User__UG = aliased(User__UserGroup)

    """
    Here we select token_rate_limits by relation:
    User -> User__UserGroup -> TokenRateLimit__UserGroup ->
    TokenRateLimit
    """
    stmt = stmt.outerjoin(TRLimit_UG).outerjoin(
        User__UG,
        User__UG.user_group_id == TRLimit_UG.user_group_id,
    )

    """
    Filter token_rate_limits by:
    - if the user is in the user_group that owns the token_rate_limit
    - if the user is not a global_curator, they must also have a curator relationship
    to the user_group
    - if editing is being done, we also filter out token_rate_limits that are owned by groups
    that the user isn't a curator for
    - if we are not editing, we show all token_rate_limits in the groups the user curates
    """

    # If user is None, this is an anonymous user and we should only show public token_rate_limits
    if user is None:
        where_clause = TokenRateLimit.scope == TokenRateLimitScope.GLOBAL
        return stmt.where(where_clause)

    where_clause = User__UG.user_id == user.id
    if user.role == UserRole.CURATOR and get_editable:
        where_clause &= User__UG.is_curator == True  # noqa: E712
    if get_editable:
        user_groups = select(User__UG.user_group_id).where(User__UG.user_id == user.id)
        if user.role == UserRole.CURATOR:
            user_groups = user_groups.where(
                User__UserGroup.is_curator == True  # noqa: E712
            )
        where_clause &= (
            ~exists()
            .where(TRLimit_UG.rate_limit_id == TokenRateLimit.id)
            .where(~TRLimit_UG.user_group_id.in_(user_groups))
            .correlate(TokenRateLimit)
        )

    return stmt.where(where_clause)


def fetch_all_user_group_token_rate_limits_by_group(
    db_session: Session,
) -> Sequence[Row[tuple[TokenRateLimit, str]]]:
    query = (
        select(TokenRateLimit, UserGroup.name)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .join(UserGroup, UserGroup.id == TokenRateLimit__UserGroup.user_group_id)
    )

    return db_session.execute(query).all()


def insert_user_group_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
    group_id: int,
) -> TokenRateLimit:
    token_limit = TokenRateLimit(
        enabled=token_rate_limit_settings.enabled,
        token_budget=token_rate_limit_settings.token_budget,
        period_hours=token_rate_limit_settings.period_hours,
        scope=TokenRateLimitScope.USER_GROUP,
    )
    db_session.add(token_limit)
    db_session.flush()

    rate_limit = TokenRateLimit__UserGroup(
        rate_limit_id=token_limit.id, user_group_id=group_id
    )
    db_session.add(rate_limit)
    db_session.commit()

    return token_limit


def fetch_user_group_token_rate_limits_for_user(
    db_session: Session,
    group_id: int,
    user: User | None,
    enabled_only: bool = False,
    ordered: bool = True,
    get_editable: bool = True,
) -> Sequence[TokenRateLimit]:
    stmt = select(TokenRateLimit)
    stmt = stmt.where(User__UserGroup.user_group_id == group_id)
    stmt = _add_user_filters(stmt, user, get_editable)

    if enabled_only:
        stmt = stmt.where(TokenRateLimit.enabled.is_(True))

    if ordered:
        stmt = stmt.order_by(TokenRateLimit.created_at.desc())

    return db_session.scalars(stmt).all()
