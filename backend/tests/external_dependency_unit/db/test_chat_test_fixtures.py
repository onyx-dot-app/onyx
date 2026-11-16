"""Chat test fixtures release owned rows without changing unrelated state."""

from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import fetch_default_model, update_default_model
from onyx.db.models import (
    ChatSession,
    DocumentSet,
    LLMModelFlow,
    LLMProvider,
    MCPServer,
    MCPServer__UserGroup,
    Persona,
    Persona__DocumentSet,
    Persona__PersonaLabel,
    Persona__User,
    Persona__UserGroup,
    PersonaLabel,
    Project__UserFile,
    User,
    UserFile,
    UserGroup,
    UserProject,
)
from tests.external_dependency_unit import conftest
from tests.external_dependency_unit.conftest import (
    MakeTestUser,
    create_processing_user_file,
    delete_test_users_and_owned_rows,
    temporary_default_llm_provider,
)


def test_user_cleanup_preserves_shared_personas_and_their_chats(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("fixture_owner")
    visitor = make_test_user("fixture_visitor")
    owned = Persona(name="Owned test agent", description="", user_id=visitor.id)
    shared = Persona(name="Shared test agent", description="", user_id=owner.id)
    db_session.add_all([owned, shared])
    db_session.flush()
    db_session.add(Persona__User(persona_id=shared.id, user_id=visitor.id))
    retained_chat = ChatSession(user_id=owner.id, persona_id=shared.id)
    removed_chat = ChatSession(user_id=visitor.id, persona_id=shared.id)
    detached_chat = ChatSession(user_id=owner.id, persona_id=owned.id)
    db_session.add_all([retained_chat, removed_chat, detached_chat])
    db_session.commit()
    visitor_id, email = visitor.id, visitor.email
    owned_id, shared_id = owned.id, shared.id
    retained_id, removed_id = retained_chat.id, removed_chat.id
    detached_id = detached_chat.id

    delete_test_users_and_owned_rows(db_session, [visitor_id], [email])

    assert db_session.get(User, visitor_id) is None
    assert db_session.get(Persona, owned_id) is None
    assert db_session.get(ChatSession, removed_id) is None
    assert db_session.get(Persona, shared_id) is not None
    assert db_session.get(ChatSession, retained_id) is not None
    detached = db_session.get(ChatSession, detached_id)
    assert detached is not None and detached.persona_id is None
    assert (
        db_session.scalar(
            select(Persona__User).where(Persona__User.user_id == visitor_id)
        )
        is None
    )


@pytest.mark.parametrize("has_default", [False, True])
def test_temporary_provider_restores_default_after_failure(
    db_session: Session, has_default: bool
) -> None:
    # The outer scope also restores whatever default existed before this test.
    with temporary_default_llm_provider(db_session):
        original = fetch_default_model(db_session, LLMModelFlowType.CHAT)
        assert original is not None
        original_id = original.id
        provider_id = original.llm_provider_id
        provider_name = original.llm_provider.name
        if not has_default:
            db_session.execute(
                update(LLMModelFlow)
                .where(LLMModelFlow.llm_model_flow_type == LLMModelFlowType.CHAT)
                .values(is_default=False)
            )
            db_session.commit()
        try:
            with pytest.raises(RuntimeError, match="test failed"):
                with temporary_default_llm_provider(db_session):
                    current = fetch_default_model(db_session, LLMModelFlowType.CHAT)
                    assert current is not None
                    temporary_id = current.llm_provider_id
                    assert temporary_id != provider_id
                    raise RuntimeError("test failed")

            restored = fetch_default_model(db_session, LLMModelFlowType.CHAT)
            assert (restored.id if restored is not None else None) == (
                original_id if has_default else None
            )
            assert db_session.get(LLMProvider, temporary_id) is None
            kept = db_session.get(LLMProvider, provider_id)
            assert kept is not None and kept.name == provider_name
        finally:
            update_default_model(
                db_session, provider_id, original.name, LLMModelFlowType.CHAT
            )


def test_user_cleanup_removes_persona_links(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    user = make_test_user("linked_agent_owner")
    persona = Persona(name="Linked agent", description="", user_id=user.id)
    suffix = uuid4().hex
    document_set = DocumentSet(name=f"fixture-docs-{suffix}")
    group = UserGroup(name=f"fixture-group-{suffix}")
    label = PersonaLabel(name=f"fixture-label-{suffix}")
    server = MCPServer(
        owner=user.email, name="Fixture server", server_url="https://example.com/mcp"
    )
    db_session.add_all([persona, document_set, group, label, server])
    db_session.flush()
    db_session.add_all(
        [
            MCPServer__UserGroup(mcp_server_id=server.id, user_group_id=group.id),
            Persona__DocumentSet(
                persona_id=persona.id, document_set_id=document_set.id
            ),
            Persona__UserGroup(persona_id=persona.id, user_group_id=group.id),
            Persona__PersonaLabel(persona_id=persona.id, persona_label_id=label.id),
        ]
    )
    db_session.commit()
    persona_id, server_id = persona.id, server.id
    try:
        delete_test_users_and_owned_rows(db_session, [user.id], [user.email])
        assert db_session.get(Persona, persona_id) is None
        assert db_session.get(MCPServer, server_id) is None
        assert db_session.get(DocumentSet, document_set.id) is not None
        assert db_session.get(UserGroup, group.id) is not None
        assert db_session.get(PersonaLabel, label.id) is not None
    finally:
        db_session.rollback()
        for row in (document_set, group, label):
            db_session.delete(row)
        db_session.commit()


def test_temporary_provider_cleans_up_failed_setup(db_session: Session) -> None:
    original_setup = conftest.ensure_default_llm_provider
    with temporary_default_llm_provider(db_session):
        original = fetch_default_model(db_session, LLMModelFlowType.CHAT)
        assert original is not None
        original_id = original.id
        created_names: list[str] = []

        def fail_after_setup(session: Session, provider_name: str) -> None:
            created_names.append(provider_name)
            original_setup(session, provider_name)
            raise RuntimeError("setup failed")

        with patch.object(conftest, "ensure_default_llm_provider", fail_after_setup):
            with pytest.raises(RuntimeError, match="setup failed"):
                with temporary_default_llm_provider(db_session):
                    pytest.fail("setup must fail before yielding")

        restored = fetch_default_model(db_session, LLMModelFlowType.CHAT)
        assert restored is not None and restored.id == original_id
        assert (
            db_session.scalar(
                select(LLMProvider).where(LLMProvider.name.in_(created_names))
            )
            is None
        )


def test_user_cleanup_preserves_unrelated_project_resources(
    db_session: Session, make_test_user: MakeTestUser
) -> None:
    owner = make_test_user("project_owner")
    other = make_test_user("other_project_owner")
    owned_project = UserProject(user_id=owner.id, name="Owned", instructions="")
    kept_project = UserProject(user_id=other.id, name="Kept", instructions="")
    db_session.add_all([owned_project, kept_project])
    owned_file = create_processing_user_file(db_session, owner.id)
    kept_file = create_processing_user_file(db_session, other.id)
    db_session.add_all(
        [
            Project__UserFile(project_id=owned_project.id, user_file_id=kept_file.id),
            Project__UserFile(project_id=kept_project.id, user_file_id=owned_file.id),
            Project__UserFile(project_id=kept_project.id, user_file_id=kept_file.id),
        ]
    )
    kept_chat = ChatSession(user_id=other.id, project_id=owned_project.id)
    db_session.add(kept_chat)
    db_session.commit()
    owner_id, owner_email = owner.id, owner.email
    owned_project_id, owned_file_id = owned_project.id, owned_file.id
    kept_project_id, kept_file_id, kept_chat_id = (
        kept_project.id,
        kept_file.id,
        kept_chat.id,
    )

    delete_test_users_and_owned_rows(db_session, [owner_id], [owner_email])

    assert db_session.get(User, owner_id) is None
    assert db_session.get(UserProject, owned_project_id) is None
    assert db_session.get(UserFile, owned_file_id) is None
    assert db_session.get(UserProject, kept_project_id) is not None
    assert db_session.get(UserFile, kept_file_id) is not None
    retained = db_session.get(ChatSession, kept_chat_id)
    assert retained is not None and retained.project_id is None
    assert (
        db_session.get(Project__UserFile, (kept_project_id, kept_file_id)) is not None
    )
