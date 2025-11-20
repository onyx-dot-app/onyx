import datetime
from collections import defaultdict

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from smartsearch.onyx.db.analytics import (
    fetch_assistant_message_analytics,
    fetch_assistant_unique_users,
    fetch_assistant_unique_users_total,
    fetch_per_user_query_analytics,
    fetch_persona_message_analytics,
    fetch_persona_unique_users,
    fetch_query_analytics,
    user_can_view_assistant_stats,
)
from smartsearch.onyx.server.analytics.models import (
    AssistantDailyUsageResponse,
    AssistantStatsResponse,
    PersonaMessageAnalyticsResponse,
    PersonaUniqueUsersResponse,
    QueryAnalyticsResponse,
    UserAnalyticsResponse,
)
from onyx.auth.users import (
    current_admin_user,
    current_user,
)
from onyx.db.engine import get_session
from onyx.db.models import User

router = APIRouter(tags=["Analytics"])


_DEFAULT_ANALYTICS_PERIOD_DAYS = 30


@router.get(
    "/analytics/admin/query",
    summary="Получение аналитики по ассистентским сообщениям за период",
    response_model=list[QueryAnalyticsResponse],
)
def get_query_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[QueryAnalyticsResponse]:
    """Получение аналитики по ассистентским сообщениям за период.

    Считает для каждого дня:
    - общее количество ответов ассистента
    - количество лайков (положительных фидбеков)
    - количество дизлайков (отрицательных фидбеков)

    По умолчанию возвращает данные за последние 30 дней.
    Фильтрует только сообщения типа ASSISTANT.

    Args:
        start: Начало периода (включительно). Если None - 30 дней назад.
        end: Конец периода (включительно). Если None - текущее время.

    Returns:
        Список статистики по дням с агрегированными метриками.
    """
    start_time = start
    end_time = end

    default_period = datetime.timedelta(days=_DEFAULT_ANALYTICS_PERIOD_DAYS)
    current_time = datetime.datetime.now(datetime.UTC)

    if start_time is None:
        analysis_start = current_time - default_period
    else:
        analysis_start = start_time

    if end_time is None:
        analysis_end = datetime.datetime.utcnow()
    else:
        analysis_end = end_time

    daily_query_usage_info = fetch_query_analytics(
        start=analysis_start,
        end=analysis_end,
        db_session=db_session,
    )

    analytics_result = []
    for total_queries, total_likes, total_dislikes, date in daily_query_usage_info:
        analytics_result.append(
            QueryAnalyticsResponse(
                total_queries=total_queries,
                total_likes=total_likes,
                total_dislikes=total_dislikes,
                date=date,
            )
        )

    return analytics_result


@router.get(
    "/analytics/admin/user",
    summary = "Получение статистики по уникальным активным пользователям за период",
    response_model = list[UserAnalyticsResponse],
)
def get_user_analytics(
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserAnalyticsResponse]:
    """Получение статистики по уникальным активным пользователям за период.

    Считает количество пользователей, которые получили хотя бы один ответ ассистента
    в течение каждого дня. Пользователь считается активным в день, если ему был
    отправлен ответ ассистента.

    По умолчанию возвращает данные за последние 30 дней.

    Args:
        start: Начало периода анализа. Если не указано - 30 дней назад.
        end: Окончание периода анализа. Если не указано - текущее время.

    Returns:
        Список с количеством активных пользователей по дням.
    """
    start_time = start
    end_time = end

    default_period = datetime.timedelta(days=_DEFAULT_ANALYTICS_PERIOD_DAYS)
    current_time = datetime.datetime.now(datetime.UTC)

    if start_time is None:
        analysis_start = current_time - default_period
    else:
        analysis_start = start_time

    if end_time is None:
        analysis_end = current_time
    else:
        analysis_end = end_time

    user_activity_records = fetch_per_user_query_analytics(
        start=analysis_start,
        end=analysis_end,
        db_session=db_session,
    )

    daily_active_users: dict[datetime.date, int] = defaultdict(int)
    for count, likes, dislikes, date, user_id in user_activity_records:
        daily_active_users[date] += 1

    analytics_result = []
    for activity_date, user_count in daily_active_users.items():
        analytics_result.append(
            UserAnalyticsResponse(
                total_active_users=user_count,
                date=activity_date,
            )
        )

    return analytics_result


@router.get(
    "/analytics/admin/persona/messages",
    summary = "Получение статистики по ответам конкретного ассистента",
    response_model = list[PersonaMessageAnalyticsResponse],
)
def get_persona_messages(
    persona_id: int,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaMessageAnalyticsResponse]:
    """Получение статистики по ответам конкретного ассистента.

    Считает количество ответов указанного ассистента за каждый день
    в заданном периоде. Учитывает сообщения, где ассистент установлен
    либо в сессии, либо как альтернативный ассистент.

    По умолчанию возвращает данные за последние 30 дней.

    Args:
        persona_id: ID ассистента для анализа
        start: Начало периода. Если не указано - 30 дней назад.
        end: Конец периода. Если не указано - текущее время.

    Returns:
        Список с количеством ответов ассистента по дням.
    """
    start_time = start
    end_time = end

    default_period = datetime.timedelta(days=_DEFAULT_ANALYTICS_PERIOD_DAYS)
    current_time = datetime.datetime.now(datetime.UTC)

    if start_time is None:
        analysis_start = current_time - default_period
    else:
        analysis_start = start_time

    if end_time is None:
        analysis_end = current_time
    else:
        analysis_end = end_time

    persona_message_data = fetch_persona_message_analytics(
        db_session=db_session,
        persona_id=persona_id,
        start=analysis_start,
        end=analysis_end,
    )

    analytics_result = []
    for message_count, message_date in persona_message_data:
        analytics_result.append(
            PersonaMessageAnalyticsResponse(
                total_messages=message_count,
                date=message_date,
                persona_id=persona_id,
            )
        )

    return analytics_result


