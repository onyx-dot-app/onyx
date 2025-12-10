from collections.abc import Sequence
from typing import cast

from sqlalchemy import Row, Select, exists, select
from sqlalchemy.orm import Session, aliased

from onyx.configs.app_configs import DISABLE_AUTH
from onyx.configs.constants import TokenRateLimitScope
from onyx.db.models import TokenRateLimit, TokenRateLimit__UserGroup, User, UserGroup, UserRole, User__UserGroup
from onyx.server.token_rate_limits.models import TokenRateLimitArgs


def _apply_admin_access(stmt: Select, current_user: User | None) -> bool:
    """Проверяет, имеет ли пользователь права администратора."""
    return (current_user is None and DISABLE_AUTH) or (current_user and current_user.role == UserRole.ADMIN)


def _setup_group_aliases() -> tuple:
    """Инициализирует алиасы для таблиц связей групп."""
    trl_ug_alias = aliased(TokenRateLimit__UserGroup)
    user_ug_alias = aliased(User__UserGroup)
    return trl_ug_alias, user_ug_alias


def _build_group_ownership_filter(
    trl_ug_alias, user_ug_alias, current_user: User, editable: bool
) -> Select:
    """Формирует фильтр владения группами для куратора."""
    group_query = select(User__UserGroup.user_group_id).where(
        User__UserGroup.user_id == current_user.id
    )
    if current_user.role == UserRole.CURATOR:
        group_query = group_query.where(User__UserGroup.is_curator == True)  # noqa: E712
    return group_query


def _construct_editable_constraint(
    stmt: Select, trl_ug_alias, user_groups_query: Select
) -> Select:
    """Добавляет ограничение редактируемости для групп."""
    return stmt.where(
        ~exists()
        .where(trl_ug_alias.rate_limit_id == TokenRateLimit.id)
        .where(~trl_ug_alias.user_group_id.in_(user_groups_query))
        .correlate(TokenRateLimit)
    )


def _add_user_filters(
    stmt: Select, user: User | None, get_editable: bool = True
) -> Select:
    """
    Добавляет фильтры доступа на основе роли пользователя.
    Для анонимов - только глобальные лимиты.
    """
    if _apply_admin_access(stmt, user):
        return stmt

    stmt = stmt.distinct()
    trl_group_link, user_group_link = _setup_group_aliases()

    stmt = stmt.outerjoin(trl_group_link).outerjoin(
        user_group_link,
        user_group_link.user_group_id == trl_group_link.user_group_id,
    )

    if user is None:
        return stmt.where(TokenRateLimit.scope == TokenRateLimitScope.GLOBAL)

    base_condition = user_group_link.user_id == user.id
    if user.role == UserRole.CURATOR and get_editable:
        base_condition &= user_group_link.is_curator == True  # noqa: E712

    if get_editable:
        allowed_groups = _build_group_ownership_filter(trl_group_link, user_group_link, user, get_editable)
        stmt = _construct_editable_constraint(stmt, trl_group_link, allowed_groups)
        base_condition &= True  # Для совместимости с where

    return stmt.where(base_condition)


def fetch_all_user_group_token_rate_limits_by_group(
    db_session: Session,
) -> Sequence[Row[tuple[TokenRateLimit, str]]]:
    """Извлекает все лимиты токенов по группам с именами."""
    base_query = (
        select(TokenRateLimit, UserGroup.name)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .join(UserGroup, UserGroup.id == TokenRateLimit__UserGroup.user_group_id)
    )
    return db_session.execute(base_query).all()


def insert_user_group_token_rate_limit(
    db_session: Session,
    token_rate_limit_settings: TokenRateLimitArgs,
    group_id: int,
) -> TokenRateLimit:
    """Создает и сохраняет лимит токенов для группы."""
    session = db_session
    settings = token_rate_limit_settings
    target_group = group_id

    new_limit = TokenRateLimit(
        enabled=settings.enabled,
        token_budget=settings.token_budget,
        period_hours=settings.period_hours,
        scope=TokenRateLimitScope.USER_GROUP,
    )
    session.add(new_limit)
    session.flush()

    group_link = TokenRateLimit__UserGroup(
        rate_limit_id=new_limit.id, user_group_id=target_group
    )
    session.add(group_link)
    session.commit()

    return new_limit


def fetch_user_group_token_rate_limits_for_user(
    db_session: Session,
    group_id: int,
    user: User | None,
    enabled_only: bool = False,
    ordered: bool = True,
    get_editable: bool = True,
) -> Sequence[TokenRateLimit]:
    """Получает лимиты токенов для группы с учетом доступа пользователя."""
    session = db_session
    target_group_id = group_id
    current_user = user
    editable_flag = get_editable
    enabled_flag = enabled_only
    sort_flag = ordered

    base_stmt = select(TokenRateLimit)
    base_stmt = base_stmt.where(User__UserGroup.user_group_id == target_group_id)
    base_stmt = _add_user_filters(base_stmt, current_user, editable_flag)

    if enabled_flag:
        base_stmt = base_stmt.where(TokenRateLimit.enabled.is_(True))

    if sort_flag:
        base_stmt = base_stmt.order_by(TokenRateLimit.created_at.desc())

    return session.scalars(base_stmt).all()
