from uuid import UUID

from pydantic import BaseModel, Field


class MinimalUsersSnapshot(BaseModel):
    id: UUID = Field(
        description="Уникальный идентификатор пользователя",
    )
    email: str = Field(
        description="Уникальная почта пользователя",
    )