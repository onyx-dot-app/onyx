from sqlalchemy import inspect
from sqlalchemy.orm import Session

from onyx.db.chat import create_chat_session
from onyx.db.chat import get_chat_session_by_id
from onyx.db.models import Persona
from onyx.db.models import UserProject
from tests.external_dependency_unit.conftest import create_test_user


def test_eager_load_persona_loads_relationships(db_session: Session) -> None:
    """Verify that eager_load_persona pre-loads persona, its collections, and project."""
    user = create_test_user(db_session, "eager-load")
    persona = Persona(name="eager-load-test", description="test")
    project = UserProject(name="eager-load-project", user_id=user.id)
    db_session.add_all([persona, project])
    db_session.flush()

    chat_session = create_chat_session(
        db_session=db_session,
        description="test",
        user_id=None,
        persona_id=persona.id,
        project_id=project.id,
    )

    loaded = get_chat_session_by_id(
        chat_session_id=chat_session.id,
        user_id=None,
        db_session=db_session,
        eager_load_persona=True,
    )

    try:
        tmp = inspect(loaded)
        assert tmp is not None
        unloaded = tmp.unloaded
        assert "persona" not in unloaded
        assert "project" not in unloaded

        tmp = inspect(loaded.persona)
        assert tmp is not None
        persona_unloaded = tmp.unloaded
        assert "tools" not in persona_unloaded
        assert "user_files" not in persona_unloaded
        assert "document_sets" not in persona_unloaded
        assert "attached_documents" not in persona_unloaded
        assert "hierarchy_nodes" not in persona_unloaded
    finally:
        db_session.rollback()
