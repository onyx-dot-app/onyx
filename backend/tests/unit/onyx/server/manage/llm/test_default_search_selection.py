from collections.abc import Generator
from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.enums import LLMModelFlowType, Permission, PermissionAuthority
from onyx.db.llm import ModelConfigurationWindow
from onyx.db.models import Persona, User
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.manage.llm import api
from onyx.server.manage.llm.models import DefaultModel
from tests.unit.onyx.server.manage.llm.test_default_chat_naming import (
    _provider_with_chat_naming,
)
from tests.unit.onyx.server.manage.llm.test_default_chat_naming import (
    listing_defaults as listing_defaults,
)


@pytest.fixture
def client() -> Generator[TestClient, None, None]:
    app = FastAPI()
    app.include_router(api.admin_router)
    register_onyx_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: User()
    app.dependency_overrides[api.get_session] = lambda: MagicMock(spec=Session)
    with TestClient(app) as test_client:
        yield test_client


def test_manage_llms_can_set_and_clear_search_selection(client: TestClient) -> None:
    with (
        patch(
            "onyx.auth.permissions.has_permission",
            side_effect=lambda _, permission: (
                PermissionAuthority.GLOBAL
                if permission == Permission.MANAGE_LLMS
                else PermissionAuthority.NONE
            ),
        ),
        patch.object(api, "update_default_search_selection_provider") as set_default,
        patch.object(
            api, "update_no_default_search_selection_provider"
        ) as clear_default,
        patch.object(api, "update_default_chat_naming_provider") as set_chat_naming,
        patch.object(
            api, "update_no_default_chat_naming_provider"
        ) as clear_chat_naming,
        patch.object(api, "invalidate_provider_listing_cache") as invalidate,
    ):
        response = client.post(
            "/admin/llm/default-search-selection",
            json={"provider_id": 7, "model_name": "gpt-5-mini"},
        )
        assert (response.status_code, response.json()) == (200, None)
        assert set_default.call_args.kwargs["provider_id"] == 7
        assert set_default.call_args.kwargs["model_name"] == "gpt-5-mini"
        response = client.delete("/admin/llm/default-search-selection")
        assert (response.status_code, response.json()) == (200, None)
        clear_default.assert_called_once()
        assert invalidate.call_count == 2
        set_chat_naming.assert_not_called()
        clear_chat_naming.assert_not_called()


@pytest.mark.parametrize("method", ["post", "delete"])
def test_search_selection_requires_manage_llms(client: TestClient, method: str) -> None:
    with (
        patch(
            "onyx.auth.permissions.has_permission",
            return_value=PermissionAuthority.NONE,
        ),
        patch.object(api, "update_default_search_selection_provider") as set_default,
        patch.object(
            api, "update_no_default_search_selection_provider"
        ) as clear_default,
    ):
        response = client.request(
            method,
            "/admin/llm/default-search-selection",
            json={"provider_id": 7, "model_name": "gpt-5-mini"},
        )
    assert response.status_code == 403
    set_default.assert_not_called()
    clear_default.assert_not_called()


def test_invalid_search_selection_returns_validation_error(client: TestClient) -> None:
    with (
        patch(
            "onyx.auth.permissions.has_permission",
            return_value=PermissionAuthority.GLOBAL,
        ),
        patch.object(
            api,
            "update_default_search_selection_provider",
            side_effect=ValueError("Unknown model"),
        ),
        patch.object(api, "invalidate_provider_listing_cache") as invalidate,
    ):
        response = client.post(
            "/admin/llm/default-search-selection",
            json={"provider_id": 7, "model_name": "missing-model"},
        )
    assert response.status_code == 400
    assert response.json() == {
        "error_code": "VALIDATION_ERROR",
        "detail": "Unknown model",
    }
    invalidate.assert_not_called()


@pytest.mark.usefixtures("listing_defaults")
def test_admin_pins_hidden_search_selection_without_changing_chat_naming() -> None:
    provider, visible, hidden = _provider_with_chat_naming()
    hidden.llm_model_flows[-1].llm_model_flow_type = LLMModelFlowType.SEARCH_SELECTION
    with (
        patch.object(api, "fetch_existing_llm_providers", return_value=[provider]),
        patch.object(
            api,
            "fetch_default_model",
            side_effect=lambda _db, flow: {
                LLMModelFlowType.CHAT_NAMING: visible,
                LLMModelFlowType.SEARCH_SELECTION: hidden,
            }.get(flow),
        ),
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
        provider_id=7, model_name="gpt-5-mini"
    )
    assert response.default_search_selection == DefaultModel(
        provider_id=7, model_name="gpt-5-nano"
    )
    assert [
        (model.name, model.is_visible)
        for model in response.providers[0].model_configurations
    ] == [("gpt-5-mini", True), ("gpt-5-nano", False)]
    assert "sk-test-workspace-key-123456789" not in response.model_dump_json()


@pytest.mark.usefixtures("listing_defaults")
@pytest.mark.parametrize("persona_id", [None, 42])
def test_user_listing_does_not_publish_search_selection(persona_id: int | None) -> None:
    provider, visible, hidden = _provider_with_chat_naming()
    with (
        patch.object(api, "fetch_existing_llm_providers", return_value=[provider]),
        patch.object(
            api,
            "fetch_default_model",
            side_effect=lambda _db, flow: {
                LLMModelFlowType.SEARCH_SELECTION: hidden
            }.get(flow),
        ) as fetch,
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
        response = (
            api.list_llm_provider_basics(User(), MagicMock(spec=Session))
            if persona_id is None
            else api.list_llm_providers_for_persona(
                persona_id, User(), MagicMock(spec=Session)
            )
        )
    assert response.default_search_selection is None
    assert "gpt-5-nano" not in response.model_dump_json()
    assert all(
        call.args[1] != LLMModelFlowType.SEARCH_SELECTION
        for call in fetch.call_args_list
    )
