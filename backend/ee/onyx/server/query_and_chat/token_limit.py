from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from itertools import groupby
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.db.api_key import is_api_key_email_address
from onyx.db.engine import get_session_with_current_tenant
from onyx.db.models import (
    ChatMessage,
    ChatSession,
    TokenRateLimit,
    TokenRateLimit__UserGroup,
    User,
    User__UserGroup,
    UserGroup,
)
from onyx.db.token_limit import fetch_all_user_token_rate_limits
from onyx.server.query_and_chat.token_limit import (
    _get_cutoff_time,
    _is_rate_limited,
    _user_is_rate_limited_by_global,
)
from onyx.utils.threadpool_concurrency import run_functions_tuples_in_parallel


def _check_token_rate_limits(user: User | None) -> None:
    """Проверяет ограничения использования токенов для пользователя.

    Многоуровневая система ограничений для контроля потребления токенов:
        - Глобальные лимиты - защита всей системы от перегрузки
        - Групповые лимиты - контроль потребления по группам доступа
        - Персональные лимиты - индивидуальные ограничения пользователей

    Args:
        user: Объект пользователя или None для анонимного доступа
    """
    # Анонимные пользователи проверяются только по глобальным лимитам
    if user is None:
        _user_is_rate_limited_by_global()

    # API-ключи также проверяются только по глобальным лимитам
    elif is_api_key_email_address(user.email):
        _user_is_rate_limited_by_global()

    # Обычные пользователи проходят полную проверку всех уровней лимитов
    else:
        run_functions_tuples_in_parallel(
            [
                (_user_is_rate_limited, (user.id,)),    # Личные лимиты
                (_user_is_rate_limited_by_group, (user.id,)),   # Групповые лимиты
                (_user_is_rate_limited_by_global, ()),  # Глобальные лимиты
            ]
        )


"""
Лимиты пользователей
"""


def _user_is_rate_limited(user_id: UUID) -> None:
    """Проверяет превышение личных лимитов токенов для пользователя.

    Загружает активные ограничения пользователя, вычисляет период проверки,
    суммирует использование токенов и проверяет превышение лимитов.

    Args:
        user_id: UUID идентификатор пользователя

    Raises:
        HTTPException: 429 если пользователь превысил свои лимиты токенов
    """
    with get_session_with_current_tenant() as db_session:

        # Загружаем активные лимиты токенов для пользователя
        user_limits = fetch_all_user_token_rate_limits(
            db_session=db_session, enabled_only=True, ordered=False
        )

        # Если есть установленные лимиты, проверяем их соблюдение
        if user_limits:
            # Определяем период проверки по самому длинному интервалу лимитов
            check_period_start = _get_cutoff_time(rate_limits=user_limits)

            # Получаем статистику использования токенов за период
            token_usage_stats = _fetch_user_usage(
                user_id=user_id,
                cutoff_time=check_period_start,
                db_session=db_session,
            )

            # Проверяем превышение лимитов
            if _is_rate_limited(user_limits, token_usage_stats):
                raise HTTPException(
                    status_code=429,
                    detail="Превышен личный лимит токенов. Попробуйте позже.",
                )


def _fetch_user_usage(
    user_id: UUID, cutoff_time: datetime, db_session: Session
) -> Sequence[tuple[datetime, int]]:
    """Собирает статистику использования токенов пользователем за указанный период.

    Выполняет запрос к базе данных для получения суммы токенов, использованных
    пользователем, сгруппированных по минутам отправки сообщений.

    Args:
        user_id: Уникальный идентификатор пользователя
        cutoff_time: Время начала периода для сбора статистики

    Returns:
        Список кортежей (время_минута, сумма_токенов) за указанный период
    """
    # Формируем SQL запрос для получения статистики использования токенов
    usage_query = (
        select(
            # Группируем по минутам для агрегации
            func.date_trunc("minute", ChatMessage.time_sent),
            # Суммируем количество токенов в каждой минуте
            func.sum(ChatMessage.token_count),
        )
        # Соединяем с таблицей чат-сессий для фильтрации по пользователю
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        # Фильтруем по пользователю и временному периоду
        .where(
            ChatSession.user_id == user_id,
            ChatMessage.time_sent >= cutoff_time
        )
        # Группируем результаты по минутам
        .group_by(func.date_trunc("minute", ChatMessage.time_sent))
    )

    # Выполняем запрос к базе данных
    query_result = db_session.execute(usage_query).all()

    # Преобразуем результат в список кортежей через обычный цикл
    usage_data = []
    for row in query_result:
        timestamp = row[0]
        token_count = row[1]
        usage_data.append((timestamp, token_count))

    return usage_data


"""
Лимиты групп пользователей
"""


