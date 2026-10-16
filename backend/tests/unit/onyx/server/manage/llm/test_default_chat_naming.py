from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.enums import LLMModelFlowType, Permission, PermissionAuthority
from onyx.db.llm import ModelConfigurationWindow
from onyx.db.models import (
    ApiToken,
    LLMModelFlow,
    LLMProvider,
    ModelConfiguration,
    Persona,
    User,
)
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.manage.llm import api
from onyx.server.manage.llm.models import DefaultModel
from onyx.server.manage.llm.provider_cache import ProviderListingCacheLookup
from onyx.utils.sensitive import make_mock_sensitive_value


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(api.admin_router)
    register_onyx_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: User()
    app.dependency_overrides[api.get_session] = lambda: MagicMock(spec=Session)
    with TestClient(app) as test_client:
        yield test_client


def test_manage_llms_permission_can_set_and_clear_chat_naming(
    client: TestClient,
) -> None:
    def permission_for_user(_: User, permission: Permission) -> PermissionAuthority:
        return (
            PermissionAuthority.GLOBAL
            if permission == Permission.MANAGE_LLMS
            else PermissionAuthority.NONE
        )

    with (
        patch("onyx.auth.permissions.has_permission", side_effect=permission_for_user),
        patch.object(api, "update_default_chat_naming_provider") as set_default,
        patch.object(api, "update_no_default_chat_naming_provider") as clear_default,
        patch.object(api, "invalidate_provider_listing_cache") as invalidate,
    ):
        response = client.post(
            "/admin/llm/default-chat-naming",
            json={"provider_id": 7, "model_name": "gpt-5-nano"},
        )
        assert (response.status_code, response.json()) == (200, None)
        assert set_default.call_args.kwargs["provider_id"] == 7
        assert set_default.call_args.kwargs["chat_naming_model"] == "gpt-5-nano"
        assert isinstance(set_default.call_args.kwargs["db_session"], MagicMock)

        response = client.delete("/admin/llm/default-chat-naming")
        assert (response.status_code, response.json()) == (200, None)
        assert isinstance(clear_default.call_args.kwargs["db_session"], MagicMock)
        assert invalidate.call_count == 2


@pytest.mark.parametrize("method", ["post", "delete"])
def test_retired_fast_endpoints_are_not_available(
    client: TestClient, method: str
) -> None:
    response = client.request(
        method,
        "/admin/llm/default-fast",
        json={"provider_id": 7, "model_name": "gpt-5-nano"},
    )
    assert response.status_code == 404


@pytest.mark.parametrize("method", ["post", "delete"])
def test_chat_naming_mutation_rejects_users_without_manage_llms(
    client: TestClient, method: str
) -> None:
    with (
        patch(
            "onyx.auth.permissions.has_permission",
            return_value=PermissionAuthority.NONE,
        ),
        patch.object(api, "update_default_chat_naming_provider") as set_default,
        patch.object(api, "update_no_default_chat_naming_provider") as clear_default,
    ):
        response = client.request(
            method,
            "/admin/llm/default-chat-naming",
            json={"provider_id": 7, "model_name": "gpt-5-nano"},
        )
    assert response.status_code == 403
    assert response.json()["error_code"] == "INSUFFICIENT_PERMISSIONS"
    set_default.assert_not_called()
    clear_default.assert_not_called()


def test_invalid_chat_naming_selection_returns_a_validation_error(
    client: TestClient,
) -> None:
    with (
        patch(
            "onyx.auth.permissions.has_permission",
            return_value=PermissionAuthority.GLOBAL,
        ),
        patch.object(
            api,
            "update_default_chat_naming_provider",
            side_effect=ValueError("Unknown model"),
        ),
        patch.object(api, "invalidate_provider_listing_cache") as invalidate,
    ):
        response = client.post(
            "/admin/llm/default-chat-naming",
            json={"provider_id": 7, "model_name": "missing-model"},
        )
    assert response.status_code == 400
    assert response.json() == {
        "error_code": "VALIDATION_ERROR",
        "detail": "Unknown model",
    }
    invalidate.assert_not_called()


