"""
Tests for the LLM Provider Auto Mode feature.

This tests the automatic model syncing from GitHub config when a provider
is uploaded with is_auto_mode=True.
"""

from collections.abc import Generator
from datetime import datetime
from unittest.mock import MagicMock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import LLMModelFlowType
from onyx.db.llm import fetch_default_llm_model
from onyx.db.llm import fetch_existing_llm_provider
from onyx.db.llm import fetch_existing_llm_providers
from onyx.db.llm import remove_llm_provider
from onyx.db.llm import sync_auto_mode_models
from onyx.db.llm import update_default_provider
from onyx.db.models import UserRole
from onyx.llm.constants import LlmProviderNames
from onyx.llm.interfaces import LLM
from onyx.llm.well_known_providers.auto_update_models import LLMProviderRecommendation
from onyx.llm.well_known_providers.auto_update_models import LLMRecommendations
from onyx.llm.well_known_providers.models import SimpleKnownModel
from onyx.server.manage.llm.api import put_llm_provider
from onyx.server.manage.llm.api import (
    test_default_provider as run_test_default_provider,
)
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest


def _create_mock_admin() -> MagicMock:
    """Create a mock admin user for testing."""
    mock_admin = MagicMock()
    mock_admin.role = UserRole.ADMIN
    return mock_admin


def _cleanup_provider(db_session: Session, name: str) -> None:
    """Helper to clean up a test provider by name."""
    provider = fetch_existing_llm_provider(name=name, db_session=db_session)
    if provider:
        remove_llm_provider(db_session, provider.id)


def _create_mock_llm_recommendations(
    provider: str,
    default_model_name: str,
    additional_models: list[str],
) -> LLMRecommendations:
    """Create a mock LLMRecommendations object for testing.

    Args:
        provider: The provider name (e.g., "openai")
        default_model_name: The name of the default model
        additional_models: List of additional visible model names

    Returns:
        LLMRecommendations object with the specified configuration
    """
    return LLMRecommendations(
        version="1.0.0",
        updated_at=datetime.now(),
        providers={
            provider: LLMProviderRecommendation(
                default_model=SimpleKnownModel(
                    name=default_model_name,
                    display_name=default_model_name.upper(),
                ),
                additional_visible_models=[
                    SimpleKnownModel(name=model, display_name=model.upper())
                    for model in additional_models
                ],
            )
        },
    )


@pytest.fixture
def provider_name() -> Generator[str, None, None]:
    """Generate a unique provider name for each test."""
    yield f"test-auto-provider-{uuid4().hex[:8]}"


