"""
Integration tests for the Update Recommended Selected Models task.

These tests verify the functionality of the update_recommended_selected_models
Celery task which updates LLM model visibility, default model, and fast default model
settings based on recommended configurations.

To run these tests:
    cd backend
    pytest tests/integration/tests/update_recommended_selected_models/test_update_recommended_selected_models.py -v

Prerequisites:
    - PostgreSQL database running
    - Proper environment variables set for database connection
"""

import uuid
from unittest.mock import Mock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.update_recommended_selected_models.tasks import (
    update_recommended_selected_models,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

# Test constants
TEST_TENANT_ID = "test-tenant-id"


@pytest.fixture(scope="function")
def db_session() -> Session:
    """Create a database session for testing"""
    with get_session_with_current_tenant() as session:
        yield session


@pytest.fixture(scope="function")
def tenant_context():
    """Set up tenant context for testing"""
    token = CURRENT_TENANT_ID_CONTEXTVAR.set(TEST_TENANT_ID)
    try:
        yield
    finally:
        CURRENT_TENANT_ID_CONTEXTVAR.reset(token)


def _create_test_llm_provider(
    db_session: Session,
    provider_name: str,
    provider_type: str,
    use_recommended_models: bool = True,
    default_model_name: str = "default-model",
    fast_default_model_name: str = "fast-default-model",
) -> LLMProvider:
    """Helper to create a test LLM provider"""
    # Try to find an existing provider first to avoid constraint violations
    existing_provider = (
        db_session.query(LLMProvider).filter(LLMProvider.name == provider_name).first()
    )

    if existing_provider:
        # Update existing provider
        existing_provider.use_recommended_models = use_recommended_models
        existing_provider.default_model_name = default_model_name
        existing_provider.fast_default_model_name = fast_default_model_name
        db_session.commit()
        db_session.refresh(existing_provider)
        return existing_provider

    # Create new provider
    llm_provider = LLMProvider(
        name=provider_name,
        provider=provider_type,
        default_model_name=default_model_name,
        fast_default_model_name=fast_default_model_name,
        is_default_provider=False,
        is_public=True,
        use_recommended_models=use_recommended_models,
    )

    try:
        db_session.add(llm_provider)
        db_session.commit()
        db_session.refresh(llm_provider)
        return llm_provider
    except Exception:
        # If we get a constraint error, try to find and return the existing one
        db_session.rollback()
        existing_provider = (
            db_session.query(LLMProvider)
            .filter(LLMProvider.name == provider_name)
            .first()
        )
        if existing_provider:
            return existing_provider
        raise


def _create_test_model_configuration(
    db_session: Session,
    llm_provider: LLMProvider,
    model_name: str,
    is_visible: bool = True,
    recommended_default: bool = False,
    recommended_fast_default: bool = False,
    recommended_is_visible: bool | None = None,
) -> ModelConfiguration:
    """Helper to create a test model configuration"""
    # Try to find existing model configuration first
    existing_config = (
        db_session.query(ModelConfiguration)
        .filter(
            ModelConfiguration.llm_provider_id == llm_provider.id,
            ModelConfiguration.name == model_name,
        )
        .first()
    )

    if existing_config:
        # Update existing configuration
        existing_config.is_visible = is_visible
        existing_config.recommended_default = recommended_default
        existing_config.recommended_fast_default = recommended_fast_default
        existing_config.recommended_is_visible = recommended_is_visible
        db_session.commit()
        db_session.refresh(existing_config)
        return existing_config

    # Create new configuration
    model_config = ModelConfiguration(
        llm_provider_id=llm_provider.id,
        name=model_name,
        is_visible=is_visible,
        recommended_default=recommended_default,
        recommended_fast_default=recommended_fast_default,
        recommended_is_visible=recommended_is_visible,
    )
    db_session.add(model_config)
    db_session.commit()
    db_session.refresh(model_config)
    return model_config


class TestUpdateRecommendedSelectedModels:
    """Test class for update recommended selected models task"""

    def test_updates_visibility_based_on_recommended_is_visible(
        self, db_session: Session, tenant_context
    ) -> None:
        """Test that model visibility is updated based on recommended_is_visible"""
        # Create unique provider name for this test
        provider_name = f"Test Provider Visibility {uuid.uuid4().hex[:8]}"

        # Create test LLM provider
        llm_provider = _create_test_llm_provider(
            db_session, provider_name, "openai", use_recommended_models=True
        )

        # Create model with is_visible=True but recommended_is_visible=False
        model_config = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-4",
            is_visible=True,
            recommended_is_visible=False,
        )

        # Run the task
        result = update_recommended_selected_models(Mock(), tenant_id=TEST_TENANT_ID)

        # Verify task completed successfully
        assert result is True

        # Refresh the model from database
        db_session.refresh(model_config)

        # Verify visibility was updated
        assert model_config.is_visible is False

    def test_updates_default_model_name_based_on_recommended_default(
        self, db_session: Session, tenant_context
    ) -> None:
        """Test that provider default_model_name is updated based on recommended_default"""
        # Create unique provider name for this test
        provider_name = f"Test Provider Default {uuid.uuid4().hex[:8]}"

        # Create test LLM provider
        llm_provider = _create_test_llm_provider(
            db_session,
            provider_name,
            "openai",
            use_recommended_models=True,
            default_model_name="old-default-model",
        )

        # Create model with recommended_default=True
        _ = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-4",
            recommended_default=True,
        )

        # Run the task
        result = update_recommended_selected_models(Mock(), tenant_id=TEST_TENANT_ID)

        # Verify task completed successfully
        assert result is True

        # Refresh the provider from database
        db_session.refresh(llm_provider)

        # Verify default_model_name was updated
        assert llm_provider.default_model_name == "gpt-4"

    def test_skips_providers_without_use_recommended_models(
        self, db_session: Session, tenant_context
    ) -> None:
        """Test that providers without use_recommended_models=True are skipped"""
        # Create unique provider name for this test
        provider_name = f"Test Provider Skip {uuid.uuid4().hex[:8]}"

        # Create test LLM provider with use_recommended_models=False
        llm_provider = _create_test_llm_provider(
            db_session,
            provider_name,
            "openai",
            use_recommended_models=False,
            default_model_name="old-default-model",
        )

        # Create model with recommended_default=True
        model_config = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-4",
            is_visible=True,
            recommended_default=True,
            recommended_is_visible=False,
        )

        # Run the task
        result = update_recommended_selected_models(Mock(), tenant_id=TEST_TENANT_ID)

        # Verify task completed successfully
        assert result is True

        # Refresh the provider and model from database
        db_session.refresh(llm_provider)
        db_session.refresh(model_config)

        # Verify nothing was updated (provider was skipped)
        assert llm_provider.default_model_name == "old-default-model"
        assert model_config.is_visible is True

    def test_handles_exception_gracefully(
        self, db_session: Session, tenant_context
    ) -> None:
        """Test that the task handles exceptions gracefully"""
        # Create unique provider name for this test
        provider_name = f"Test Provider Exception {uuid.uuid4().hex[:8]}"

        # Create test LLM provider
        _create_test_llm_provider(
            db_session, provider_name, "openai", use_recommended_models=True
        )

        # Mock get_session_with_current_tenant to raise an exception
        with patch(
            "onyx.background.celery.tasks.update_recommended_selected_models.tasks.get_session_with_current_tenant"
        ) as mock_get_session:
            mock_get_session.side_effect = Exception("Database connection failed")

            # Run the task
            result = update_recommended_selected_models(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task returned None (indicating failure)
            assert result is None
