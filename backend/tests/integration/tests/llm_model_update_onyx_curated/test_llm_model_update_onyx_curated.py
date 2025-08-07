"""
Integration tests for the LLM Model Update Onyx Curated task.
"""

from unittest.mock import Mock
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks import (
    _delete_deprecated_not_visible_models,
)
from onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks import (
    _sync_model_configurations_with_curated_models,
)
from onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks import (
    check_for_llm_model_update_onyx_curated,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import LLMProvider
from onyx.db.models import ModelConfiguration
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser

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


@pytest.fixture(scope="function")
def admin_user() -> DATestUser:
    """Create an admin user for testing"""
    return UserManager.create(name="admin_user")


def _create_test_llm_provider(
    db_session: Session, provider_name: str, provider_type: str
) -> LLMProvider:
    """Helper to create a test LLM provider"""
    llm_provider = LLMProvider(
        name=provider_name,
        provider=provider_type,
        default_model_name="test-model",
        is_default_provider=False,
        is_public=True,
    )
    db_session.add(llm_provider)
    db_session.commit()
    db_session.refresh(llm_provider)
    return llm_provider


def _create_test_model_configuration(
    db_session: Session,
    llm_provider: LLMProvider,
    model_name: str,
    is_visible: bool = True,
    recommended_default: bool = False,
    recommended_fast_default: bool = False,
    recommended_is_visible: bool = True,
) -> ModelConfiguration:
    """Helper to create a test model configuration"""
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


def _get_model_configurations_for_provider(
    db_session: Session, llm_provider: LLMProvider
) -> list[ModelConfiguration]:
    """Helper to get all model configurations for a provider"""
    return (
        db_session.query(ModelConfiguration)
        .filter(ModelConfiguration.llm_provider_id == llm_provider.id)
        .all()
    )


class TestLLMModelUpdateOnyxCurated:
    """Test class for LLM model update curated tasks"""

    def test_sync_adds_new_models_from_curated_list(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that new models from curated list are added to database"""
        # Create test LLM provider
        llm_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")

        # Verify no models exist initially
        initial_models = _get_model_configurations_for_provider(
            db_session, llm_provider
        )
        assert len(initial_models) == 0

        # Mock curated_models data
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": True,
                    "deprecated": False,
                },
                {
                    "name": "gpt-4o-mini",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": True,
                    "recommended_is_visible": True,
                    "deprecated": False,
                },
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task completed successfully
            assert result is True

            # Verify models were added
            updated_models = _get_model_configurations_for_provider(
                db_session, llm_provider
            )
            assert len(updated_models) == 2

            # Verify model details
            model_names = {model.name for model in updated_models}
            assert "gpt-4" in model_names
            assert "gpt-4o-mini" in model_names

            # Verify recommendations were set correctly
            gpt4_model = next(m for m in updated_models if m.name == "gpt-4")
            assert gpt4_model.recommended_default is True
            assert gpt4_model.recommended_fast_default is False
            assert gpt4_model.recommended_is_visible is True

            gpt4o_mini_model = next(
                m for m in updated_models if m.name == "gpt-4o-mini"
            )
            assert gpt4o_mini_model.recommended_default is False
            assert gpt4o_mini_model.recommended_fast_default is True
            assert gpt4o_mini_model.recommended_is_visible is True

    def test_sync_updates_existing_models_with_new_recommendations(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that existing models are updated with new recommendations"""
        # Create test LLM provider
        llm_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")

        # Create existing model with old recommendations
        existing_model = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-4",
            recommended_default=False,
            recommended_fast_default=False,
            recommended_is_visible=False,
        )

        # Mock curated_models data with updated recommendations
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": True,
                    "recommended_is_visible": True,
                    "deprecated": False,
                }
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task completed successfully
            assert result is True

            # Refresh the model from database
            db_session.refresh(existing_model)

            # Verify recommendations were updated
            assert existing_model.recommended_default is True
            assert existing_model.recommended_fast_default is True
            assert existing_model.recommended_is_visible is True

    def test_sync_deletes_deprecated_not_visible_models(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that deprecated models that are not visible are deleted"""
        llm_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")
        _ = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-3.5-turbo",
            is_visible=False,
        )
        _ = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-4",
            is_visible=True,
        )
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-3.5-turbo",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": False,
                    "deprecated": True,
                },
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": True,
                    "deprecated": False,
                },
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task completed successfully
            assert result is True

            # Verify deprecated model was deleted
            remaining_models = _get_model_configurations_for_provider(
                db_session, llm_provider
            )
            model_names = {model.name for model in remaining_models}
            assert "gpt-3.5-turbo" not in model_names
            assert "gpt-4" in model_names
            assert len(remaining_models) == 1

    def test_sync_skips_providers_with_custom_models(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that providers with custom models are skipped"""
        # Create test LLM provider
        llm_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")

        # Create custom model not in curated list
        _ = _create_test_model_configuration(
            db_session,
            llm_provider,
            "custom-model-not-in-curated",
            is_visible=True,
        )

        # Mock curated_models data without the custom model
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": True,
                    "deprecated": False,
                }
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task completed successfully
            assert result is True

            # Verify custom model still exists (provider was skipped)
            remaining_models = _get_model_configurations_for_provider(
                db_session, llm_provider
            )
            assert len(remaining_models) == 1
            assert remaining_models[0].name == "custom-model-not-in-curated"

            # Verify no new models were added
            model_names = {model.name for model in remaining_models}
            assert "gpt-4" not in model_names

    def test_sync_skips_providers_not_in_curated_models(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that providers not in curated_models are skipped"""
        # Create test LLM provider for unsupported provider
        llm_provider = _create_test_llm_provider(
            db_session, "Test Custom", "custom_provider"
        )

        # Create existing model
        _ = _create_test_model_configuration(
            db_session,
            llm_provider,
            "custom-model",
            is_visible=True,
        )

        # Mock curated_models data without the custom provider
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": True,
                    "deprecated": False,
                }
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task completed successfully
            assert result is True

            # Verify existing model is unchanged (provider was skipped)
            remaining_models = _get_model_configurations_for_provider(
                db_session, llm_provider
            )
            assert len(remaining_models) == 1
            assert remaining_models[0].name == "custom-model"

    def test_sync_handles_multiple_providers_correctly(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that multiple providers are handled correctly"""
        # Create test LLM providers
        openai_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")
        anthropic_provider = _create_test_llm_provider(
            db_session, "Test Anthropic", "anthropic"
        )

        # Mock curated_models data for both providers
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": True,
                    "deprecated": False,
                }
            ],
            "anthropic": [
                {
                    "name": "claude-3-opus",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": True,
                    "recommended_is_visible": True,
                    "deprecated": False,
                }
            ],
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task completed successfully
            assert result is True

            # Verify models were added for both providers
            openai_models = _get_model_configurations_for_provider(
                db_session, openai_provider
            )
            anthropic_models = _get_model_configurations_for_provider(
                db_session, anthropic_provider
            )

            assert len(openai_models) == 1
            assert openai_models[0].name == "gpt-4"
            assert openai_models[0].recommended_default is True

            assert len(anthropic_models) == 1
            assert anthropic_models[0].name == "claude-3-opus"
            assert anthropic_models[0].recommended_fast_default is True

    def test_sync_handles_exception_gracefully(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test that the task handles exceptions gracefully"""
        # Create test LLM provider
        _create_test_llm_provider(db_session, "Test OpenAI", "openai")

        # Mock curated_models to raise an exception
        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            side_effect=Exception("Test exception"),
        ):
            # Run the task
            result = check_for_llm_model_update_onyx_curated(
                Mock(), tenant_id=TEST_TENANT_ID
            )

            # Verify task returned None (indicating failure)
            assert result is None

    def test_helper_function_delete_deprecated_not_visible_models(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test the helper function for deleting deprecated models"""
        # Create test LLM provider
        llm_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")

        # Create test models
        _ = _create_test_model_configuration(
            db_session, llm_provider, "deprecated-model", is_visible=False
        )
        _ = _create_test_model_configuration(
            db_session, llm_provider, "deprecated-visible-model", is_visible=True
        )
        _ = _create_test_model_configuration(
            db_session, llm_provider, "active-model", is_visible=False
        )

        # Mock curated_models data
        mock_curated_models = {
            "openai": [
                {
                    "name": "deprecated-model",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": False,
                    "deprecated": True,
                },
                {
                    "name": "deprecated-visible-model",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": False,
                    "deprecated": True,
                },
                {
                    "name": "active-model",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": False,
                    "deprecated": False,
                },
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Get all model configurations
            model_configurations = _get_model_configurations_for_provider(
                db_session, llm_provider
            )

            # Call the helper function
            _delete_deprecated_not_visible_models(
                db_session, llm_provider, model_configurations
            )

            # Verify only the deprecated and not visible model was deleted
            remaining_models = _get_model_configurations_for_provider(
                db_session, llm_provider
            )
            model_names = {model.name for model in remaining_models}

            assert "deprecated-model" not in model_names  # Should be deleted
            assert "deprecated-visible-model" in model_names  # Should remain (visible)
            assert "active-model" in model_names  # Should remain (not deprecated)
            assert len(remaining_models) == 2

    def test_helper_function_sync_model_configurations(
        self, db_session: Session, tenant_context, admin_user: DATestUser
    ) -> None:
        """Test the helper function for syncing model configurations"""
        # Create test LLM provider
        llm_provider = _create_test_llm_provider(db_session, "Test OpenAI", "openai")

        # Create existing model with old recommendations
        existing_model = _create_test_model_configuration(
            db_session,
            llm_provider,
            "gpt-4",
            recommended_default=False,
            recommended_fast_default=False,
            recommended_is_visible=False,
        )

        # Mock curated_models data
        mock_curated_models = {
            "openai": [
                {
                    "name": "gpt-4",
                    "recommended_default_model": True,
                    "recommended_fast_default_model": True,
                    "recommended_is_visible": True,
                    "deprecated": False,
                },
                {
                    "name": "gpt-4o",
                    "recommended_default_model": False,
                    "recommended_fast_default_model": False,
                    "recommended_is_visible": True,
                    "deprecated": False,
                },
            ]
        }

        with patch(
            "onyx.background.celery.tasks.llm_model_update_onyx_curated.tasks.curated_models",
            mock_curated_models,
        ):
            # Get all model configurations
            model_configurations = _get_model_configurations_for_provider(
                db_session, llm_provider
            )

            # Call the helper function
            _sync_model_configurations_with_curated_models(
                db_session, llm_provider, model_configurations
            )

            # Verify existing model was updated and new model was added
            updated_models = _get_model_configurations_for_provider(
                db_session, llm_provider
            )
            assert len(updated_models) == 2

            # Verify existing model was updated
            db_session.refresh(existing_model)
            assert existing_model.recommended_default is True
            assert existing_model.recommended_fast_default is True
            assert existing_model.recommended_is_visible is True

            # Verify new model was added
            model_names = {model.name for model in updated_models}
            assert "gpt-4" in model_names
            assert "gpt-4o" in model_names
