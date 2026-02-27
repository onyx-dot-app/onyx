"""
Tests for LLM provider api_base and custom_config change restrictions.

This ensures we don't have a vulnerability where an admin could change the api_base
or custom_config of an LLM provider without changing the API key, allowing them to
redirect API requests (containing the real API key in headers) to an attacker-controlled
server.

These are external dependency unit tests because they need a real database but
also need to control the MULTI_TENANT setting via patching.
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
from onyx.db.llm import upsert_llm_provider
from onyx.db.models import UserRole
from onyx.llm.constants import LlmProviderNames
from onyx.server.manage.llm.api import _mask_string
from onyx.server.manage.llm.api import put_llm_provider
from onyx.server.manage.llm.api import test_llm_configuration as run_llm_config_test
from onyx.server.manage.llm.models import LLMProviderUpsertRequest
from onyx.server.manage.llm.models import LLMProviderView
from onyx.server.manage.llm.models import ModelConfigurationUpsertRequest
from onyx.server.manage.llm.models import TestLLMRequest as LLMTestRequest
from tests.external_dependency_unit.mock_llm import LLM


def _create_test_provider(
    db_session: Session,
    name: str,
    api_base: str | None = None,
    custom_config: dict[str, str] | None = None,
) -> LLMProviderView:
    """Helper to create a test LLM provider."""
    return upsert_llm_provider(
        LLMProviderUpsertRequest(
            name=name,
            provider=LlmProviderNames.OPENAI,
            api_key="sk-test-key-00000000000000000000000000000000000",
            api_key_changed=True,
            api_base=api_base,
            custom_config=custom_config,
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


def _create_mock_admin() -> MagicMock:
    """Create a mock admin user for testing."""
    mock_admin = MagicMock()
    mock_admin.role = UserRole.ADMIN
    return mock_admin


@pytest.fixture
def provider_name() -> Generator[str, None, None]:
    """Generate a unique provider name for each test."""
    yield f"test-provider-{uuid4().hex[:8]}"


class TestLLMProviderChanges:
    """Tests for api_base change restrictions when updating LLM providers."""

    def test_blocks_api_base_change_without_key_change__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        In multi-tenant mode, changing api_base without also changing
        the API key should be blocked.
        """
        try:
            provider = _create_test_provider(db_session, provider_name)

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_base="https://attacker.example.com",
                )

                with pytest.raises(HTTPException) as exc_info:
                    put_llm_provider(
                        llm_provider_upsert_request=update_request,
                        is_creation=False,
                        _=_create_mock_admin(),
                        db_session=db_session,
                    )

                assert exc_info.value.status_code == 400
                assert "cannot be changed without changing the API key" in str(
                    exc_info.value.detail
                )
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_api_base_change_with_key_change__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Changing api_base IS allowed when the API key is also being changed.
        """
        try:
            provider = _create_test_provider(db_session, provider_name)

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-new-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    api_base="https://custom-endpoint.example.com/v1",
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.api_base == "https://custom-endpoint.example.com/v1"
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_same_api_base__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Keeping the same api_base (no change) is allowed without changing the API key.
        """
        original_api_base = "https://original.example.com/v1"

        try:
            provider = _create_test_provider(
                db_session, provider_name, api_base=original_api_base
            )

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_base=original_api_base,
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.api_base == original_api_base
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_empty_string_api_base_when_existing_is_none__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Treat empty-string api_base from clients as unset when comparing provider
        changes. This allows model-only updates when provider has no custom base URL.
        """
        try:
            view = _create_test_provider(db_session, provider_name, api_base=None)

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=view.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_base="",
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.api_base is None
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_blocks_clearing_api_base__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Clearing api_base (setting to None when it was previously set)
        is also blocked without changing the API key.
        """
        original_api_base = "https://original.example.com/v1"

        try:
            provider = _create_test_provider(
                db_session, provider_name, api_base=original_api_base
            )

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_base=None,
                )

                with pytest.raises(HTTPException) as exc_info:
                    put_llm_provider(
                        llm_provider_upsert_request=update_request,
                        is_creation=False,
                        _=_create_mock_admin(),
                        db_session=db_session,
                    )

                assert exc_info.value.status_code == 400
                assert "cannot be changed without changing the API key" in str(
                    exc_info.value.detail
                )
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_api_base_change__single_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        In single-tenant mode (MULTI_TENANT=False), changing api_base without
        changing the API key IS allowed. This is by design since single-tenant
        users have full control over their deployment.
        """
        try:
            provider = _create_test_provider(db_session, provider_name)

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", False):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_base="https://custom.example.com/v1",
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.api_base == "https://custom.example.com/v1"
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_new_provider_creation_not_affected__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Creating a new provider with an api_base should work regardless of
        api_key_changed (since there's no existing key to protect).
        """
        try:
            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                create_request = LLMProviderUpsertRequest(
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-new-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    api_base="https://custom.example.com/v1",
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=create_request,
                    is_creation=True,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.api_base == "https://custom.example.com/v1"
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_blocks_custom_config_change_without_key_change__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        In multi-tenant mode, changing custom_config without also changing
        the API key should be blocked (custom_config can set env vars that
        redirect LLM API requests).
        """
        try:
            provider = _create_test_provider(
                db_session,
                provider_name,
                custom_config={"SOME_CONFIG": "original_value"},
            )

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    custom_config={"OPENAI_API_BASE": "https://attacker.example.com"},
                    custom_config_changed=True,
                )

                with pytest.raises(HTTPException) as exc_info:
                    put_llm_provider(
                        llm_provider_upsert_request=update_request,
                        is_creation=False,
                        _=_create_mock_admin(),
                        db_session=db_session,
                    )

                assert exc_info.value.status_code == 400
                assert "cannot be changed without changing the API key" in str(
                    exc_info.value.detail
                )
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_blocks_adding_custom_config_without_key_change__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Adding custom_config when none existed should also be blocked
        without changing the API key.
        """
        try:
            provider = _create_test_provider(db_session, provider_name)

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    custom_config={"OPENAI_API_BASE": "https://attacker.example.com"},
                    custom_config_changed=True,
                )

                with pytest.raises(HTTPException) as exc_info:
                    put_llm_provider(
                        llm_provider_upsert_request=update_request,
                        is_creation=False,
                        _=_create_mock_admin(),
                        db_session=db_session,
                    )

                assert exc_info.value.status_code == 400
                assert "cannot be changed without changing the API key" in str(
                    exc_info.value.detail
                )
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_custom_config_change_with_key_change__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Changing custom_config IS allowed when the API key is also being changed.
        """
        new_config = {"AWS_REGION_NAME": "us-west-2"}

        try:
            provider = _create_test_provider(
                db_session,
                provider_name,
                custom_config={"AWS_REGION_NAME": "us-east-1"},
            )

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    api_key="sk-new-key-00000000000000000000000000000000000",
                    api_key_changed=True,
                    custom_config_changed=True,
                    custom_config=new_config,
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.custom_config == new_config
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_same_custom_config__multi_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        Keeping the same custom_config (no change) is allowed without changing the API key.
        """
        original_config = {"AWS_REGION_NAME": "us-east-1"}

        try:
            provider = _create_test_provider(
                db_session, provider_name, custom_config=original_config
            )

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", True):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    custom_config=original_config,
                    custom_config_changed=True,
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.custom_config == original_config
        finally:
            _cleanup_provider(db_session, provider_name)

    def test_allows_custom_config_change__single_tenant(
        self,
        db_session: Session,
        provider_name: str,
    ) -> None:
        """
        In single-tenant mode, changing custom_config without changing
        the API key IS allowed.
        """
        new_config = {"AWS_REGION_NAME": "eu-west-1"}

        try:
            provider = _create_test_provider(
                db_session,
                provider_name,
                custom_config={"AWS_REGION_NAME": "us-east-1"},
            )

            with patch("onyx.server.manage.llm.api.MULTI_TENANT", False):
                update_request = LLMProviderUpsertRequest(
                    id=provider.id,
                    name=provider_name,
                    provider=LlmProviderNames.OPENAI,
                    custom_config=new_config,
                    custom_config_changed=True,
                )

                result = put_llm_provider(
                    llm_provider_upsert_request=update_request,
                    is_creation=False,
                    _=_create_mock_admin(),
                    db_session=db_session,
                )

                assert result.custom_config == new_config
        finally:
            _cleanup_provider(db_session, provider_name)


