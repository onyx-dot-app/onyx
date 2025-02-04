import uuid

import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.test_models import DATestUser


_DEFAULT_MODELS = ["gpt-4", "gpt-4o"]


def _get_provider_by_id(admin_user: DATestUser, provider_id: str) -> dict | None:
    """Utility function to fetch an LLM provider by ID"""
    response = requests.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    assert response.status_code == 200
    providers = response.json()
    return next((p for p in providers if p["id"] == provider_id), None)


def test_create_llm_provider_without_display_model_names(
    admin_user: DATestUser,
) -> None:
    """Test creating an LLM provider without specifying
    display_model_names and verify it's null in response"""
    # Create LLM provider without model_names
    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "name": str(uuid.uuid4()),
            "provider": "openai",
            "default_model_name": _DEFAULT_MODELS[0],
            "model_names": _DEFAULT_MODELS,
            "is_public": True,
            "groups": [],
        },
    )
    assert response.status_code == 200
    created_provider = response.json()
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])

    # Verify model_names is None/null
    assert provider_data is not None
    assert provider_data["model_names"] == _DEFAULT_MODELS
    assert provider_data["default_model_name"] == _DEFAULT_MODELS[0]
    assert provider_data["display_model_names"] is None


def test_update_llm_provider_model_names(admin_user: DATestUser) -> None:
    """Test updating an LLM provider's model_names"""
    # First create provider without model_names
    name = str(uuid.uuid4())
    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "name": name,
            "provider": "openai",
            "default_model_name": _DEFAULT_MODELS[0],
            "model_names": [_DEFAULT_MODELS[0]],
            "is_public": True,
            "groups": [],
        },
    )
    assert response.status_code == 200
    created_provider = response.json()

    # Update with model_names
    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "id": created_provider["id"],
            "name": name,
            "provider": created_provider["provider"],
            "default_model_name": _DEFAULT_MODELS[0],
            "model_names": _DEFAULT_MODELS,
            "is_public": True,
            "groups": [],
        },
    )
    assert response.status_code == 200

    # Verify update
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is not None
    assert provider_data["model_names"] == _DEFAULT_MODELS


def test_delete_llm_provider(admin_user: DATestUser) -> None:
    """Test deleting an LLM provider"""
    # Create a provider
    response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
        json={
            "name": "test-provider-delete",
            "provider": "openai",
            "default_model_name": _DEFAULT_MODELS[0],
            "model_names": _DEFAULT_MODELS,
            "is_public": True,
            "groups": [],
        },
    )
    assert response.status_code == 200
    created_provider = response.json()

    # Delete the provider
    response = requests.delete(
        f"{API_SERVER_URL}/admin/llm/provider/{created_provider['id']}",
        headers=admin_user.headers,
    )
    assert response.status_code == 200

    # Verify provider is deleted by checking it's not in the list
    provider_data = _get_provider_by_id(admin_user, created_provider["id"])
    assert provider_data is None
