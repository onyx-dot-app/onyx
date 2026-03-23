from sqlalchemy import inspect
from sqlalchemy.orm import Session

from onyx.db.chat import create_chat_session
from onyx.db.chat import get_chat_session_by_id
from onyx.db.models import Persona


def test_eager_load_persona_loads_relationships(db_session: Session) -> None:
    """Verify that eager_load_persona pre-loads persona, its collections, and project."""
    persona = Persona(name="eager-load-test", description="test")
    db_session.add(persona)
    db_session.flush()

    chat_session = create_chat_session(
        db_session=db_session,
        description="test",
        user_id=None,
        persona_id=persona.id,
    )

    loaded = get_chat_session_by_id(
        chat_session_id=chat_session.id,
        user_id=None,
        db_session=db_session,
        eager_load_persona=True,
    )

    unloaded = inspect(loaded).unloaded
    assert "persona" not in unloaded
    assert "project" not in unloaded

    persona_unloaded = inspect(loaded.persona).unloaded
    assert "tools" not in persona_unloaded
    assert "user_files" not in persona_unloaded

    db_session.rollback()