def _user_is_rate_limited_by_group(user_id: UUID) -> None:
    """Проверяет превышение групповых лимитов токенов для пользователя.

    Для каждого пользователя проверяются все группы, в которых он состоит.
    Пользователь блокируется только если ВСЕ его группы превысили лимиты.
    Если хотя бы одна группа не превысила лимит - доступ разрешен.

    Args:
        user_id: UUID идентификатор пользователя

    Raises:
        HTTPException: 429 если все группы пользователя превысили лимиты токенов
    """
    with get_session_with_current_tenant() as db_session:
        # Загружаем лимиты токенов для всех групп пользователя
        group_limits_dict = _fetch_all_user_group_rate_limits(user_id, db_session)

        # Если у пользователя нет групп с лимитами, проверка не требуется
        if not group_limits_dict:
            return

        # Вычисляем общее время начала проверки для всех групп
        # Используем самый длинный период среди всех групповых лимитов
        all_group_limits = []
        for limits_list in group_limits_dict.values():
            for limit in limits_list:
                all_group_limits.append(limit)


        check_period_start = _get_cutoff_time(all_group_limits)

        # Получаем ID всех групп пользователя для запроса статистики
        user_group_ids = list(group_limits_dict.keys())

        # Загружаем статистику использования токенов по группам
        group_usage_stats = _fetch_user_group_usage(
            user_group_ids=user_group_ids,
            cutoff_time=check_period_start,
            db_session=db_session,
        )


        # Проверяем есть ли хотя бы одна группа, не превысившая лимиты
        has_available_group = False
        for group_id, group_limits in group_limits_dict.items():
            # Получаем статистику использования для текущей группы
            group_usage = group_usage_stats.get(group_id, [])

            # Если группа не превысила лимиты - пользователь имеет доступ
            if not _is_rate_limited(group_limits, group_usage):
                has_available_group = True
                break

        if not has_available_group:
            raise HTTPException(
                status_code=429,
                detail="Превышены лимиты токенов во всех группах пользователя. Попробуйте позже.",
            )


def _fetch_all_user_group_rate_limits(
    user_id: UUID, db_session: Session
) -> dict[int, list[TokenRateLimit]]:
    """Загружает лимиты токенов для всех групп пользователя.

    Args:
        user_id: UUID идентификатор пользователя

    Returns:
        Словарь {group_id: [список лимитов]} для всех групп пользователя
    """
    # Формируем запрос для получения лимитов групп пользователя
    group_limits_query = (
        select(TokenRateLimit, User__UserGroup.user_group_id)
        .join(
            TokenRateLimit__UserGroup,
            TokenRateLimit.id == TokenRateLimit__UserGroup.rate_limit_id,
        )
        .join(
            UserGroup,
            UserGroup.id == TokenRateLimit__UserGroup.user_group_id,
        )
        .join(
            User__UserGroup,
            User__UserGroup.user_group_id == UserGroup.id,
        )
        .where(
            User__UserGroup.user_id == user_id,
            TokenRateLimit.enabled.is_(True),
        )
    )

    # Выполняем запрос и получаем сырые данные
    query_result = db_session.execute(group_limits_query).all()

    # Группируем лимиты по ID групп
    grouped_limits = defaultdict(list)
    for rate_limit, user_group_id in query_result:
        grouped_limits[user_group_id].append(rate_limit)

    return grouped_limits


def _fetch_user_group_usage(
    user_group_ids: list[int], cutoff_time: datetime, db_session: Session
) -> dict[int, list[tuple[datetime, int]]]:
    """Собирает статистику использования токенов по группам пользователя.

    Args:
        user_group_ids: Список ID групп для сбора статистики
        cutoff_time: Время начала периода проверки

    Returns:
        Словарь {group_id: [(время, количество_токенов)]} с статистикой по группам
    """
    # Выполняем запрос для получения статистики по группам
    usage_query = (
        select(
            # Суммируем количество токенов использованных в сообщениях
            func.sum(ChatMessage.token_count),
            # Группируем по минутам для агрегации данных
            func.date_trunc("minute", ChatMessage.time_sent),
            # ID группы для группировки результатов
            UserGroup.id,
        )
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .join(User__UserGroup, User__UserGroup.user_id == ChatSession.user_id)
        .join(UserGroup, UserGroup.id == User__UserGroup.user_group_id)
        # Фильтруем по указанным группам и временному периоду
        .filter(
            UserGroup.id.in_(user_group_ids),
            ChatMessage.time_sent >= cutoff_time,
        )
        # Группируем результаты по минутам и ID групп
        .group_by(func.date_trunc("minute", ChatMessage.time_sent), UserGroup.id)
    )

    # Выполняем запрос к базе данных
    query_result = db_session.execute(usage_query).all()

    # Группируем результаты по ID групп
    grouped_usage_data = {}

    # Группируем результаты по ID групп
    for group_id, group_rows in groupby(query_result, key=lambda row: row[2]):
        # Создаем список для хранения данных текущей группы
        group_data = []

        # Обрабатываем каждую строку в группе
        for time_sent, usage, _ in group_rows:
            group_data.append((usage, time_sent))

        # Добавляем данные группы в общий словарь
        grouped_usage_data[group_id] = group_data

    return grouped_usage_data
