from uuid import UUID

from pydantic import BaseModel
from pydantic import ConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Memory
from onyx.db.models import User
from onyx.prompts.user_info import BASIC_INFORMATION_PROMPT
from onyx.prompts.user_info import USER_MEMORIES_PROMPT
from onyx.prompts.user_info import USER_PREFERENCES_PROMPT
from onyx.prompts.user_info import USER_ROLE_PROMPT

MAX_MEMORIES_PER_USER = 10


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
    model_config = ConfigDict(frozen=True)

    user_id: UUID | None = None
    user_info: UserInfo
    user_preferences: str | None = None
    memories: tuple[str, ...] = ()

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

    def as_formatted_prompt(self) -> str:
        """Returns structured prompt sections for the system prompt."""
        has_basic_info = (
            self.user_info.name or self.user_info.email or self.user_info.role
        )
        if not has_basic_info and not self.user_preferences and not self.memories:
            return ""

        sections: list[str] = []

        if has_basic_info:
            role_line = (
                USER_ROLE_PROMPT.format(user_role=self.user_info.role).strip()
                if self.user_info.role
                else ""
            )
            if role_line:
                role_line = "\n" + role_line
            sections.append(
                BASIC_INFORMATION_PROMPT.format(
                    user_name=self.user_info.name or "",
                    user_email=self.user_info.email or "",
                    user_role=role_line,
                )
            )

        if self.user_preferences:
            sections.append(
                USER_PREFERENCES_PROMPT.format(user_preferences=self.user_preferences)
            )

        if self.memories:
            formatted_memories = "\n".join(f"- {memory}" for memory in self.memories)
            sections.append(
                USER_MEMORIES_PROMPT.format(user_memories=formatted_memories)
            )

        return "".join(sections)


def get_memories(user: User, db_session: Session) -> UserMemoryContext:
    user_info = UserInfo(
        name=user.personal_name,
        role=user.personal_role,
        email=user.email,
    )

    user_preferences = None
    if user.user_preferences:
        user_preferences = user.user_preferences

    memory_rows = db_session.scalars(
        select(Memory).where(Memory.user_id == user.id).order_by(Memory.id.asc())
    ).all()
    memories = tuple(memory.memory_text for memory in memory_rows if memory.memory_text)

    return UserMemoryContext(
        user_id=user.id,
        user_info=user_info,
        user_preferences=user_preferences,
        memories=memories,
    )


def add_memory(
    user_id: UUID,
    memory_text: str,
    db_session: Session,
) -> Memory:
    """Insert a new Memory row for the given user.

    If the user already has MAX_MEMORIES_PER_USER memories, the oldest
    one (lowest id) is deleted before inserting the new one.
    """
    existing = db_session.scalars(
        select(Memory).where(Memory.user_id == user_id).order_by(Memory.id.asc())
    ).all()

    if len(existing) >= MAX_MEMORIES_PER_USER:
        db_session.delete(existing[0])

    memory = Memory(
        user_id=user_id,
        memory_text=memory_text,
    )
    db_session.add(memory)
    db_session.commit()
    return memory


def update_memory_at_index(
    user_id: UUID,
    index: int,
    new_text: str,
    db_session: Session,
) -> Memory | None:
    """Update the memory at the given 0-based index (ordered by id ASC, matching get_memories()).

    Returns the updated Memory row, or None if the index is out of range.
    """
    memory_rows = db_session.scalars(
        select(Memory).where(Memory.user_id == user_id).order_by(Memory.id.asc())
    ).all()

    if index < 0 or index >= len(memory_rows):
        return None

    memory = memory_rows[index]
    memory.memory_text = new_text
    db_session.commit()
    return memory
