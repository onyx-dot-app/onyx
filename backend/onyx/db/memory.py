from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.login_claims_capture import (
    get_idp_profile_fields,
    get_idp_profile_placeholder_values,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant_if_none
from onyx.db.models import Memory, User

MAX_MEMORIES_PER_USER = 10


class UserInfo(BaseModel):
    name: str | None = None
    role: str | None = None
    email: str | None = None
    # Directory profile from the IdP login snapshot (country, department, ...)
    # as ordered {label: value} pairs. Fork feature: lets the model give
    # location/role-aware answers (e.g. country-specific HR policies).
    organization_profile: dict[str, str] = Field(default_factory=dict)
    # Same directory profile plus basic identity, keyed by snake_case
    # `{{user.<key>}}` placeholder key (e.g. department/job_title/city/email),
    # for author-controlled placeholder substitution in agent prompts.
    placeholder_values: dict[str, str] = Field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "role": self.role,
            "email": self.email,
            "organization_profile": self.organization_profile,
            "placeholder_values": self.placeholder_values,
        }


class UserMemoryContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    user_id: UUID | None = None
    user_info: UserInfo
    user_preferences: str | None = None
    memories: tuple[str, ...] = ()

    def without_memories(self) -> "UserMemoryContext":
        """Return a copy with memories cleared but user info/preferences intact."""
        return UserMemoryContext(
            user_id=self.user_id,
            user_info=self.user_info,
            user_preferences=self.user_preferences,
            memories=(),
        )

    def as_formatted_list(self) -> list[str]:
        """Returns combined list of user info, preferences, and memories."""
        result = []
        if self.user_info.name:
            result.append(f"User's name: {self.user_info.name}")
        if self.user_info.role:
            result.append(f"User's role: {self.user_info.role}")
        if self.user_info.email:
            result.append(f"User's email: {self.user_info.email}")
        for label, value in self.user_info.organization_profile.items():
            result.append(f"User's {label.lower()}: {value}")
        if self.user_preferences:
            result.append(f"User preferences: {self.user_preferences}")
        result.extend(self.memories)
        return result


def get_memories(user: User, db_session: Session) -> UserMemoryContext:
    # `{{user.<key>}}` placeholder values: IdP directory profile plus basic
    # identity. Identity keys use setdefault so a directory field never gets
    # clobbered (they don't overlap today, but keeps precedence explicit).
    placeholder_values = get_idp_profile_placeholder_values(user.email)
    if user.email:
        placeholder_values.setdefault("email", user.email)
    if user.personal_name:
        placeholder_values.setdefault("name", user.personal_name)
    if user.personal_role:
        placeholder_values.setdefault("role", user.personal_role)

    user_info = UserInfo(
        name=user.personal_name,
        role=user.personal_role,
        email=user.email,
        organization_profile=get_idp_profile_fields(user.email),
        placeholder_values=placeholder_values,
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
    db_session: Session | None = None,
) -> int:
    """Insert a new Memory row for the given user.

    If the user already has MAX_MEMORIES_PER_USER memories, the oldest
    one (lowest id) is deleted before inserting the new one.

    Returns the id of the newly created Memory row.
    """
    with get_session_with_current_tenant_if_none(db_session) as db_session:
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
        return memory.id


def update_memory_at_index(
    user_id: UUID,
    index: int,
    new_text: str,
    db_session: Session | None = None,
) -> int | None:
    """Update the memory at the given 0-based index (ordered by id ASC, matching get_memories()).

    Returns the id of the updated Memory row, or None if the index is out of range.
    """
    with get_session_with_current_tenant_if_none(db_session) as db_session:
        memory_rows = db_session.scalars(
            select(Memory).where(Memory.user_id == user_id).order_by(Memory.id.asc())
        ).all()

        if index < 0 or index >= len(memory_rows):
            return None

        memory = memory_rows[index]
        memory.memory_text = new_text
        db_session.commit()
        return memory.id