def _provider_with_chat_naming() -> tuple[
    LLMProvider, ModelConfiguration, ModelConfiguration
]:
    provider = LLMProvider(
        id=7,
        name="Workspace provider",
        provider="openai",
        is_public=True,
        is_auto_mode=False,
        api_token=ApiToken(
            platform="openai",
            value=make_mock_sensitive_value("sk-test-workspace-key-123456789"),
        ),
        custom_config={"api_key": "workspace-custom-secret"},
        groups=[],
        personas=[],
    )
    visible = ModelConfiguration(
        id=70,
        llm_provider=provider,
        llm_provider_id=provider.id,
        name="gpt-5-mini",
        display_name="Chat model",
        is_visible=True,
        is_router=False,
        max_input_tokens=16000,
        llm_model_flows=[LLMModelFlow(llm_model_flow_type=LLMModelFlowType.CHAT)],
    )
    hidden_chat_naming = ModelConfiguration(
        id=71,
        llm_provider=provider,
        llm_provider_id=provider.id,
        name="gpt-5-nano",
        display_name="Utility model",
        is_visible=False,
        is_router=False,
        max_input_tokens=8000,
        llm_model_flows=[
            LLMModelFlow(llm_model_flow_type=LLMModelFlowType.CHAT),
            LLMModelFlow(
                llm_model_flow_type=LLMModelFlowType.CHAT_NAMING, is_default=True
            ),
        ],
    )
    return provider, visible, hidden_chat_naming


@pytest.fixture
def listing_defaults() -> Generator[None, None, None]:
    with (
        patch.object(api, "fetch_default_llm_model", return_value=None),
        patch.object(api, "fetch_default_vision_model", return_value=None),
        patch.object(api, "fetch_default_chat_naming_model", return_value=None),
        patch.object(api, "fetch_default_craft_model", return_value=None),
        patch.object(api, "fetch_default_search_selection_model", return_value=None),
        patch.object(api, "has_global_permission", return_value=False),
        patch.object(api, "fetch_user_group_ids", return_value=set()),
        patch.object(
            api,
            "get_cached_provider_listing",
            return_value=ProviderListingCacheLookup(response=None, version=None),
        ),
        patch.object(api, "cache_provider_listing"),
    ):
        yield


@pytest.mark.usefixtures("listing_defaults")
def test_admin_listing_pins_hidden_chat_naming_and_masks_credentials() -> None:
    provider, visible, naming = _provider_with_chat_naming()
    with (
        patch.object(api, "fetch_existing_llm_providers", return_value=[provider]),
        patch.object(api, "fetch_default_chat_naming_model", return_value=naming),
        patch.object(
            api,
            "fetch_model_configurations_page",
            return_value={
                7: ModelConfigurationWindow(
                    model_configurations=[visible], next_offset=1
                )
            },
        ),
    ):
        response = api.list_llm_providers(
            include_image_gen=False,
            page_models=True,
            _=User(),
            db_session=MagicMock(spec=Session),
        )

    assert response.default_chat_naming == DefaultModel(
        provider_id=7, model_name="gpt-5-nano"
    )
    assert "default_fast" not in response.model_dump()
    assert [
        (model.name, model.is_visible)
        for model in response.providers[0].model_configurations
    ] == [("gpt-5-mini", True), ("gpt-5-nano", False)]
    assert response.providers[0].next_model_configuration_offset == 1
    payload = response.model_dump_json()
    assert "sk-test-workspace-key-123456789" not in payload
    assert "workspace-custom-secret" not in payload


@pytest.mark.usefixtures("listing_defaults")
@pytest.mark.parametrize("persona_id", [None, 42])
@pytest.mark.parametrize("provider_is_public", [False, True])
def test_user_listings_do_not_publish_or_pin_chat_naming(
    persona_id: int | None, provider_is_public: bool
) -> None:
    provider, visible, naming = _provider_with_chat_naming()
    provider.is_public = provider_is_public
    with (
        patch.object(api, "fetch_existing_llm_providers", return_value=[provider]),
        patch.object(api, "fetch_default_chat_naming_model", return_value=naming),
        patch.object(
            api,
            "fetch_model_configurations_page",
            return_value={
                7: ModelConfigurationWindow(
                    model_configurations=[visible], next_offset=1
                )
            },
        ),
        patch.object(api, "_fetch_persona_for_listing", return_value=Persona(id=42)),
    ):
        if persona_id is None:
            response = api.list_llm_provider_basics(User(), MagicMock(spec=Session))
        else:
            response = api.list_llm_providers_for_persona(
                persona_id, User(), MagicMock(spec=Session)
            )

    assert response.default_chat_naming is None
    assert "gpt-5-nano" not in response.model_dump_json()
    assert [item.id for item in response.providers] == (
        [7] if provider_is_public else []
    )
    if provider_is_public:
        assert [model.name for model in response.providers[0].model_configurations] == [
            "gpt-5-mini"
        ]
        assert response.providers[0].next_model_configuration_offset == 1
