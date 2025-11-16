from collections import defaultdict

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ee.onyx.db.token_limit import (
    fetch_all_user_group_token_rate_limits_by_group,
    fetch_user_group_token_rate_limits_for_user,
    insert_user_group_token_rate_limit,
)
from onyx.auth.users import (
    current_admin_user,
    current_curator_or_admin_user,
)
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.db.token_limit import (
    fetch_all_user_token_rate_limits,
    insert_user_token_rate_limit,
)
from onyx.server.query_and_chat.token_limit import any_rate_limit_exists
from onyx.server.token_rate_limits.models import (
    TokenRateLimitArgs,
    TokenRateLimitDisplay,
)

router = APIRouter(tags=["Управление лимитами по токенам групп и пользователей"])


"""
API для управления настройками лимитов токенов групп пользователей
"""


@router.get(
    "/admin/token-rate-limits/user-groups",
    summary="Получить все настройки лимитов токенов по группам",
    response_model=dict[str, list[TokenRateLimitDisplay]],
)
def get_all_group_token_limit_settings(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, list[TokenRateLimitDisplay]]:
    """Возвращает все настройки лимитов токенов, сгруппированные по названиям групп.

    Используется администраторами для просмотра всех групповых ограничений
    на использование токенов в системе.

    Returns:
        Словарь {название_группы: [список_лимитов]} с настройками лимитов
    """
    # Получаем все лимиты токенов с именами групп из базы данных
    group_limits_with_names = fetch_all_user_group_token_rate_limits_by_group(db_session)

    # Группируем лимиты по названиям групп
    limits_by_group = defaultdict(list)
    for token_limit, group_name in group_limits_with_names:

        # Преобразуем каждый лимит в формат для отображения
        display_limit = TokenRateLimitDisplay.from_db(token_limit)
        limits_by_group[group_name].append(display_limit)

    limits_by_group_response = dict(limits_by_group)

    return limits_by_group_response


@router.get(
    "/admin/token-rate-limits/user-group/{group_id}",
    summary="Получить настройки лимитов токенов для конкретной группы",
    response_model=list[TokenRateLimitDisplay],
)
def get_group_token_limit_settings(
    group_id: int,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[TokenRateLimitDisplay]:
    """Возвращает настройки лимитов токенов для указанной группы.

    Доступно кураторам и администраторам для просмотра ограничений
    конкретной группы пользователей.

    Args:
        group_id: ID группы пользователей

    Returns:
        Список настроек лимитов токенов для указанной группы
    """
    # Получаем лимиты токенов для указанной группы
    group_limits = fetch_user_group_token_rate_limits_for_user(
        db_session=db_session,
        group_id=group_id,
        user=user,
    )

    # Преобразуем каждый лимит в формат для отображения
    display_limits_response = []
    for token_limit in group_limits:
        display_limit = TokenRateLimitDisplay.from_db(token_limit)
        display_limits_response.append(display_limit)

    return display_limits_response


@router.post(
    "/admin/token-rate-limits/user-group/{group_id}",
    summary="Создать новую настройку лимита токенов для группы",
    response_model=TokenRateLimitDisplay,
)
def create_group_token_limit_settings(
    group_id: int,
    token_limit_settings: TokenRateLimitArgs,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    """Создает новую настройку лимита токенов для указанной группы.

    Позволяет администраторам устанавливать новые ограничения
    на использование токенов для конкретной группы пользователей.

    Args:
        group_id: ID группы пользователей
        token_limit_settings: Параметры нового лимита токенов

    Returns:
        Созданная настройка лимита токенов в формате для отображения
    """
    # Создаем новую запись лимита токенов для группы
    new_token_limit = insert_user_group_token_rate_limit(
        db_session=db_session,
        token_rate_limit_settings=token_limit_settings,
        group_id=group_id,
    )

    # Преобразуем созданную запись в формат для отображения
    created_display_response = TokenRateLimitDisplay.from_db(new_token_limit)

    # Очищаем кэш, так как мог быть создан первый лимит
    any_rate_limit_exists.cache_clear()


    return created_display_response


"""
API для управления настройками лимитов токенов пользователей
"""


@router.get(
    "/admin/token-rate-limits/users",
    summary="Получить все настройки лимитов токенов пользователей",
    response_model=list[TokenRateLimitDisplay],
)
def get_user_token_limit_settings(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[TokenRateLimitDisplay]:
    """Возвращает список всех настроек лимитов токенов для пользователей.

    Используется администраторами для просмотра текущих ограничений
    на использование токенов в системе.

    Returns:
        Список настроек лимитов токенов в формате для отображения
    """
    # Получаем все настройки лимитов токенов из базы данных
    token_limits = fetch_all_user_token_rate_limits(db_session)

    # Преобразуем каждую настройку в формат для отображения
    display_settings_response = []
    for token_limit in token_limits:
        display_setting = TokenRateLimitDisplay.from_db(token_limit)
        display_settings_response.append(display_setting)

    return display_settings_response


@router.post(
    "/admin/token-rate-limits/users",
    summary="Создать новую настройку лимита токенов пользователей",
    response_model=TokenRateLimitDisplay,
)
def create_user_token_limit_settings(
    token_limit_settings: TokenRateLimitArgs,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> TokenRateLimitDisplay:
    """Создает новую настройку лимита токенов для пользователей.

    Позволяет администраторам устанавливать новые ограничения
    на использование токенов в системе.

    Args:
        token_limit_settings: Параметры нового лимита токенов

    Returns:
        Созданная настройка лимита токенов в формате для отображения
    """
    # Создаем новую запись лимита токенов в базе данных
    new_token_limit = insert_user_token_rate_limit(
        db_session, token_limit_settings
    )

    # Преобразуем созданную запись в формат для отображения
    created_display_response = TokenRateLimitDisplay.from_db(new_token_limit)

    # Очищаем кэш, так как мог быть создан первый лимит
    any_rate_limit_exists.cache_clear()

    return created_display_response

