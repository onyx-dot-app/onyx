"""Covers the Craft default model, which the CRAFT model role holds."""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import ModelRole
from onyx.db.llm import (
    clear_role,
    fetch_existing_llm_provider,
    fetch_role_model,
    remove_llm_provider,
    set_role_model,
    upsert_llm_provider,
)
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    LLMProviderView,
    ModelConfigurationUpsertRequest,
)


def _create_test_provider(db_session: Session, name: str) -> LLMProviderView:
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-6-sol", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-6-luna", is_visible=False),
            ],
        ),
        db_session=db_session,
    )


@pytest.fixture
def provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"test-provider-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    clear_role(db_session, ModelRole.CRAFT)
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


class TestDefaultCraftModel:
    def test_sets_the_craft_default(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)

        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        default = fetch_role_model(db_session, ModelRole.CRAFT)
        assert default is not None
        assert default.name == "gpt-6-sol"
        assert default.llm_provider_id == provider.id

    def test_replacing_the_default_leaves_exactly_one(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)

        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-luna",
        )

        default = fetch_role_model(db_session, ModelRole.CRAFT)
        assert default is not None
        assert default.name == "gpt-6-luna"

    def test_clearing_the_default_leaves_none(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        set_role_model(
            db_session=db_session,
            role=ModelRole.CRAFT,
            provider_id=provider.id,
            model_name="gpt-6-sol",
        )

        clear_role(db_session, ModelRole.CRAFT)

        assert fetch_role_model(db_session, ModelRole.CRAFT) is None

    def test_rejects_a_model_the_provider_does_not_have(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)

        with pytest.raises(ValueError, match="is not a valid model"):
            set_role_model(
                db_session=db_session,
                role=ModelRole.CRAFT,
                provider_id=provider.id,
                model_name="not-a-real-model",
            )