def test_upload_with_custom_config_then_change(
    db_session: Session,
) -> None:
    """
    Run test + upload with a custom config (vertex).
    Edit attributes of provider that are not custom config or api key.
    Check that the test and update maintain the same values.
    """
    custom_config = {
        "vertex_credentials": "1234",
        "vertex_location": "us-east-1",
    }
    name = "test-provider-vertex-ai"
    provider_name = LlmProviderNames.VERTEX_AI.value
    default_model_name = "gemini-2.5-pro"

    # List to capture LLM inputs passed to test_llm
    captured_llms: list = []

    def capture_test_llm(llm: LLM) -> str:
        """Captures the LLM input and returns None (success)."""
        captured_llms.append(llm)
        return ""

    try:
        # Patch the test_llm method
        with patch("onyx.server.manage.llm.api.test_llm", side_effect=capture_test_llm):
            run_llm_config_test(
                LLMTestRequest(
                    provider=provider_name,
                    model=default_model_name,
                    api_key_changed=False,
                    custom_config_changed=True,
                    custom_config=custom_config,
                ),
                _=_create_mock_admin(),
                db_session=db_session,
            )

            provider = put_llm_provider(
                llm_provider_upsert_request=LLMProviderUpsertRequest(
                    name=name,
                    provider=provider_name,
                    custom_config=custom_config,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name=default_model_name, is_visible=True
                        )
                    ],
                    api_key_changed=False,
                    custom_config_changed=True,
                    is_auto_mode=False,
                ),
                is_creation=True,
                _=_create_mock_admin(),
                db_session=db_session,
            )

            # Turn auto mode off
            run_llm_config_test(
                LLMTestRequest(
                    id=provider.id,
                    provider=provider_name,
                    model=default_model_name,
                    api_key_changed=False,
                    custom_config_changed=False,
                ),
                _=_create_mock_admin(),
                db_session=db_session,
            )

            put_llm_provider(
                llm_provider_upsert_request=LLMProviderUpsertRequest(
                    id=provider.id,
                    name=name,
                    provider=provider_name,
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name=default_model_name, is_visible=True
                        ),
                        ModelConfigurationUpsertRequest(
                            name="gpt-4o-mini", is_visible=True
                        ),
                    ],
                    api_key_changed=False,
                    custom_config_changed=False,
                    is_auto_mode=False,
                ),
                is_creation=False,
                _=_create_mock_admin(),
                db_session=db_session,
            )

            # Verify that test_llm was called and custom_config matches
            assert len(captured_llms) == 2, "test_llm should have been called 2 times"

            for llm in captured_llms:
                assert llm.config.custom_config == custom_config, (
                    f"Expected custom_config {custom_config}, "
                    f"but got {llm.config.custom_config}"
                )

            # Check inside the database and check that custom_config is the same as the original
            db_provider = fetch_existing_llm_provider(name=name, db_session=db_session)
            if not db_provider:
                assert False, "Provider not found in the database"

            assert db_provider.custom_config == custom_config, (
                f"Expected custom_config {custom_config}, "
                f"but got {db_provider.custom_config}"
            )
    finally:
        db_session.rollback()
        _cleanup_provider(db_session, name)