class TestAutoModeSyncFeature:
    """Tests for the Auto Mode model syncing feature."""

    def test_auto_mode_syncs_models_from_github_config(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that when a provider is uploaded with auto mode enabled and no model
        configurations, the models from fetch_llm_recommendations_from_github()
        are synced to the provider.

        Steps:
        1. Mock fetch_llm_recommendations_from_github to return a known config
        2. Upload provider with is_auto_mode=True and no model_configurations
        3. Fetch the provider and verify all recommended models are present
        4. Set the provider as default
        5. Fetch the default provider and verify the default model matches the config
        """
        # Define the expected models from the mock GitHub config
        expected_default_model = "gpt-4o"
        expected_additional_models = ["gpt-4o-mini", "gpt-4-turbo"]
        all_expected_models = [expected_default_model] + expected_additional_models

        # Create the mock LLMRecommendations
        mock_recommendations = _create_mock_llm_recommendations(
            provider=LlmProviderNames.OPENAI,
            default_model_name=expected_default_model,
            additional_models=expected_additional_models,
        )

        try:
            with patch(
                "onyx.server.manage.llm.api.fetch_llm_recommendations_from_github",
                return_value=mock_recommendations,
            ):
                # Step 1-2: Upload provider with auto mode on and no model configs
                # NOTE: We need to provide a default_model_name for the initial upsert,
                # but auto mode will override it with the GitHub config's default
                put_llm_provider(
                    llm_provider_upsert_request=LLMProviderUpsertRequest(
                        name=provider_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key="sk-test-key-00000000000000000000000000000000000",
                        api_key_changed=True,
                        is_auto_mode=True,
                        default_model_name=expected_default_model,
                        model_configurations=[],  # No model configs provided
                    ),
                    is_creation=True,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Step 3: Verify all models from the GitHub config are present
            # Fetch the provider fresh from the database
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None, "Provider should exist"
            assert provider.is_auto_mode is True, "Provider should be in auto mode"

            # Check that all expected models are present and visible
            model_names = {mc.name for mc in provider.model_configurations}
            for expected_model in all_expected_models:
                assert (
                    expected_model in model_names
                ), f"Expected model '{expected_model}' not found in provider models"

            # Verify visibility of all synced models
            for mc in provider.model_configurations:
                if mc.name in all_expected_models:
                    assert mc.is_visible is True, f"Model '{mc.name}' should be visible"

            # Verify the default model was set correctly
            assert (
                provider.default_model_name == expected_default_model
            ), f"Default model should be '{expected_default_model}'"

            # Step 4: Set the provider as default
            update_default_provider(provider.id, db_session)

            # Step 5: Fetch the default provider and verify
            default_model = fetch_default_llm_model(db_session)
            assert default_model is not None, "Default provider should exist"
            assert (
                default_model.llm_provider.name == provider_name
            ), "Default provider should be our test provider"
            assert (
                default_model.name == expected_default_model
            ), f"Default provider's default model should be '{expected_default_model}'"
            assert (
                default_model.llm_provider.is_auto_mode is True
            ), "Default provider should be in auto mode"

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_auto_mode_with_multiple_providers_in_config(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that auto mode only syncs models for the matching provider type,
        ignoring models from other providers in the config.
        """
        # Create recommendations with multiple providers
        mock_recommendations = LLMRecommendations(
            version="1.0.0",
            updated_at=datetime.now(),
            providers={
                LlmProviderNames.OPENAI: LLMProviderRecommendation(
                    default_model=SimpleKnownModel(
                        name="gpt-4o", display_name="GPT-4o"
                    ),
                    additional_visible_models=[
                        SimpleKnownModel(name="gpt-4o-mini", display_name="GPT-4o Mini")
                    ],
                ),
                LlmProviderNames.ANTHROPIC: LLMProviderRecommendation(
                    default_model=SimpleKnownModel(
                        name="claude-3-5-sonnet-latest",
                        display_name="Claude 3.5 Sonnet",
                    ),
                    additional_visible_models=[
                        SimpleKnownModel(
                            name="claude-3-5-haiku-latest",
                            display_name="Claude 3.5 Haiku",
                        )
                    ],
                ),
            },
        )

        try:
            with patch(
                "onyx.server.manage.llm.api.fetch_llm_recommendations_from_github",
                return_value=mock_recommendations,
            ):
                # Upload an OpenAI provider with auto mode
                put_llm_provider(
                    llm_provider_upsert_request=LLMProviderUpsertRequest(
                        name=provider_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key="sk-test-key-00000000000000000000000000000000000",
                        api_key_changed=True,
                        is_auto_mode=True,
                        default_model_name="gpt-4o",
                        model_configurations=[],
                    ),
                    is_creation=True,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Verify only OpenAI models are synced, not Anthropic models
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None

            model_names = {mc.name for mc in provider.model_configurations}

            # OpenAI models should be present
            assert "gpt-4o" in model_names
            assert "gpt-4o-mini" in model_names

            # Anthropic models should NOT be present
            assert "claude-3-5-sonnet-latest" not in model_names
            assert "claude-3-5-haiku-latest" not in model_names

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_existing_provider_transition_to_auto_mode(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that when an existing provider with visible models transitions to auto mode,
        models from the auto mode config become visible, and models not in the config
        become not visible.

        Steps:
        1. Upload a provider with some visible model configurations (not in auto mode)
        2. Update the provider to enable auto mode
        3. Verify:
           - Models in the auto mode config are now visible
           - Models NOT in the auto mode config are now NOT visible
        """
        # Initial models on the provider (all visible initially)
        initial_models = [
            ModelConfigurationUpsertRequest(
                name="gpt-4", is_visible=True
            ),  # Will NOT be in auto config
            ModelConfigurationUpsertRequest(
                name="gpt-4o", is_visible=True
            ),  # Will be in auto config
            ModelConfigurationUpsertRequest(
                name="gpt-3.5-turbo", is_visible=True
            ),  # Will NOT be in auto config
        ]

        # Auto mode config: gpt-4o (default) + gpt-4o-mini (additional)
        # Note: gpt-4 and gpt-3.5-turbo are NOT in this config
        auto_mode_default = "gpt-4o"
        auto_mode_additional = ["gpt-4o-mini"]
        all_auto_mode_models = [auto_mode_default] + auto_mode_additional

        mock_recommendations = _create_mock_llm_recommendations(
            provider=LlmProviderNames.OPENAI,
            default_model_name=auto_mode_default,
            additional_models=auto_mode_additional,
        )

        try:
            # Step 1: Upload provider WITHOUT auto mode, with initial models
            put_llm_provider(
                llm_provider_upsert_request=LLMProviderUpsertRequest(
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    is_auto_mode=False,  # Not in auto mode initially
                    default_model_name="gpt-4",
                    model_configurations=initial_models,
                ),
                is_creation=True,
                _=_create_mock_admin(),
                db_session=db_session,
            )

            # Verify initial state: all models are visible
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None
            assert provider.is_auto_mode is False

            for mc in provider.model_configurations:
                assert (
                    mc.is_visible is True
                ), f"Initial model '{mc.name}' should be visible"

            # Step 2: Update provider to enable auto mode
            with patch(
                "onyx.server.manage.llm.api.fetch_llm_recommendations_from_github",
                return_value=mock_recommendations,
            ):
                put_llm_provider(
                    llm_provider_upsert_request=LLMProviderUpsertRequest(
                        name=provider_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key=None,  # Not changing API key
                        api_key_changed=False,
                        is_auto_mode=True,  # Now enabling auto mode
                        default_model_name=auto_mode_default,
                        model_configurations=[],  # Auto mode will sync from config
                    ),
                    is_creation=False,  # This is an update
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Step 3: Verify model visibility after auto mode transition
            # Expire session cache to force fresh fetch after sync_auto_mode_models committed
            db_session.expire_all()
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None
            assert provider.is_auto_mode is True

            # Build a map of model name -> visibility
            model_visibility = {
                mc.name: mc.is_visible for mc in provider.model_configurations
            }

            # Models in auto mode config should be visible
            for model_name in all_auto_mode_models:
                assert (
                    model_name in model_visibility
                ), f"Auto mode model '{model_name}' should exist"
                assert (
                    model_visibility[model_name] is True
                ), f"Auto mode model '{model_name}' should be visible"

            # Models NOT in auto mode config should NOT be visible
            models_not_in_config = ["gpt-4", "gpt-3.5-turbo"]
            for model_name in models_not_in_config:
                if model_name in model_visibility:
                    assert (
                        model_visibility[model_name] is False
                    ), f"Model '{model_name}' not in auto config should NOT be visible"

            # Verify the default model was updated
            assert provider.default_model_name == auto_mode_default

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_auto_mode_provider_not_in_config(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Test that when the provider type is not in the GitHub config,
        no model syncing occurs.
        """
        # Create recommendations that don't include OpenAI
        mock_recommendations = LLMRecommendations(
            version="1.0.0",
            updated_at=datetime.now(),
            providers={
                LlmProviderNames.ANTHROPIC: LLMProviderRecommendation(
                    default_model=SimpleKnownModel(
                        name="claude-3-5-sonnet-latest",
                        display_name="Claude 3.5 Sonnet",
                    ),
                    additional_visible_models=[],
                ),
            },
        )

        try:
            with patch(
                "onyx.server.manage.llm.api.fetch_llm_recommendations_from_github",
                return_value=mock_recommendations,
            ):
                # Upload an OpenAI provider (not in config)
                put_llm_provider(
                    llm_provider_upsert_request=LLMProviderUpsertRequest(
                        name=provider_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key="sk-test-key-00000000000000000000000000000000000",
                        api_key_changed=True,
                        is_auto_mode=True,
                        default_model_name="gpt-4o",
                        model_configurations=[],
                    ),
                    is_creation=True,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Provider should be created but without synced models from config
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None
            assert provider.is_auto_mode is True

            # Only the default model provided in the request should exist
            model_names = {mc.name for mc in provider.model_configurations}
            assert "gpt-4o" in model_names
            # Anthropic models should NOT be synced
            assert "claude-3-5-sonnet-latest" not in model_names

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)

    def test_switching_default_between_auto_mode_providers(
        self,
        db_session: Session,
    ) -> None:
        """
        Test switching the default provider between two auto mode providers
        and verifying test_default_provider uses the correct default model.

        Steps:
        1. Create provider 1 (OpenAI) with auto mode, set as default
        2. Create provider 2 (Anthropic) with auto mode
        3. Verify provider 1 is the default
        4. Change default to provider 2
        5. Verify provider 2 is the default
        6. Run test_default_provider and verify it uses provider 2's default model
        """
        provider_1_name = f"test-auto-openai-{uuid4().hex[:8]}"
        provider_2_name = f"test-auto-anthropic-{uuid4().hex[:8]}"

        provider_1_api_key = "sk-provider1-key-000000000000000000000000000"
        provider_2_api_key = "sk-ant-provider2-key-0000000000000000000000"

        # Provider 1 (OpenAI) config
        provider_1_default_model = "gpt-4o"
        provider_1_additional_models = ["gpt-4o-mini"]

        # Provider 2 (Anthropic) config
        provider_2_default_model = "claude-3-5-sonnet-latest"
        provider_2_additional_models = ["claude-3-5-haiku-latest"]

        # Create mock recommendations with both providers
        mock_recommendations = LLMRecommendations(
            version="1.0.0",
            updated_at=datetime.now(),
            providers={
                LlmProviderNames.OPENAI: LLMProviderRecommendation(
                    default_model=SimpleKnownModel(
                        name=provider_1_default_model,
                        display_name="GPT-4o",
                    ),
                    additional_visible_models=[
                        SimpleKnownModel(name=m, display_name=m.upper())
                        for m in provider_1_additional_models
                    ],
                ),
                LlmProviderNames.ANTHROPIC: LLMProviderRecommendation(
                    default_model=SimpleKnownModel(
                        name=provider_2_default_model,
                        display_name="Claude 3.5 Sonnet",
                    ),
                    additional_visible_models=[
                        SimpleKnownModel(name=m, display_name=m.upper())
                        for m in provider_2_additional_models
                    ],
                ),
            },
        )

        captured_llms: list[LLM] = []

        def mock_test_llm_capture(llm: LLM) -> str | None:
            """Mock test_llm that captures the LLM for inspection."""
            captured_llms.append(llm)
            return None  # Success

        try:
            with patch(
                "onyx.server.manage.llm.api.fetch_llm_recommendations_from_github",
                return_value=mock_recommendations,
            ):
                # Step 1: Create provider 1 (OpenAI) with auto mode
                put_llm_provider(
                    llm_provider_upsert_request=LLMProviderUpsertRequest(
                        name=provider_1_name,
                        provider=LlmProviderNames.OPENAI,
                        api_key=provider_1_api_key,
                        api_key_changed=True,
                        is_auto_mode=True,
                        default_model_name=provider_1_default_model,
                        model_configurations=[],
                    ),
                    is_creation=True,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Set provider 1 as the default
            db_session.expire_all()
            provider_1 = fetch_existing_llm_provider(
                name=provider_1_name, db_session=db_session
            )
            assert provider_1 is not None
            update_default_provider(provider_1.id, db_session)

            with patch(
                "onyx.server.manage.llm.api.fetch_llm_recommendations_from_github",
                return_value=mock_recommendations,
            ):
                # Step 2: Create provider 2 (Anthropic) with auto mode
                put_llm_provider(
                    llm_provider_upsert_request=LLMProviderUpsertRequest(
                        name=provider_2_name,
                        provider=LlmProviderNames.ANTHROPIC,
                        api_key=provider_2_api_key,
                        api_key_changed=True,
                        is_auto_mode=True,
                        default_model_name=provider_2_default_model,
                        model_configurations=[],
                    ),
                    is_creation=True,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

            # Step 3: Verify provider 1 is still the default
            db_session.expire_all()
            default_model = fetch_default_llm_model(db_session)
            assert default_model is not None
            assert default_model.llm_provider.name == provider_1_name
            assert default_model.name == provider_1_default_model
            assert default_model.llm_provider.is_auto_mode is True

            # Step 4: Change the default to provider 2
            provider_2 = fetch_existing_llm_provider(
                name=provider_2_name, db_session=db_session
            )
            assert provider_2 is not None
            update_default_provider(provider_2.id, db_session)

            # Step 5: Verify provider 2 is now the default
            db_session.expire_all()
            default_model = fetch_default_llm_model(db_session)
            assert default_model is not None
            assert default_model.llm_provider.name == provider_2_name
            assert default_model.name == provider_2_default_model
            assert default_model.llm_provider.is_auto_mode is True

            # Step 6: Run test_default_provider and verify it uses provider 2's model
            with patch(
                "onyx.server.manage.llm.api.test_llm", side_effect=mock_test_llm_capture
            ):
                run_test_default_provider(_=_create_mock_admin())

            # Verify test_llm was called with provider 2's default model
            assert len(captured_llms) == 1
            assert captured_llms[0].config.model_name == provider_2_default_model
            assert captured_llms[0].config.api_key == provider_2_api_key

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_1_name)
            _cleanup_provider(db_session, provider_2_name)


class TestAutoModeMissingFlows:
    """Regression test: sync_auto_mode_models must create LLMModelFlow rows
    for every ModelConfiguration it inserts, otherwise the provider vanishes
    from listing queries that join through LLMModelFlow."""

    def test_sync_auto_mode_creates_flow_rows(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Steps:
        1. Create a provider with no model configs (empty shell).
        2. Call sync_auto_mode_models to add models from a mock config.
        3. Assert every new ModelConfiguration has at least one LLMModelFlow.
        4. Assert fetch_existing_llm_providers (which joins through
           LLMModelFlow) returns the provider.
        """
        mock_recommendations = _create_mock_llm_recommendations(
            provider=LlmProviderNames.OPENAI,
            default_model_name="gpt-4o",
            additional_models=["gpt-4o-mini"],
        )

        try:
            # Step 1: Create provider with no model configs
            put_llm_provider(
                llm_provider_upsert_request=LLMProviderUpsertRequest(
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-test-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    is_auto_mode=True,
                    default_model_name="gpt-4o",
                    model_configurations=[],
                ),
                is_creation=True,
                _=_create_mock_admin(),
                db_session=db_session,
            )

            # Step 2: Run sync_auto_mode_models (simulating the periodic sync)
            db_session.expire_all()
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None

            sync_auto_mode_models(
                db_session=db_session,
                provider=provider,
                llm_recommendations=mock_recommendations,
            )

            # Step 3: Every ModelConfiguration must have at least one LLMModelFlow
            db_session.expire_all()
            provider = fetch_existing_llm_provider(
                name=provider_name, db_session=db_session
            )
            assert provider is not None

            synced_model_names = {mc.name for mc in provider.model_configurations}
            assert "gpt-4o" in synced_model_names
            assert "gpt-4o-mini" in synced_model_names

            for mc in provider.model_configurations:
                assert len(mc.llm_model_flows) > 0, (
                    f"ModelConfiguration '{mc.name}' (id={mc.id}) has no "
                    f"LLMModelFlow rows — it will be invisible to listing queries"
                )

                flow_types = {f.llm_model_flow_type for f in mc.llm_model_flows}
                assert (
                    LLMModelFlowType.CHAT in flow_types
                ), f"ModelConfiguration '{mc.name}' is missing a CHAT flow"

            # Step 4: The provider must appear in fetch_existing_llm_providers
            listed_providers = fetch_existing_llm_providers(
                db_session=db_session,
                flow_types=[LLMModelFlowType.CHAT],
            )
            listed_provider_names = {p.name for p in listed_providers}
            assert provider_name in listed_provider_names, (
                f"Provider '{provider_name}' not returned by "
                f"fetch_existing_llm_providers — models are missing flow rows"
            )

        finally:
            db_session.rollback()
            _cleanup_provider(db_session, provider_name)
