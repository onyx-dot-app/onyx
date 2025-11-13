from pydantic import BaseModel, Field

import datetime


class QueryAnalyticsResponse(BaseModel):
    total_queries: int = Field(
        description="Общее количество ответов ассистента за день",
    )
    total_likes: int = Field(
        description="Количество положительных отзывов (лайков) за день",
    )
    total_dislikes: int = Field(
        description="Количество отрицательных отзывов (дизлайков) за день",
    )
    date: datetime.date = Field(
        description="Дата, за которую собрана статистика",
    )


class UserAnalyticsResponse(BaseModel):
    total_active_users: int = Field(
        description="Количество уникальных активных пользователей за день",
    )
    date: datetime.date = Field(
        description="Дата, за которую собрана статистика по активным пользователям",
    )


class PersonaMessageAnalyticsResponse(BaseModel):
    total_messages: int = Field(
        description="Количество ответов ассистента за день",
    )
    date: datetime.date = Field(
        description="Дата, за которую собрана статистика",
    )
    persona_id: int = Field(
        description="Идентификатор ассистента",
    )

class PersonaUniqueUsersResponse(BaseModel):
    unique_users: int = Field(
        description="Количество уникальных пользователей, взаимодействовавших с ассистентом за день",
    )
    date: datetime.date = Field(
        description="Дата, за которую собрана статистика",
    )
    persona_id: int = Field(
        description="Идентификатор ассистента",
    )


class AssistantDailyUsageResponse(BaseModel):
    date: datetime.date = Field(
        description="Дата статистики",
    )
    total_messages: int = Field(
        description="Количество сообщений за день",
    )
    total_unique_users: int = Field(
        description="Количество уникальных пользователей за день",
    )


class AssistantStatsResponse(BaseModel):
    daily_stats: list[AssistantDailyUsageResponse] = Field(
        description="Ежедневная статистика",
    )
    total_messages: int = Field(
        description="Общее количество сообщений за период",
    )
    total_unique_users: int = Field(
        description="Общее количество уникальных пользователей за период",
    )