def test_preserves_masked_sensitive_custom_config_on_provider_update(
    db_session: Session,
) -> None:
    """Masked sensitive values from the UI should not overwrite stored secrets."""
    name = f"test-provider-vertex-update-{uuid4().hex[:8]}"
    provider = LlmProviderNames.VERTEX_AI.value
    default_model_name = "gemini-2.5-pro"
    original_custom_config = {
        "vertex_credentials": '{"type":"service_account","private_key":"REAL_PRIVATE_KEY"}',
        "vertex_location": "global",
    }

    try:
        view = put_llm_provider(
            llm_provider_upsert_request=LLMProviderUpsertRequest(
                name=name,
                provider=provider,
                custom_config=original_custom_config,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name=default_model_name, is_visible=True
                    )
                ],
                api_key_changed=False,
                custom_config_changed=True,
                is_auto_mode=False,
            ),
            is_creation=True,
            _=_create_mock_admin(),
            db_session=db_session,
        )

        with patch("onyx.server.manage.llm.api.MULTI_TENANT", False):
            put_llm_provider(
                llm_provider_upsert_request=LLMProviderUpsertRequest(
                    id=view.id,
                    name=name,
                    provider=provider,
                    custom_config={
                        "vertex_credentials": _mask_string(
                            original_custom_config["vertex_credentials"]
                        ),
                        "vertex_location": "us-central1",
                    },
                    model_configurations=[
                        ModelConfigurationUpsertRequest(
                            name=default_model_name, is_visible=True
                        )
                    ],
                    api_key_changed=False,
                    custom_config_changed=True,
                    is_auto_mode=False,
                ),
                is_creation=False,
                _=_create_mock_admin(),
                db_session=db_session,
            )

        updated_provider = fetch_existing_llm_provider(name=name, db_session=db_session)
        assert updated_provider is not None
        assert updated_provider.custom_config is not None
        assert (
            updated_provider.custom_config["vertex_credentials"]
            == original_custom_config["vertex_credentials"]
        )
        assert updated_provider.custom_config["vertex_location"] == "us-central1"
    finally:
        db_session.rollback()
        _cleanup_provider(db_session, name)


