from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Memory
from onyx.db.models import User


class UserInfo(BaseModel):
    name: str | None = None
    role: str | None = None
    email: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "email": self.email,
        }


class UserMemoryContext(BaseModel):
    user_info: UserInfo
    user_preferences: str | None = None
    memories: list[str] = []

    def as_formatted_list(self) -> list[str]:
        """Returns combined list of user info, preferences, and memories."""
        result = []
        if self.user_info.name:
            result.append(f"User's name: {self.user_info.name}")
        if self.user_info.role:
            result.append(f"User's role: {self.user_info.role}")
        if self.user_info.email:
            result.append(f"User's email: {self.user_info.email}")
        if self.user_preferences:
            result.append(f"User preferences: {self.user_preferences}")
        result.extend(self.memories)
        return result


def get_memories(user: User, db_session: Session) -> UserMemoryContext:
    if not user.use_memories:
        return UserMemoryContext(user_info=UserInfo())

    user_info = UserInfo(
        name=user.personal_name,
        role=user.personal_role,
        email=user.email,
    )

    user_preferences = None
    if user.use_user_preferences and user.user_preferences:
        user_preferences = user.user_preferences

    memory_rows = db_session.scalars(
        select(Memory).where(Memory.user_id == user.id).order_by(Memory.id.asc())
    ).all()
    memories = [memory.memory_text for memory in memory_rows if memory.memory_text]

    return UserMemoryContext(
        user_info=user_info,
        user_preferences=user_preferences,
        memories=memories,
    )
