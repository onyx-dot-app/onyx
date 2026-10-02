"""A save with keep_existing_models touches only the models it names: the
sent models are upserted, removed_model_names are deleted, and every other
stored model keeps its state."""

from onyx.server.manage.llm.models import (
    LLMProviderUpsertRequest,
    ModelConfigurationUpsertRequest,
)
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.llm_provider import LLMProviderManager
from tests.integration.common_utils.test_models import DATestLLMProvider, DATestUser


def _partial_save(
    user: DATestUser,
    provider: DATestLLMProvider,
    model_configurations: list[ModelConfigurationUpsertRequest],
    removed_model_names: list[str],
) -> int:
    request = LLMProviderUpsertRequest(
        id=provider.id,
        name=provider.name,
        provider=provider.provider,
        api_key_changed=False,
        keep_existing_models=True,
        model_configurations=model_configurations,
        removed_model_names=removed_model_names,
    )
    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        json=request.model_dump(),
        headers=user.headers,
    )
    return response.status_code


def _stored_models(user: DATestUser, provider_id: int) -> dict[str, dict]:
    response = client.get(
        f"{API_SERVER_URL}/admin/llm/provider/{provider_id}",
        headers=user.headers,
    )
    response.raise_for_status()
    return {mc["name"]: mc for mc in response.json()["model_configurations"]}


def test_partial_save_touches_only_the_named_models(
    new_admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="partial-default",
        model_names=["partial-hide", "partial-drop", "partial-keep"],
        set_as_default=False,
    )

    status = _partial_save(
        new_admin_user,
        provider,
        model_configurations=[
            ModelConfigurationUpsertRequest(name="partial-hide", is_visible=False),
            ModelConfigurationUpsertRequest(name="partial-new", is_visible=True),
        ],
        removed_model_names=["partial-drop"],
    )
    assert status == 200

    models = _stored_models(new_admin_user, provider.id)
    assert set(models) == {
        "partial-default",
        "partial-hide",
        "partial-keep",
        "partial-new",
    }
    assert models["partial-hide"]["is_visible"] is False
    assert models["partial-new"]["is_visible"] is True
    # Models the request did not mention keep their stored state.
    assert models["partial-keep"]["is_visible"] is True
    assert models["partial-keep"]["supports_image_input"] is True


def test_partial_save_cannot_remove_the_default_model(
    new_admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="partial-chat-default",
        model_names=["partial-other"],
        set_as_default=True,
    )

    status = _partial_save(
        new_admin_user,
        provider,
        model_configurations=[],
        removed_model_names=["partial-chat-default"],
    )
    assert status == 400
    assert "partial-chat-default" in _stored_models(new_admin_user, provider.id)


def test_partial_save_rejects_a_model_both_sent_and_removed(
    new_admin_user: DATestUser,
) -> None:
    provider = LLMProviderManager.create(
        user_performing_action=new_admin_user,
        default_model_name="partial-default",
        model_names=["partial-both"],
        set_as_default=False,
    )

    # Raw JSON: building the request model here would trip its validator first.
    response = client.put(
        f"{API_SERVER_URL}/admin/llm/provider",
        json={
            "id": provider.id,
            "provider": provider.provider,
            "keep_existing_models": True,
            "model_configurations": [{"name": "partial-both", "is_visible": False}],
            "removed_model_names": ["partial-both"],
        },
        headers=new_admin_user.headers,
    )
    assert response.status_code == 400
    assert _stored_models(new_admin_user, provider.id)["partial-both"]["is_visible"]
