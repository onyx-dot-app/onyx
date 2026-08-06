"""LLM provider catalogs include providers usable through an accessible agent."""

from uuid import uuid4

from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_all_llm_providers_accessible_in_any_context,
    remove_llm_provider,
    upsert_llm_provider,
)
from onyx.db.models import User
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.agent_sharing_helpers import create_test_persona


def _provider_ids_accessible_in_any_context(
    db_session: Session, user: User
) -> set[int]:
    return {
        provider.id
        for provider in fetch_all_llm_providers_accessible_in_any_context(
            db_session, user
        )
    }


def test_persona_restricted_provider_requires_persona_access(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    persona_owner = make_user(db_session)
    other_user = make_user(db_session)
    persona = create_test_persona(db_session, owner=persona_owner)
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"any-context-{uuid4().hex[:8]}",
            provider="anthropic",
            api_key="sk-ant-not-used",
            api_key_changed=True,
            is_public=False,
            personas=[persona.id],
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name="claude-haiku-4-5", is_visible=True
                )
            ],
        ),
        db_session,
    )
    db_session.commit()

    try:
        assert provider.id in _provider_ids_accessible_in_any_context(
            db_session, persona_owner
        )
        assert provider.id not in _provider_ids_accessible_in_any_context(
            db_session, other_user
        )
    finally:
        remove_llm_provider(db_session, provider.id)
        db_session.delete(persona)
        db_session.commit()