def test_preserves_masked_sensitive_custom_config_on_test_request(
    db_session: Session,
) -> None:
    """LLM test should restore masked sensitive custom config values before invocation."""
    name = f"test-provider-vertex-test-{uuid4().hex[:8]}"
    provider_name = LlmProviderNames.VERTEX_AI.value
    default_model_name = "gemini-2.5-pro"
    original_custom_config = {
        "vertex_credentials": '{"type":"service_account","private_key":"REAL_PRIVATE_KEY"}',
        "vertex_location": "global",
    }
    captured_llms: list[LLM] = []

    def capture_test_llm(llm: LLM) -> str:
        captured_llms.append(llm)
        return ""

    try:
        provider = put_llm_provider(
            llm_provider_upsert_request=LLMProviderUpsertRequest(
                name=name,
                provider=provider_name,
                custom_config=original_custom_config,
                model_configurations=[
                    ModelConfigurationUpsertRequest(
                        name=default_model_name, is_visible=True
                    )
                ],
                api_key_changed=False,
                custom_config_changed=True,
                is_auto_mode=False,
            ),
            is_creation=True,
            _=_create_mock_admin(),
            db_session=db_session,
        )

        with patch("onyx.server.manage.llm.api.test_llm", side_effect=capture_test_llm):
            run_llm_config_test(
                LLMTestRequest(
                    id=provider.id,
                    provider=provider_name,
                    model=default_model_name,
                    api_key_changed=False,
                    custom_config_changed=True,
                    custom_config={
                        "vertex_credentials": _mask_string(
                            original_custom_config["vertex_credentials"]
                        ),
                        "vertex_location": "us-central1",
                    },
                ),
                _=_create_mock_admin(),
                db_session=db_session,
            )

        assert len(captured_llms) == 1
        assert captured_llms[0].config.custom_config is not None
        assert (
            captured_llms[0].config.custom_config["vertex_credentials"]
            == original_custom_config["vertex_credentials"]
        )
        assert captured_llms[0].config.custom_config["vertex_location"] == "us-central1"
    finally:
        db_session.rollback()
        _cleanup_provider(db_session, name)
