from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.auth.login_claims_capture import get_idp_profile
from onyx.context.models import UserInfo, UserMemoryContext
from onyx.db.engine.sql_engine import get_session_with_current_tenant_if_none
from onyx.db.enums import SupportedLanguage
from onyx.db.models import Memory, User
from onyx.server.settings.store import resolve_user_language
from onyx.utils.logger import setup_logger

logger = setup_logger()

MAX_MEMORIES_PER_USER = 10


def supported_language_or_none(code: str | None) -> SupportedLanguage | None:
    """User.language and Settings.default_language are both written through
    the enum, so any other value is stale or corrupt data. It is logged and
    dropped rather than allowed to break chat."""
    if not code:
        return None
    try:
        return SupportedLanguage(code)
    except ValueError:
        logger.warning("Unknown user language %r, omitting the language hint", code)
        return None


def get_memories(user: User, db_session: Session) -> UserMemoryContext:
    # `{{user.<key>}}` placeholder values: IdP directory profile plus basic
    # identity. Identity keys use setdefault so a directory field never gets
    # clobbered (they don't overlap today, but keeps precedence explicit).
    profile_views = get_idp_profile(user.email)
    placeholder_values = profile_views.placeholders
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
        organization_profile=profile_views.fields,
        placeholder_values=placeholder_values,
        language=supported_language_or_none(resolve_user_language(user.language)),
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
