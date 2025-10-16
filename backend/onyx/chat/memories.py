from collections.abc import Callable

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.models import Memory
from onyx.db.models import User


def make_memories_callback(
    user: User | None, db_session: Session
) -> Callable[[], list[str]]:
    def memories_callback() -> list[str]:
        if user is None:
            return []

        user_info = [
            f"User's name: {user.personal_name or ''}",
            f"User's role: {user.personal_role or ''}",
            f"User's email: {user.email}",
        ]

        memory_rows = db_session.scalars(
            select(Memory).where(Memory.user_id == user.id)
        ).all()
        memories = [memory.memory_text for memory in memory_rows]
        return user_info + memories

    return memories_callback
