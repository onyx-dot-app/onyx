"""
This should act as the main point of reference for testing that default model
logic is consisten.

 -
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import (
    fetch_default_contextual_rag_model,
    fetch_default_craft_model,
    fetch_existing_llm_provider,
    remove_llm_provider,
    update_default_contextual_model,
    update_default_craft_provider,
    update_default_provider,
    update_default_vision_provider,
    upsert_llm_provider,
)
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    LLMProviderView,
    ModelConfigurationUpsertRequest,
)


def _create_test_provider(
    db_session: Session,
    name: str,
    models: list[ModelConfigurationUpsertRequest] | None = None,
) -> LLMProviderView:
    """Helper to create a test LLM provider with multiple models."""
    if models is None:
        models = [
            ModelConfigurationUpsertRequest(
                name="gpt-4o", is_visible=True, supports_image_input=True
            ),
            ModelConfigurationUpsertRequest(
                name="gpt-4o-mini", is_visible=True, supports_image_input=False
            ),
        ]
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            model_configurations=models,
        ),
        db_session=db_session,
    )


def _cleanup_provider(db_session: Session, name: str) -> None:
    """Helper to clean up a test provider by name."""
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


@pytest.fixture
def provider_name(db_session: Session) -> Generator[str, None, None]:
    """Generate a unique provider name for each test, with automatic cleanup."""
    name = f"test-provider-{uuid4().hex[:8]}"
    yield name
    db_session.rollback()
    _cleanup_provider(db_session, name)


class TestDefaultModelProtection:
    """Tests that the default model cannot be removed or hidden."""

    def test_cannot_remove_default_text_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing the default text model from a provider should raise ValueError."""
        provider = _create_test_provider(db_session, provider_name)
        update_default_provider(provider.id, "gpt-4o", db_session)

        # Try to update the provider without the default model
        with pytest.raises(ValueError, match="Cannot remove the default model"):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

    def test_cannot_hide_default_text_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Setting is_visible=False on the default text model should raise ValueError."""
        provider = _create_test_provider(db_session, provider_name)
        update_default_provider(provider.id, "gpt-4o", db_session)

        # Try to hide the default model
        with pytest.raises(ValueError, match="Cannot hide the default model"):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o", is_visible=False
                        ),
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

    def test_cannot_remove_default_vision_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing the default vision model from a provider should raise ValueError."""
        provider = _create_test_provider(db_session, provider_name)
        # Set gpt-4o as both the text and vision default
        update_default_provider(provider.id, "gpt-4o", db_session)
        update_default_vision_provider(provider.id, "gpt-4o", db_session)

        # Try to remove the default vision model
        with pytest.raises(ValueError, match="Cannot remove the default model"):
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

    def test_can_remove_non_default_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing a non-default model should succeed."""
        provider = _create_test_provider(db_session, provider_name)
        update_default_provider(provider.id, "gpt-4o", db_session)

        # Remove gpt-4o-mini (not default) — should succeed
        updated = upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o", is_visible=True, supports_image_input=True
                    ),
                ],
            ),
            db_session=db_session,
        )

        model_names = {mc.name for mc in updated.model_configurations}
        assert "gpt-4o" in model_names
        assert "gpt-4o-mini" not in model_names

    def test_can_hide_non_default_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Hiding a non-default model should succeed."""
        provider = _create_test_provider(db_session, provider_name)
        update_default_provider(provider.id, "gpt-4o", db_session)

        # Hide gpt-4o-mini (not default) — should succeed
        updated = upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider.id,
                name=provider_name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o", is_visible=True, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o-mini", is_visible=False
                    ),
                ],
            ),
            db_session=db_session,
        )

        model_visibility = {
            mc.name: mc.is_visible for mc in updated.model_configurations
        }
        assert model_visibility["gpt-4o"] is True
        assert model_visibility["gpt-4o-mini"] is False


class TestPointerFlowDefaultsSurviveAProviderUpdate:
    """CONTEXTUAL_RAG, CHAT_NAMING and CRAFT are pointer flows: each is set by
    its own endpoint and implied by no supports_* field, so none is ever in
    supported_flows. Reconciling against that list deleted the row, and the
    default it carries went with it.
    """

    def _update_provider(
        self, db_session: Session, provider_id: int, name: str
    ) -> None:
        """An ordinary edit that names no pointer flow, as the admin UI sends."""
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider_id,
                name=name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o", is_visible=True, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o-mini", is_visible=True, supports_image_input=False
                    ),
                ],
            ),
            db_session=db_session,
        )

    def test_craft_default_survives(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        update_default_craft_provider(provider.id, "gpt-4o-mini", db_session)
        assert fetch_default_craft_model(db_session) is not None

        self._update_provider(db_session, provider.id, provider_name)

        default_craft = fetch_default_craft_model(db_session)
        assert default_craft is not None
        assert default_craft.name == "gpt-4o-mini"

    def test_contextual_rag_default_survives(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        model_config = next(
            mc for mc in provider.model_configurations if mc.name == "gpt-4o-mini"
        )
        update_default_contextual_model(
            db_session=db_session,
            enable_contextual_rag=True,
            model_configuration_id=model_config.id,
        )
        db_session.commit()
        assert fetch_default_contextual_rag_model(db_session) is not None

        self._update_provider(db_session, provider.id, provider_name)

        default_contextual = fetch_default_contextual_rag_model(db_session)
        assert default_contextual is not None
        assert default_contextual.name == "gpt-4o-mini"

    def _hide_mini(self, db_session: Session, provider_id: int, name: str) -> None:
        upsert_llm_provider(
            LLMProviderUpsertRequest(
                id=provider_id,
                name=name,
                provider=LlmProviderNames.OPENAI,
                api_key="sk-test-key-00000000000000000000000000000000000",
                api_key_changed=True,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o", is_visible=True, supports_image_input=True
                    ),
                    ModelConfigurationUpsertRequest(
                        name="gpt-4o-mini", is_visible=False, supports_image_input=False
                    ),
                ],
            ),
            db_session=db_session,
        )

    def test_hiding_the_craft_default_is_refused(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Keeping the row means the model under it must stay visible. Neither
        resolver checks is_visible, so a hidden default would still be used."""
        provider = _create_test_provider(db_session, provider_name)
        update_default_craft_provider(provider.id, "gpt-4o-mini", db_session)

        with pytest.raises(ValueError, match="Cannot hide the default model"):
            self._hide_mini(db_session, provider.id, provider_name)

    def test_hiding_the_contextual_rag_default_is_refused(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        provider = _create_test_provider(db_session, provider_name)
        model_config = next(
            mc for mc in provider.model_configurations if mc.name == "gpt-4o-mini"
        )
        update_default_contextual_model(
            db_session=db_session,
            enable_contextual_rag=True,
            model_configuration_id=model_config.id,
        )
        db_session.commit()

        with pytest.raises(ValueError, match="Cannot hide the default model"):
            self._hide_mini(db_session, provider.id, provider_name)
