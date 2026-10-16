"""A saved API key is shared by reference across features: it lists where it is
used, a rotation reaches every user, and it goes away with its last user."""

from typing import Any
from uuid import uuid4

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.llm.constants import LlmProviderNames
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_KEY = "sk-" + "1" * 48
_ROTATED_KEY = "sk-" + "2" * 48


def _create_llm_provider(
    user: DATestUser, provider: str, api_key: str | dict[str, Any]
) -> dict[str, Any]:
    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=user.headers,
        json={
            "name": f"provider-{uuid4()}",
            "provider": provider,
            "api_key": api_key,
            "model_configurations": [{"name": "gpt-4o-mini", "is_visible": True}],
            "is_public": True,
            "groups": [],
        },
    )
    return {"status": response.status_code, **response.json()}


def _create_image_gen_config(
    user: DATestUser, api_key: dict[str, Any]
) -> dict[str, Any]:
    response = client.post(
        f"{API_SERVER_URL}/admin/image-generation/config",
        headers=user.headers,
        json={
            "image_provider_id": f"image-{uuid4()}",
            "model_name": "gpt-image-1",
            "provider": LlmProviderNames.OPENAI,
            "api_key": api_key,
            "is_default": False,
        },
    )
    response.raise_for_status()
    return response.json()


def _list_tokens(user: DATestUser, platform: str) -> list[dict[str, Any]]:
    response = client.get(
        f"{API_SERVER_URL}/admin/api-tokens",
        params={"platform": platform},
        headers=user.headers,
    )
    response.raise_for_status()
    return response.json()


def _get_llm_provider(user: DATestUser, provider_id: int) -> dict[str, Any]:
    response = client.get(
        f"{API_SERVER_URL}/admin/llm/provider/{provider_id}", headers=user.headers
    )
    response.raise_for_status()
    return response.json()


def test_saved_key_is_shared_across_features(admin_user: DATestUser) -> None:
    # Precondition.
    llm_provider = _create_llm_provider(admin_user, LlmProviderNames.OPENAI, _KEY)
    token_id = llm_provider["api_token_id"]
    image_config = _create_image_gen_config(
        admin_user, {"type": "existing", "id": token_id}
    )

    # Under test.
    listed = {token["id"]: token for token in _list_tokens(admin_user, "openai")}

    # Postcondition.
    token = listed[token_id]
    assert token["masked_value"] == "sk-1...1111"
    assert {(usage["kind"], usage["name"]) for usage in token["usages"]} == {
        ("llm_provider", llm_provider["name"]),
        ("image_generation", image_config["image_provider_id"]),
    }


def test_rotating_a_key_reaches_every_user(admin_user: DATestUser) -> None:
    # Precondition.
    first = _create_llm_provider(admin_user, LlmProviderNames.OPENAI, _KEY)
    token_id = first["api_token_id"]
    second = _create_llm_provider(
        admin_user, LlmProviderNames.OPENAI, {"type": "existing", "id": token_id}
    )

    # Under test.
    response = client.patch(
        f"{API_SERVER_URL}/admin/api-tokens/{token_id}",
        headers=admin_user.headers,
        json={"value": _ROTATED_KEY},
    )
    response.raise_for_status()

    # Postcondition.
    for provider in (first, second):
        assert _get_llm_provider(admin_user, provider["id"])["api_key"] == (
            "sk-2...2222"
        )


def test_key_for_another_platform_is_rejected(admin_user: DATestUser) -> None:
    # Precondition.
    openai_provider = _create_llm_provider(admin_user, LlmProviderNames.OPENAI, _KEY)

    # Under test.
    result = _create_llm_provider(
        admin_user,
        LlmProviderNames.ANTHROPIC,
        {"type": "existing", "id": openai_provider["api_token_id"]},
    )

    # Postcondition.
    assert result["status"] == OnyxErrorCode.INVALID_INPUT.status_code


def test_key_is_deleted_with_its_last_user(admin_user: DATestUser) -> None:
    # Precondition.
    provider = _create_llm_provider(admin_user, LlmProviderNames.OPENAI, _KEY)
    token_id = provider["api_token_id"]

    # Under test.
    response = client.delete(
        f"{API_SERVER_URL}/admin/llm/provider/{provider['id']}?force=true",
        headers=admin_user.headers,
    )
    response.raise_for_status()

    # Postcondition.
    assert token_id not in {token["id"] for token in _list_tokens(admin_user, "openai")}


def test_only_admins_can_list_keys(basic_user: DATestUser) -> None:
    # Under test.
    response = client.get(
        f"{API_SERVER_URL}/admin/api-tokens",
        params={"platform": "openai"},
        headers=basic_user.headers,
    )

    # Postcondition.
    assert response.status_code == 403
