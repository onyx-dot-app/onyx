from uuid import UUID

from pydantic import BaseModel

from onyx.auth.schemas import UserRole


class APIKeyArgs(BaseModel):
    name: str | None = None
    user_id: UUID | None = None
    role: UserRole = UserRole.BASIC
