"""Read routes reached by basic users must not change shared state."""

from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.llm import remove_llm_provider, upsert_llm_provider
from onyx.db.models import Persona
from onyx.llm.constants import LlmProviderNames
from onyx.server.features.persona.api import get_persona
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.external_dependency_unit.conftest import create_test_user, delete_test_user


def test_viewer_outside_provider_group_keeps_agent_model_pin(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    owner = create_test_user(db_session, "pin_owner", is_admin=True)
    viewer = create_test_user(db_session, "pin_viewer")
    provider = upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=f"restricted-{uuid4().hex[:8]}",
            provider=LlmProviderNames.OPENAI,
            api_key="sk-test-00000000000000000000000000000000000000",
            api_key_changed=True,
            is_public=False,
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-6-luna", is_visible=True)
            ],
        ),
        db_session=db_session,
    )
    pinned_id = provider.model_configurations[0].id
    assert pinned_id is not None
    persona = Persona(
        name=f"pinned-{uuid4().hex[:8]}",
        description="pinned model",
        user_id=owner.id,
        is_public=True,
        default_model_configuration_id=pinned_id,
    )
    db_session.add(persona)
    db_session.commit()

    try:
        snapshot = get_persona(persona.id, viewer, db_session)

        # The viewer cannot use the model, so the response hides it.
        assert snapshot.default_model_configuration_id is None
        db_session.expire_all()
        stored = db_session.get(Persona, persona.id)
        assert stored is not None
        assert stored.default_model_configuration_id == pinned_id
        assert (
            get_persona(persona.id, owner, db_session).default_model_configuration_id
            == pinned_id
        )
    finally:
        db_session.rollback()
        db_session.execute(delete(Persona).where(Persona.id == persona.id))
        db_session.commit()
        remove_llm_provider(db_session, provider.id)
        delete_test_user(db_session, owner, viewer)
        db_session.commit()
