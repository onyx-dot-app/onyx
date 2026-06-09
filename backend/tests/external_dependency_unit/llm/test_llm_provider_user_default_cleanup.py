"""
Tests that deleting an LLM provider clears personal default models
(User.default_model) referencing it, so users fall back to the global
default instead of a dangling provider reference.
"""

from uuid import uuid4

from sqlalchemy import delete
from sqlalchemy.orm import Session

from onyx.db.llm import remove_llm_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import User
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_provider(db_session: Session, name: str) -> LLMProviderView:
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-4o-mini", is_visible=True)
            ],
        ),
        db_session=db_session,
    )


def test_remove_llm_provider_clears_matching_user_defaults(
    db_session: Session,
) -> None:
    provider_to_delete = _create_test_provider(
        db_session, f"test-provider-{uuid4().hex[:8]}"
    )
    provider_to_keep = _create_test_provider(
        db_session, f"test-provider-{uuid4().hex[:8]}"
    )

    affected_user = create_test_user(db_session, "default_model_cleared")
    unaffected_user = create_test_user(db_session, "default_model_kept")

    kept_default = f"{provider_to_keep.name}__openai__gpt-4o-mini"
    affected_user.default_model = f"{provider_to_delete.name}__openai__gpt-4o-mini"
    unaffected_user.default_model = kept_default
    db_session.commit()

    try:
        remove_llm_provider(db_session, provider_to_delete.id)

        db_session.refresh(affected_user)
        db_session.refresh(unaffected_user)

        assert affected_user.default_model is None
        assert unaffected_user.default_model == kept_default
    finally:
        remove_llm_provider(db_session, provider_to_keep.id)
        # Bulk delete to avoid loading the users' relationship graph
        db_session.execute(
            delete(User).where(User.id.in_([affected_user.id, unaffected_user.id]))
        )
        db_session.commit()
