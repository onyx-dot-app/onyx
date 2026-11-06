"""Image generation configs linked to an existing LLM provider reuse that
provider's credentials and never own or delete it."""

from typing import Any

import httpx
import pytest

from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.image_generation import (
    ImageGenerationConfigManager,
)
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser

CHAT_MODEL = "gpt-5.4-mini"
IMAGE_MODEL = "gpt-image-2"


@pytest.fixture(scope="module")
def admin_user() -> DATestUser:
    reset_all()
    return UserManager.create(name="admin_user")


@pytest.fixture(scope="module")
def llm_provider(admin_user: DATestUser) -> DATestLLMProvider:
    return LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key="sk-linked-test",
        default_model_name=CHAT_MODEL,
    )


def _provider_entry(admin_user: DATestUser, llm_provider_id: int) -> dict[str, Any]:
    providers = ImageGenerationConfigManager.list_llm_provider_models(admin_user)
    return next(p for p in providers if p["llm_provider_id"] == llm_provider_id)


def _chat_model_names(admin_user: DATestUser, llm_provider_id: int) -> list[str]:
    providers = LLMProviderManager.get_all(user_performing_action=admin_user)
    provider = next(p for p in providers if p.id == llm_provider_id)
    return [mc.name for mc in provider.model_configurations]


def test_lists_catalog_image_models_for_connected_provider(
    admin_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    models = {
        m["name"]: m for m in _provider_entry(admin_user, llm_provider.id)["models"]
    }
    assert models[IMAGE_MODEL]["is_recommended"] is True
    assert models[CHAT_MODEL]["is_recommended"] is False
    assert "gpt-image-1" not in models  # deprecated


def test_link_reuses_provider_and_survives_provider_edit(
    admin_user: DATestUser, llm_provider: DATestLLMProvider
) -> None:
    config = ImageGenerationConfigManager.link(
        llm_provider_id=llm_provider.id,
        model_name=IMAGE_MODEL,
        is_default=True,
        user_performing_action=admin_user,
    )
    assert config.llm_provider_id == llm_provider.id
    assert config.llm_provider_owned is False

    entry = _provider_entry(admin_user, llm_provider.id)
    linked = next(m for m in entry["models"] if m["name"] == IMAGE_MODEL)
    assert linked["image_provider_id"] == config.image_provider_id

    # The image model stays out of chat model lists.
    assert IMAGE_MODEL not in _chat_model_names(admin_user, llm_provider.id)

    # Saving the LLM provider without the image model keeps the link.
    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=false",
        json=LLMProviderUpsertRequest(
            id=llm_provider.id,
            name=llm_provider.name,
            provider=llm_provider.provider,
            api_key=None,
            api_key_changed=False,
            is_public=True,
            groups=[],
            personas=[],
            model_configurations=[
                ModelConfigurationUpsertRequest(
                    name=CHAT_MODEL, is_visible=True, max_input_tokens=None
                )
            ],
        ).model_dump(),
        headers=admin_user.headers,
    )
    response.raise_for_status()
    ImageGenerationConfigManager.verify(
        config=config, user_performing_action=admin_user
    )

    # Linked configs have no credentials of their own.
    response = client.get(
        f"{API_SERVER_URL}/admin/image-generation/config/{config.image_provider_id}/credentials",
        headers=admin_user.headers,
    )
    assert response.status_code == 400

    ImageGenerationConfigManager.delete(
        image_provider_id=config.image_provider_id,
        user_performing_action=admin_user,
    )
    ImageGenerationConfigManager.verify(
        config=config, verify_deleted=True, user_performing_action=admin_user
    )
    assert CHAT_MODEL in _chat_model_names(admin_user, llm_provider.id)


def test_link_rejects_private_provider(admin_user: DATestUser) -> None:
    private_provider = LLMProviderManager.create(
        user_performing_action=admin_user,
        api_key="sk-private-test",
        is_public=False,
        set_as_default=False,
    )
    with pytest.raises(httpx.HTTPStatusError) as exc_info:
        ImageGenerationConfigManager.link(
            llm_provider_id=private_provider.id,
            model_name=IMAGE_MODEL,
            user_performing_action=admin_user,
        )
    assert exc_info.value.response.status_code == 400
