"""Covers the Craft default model, whose flow rows no provider upsert creates.

CHAT / VISION / REASONING rows are written during upsert from the model's
capabilities. CRAFT is a pointer, not a capability, so setting the Craft
default has to create its own flow row first.
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_default_craft_model,
    fetch_existing_llm_provider,
    remove_llm_provider,
    update_default_craft_provider,
    update_no_default_craft_provider,
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
                ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
                ModelConfigurationUpsertRequest(name="gpt-4o-mini", is_visible=False),
            ],
        ),
        db_session=db_session,
    )


@pytest.fixture
def provider_name(db_session: Session) -> Generator[str, None, None]:
    name = f"test-provider-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    update_no_default_craft_provider(db_session)
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


class TestDefaultCraftModel:
    def test_sets_default_on_a_model_with_no_craft_flow_row(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """The regression: nothing seeds CRAFT rows, so this used to raise."""
        provider = _create_test_provider(db_session, provider_name)

        update_default_craft_provider(provider.id, "gpt-4o", db_session)

        default = fetch_default_craft_model(db_session)
        assert default is not None
        assert default.name == "gpt-4o"
        assert default.llm_provider_id == provider.id

    def test_replacing_the_default_leaves_exactly_one(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)

        update_default_craft_provider(provider.id, "gpt-4o", db_session)
        update_default_craft_provider(provider.id, "gpt-4o-mini", db_session)

        default = fetch_default_craft_model(db_session)
        assert default is not None
        assert default.name == "gpt-4o-mini"

    def test_clearing_the_default_leaves_none(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        update_default_craft_provider(provider.id, "gpt-4o", db_session)

        update_no_default_craft_provider(db_session)

        assert fetch_default_craft_model(db_session) is None

    def test_rejects_a_model_the_provider_does_not_have(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)

        with pytest.raises(ValueError, match="is not a valid model"):
            update_default_craft_provider(provider.id, "not-a-real-model", db_session)
