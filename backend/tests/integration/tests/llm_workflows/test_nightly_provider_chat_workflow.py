import json
import os
import time
from uuid import uuid4

import pytest
import requests
from pydantic import BaseModel
from pydantic import ConfigDict

from onyx.configs import app_configs
from onyx.configs.constants import DocumentSource
from onyx.tools.constants import SEARCH_TOOL_ID
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.cc_pair import CCPairManager
from tests.integration.common_utils.managers.chat import ChatSessionManager
from tests.integration.common_utils.managers.tool import ToolManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.common_utils.test_models import ToolName


_ENV_PROVIDER = "NIGHTLY_LLM_PROVIDER"
_ENV_MODELS = "NIGHTLY_LLM_MODELS"
_ENV_API_KEY = "NIGHTLY_LLM_API_KEY"
_ENV_API_BASE = "NIGHTLY_LLM_API_BASE"
_ENV_CUSTOM_CONFIG_JSON = "NIGHTLY_LLM_CUSTOM_CONFIG_JSON"
_ENV_STRICT = "NIGHTLY_LLM_STRICT"


class NightlyProviderConfig(BaseModel):
    model_config = ConfigDict(frozen=True)

    provider: str
    model_names: list[str]
    api_key: str | None
    api_base: str | None
    custom_config: dict[str, str] | None
    strict: bool


def _env_true(env_var: str, default: bool = False) -> bool:
    value = os.environ.get(env_var)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv_env(env_var: str) -> list[str]:
    return [
        part.strip() for part in os.environ.get(env_var, "").split(",") if part.strip()
    ]


def _load_provider_config() -> NightlyProviderConfig:
    provider = os.environ.get(_ENV_PROVIDER, "").strip().lower()
    model_names = _split_csv_env(_ENV_MODELS)
    api_key = os.environ.get(_ENV_API_KEY) or None
    api_base = os.environ.get(_ENV_API_BASE) or None
    strict = _env_true(_ENV_STRICT, default=False)

    custom_config: dict[str, str] | None = None
    custom_config_json = os.environ.get(_ENV_CUSTOM_CONFIG_JSON, "").strip()
    if custom_config_json:
        parsed = json.loads(custom_config_json)
        if not isinstance(parsed, dict):
            raise ValueError(f"{_ENV_CUSTOM_CONFIG_JSON} must be a JSON object")
        custom_config = {str(key): str(value) for key, value in parsed.items()}

    if provider == "ollama_chat" and api_key and not custom_config:
        custom_config = {"OLLAMA_API_KEY": api_key}

    return NightlyProviderConfig(
        provider=provider,
        model_names=model_names,
        api_key=api_key,
        api_base=api_base,
        custom_config=custom_config,
        strict=strict,
    )


def _skip_or_fail(strict: bool, message: str) -> None:
    if strict:
        pytest.fail(message)
    pytest.skip(message)


def _validate_provider_config(config: NightlyProviderConfig) -> None:
    if not config.provider:
        _skip_or_fail(strict=config.strict, message=f"{_ENV_PROVIDER} must be set")

    if not config.model_names:
        _skip_or_fail(
            strict=config.strict,
            message=f"{_ENV_MODELS} must include at least one model",
        )

    if config.provider != "ollama_chat" and not config.api_key:
        _skip_or_fail(
            strict=config.strict,
            message=(f"{_ENV_API_KEY} is required for provider '{config.provider}'"),
        )

    if config.provider == "ollama_chat" and not (
        config.api_base or _default_api_base_for_provider(config.provider)
    ):
        _skip_or_fail(
            strict=config.strict,
            message=(f"{_ENV_API_BASE} is required for provider '{config.provider}'"),
        )


def _assert_integration_mode_enabled() -> None:
    assert (
        app_configs.INTEGRATION_TESTS_MODE is True
    ), "Integration tests require INTEGRATION_TESTS_MODE=true."


def _seed_connector_for_search_tool(admin_user: DATestUser) -> None:
    # SearchTool is only exposed when at least one non-default connector exists.
    CCPairManager.create_from_scratch(
        source=DocumentSource.INGESTION_API,
        user_performing_action=admin_user,
    )


def _get_internal_search_tool_id(admin_user: DATestUser) -> int:
    tools = ToolManager.list_tools(user_performing_action=admin_user)
    for tool in tools:
        if tool.in_code_tool_id == SEARCH_TOOL_ID:
            return tool.id
    raise AssertionError("SearchTool must exist for this test")


def _default_api_base_for_provider(provider: str) -> str | None:
    if provider == "openrouter":
        return "https://openrouter.ai/api/v1"
    if provider == "ollama_chat":
        # host.docker.internal works when tests are running inside the integration test container.
        return "http://host.docker.internal:11434"
    return None


def _create_provider_payload(
    provider: str,
    provider_name: str,
    model_name: str,
    api_key: str | None,
    api_base: str | None,
    custom_config: dict[str, str] | None,
) -> dict:
    return {
        "name": provider_name,
        "provider": provider,
        "api_key": api_key,
        "api_base": api_base,
        "custom_config": custom_config,
        "default_model_name": model_name,
        "is_public": True,
        "groups": [],
        "personas": [],
        "model_configurations": [{"name": model_name, "is_visible": True}],
        "api_key_changed": bool(api_key),
        "custom_config_changed": bool(custom_config),
    }


