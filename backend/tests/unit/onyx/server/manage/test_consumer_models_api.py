from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.auth_check import check_router_auth
from onyx.server.manage.consumer_models_api import ConsumerModelPreferenceRequest
from onyx.server.manage.consumer_models_api import get_model_catalog
from onyx.server.manage.consumer_models_api import get_user_model_preference
from onyx.server.manage.consumer_models_api import router
from onyx.server.manage.consumer_models_api import update_user_model_preference


def test_get_model_catalog_returns_sanitized_profiles(monkeypatch) -> None:
    monkeypatch.setattr(
        "onyx.server.manage.consumer_models_api.CONSUMER_DEFAULT_LLM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "onyx.server.manage.consumer_models_api.CONSUMER_DEFAULT_LLM_API_KEY",
        "test-key",
    )

    response = get_model_catalog()
    serialized = response.model_dump()

    assert serialized["default_profile_id"] == "balanced"
    assert serialized["profiles"]
    assert "api_key" not in str(serialized)
    assert "api_base" not in str(serialized)


def test_consumer_model_routes_have_required_auth_dependencies() -> None:
    app = FastAPI()
    app.include_router(router)

    check_router_auth(app)


def test_get_model_catalog_reports_service_unavailable_when_key_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "onyx.server.manage.consumer_models_api.CONSUMER_DEFAULT_LLM_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "onyx.server.manage.consumer_models_api.CONSUMER_DEFAULT_LLM_API_KEY",
        None,
    )

    with pytest.raises(OnyxError) as exc_info:
        get_model_catalog()

    assert exc_info.value.error_code is OnyxErrorCode.SERVICE_UNAVAILABLE
    assert exc_info.value.detail == "模型服务暂不可用"


def test_get_user_model_preference_resolves_existing_default_model() -> None:
    user = SimpleNamespace(
        default_model="Qwen Coder__openai_compatible__qwen3-coder-plus"
    )

    response = get_user_model_preference(user=user)

    assert response.profile_id == "coding"


def test_update_user_model_preference_stores_structured_default_model(
    monkeypatch,
) -> None:
    update_user_default_model = Mock()
    monkeypatch.setattr(
        "onyx.server.manage.consumer_models_api.update_user_default_model",
        update_user_default_model,
    )
    user = SimpleNamespace(id="user-id")
    db_session = Mock()

    response = update_user_model_preference(
        request=ConsumerModelPreferenceRequest(profile_id="deep"),
        user=user,
        db_session=db_session,
    )

    assert response.profile_id == "deep"
    update_user_default_model.assert_called_once_with(
        "user-id", "Qwen Max__openai_compatible__qwen-max", db_session
    )
