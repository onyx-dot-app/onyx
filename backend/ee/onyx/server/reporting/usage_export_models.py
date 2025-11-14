from datetime import datetime
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, Field


class FlowType(str, Enum):
    """Тип потока сообщений"""

    CHAT = "chat"


class ChatMessageSkeleton(BaseModel):
    """Упрощенная структура сообщения чата для отчетов"""

    message_id: int = Field(description="Идентификатор сообщения")
    chat_session_id: UUID = Field(description="Идентификатор сессии чата")
    user_id: str | None = Field(description="Идентификатор пользователя")
    flow_type: FlowType = Field(description="Тип потока сообщения")
    time_sent: datetime = Field(description="Время отправки сообщения")


class UserSkeleton(BaseModel):
    """Упрощенная структура пользователя для отчетов"""

    user_id: str = Field(description="Идентификатор пользователя")
    is_active: bool = Field(description="Статус активности пользователя")


class UsageReportMetadata(BaseModel):
    report_name: str = Field(description="Название файла отчета")
    requestor: str | None = Field(description="Идентификатор пользователя, запросившего отчет")
    time_created: datetime = Field(description="Время создания отчета")
    period_from: datetime | None = Field(description="Начало периода отчета (None = за все время)")
    period_to: datetime | None = Field(description="Конец периода отчета (None = за все время)")


class GenerateUsageReportParams(BaseModel):
    period_from: str | None = Field(
        default=None,
        description="Начало периода отчета в формате ISO",
    )
    period_to: str | None = Field(
        default=None,
        description="Конец периода отчета в формате ISO",
    )
