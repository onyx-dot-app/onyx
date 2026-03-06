"""
Tests that the default model cannot be removed or hidden via provider upsert.

When a model is set as the default (for any flow type), attempts to remove it
from the provider's model list or set its visibility to False should raise a
ValueError (which the API layer converts to OnyxError VALIDATION_ERROR).
"""

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import update_default_vision_provider
from onyx.db.llm import upsert_llm_provider
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest


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
def provider_name() -> Generator[str, None, None]:
    """Generate a unique provider name for each test."""
    yield f"test-provider-{uuid4().hex[:8]}"


class TestDefaultModelProtection:
    """Tests that the default model cannot be removed or hidden."""

    def test_cannot_remove_default_text_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing the default text model from a provider should raise ValueError."""
        try:
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
        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_cannot_hide_default_text_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Setting is_visible=False on the default text model should raise ValueError."""
        try:
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
        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_cannot_remove_default_vision_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing the default vision model from a provider should raise ValueError."""
        try:
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
        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_can_remove_non_default_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Removing a non-default model should succeed."""
        try:
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
        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_can_hide_non_default_model(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """Hiding a non-default model should succeed."""
        try:
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
        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)