@router.get(
    "/analytics/admin/persona/unique-users",
    summary="Получение статистики по уникальным пользователям конкретного ассистента",
    response_model=list[PersonaUniqueUsersResponse],
)
def get_persona_unique_users(
    persona_id: int,
    start: datetime.datetime,
    end: datetime.datetime,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[PersonaUniqueUsersResponse]:
    """Получение статистики по уникальным пользователям конкретного ассистента.

    Считает количество уникальных пользователей, которые получили ответы
    от указанного ассистента за каждый день в заданном периоде.

    По умолчанию возвращает данные за последние 30 дней.

    Args:
        persona_id: ID ассистента для анализа
        start: Начало периода. Если не указано - 30 дней назад.
        end: Конец периода. Если не указано - текущее время.

    Returns:
        Список с количеством уникальных пользователей по дням для ассистента.
    """
    start_time = start
    end_time = end

    default_period = datetime.timedelta(days=_DEFAULT_ANALYTICS_PERIOD_DAYS)
    current_time = datetime.datetime.now(datetime.UTC)

    if start_time is None:
        analysis_start = current_time - default_period
    else:
        analysis_start = start_time

    if end_time is None:
        analysis_end = current_time
    else:
        analysis_end = end_time

    unique_users_data = fetch_persona_unique_users(
        db_session=db_session,
        persona_id=persona_id,
        start=analysis_start,
        end=analysis_end,
    )

    analytics_result = []
    for user_count, activity_date in unique_users_data:
        analytics_result.append(
            PersonaUniqueUsersResponse(
                unique_users=user_count,
                date=activity_date,
                persona_id=persona_id,
            )
        )

    return analytics_result


@router.get(
    "/analytics/assistant/{assistant_id}/stats",
    summary="Получение статистики использования ассистента",
    response_model=AssistantStatsResponse,
)
def get_assistant_stats(
    assistant_id: int,
    start: datetime.datetime | None = None,
    end: datetime.datetime | None = None,
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> AssistantStatsResponse:
    """Получение статистики использования ассистента.

    Возвращает ежедневные данные по сообщениям и уникальным пользователям
    для указанного ассистента, а также общие итоги за весь период.

    По умолчанию анализирует данные за последние 30 дней.
    Требует прав доступа к статистике указанного ассистента.

    Args:
        assistant_id: ID ассистента для анализа
        start: Начало периода анализа. Если не указано - 30 дней назад.
        end: Конец периода анализа. Если не указано - текущее время.

    Returns:
        Статистика использования ассистента с ежедневной разбивкой и общими итогами.
    """
    start_time = start
    end_time = end

    default_period = datetime.timedelta(days=_DEFAULT_ANALYTICS_PERIOD_DAYS)
    current_time = datetime.datetime.now(datetime.UTC)

    if start_time is None:
        analysis_start = current_time - default_period
    else:
        analysis_start = start_time

    if end_time is None:
        analysis_end = current_time
    else:
        analysis_end = end_time

    if not user_can_view_assistant_stats(db_session, user, assistant_id):
        raise HTTPException(
            status_code=403,
            detail="Недостаточно прав для просмотра статистики этого ассистента."
        )

    # Получаем данные по сообщениям и пользователям
    daily_messages_data = fetch_assistant_message_analytics(
        db_session, assistant_id, analysis_start, analysis_end
    )
    daily_users_data = fetch_assistant_unique_users(
        db_session, assistant_id, analysis_start, analysis_end
    )

    # Создаем маппинги дат на значения
    messages_by_date = {date: count for count, date in daily_messages_data}
    users_by_date = {date: count for count, date in daily_users_data}

    # Объединяем все даты из обоих наборов данных
    all_dates = set(messages_by_date.keys()) | set(users_by_date.keys())

    # Формируем ежедневную статистику
    daily_statistics = []
    for date in sorted(all_dates):
        daily_statistics.append(
            AssistantDailyUsageResponse(
                date=date,
                total_messages=messages_by_date.get(date, 0),
                total_unique_users=users_by_date.get(date, 0),
            )
        )

    # Вычисляем общие показатели за весь период
    total_message_count = sum(stat.total_messages for stat in daily_statistics)
    total_user_count = fetch_assistant_unique_users_total(
        db_session, assistant_id, analysis_start, analysis_end
    )

    analytics_result = AssistantStatsResponse(
        daily_stats=daily_statistics,
        total_messages=total_message_count,
        total_unique_users=total_user_count,
    )

    return analytics_result