def _ensure_provider_is_default(provider_id: int, admin_user: DATestUser) -> None:
    list_response = requests.get(
        f"{API_SERVER_URL}/admin/llm/provider",
        headers=admin_user.headers,
    )
    list_response.raise_for_status()
    providers = list_response.json()

    current_default = next(
        (provider for provider in providers if provider.get("is_default_provider")),
        None,
    )
    assert (
        current_default is not None
    ), "Expected a default provider after setting provider as default"
    assert (
        current_default["id"] == provider_id
    ), f"Expected provider {provider_id} to be default, found {current_default['id']}"


def _run_chat_assertions(
    admin_user: DATestUser,
    search_tool_id: int,
    provider: str,
    model_name: str,
) -> None:
    last_error: str | None = None
    # Retry once to reduce transient nightly flakes due provider-side blips.
    for attempt in range(1, 3):
        chat_session = ChatSessionManager.create(user_performing_action=admin_user)

        response = ChatSessionManager.send_message(
            chat_session_id=chat_session.id,
            message=(
                "Use internal_search to search for 'nightly-provider-regression-sentinel', "
                "then summarize the result in one short sentence."
            ),
            user_performing_action=admin_user,
            forced_tool_ids=[search_tool_id],
        )

        if response.error is None:
            used_internal_search = any(
                used_tool.tool_name == ToolName.INTERNAL_SEARCH
                for used_tool in response.used_tools
            )
            debug_has_internal_search = any(
                debug_tool_call.tool_name == "internal_search"
                for debug_tool_call in response.tool_call_debug
            )
            has_answer = bool(response.full_message.strip())

            if used_internal_search and debug_has_internal_search and has_answer:
                return

            last_error = (
                f"attempt={attempt} provider={provider} model={model_name} "
                f"used_internal_search={used_internal_search} "
                f"debug_internal_search={debug_has_internal_search} "
                f"has_answer={has_answer} "
                f"tool_call_debug={response.tool_call_debug}"
            )
        else:
            last_error = (
                f"attempt={attempt} provider={provider} model={model_name} "
                f"stream_error={response.error.error}"
            )

        time.sleep(attempt)

    pytest.fail(f"Chat/tool-call assertions failed: {last_error}")


def _create_and_test_provider_for_model(
    admin_user: DATestUser,
    config: NightlyProviderConfig,
    model_name: str,
    search_tool_id: int,
) -> None:
    provider_name = f"nightly-{config.provider}-{uuid4().hex[:12]}"
    resolved_api_base = config.api_base or _default_api_base_for_provider(
        config.provider
    )

    provider_payload = _create_provider_payload(
        provider=config.provider,
        provider_name=provider_name,
        model_name=model_name,
        api_key=config.api_key,
        api_base=resolved_api_base,
        custom_config=config.custom_config,
    )

    test_response = requests.post(
        f"{API_SERVER_URL}/admin/llm/test",
        headers=admin_user.headers,
        json=provider_payload,
    )
    assert test_response.status_code == 200, (
        f"Provider test endpoint failed for provider={config.provider} "
        f"model={model_name}: {test_response.status_code} {test_response.text}"
    )

    create_response = requests.put(
        f"{API_SERVER_URL}/admin/llm/provider?is_creation=true",
        headers=admin_user.headers,
        json=provider_payload,
    )
    assert create_response.status_code == 200, (
        f"Provider creation failed for provider={config.provider} "
        f"model={model_name}: {create_response.status_code} {create_response.text}"
    )
    provider_id = create_response.json()["id"]

    try:
        set_default_response = requests.post(
            f"{API_SERVER_URL}/admin/llm/provider/{provider_id}/default",
            headers=admin_user.headers,
        )
        assert set_default_response.status_code == 200, (
            f"Setting default provider failed for provider={config.provider} "
            f"model={model_name}: {set_default_response.status_code} "
            f"{set_default_response.text}"
        )

        _ensure_provider_is_default(provider_id=provider_id, admin_user=admin_user)
        _run_chat_assertions(
            admin_user=admin_user,
            search_tool_id=search_tool_id,
            provider=config.provider,
            model_name=model_name,
        )
    finally:
        requests.delete(
            f"{API_SERVER_URL}/admin/llm/provider/{provider_id}",
            headers=admin_user.headers,
        )


def test_nightly_provider_chat_workflow(admin_user: DATestUser) -> None:
    """Nightly regression test for provider setup + default selection + chat tool calls."""
    _assert_integration_mode_enabled()
    config = _load_provider_config()
    _validate_provider_config(config)

    _seed_connector_for_search_tool(admin_user)
    search_tool_id = _get_internal_search_tool_id(admin_user)

    for model_name in config.model_names:
        _create_and_test_provider_for_model(
            admin_user=admin_user,
            config=config,
            model_name=model_name,
            search_tool_id=search_tool_id,
        )
