"""
Tests for the test_llm_configuration endpoint (/admin/llm/test).

This tests the LLM configuration testing functionality which verifies
that LLM credentials are valid before saving them.
"""

from collections.abc import Generator
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi import HTTPException
from sqlalchemy.orm import Session

from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import update_default_provider
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import UserRole
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLM
from onyx.server.manage.llm.api import (
    test_default_provider as run_test_default_provider,
)
from onyx.server.manage.llm.api import (
    test_llm_configuration as run_test_llm_configuration,
)
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.manage.llm.models import TestLLMRequest as LLMTestRequest


def _create_mock_admin() -> MagicMock:
    """Create a mock admin user for testing."""
    mock_admin = MagicMock()
    mock_admin.role = UserRole.ADMIN
    return mock_admin


def _create_test_provider(
    db_session: Session,
    name: str,
    api_key: str = "sk-test-key-00000000000000000000000000000000000",
) -> None:
    """Helper to create a test LLM provider in the database."""
    upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key=api_key,
            api_key_changed=True,
            default_model_name="gpt-4o-mini",
            model_configurations=[
                ModelConfigurationUpsertRequest(name="gpt-4o-mini", is_visible=True)
            ],
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


class TestLLMConfigurationEndpoint:
    """Tests for the test_llm_configuration endpoint."""

    def test_successful_llm_test_with_new_provider(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that a successful LLM test returns normally (no exception).

        When test_llm returns None (success), the endpoint should complete
        without raising an exception.
        """
        captured_llms: list[LLM] = []

        def mock_test_llm_success(llm: LLM) -> str | None:
            """Mock test_llm that always succeeds."""
            captured_llms.append(llm)
            return None  # Success

        try:
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_success
            ):
                # This should complete without exception
                run_test_llm_configuration(
                    test_llm_request=LLMTestRequest(
                        name=None,  # New provider (not in DB)
                        provider=LlmProviderNames.OPENAI,
                        api_key="sk-new-test-key-0000000000000000000000000000",
                        api_key_changed=True,
                        custom_config_changed=False,
                        default_model_name="gpt-4o-mini",
                        model_configurations=[
                            ModelConfigurationUpsertRequest(
                                name="gpt-4o-mini", is_visible=True
                            )
                        ],
                    ),
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Verify test_llm was called
            assert len(captured_llms) == 1, "test_llm should have been called once"

            # Verify the LLM was configured with the correct model
            assert captured_llms[0].config.model_name == "gpt-4o-mini"
            assert captured_llms[0].config.model_provider == LlmProviderNames.OPENAI

        finally:
            db_session.rollback()

    def test_failed_llm_test_raises_http_exception(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that a failed LLM test raises an HTTPException with status 400.

        When test_llm returns an error message, the endpoint should raise
        an HTTPException with the error details.
        """
        error_message = "Invalid API key: Authentication failed"

        def mock_test_llm_failure(llm: LLM) -> str | None:
            """Mock test_llm that always fails."""
            return error_message

        try:
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_failure
            ):
                with pytest.raises(HTTPException) as exc_info:
                    run_test_llm_configuration(
                        test_llm_request=LLMTestRequest(
                            name=None,
                            provider=LlmProviderNames.OPENAI,
                            api_key="sk-invalid-key-00000000000000000000000000",
                            api_key_changed=True,
                            custom_config_changed=False,
                            default_model_name="gpt-4o-mini",
                            model_configurations=[
                                ModelConfigurationUpsertRequest(
                                    name="gpt-4o-mini", is_visible=True
                                )
                            ],
                        ),
                        _=_create_mock_admin(),
                        db_session=db_session,
                    )

                # Verify the exception details
                assert exc_info.value.status_code == 400
                assert exc_info.value.detail == error_message

        finally:
            db_session.rollback()

    def test_uses_existing_provider_api_key_when_not_changed(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that when testing an existing provider without changing the API key,
        the stored API key from the database is used.
        """
        original_api_key = "sk-original-stored-key-00000000000000000000"
        captured_llms: list[LLM] = []

        def mock_test_llm_capture(llm: LLM) -> str | None:
            """Mock test_llm that captures the LLM for inspection."""
            captured_llms.append(llm)
            return None

        try:
            # First, create the provider in the database
            _create_test_provider(db_session, provider_name, api_key=original_api_key)

            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                # Test with api_key_changed=False - should use stored key
                run_test_llm_configuration(
                    test_llm_request=LLMTestRequest(
                        name=provider_name,  # Existing provider
                        provider=LlmProviderNames.OPENAI,
                        api_key=None,  # Not providing a new key
                        api_key_changed=False,  # Using existing key
                        custom_config_changed=False,
                        default_model_name="gpt-4o-mini",
                        model_configurations=[
                            ModelConfigurationUpsertRequest(
                                name="gpt-4o-mini", is_visible=True
                            )
                        ],
                    ),
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Verify test_llm was called with the original API key
            assert len(captured_llms) == 1
            assert captured_llms[0].config.api_key == original_api_key

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_uses_new_api_key_when_changed(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that when testing an existing provider with a new API key,
        the new API key is used instead of the stored one.
        """
        original_api_key = "sk-original-stored-key-00000000000000000000"
        new_api_key = "sk-new-updated-key-000000000000000000000000"
        captured_llms: list[LLM] = []

        def mock_test_llm_capture(llm: LLM) -> str | None:
            """Mock test_llm that captures the LLM for inspection."""
            captured_llms.append(llm)
            return None

        try:
            # First, create the provider in the database
            _create_test_provider(db_session, provider_name, api_key=original_api_key)

            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                # Test with api_key_changed=True - should use new key
                run_test_llm_configuration(
                    test_llm_request=LLMTestRequest(
                        name=provider_name,  # Existing provider
                        provider=LlmProviderNames.OPENAI,
                        api_key=new_api_key,  # Providing a new key
                        api_key_changed=True,  # Key is being changed
                        custom_config_changed=False,
                        default_model_name="gpt-4o-mini",
                        model_configurations=[
                            ModelConfigurationUpsertRequest(
                                name="gpt-4o-mini", is_visible=True
                            )
                        ],
                    ),
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Verify test_llm was called with the new API key
            assert len(captured_llms) == 1
            assert captured_llms[0].config.api_key == new_api_key

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_uses_existing_custom_config_when_not_changed(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that when testing an existing provider without changing custom_config,
        the stored custom_config from the database is used.
        """
        original_custom_config = {"custom_key": "original_value"}
        captured_llms: list[LLM] = []

        def mock_test_llm_capture(llm: LLM) -> str | None:
            """Mock test_llm that captures the LLM for inspection."""
            captured_llms.append(llm)
            return None

        try:
            # First, create the provider in the database with custom_config
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    custom_config=original_custom_config,
                    custom_config_changed=True,
                    default_model_name="gpt-4o-mini",
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        )
                    ],
                ),
                db_session=db_session,
            )

            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                # Test with custom_config_changed=False - should use stored config
                run_test_llm_configuration(
                    test_llm_request=LLMTestRequest(
                        name=provider_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key=None,
                        api_key_changed=False,
                        custom_config=None,  # Not providing new config
                        custom_config_changed=False,  # Using existing config
                        default_model_name="gpt-4o-mini",
                        model_configurations=[
                            ModelConfigurationUpsertRequest(
                                name="gpt-4o-mini", is_visible=True
                            )
                        ],
                    ),
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Verify test_llm was called with the original custom_config
            assert len(captured_llms) == 1
            assert captured_llms[0].config.custom_config == original_custom_config

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_different_model_names(
        self,
        db_session: Session,
    ) -> None:
        """
        Test that the endpoint correctly passes different model names to the LLM.
        """
        captured_llms: list[LLM] = []

        def mock_test_llm_capture(llm: LLM) -> str | None:
            captured_llms.append(llm)
            return None

        test_models = ["gpt-4", "gpt-4o", "gpt-4o-mini", "gpt-3.5-turbo"]

        try:
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                for model_name in test_models:
                    run_test_llm_configuration(
                        test_llm_request=LLMTestRequest(
                            name=None,
                            provider=LlmProviderNames.OPENAI,
                            api_key="sk-test-key-00000000000000000000000000000000000",
                            api_key_changed=True,
                            custom_config_changed=False,
                            default_model_name=model_name,
                            model_configurations=[
                                ModelConfigurationUpsertRequest(
                                    name=model_name, is_visible=True
                                )
                            ],
                        ),
                        _=_create_mock_admin(),
                        db_session=db_session,
                    )

            # Verify all models were tested
            assert len(captured_llms) == len(test_models)

            for i, llm in enumerate(captured_llms):
                assert (
                    llm.config.model_name == test_models[i]
                ), f"Expected model {test_models[i]}, got {llm.config.model_name}"

        finally:
            db_session.rollback()


class TestDefaultProviderEndpoint:
    """Tests for the test_default_provider endpoint (/admin/llm/test/default)."""

    def test_default_provider_switching(
        self,
        db_session: Session,
    ) -> None:
        """
        Test that run_test_default_provider correctly uses the default provider
        and responds to changes in default model and default provider.

        Steps:
        1. Upload provider 1 with models, set as default
        2. Call run_test_default_provider - should use provider 1's default model
        3. Upload provider 2 with models (not default)
        4. Call run_test_default_provider - should still use provider 1
        5. Change the default model on provider 1
        6. Call run_test_default_provider - should use new model on provider 1
        7. Change the default provider to provider 2
        8. Call run_test_default_provider - should use provider 2
        """
        provider_1_name = f"test-provider-1-{uuid4().hex[:8]}"
        provider_2_name = f"test-provider-2-{uuid4().hex[:8]}"

        provider_1_api_key = "sk-provider1-key-000000000000000000000000000"
        provider_2_api_key = "sk-provider2-key-000000000000000000000000000"

        provider_1_initial_model = "gpt-4"
        provider_1_updated_model = "gpt-4o"
        provider_2_default_model = "gpt-4o-mini"

        captured_llms: list[LLM] = []

        def mock_test_llm_capture(llm: LLM) -> str | None:
            """Mock test_llm that captures the LLM for inspection."""
            captured_llms.append(llm)
            return None

        try:
            # Step 1: Create provider 1 with models, it becomes default (first provider)
            provider_1 = upsert_llm_provider(
                LLMProviderUpsertRequest(
                    name=provider_1_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key=provider_1_api_key,
                    api_key_changed=True,
                    default_model_name=provider_1_initial_model,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                        ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
                    ],
                ),
                db_session=db_session,
            )

            # Set provider 1 as the default provider explicitly
            update_default_provider(provider_1.id, db_session)

            # Step 2: Call run_test_default_provider - should use provider 1's default model
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                run_test_default_provider(_=_create_mock_admin())

            assert len(captured_llms) == 1
            assert captured_llms[0].config.model_name == provider_1_initial_model
            assert captured_llms[0].config.api_key == provider_1_api_key
            captured_llms.clear()

            # Step 3: Create provider 2 (not default)
            provider_2 = upsert_llm_provider(
                LLMProviderUpsertRequest(
                    name=provider_2_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key=provider_2_api_key,
                    api_key_changed=True,
                    default_model_name=provider_2_default_model,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        ),
                        ModelConfigurationUpsertRequest(
                            name="gpt-3.5-turbo", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )

            # Step 4: Call run_test_default_provider - should still use provider 1
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                run_test_default_provider(_=_create_mock_admin())

            assert len(captured_llms) == 1
            assert captured_llms[0].config.model_name == provider_1_initial_model
            assert captured_llms[0].config.api_key == provider_1_api_key
            captured_llms.clear()

            # Step 5: Update provider 1's default model
            upsert_llm_provider(
                LLMProviderUpsertRequest(
                    name=provider_1_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key=provider_1_api_key,
                    api_key_changed=True,
                    default_model_name=provider_1_updated_model,  # Changed
                    model_configurations=[
                        ModelConfigurationUpsertRequest(name="gpt-4", is_visible=True),
                        ModelConfigurationUpsertRequest(name="gpt-4o", is_visible=True),
                    ],
                ),
                db_session=db_session,
            )

            # Step 6: Call run_test_default_provider - should use new model on provider 1
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                run_test_default_provider(_=_create_mock_admin())

            assert len(captured_llms) == 1
            assert captured_llms[0].config.model_name == provider_1_updated_model
            assert captured_llms[0].config.api_key == provider_1_api_key
            captured_llms.clear()

            # Step 7: Change the default provider to provider 2
            update_default_provider(provider_2.id, db_session)

            # Step 8: Call run_test_default_provider - should use provider 2
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                run_test_default_provider(_=_create_mock_admin())

            assert len(captured_llms) == 1
            assert captured_llms[0].config.model_name == provider_2_default_model
            assert captured_llms[0].config.api_key == provider_2_api_key

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_1_name)
            _cleanup_provider(db_session, provider_2_name)

    def test_no_default_provider_raises_exception(
        self,
        db_session: Session,
    ) -> None:
        """
        Test that when no default provider exists, the endpoint raises an exception.
        """
        # Clear any existing providers to ensure no default exists
        from onyx.db.llm import fetch_existing_llm_providers

        try:
            existing_providers = fetch_existing_llm_providers(db_session)
            provider_names_to_restore: list[str] = []

            for provider in existing_providers:
                provider_names_to_restore.append(provider.name)

            # Remove all providers temporarily
            for provider in existing_providers:
                remove_llm_provider(db_session, provider.id)

            # Now run_test_default_provider should fail
            with pytest.raises(HTTPException) as exc_info:
                run_test_default_provider(_=_create_mock_admin())

            assert exc_info.value.status_code == 400
            assert "No LLM Provider setup" in exc_info.value.detail

        finally:
            db_session.rollback()

    def test_default_provider_test_failure(
        self,
        db_session: Session,
    ) -> None:
        """
        Test that when the default provider's LLM test fails, an exception is raised.
        """
        provider_name = f"test-provider-{uuid4().hex[:8]}"
        error_message = "Connection to LLM provider failed"

        def mock_test_llm_failure(llm: LLM) -> str | None:
            """Mock test_llm that always fails."""
            return error_message

        try:
            # Create a provider and set it as default
            provider = upsert_llm_provider(
                LLMProviderUpsertRequest(
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    default_model_name="gpt-4o-mini",
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        ),
                    ],
                ),
                db_session=db_session,
            )
            update_default_provider(provider.id, db_session)

            # Test should fail
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_failure
            ):
                with pytest.raises(HTTPException) as exc_info:
                    run_test_default_provider(_=_create_mock_admin())

                assert exc_info.value.status_code == 400
                assert exc_info.value.detail == error_message

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)
