"""The integration API against a live stack: the admin and member routes,
the permissions, the agent plugins, the public tool aliases and the removed
routes."""

from collections.abc import Generator
from typing import Any
from uuid import uuid4

import pytest

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.integration import IntegrationManager
from tests.integration.common_utils.test_models import DATestUser

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Weather", "description": "Weather", "version": "1.0"},
    "servers": [{"url": "https://weather.example.com"}],
    "paths": {
        "/forecast": {
            "get": {"operationId": "get_forecast", "summary": "Get the forecast"},
            "post": {"operationId": "set_alert", "summary": "Set an alert"},
        }
    },
}


def _openapi_body(
    *, for_organization: bool = True, auth_mode: str = "shared"
) -> dict[str, Any]:
    return {
        "for_organization": for_organization,
        "name": f"weather-{uuid4().hex[:8]}",
        "description": "Forecasts",
        "auth_mode": auth_mode,
        "auth_method": "api_key",
        "header_template": {"X-Api-Key": "{api_key}"},
        "config": {"shape": "openapi", "openapi_spec": OPENAPI_SPEC},
    }


@pytest.fixture
def created(admin_user: DATestUser) -> Generator[list[int], None, None]:
    ids: list[int] = []
    yield ids
    for integration_id in ids:
        IntegrationManager.delete(integration_id, admin_user)


def test_admin_create_read_update_delete(
    admin_user: DATestUser, created: list[int]
) -> None:
    detail = IntegrationManager.create(_openapi_body(), admin_user)
    created.append(detail.id)
    assert detail.shape.value == "openapi"
    assert detail.plugins[0].scope == "organization"
    assert detail.action_count == 2
    assert detail.needs_setup is True

    assert detail.id in {view.id for view in IntegrationManager.list_admin(admin_user)}
    assert IntegrationManager.get_admin(detail.id, admin_user).name == detail.name

    updated = IntegrationManager.update(detail.id, {"name": "Renamed"}, admin_user)
    assert updated.name == "Renamed"

    status = IntegrationManager.save_organization_connection(
        detail.id, {"api_key": "k"}, admin_user
    )
    assert status["state"] == "connected"
    status = IntegrationManager.delete_organization_connection(detail.id, admin_user)
    assert status["state"] == "not_set_up"

    assert IntegrationManager.delete(detail.id, admin_user).status_code == 204
    created.remove(detail.id)


def _craft_available(user: DATestUser) -> bool:
    response = client.get(f"{API_SERVER_URL}/settings", headers=user.headers)
    response.raise_for_status()
    return bool(response.json()["onyx_craft_available"])


def test_create_each_shape(admin_user: DATestUser, created: list[int]) -> None:
    custom_body: dict[str, Any] = {
        "name": f"custom-{uuid4().hex[:8]}",
        "auth_mode": "none",
        "config": {
            "shape": "custom",
            "upstream_url_patterns": ["https://api.custom.example.com/*"],
        },
    }
    presets = {preset.id for preset in IntegrationManager.presets(admin_user)}
    if _craft_available(admin_user):
        custom = IntegrationManager.create(custom_body, admin_user)
        created.append(custom.id)
        assert custom.shape.value == "custom"
        assert "GITHUB" in presets
    else:
        # Only Craft runs an external app.
        assert IntegrationManager.create_raw(custom_body, admin_user).status_code == 400
        assert presets == set()

    # Onyx loads the actions of a server with no sign-in before it saves
    # anything, so an unreachable server is refused.
    mcp_name = f"mcp-{uuid4().hex[:8]}"
    response = IntegrationManager.create_raw(
        {
            "name": mcp_name,
            "auth_mode": "none",
            "config": {
                "shape": "mcp_server",
                "server_url": "https://mcp.unreachable.example.com/mcp",
                "transport": "STREAMABLE_HTTP",
            },
        },
        admin_user,
    )
    assert response.status_code == 502
    assert mcp_name not in {
        view.name for view in IntegrationManager.list_admin(admin_user)
    }


def test_basic_user_cannot_use_admin_routes(
    admin_user: DATestUser, basic_user: DATestUser, created: list[int]
) -> None:
    assert IntegrationManager.create_raw(_openapi_body(), basic_user).status_code == 403
    detail = IntegrationManager.create(_openapi_body(), admin_user)
    created.append(detail.id)
    assert (
        IntegrationManager.update_raw(detail.id, {"name": "x"}, basic_user).status_code
        == 403
    )


def test_only_global_manager_sets_onyx_login(
    admin_user: DATestUser, created: list[int]
) -> None:
    body = _openapi_body()
    body["auth_mode"] = "individual"
    body["auth_method"] = "onyx_login"
    body["header_template"] = None
    detail = IntegrationManager.create(body, admin_user)
    created.append(detail.id)
    assert detail.auth_method is not None and detail.auth_method.value == "onyx_login"


def test_actions_get_put_and_refresh(
    admin_user: DATestUser, created: list[int]
) -> None:
    detail = IntegrationManager.create(_openapi_body(), admin_user)
    created.append(detail.id)
    actions = IntegrationManager.get_actions(detail.id, admin_user)
    defaults = {a.key: a.default_policy.value for a in actions.actions}
    assert defaults == {"get_forecast": "allow", "set_alert": "ask"}

    updated = IntegrationManager.set_actions(
        detail.id,
        {"default_policy": "blocked", "actions": {"get_forecast": "ask"}},
        admin_user,
    )
    effective = {a.key: a.effective_admin_policy.value for a in updated.actions}
    assert effective == {"get_forecast": "ask", "set_alert": "blocked"}

    refreshed = IntegrationManager.refresh_actions(detail.id, admin_user)
    assert {a.key for a in refreshed.actions} == {"get_forecast", "set_alert"}


def test_member_routes(
    admin_user: DATestUser, basic_user: DATestUser, created: list[int]
) -> None:
    detail = IntegrationManager.create(
        _openapi_body(auth_mode="individual"), admin_user
    )
    created.append(detail.id)

    listed = {view.id: view for view in IntegrationManager.list_member(basic_user)}
    assert listed[detail.id].status.state.value == "not_connected"
    assert (
        IntegrationManager.connect(detail.id, {"api_key": "mine"}, basic_user)["state"]
        == "connected"
    )

    response = IntegrationManager.set_grants_raw(
        detail.id, {"set_alert": "allow"}, basic_user
    )
    response.raise_for_status()
    grants = IntegrationManager.get_grants(detail.id, basic_user)
    assert {a.key: a.user_policy for a in grants.actions} == {
        "get_forecast": None,
        "set_alert": "allow",
    }
    assert IntegrationManager.get_member(detail.id, basic_user).id == detail.id
    IntegrationManager.set_grants_raw(
        detail.id, {"set_alert": None}, basic_user
    ).raise_for_status()
    assert all(
        action.user_policy is None
        for action in IntegrationManager.get_grants(detail.id, basic_user).actions
    )
    assert IntegrationManager.disconnect(detail.id, basic_user)["state"] == (
        "not_connected"
    )

    IntegrationManager.update(
        detail.id, {"users_can_save_always_allow": False}, admin_user
    )
    assert (
        IntegrationManager.set_grants_raw(
            detail.id, {"set_alert": "allow"}, basic_user
        ).status_code
        == 403
    )

    catalog = {
        option.plugin_id: option
        for option in IntegrationManager.agent_catalog(basic_user)
    }
    assert detail.plugins[0].plugin_id in catalog


def test_personal_integration_is_private(
    admin_user: DATestUser, basic_user: DATestUser, created: list[int]
) -> None:
    detail = IntegrationManager.create(
        _openapi_body(for_organization=False), admin_user
    )
    created.append(detail.id)
    assert detail.plugins[0].scope == "personal"
    assert IntegrationManager.get_member_raw(detail.id, basic_user).status_code == 404


def _persona_body(tool_ids: list[int], plugins: list[dict[str, Any]] | None) -> dict:
    return {
        "name": f"agent-{uuid4().hex[:8]}",
        "description": "",
        "document_set_ids": [],
        "tool_ids": tool_ids,
        "plugins": plugins,
        "system_prompt": "",
        "task_prompt": "",
        "datetime_aware": False,
    }


def test_persona_plugins_and_legacy_custom_tool_ids(
    admin_user: DATestUser, created: list[int]
) -> None:
    tool = client.post(
        f"{API_SERVER_URL}/admin/tool/custom",
        json={
            "name": f"alias-{uuid4().hex[:8]}",
            "definition": OPENAPI_SPEC,
            "passthrough_auth": False,
        },
        headers=admin_user.headers,
    )
    tool.raise_for_status()
    tool_id = tool.json()["id"]
    detail = next(
        view
        for view in IntegrationManager.list_admin(admin_user)
        if view.name == tool.json()["name"]
    )
    created.append(detail.id)
    plugin_id = str(detail.plugins[0].plugin_id)

    response = client.post(
        f"{API_SERVER_URL}/persona",
        json=_persona_body([tool_id], None),
        headers=admin_user.headers,
    )
    response.raise_for_status()
    persona_id = response.json()["id"]
    try:
        persona = client.get(
            f"{API_SERVER_URL}/persona/{persona_id}", headers=admin_user.headers
        ).json()
        assert [link["plugin_id"] for link in persona["plugins"]] == [plugin_id]

        body = _persona_body(
            [],
            [
                {
                    "plugin_id": plugin_id,
                    "action_settings": {
                        "default": "inherit",
                        "actions": {"set_alert": "blocked"},
                    },
                }
            ],
        )
        client.patch(
            f"{API_SERVER_URL}/persona/{persona_id}",
            json=body,
            headers=admin_user.headers,
        ).raise_for_status()
        persona = client.get(
            f"{API_SERVER_URL}/persona/{persona_id}", headers=admin_user.headers
        ).json()
        assert persona["plugins"][0]["action_settings"]["actions"] == {
            "set_alert": "blocked"
        }
    finally:
        client.delete(
            f"{API_SERVER_URL}/persona/{persona_id}", headers=admin_user.headers
        )


TOOL_SNAPSHOT_KEYS = {
    "id",
    "name",
    "description",
    "definition",
    "display_name",
    "in_code_tool_id",
    "custom_headers",
    "passthrough_auth",
    "mcp_server_id",
    "user_id",
    "oauth_config_id",
    "oauth_config_name",
    "enabled",
    "user_enabled_in_chat",
    "default_chat_enabled",
    "permissions",
    "chat_selectable",
    "agent_creation_selectable",
    "default_enabled",
    "default_action_policy",
    # Added for chat plugin toggles; new fields keep old callers working.
    "plugin_ids",
}


def test_public_tool_aliases_keep_their_shapes(
    admin_user: DATestUser, basic_user: DATestUser, created: list[int]
) -> None:
    validated = client.post(
        f"{API_SERVER_URL}/admin/tool/custom/validate",
        json={"definition": OPENAPI_SPEC},
        headers=admin_user.headers,
    )
    validated.raise_for_status()
    assert {m["raw_name"] for m in validated.json()["methods"]} == {
        "get_forecast",
        "set_alert",
    }

    response = client.post(
        f"{API_SERVER_URL}/admin/tool/custom",
        json={
            "name": f"alias-{uuid4().hex[:8]}",
            "description": "Alias",
            "definition": OPENAPI_SPEC,
            "custom_headers": [{"key": "X-Api-Key", "value": "secret"}],
            "passthrough_auth": False,
            "oauth_config_id": None,
            "default_chat_enabled": False,
        },
        headers=admin_user.headers,
    )
    response.raise_for_status()
    snapshot = response.json()
    assert set(snapshot) == TOOL_SNAPSHOT_KEYS
    tool_id = snapshot["id"]
    detail = next(
        view
        for view in IntegrationManager.list_admin(admin_user)
        if view.name == snapshot["name"]
    )
    created.append(detail.id)

    fetched = client.get(f"{API_SERVER_URL}/tool/{tool_id}", headers=basic_user.headers)
    fetched.raise_for_status()
    assert set(fetched.json()) == TOOL_SNAPSHOT_KEYS

    listed = client.get(f"{API_SERVER_URL}/tool", headers=basic_user.headers).json()
    assert tool_id in {item["id"] for item in listed}
    listed = client.get(
        f"{API_SERVER_URL}/tool/openapi", headers=admin_user.headers
    ).json()
    assert tool_id in {item["id"] for item in listed}

    updated = client.put(
        f"{API_SERVER_URL}/admin/tool/custom/{tool_id}",
        json={
            "name": "Renamed alias",
            "description": "Alias",
            "definition": OPENAPI_SPEC,
            "custom_headers": snapshot["custom_headers"],
            "passthrough_auth": False,
            "oauth_config_id": None,
            "default_chat_enabled": False,
        },
        headers=admin_user.headers,
    )
    updated.raise_for_status()
    assert updated.json()["name"] == "Renamed alias"

    preference = client.patch(
        f"{API_SERVER_URL}/tool/{tool_id}/preferences",
        json={"enabled_in_chat": False},
        headers=basic_user.headers,
    )
    preference.raise_for_status()
    assert preference.json() == {"enabled_in_chat": False}

    deleted = client.delete(
        f"{API_SERVER_URL}/admin/tool/custom/{tool_id}", headers=admin_user.headers
    )
    deleted.raise_for_status()
    created.remove(detail.id)
    assert (
        client.get(
            f"{API_SERVER_URL}/tool/{tool_id}", headers=admin_user.headers
        ).status_code
        == 404
    )


def _plugin_enabled_for(user: DATestUser, plugin_id: str) -> bool | None:
    for integration in IntegrationManager.list_member(user):
        for ref in integration.plugins:
            if str(ref.plugin_id) == plugin_id:
                return ref.enabled
    return None


def test_plugin_switch_and_install_setting(
    admin_user: DATestUser, basic_user: DATestUser, created: list[int]
) -> None:
    detail = IntegrationManager.create(_openapi_body(), admin_user)
    created.append(detail.id)
    plugin_id = str(detail.plugins[0].plugin_id)
    assert _plugin_enabled_for(basic_user, plugin_id) is False

    switch = client.put(
        f"{API_SERVER_URL}/plugins/{plugin_id}/enabled",
        json={"enabled": True},
        headers=basic_user.headers,
    )
    assert switch.status_code == 200, switch.text
    assert switch.json()["enabled"] is True
    assert _plugin_enabled_for(basic_user, plugin_id) is True

    policy_url = f"{API_SERVER_URL}/admin/plugins/{plugin_id}/installation-policy"
    body = {"installation_policy": "REQUIRED"}
    assert client.put(
        policy_url, json=body, headers=basic_user.headers
    ).status_code == (403)
    assert client.put(
        policy_url, json=body, headers=admin_user.headers
    ).status_code == (200)
    off = client.put(
        f"{API_SERVER_URL}/plugins/{plugin_id}/enabled",
        json={"enabled": False},
        headers=basic_user.headers,
    )
    assert off.status_code == 400


def test_owner_shares_and_publishes_a_private_plugin(
    admin_user: DATestUser, basic_user: DATestUser, created: list[int]
) -> None:
    detail = IntegrationManager.create(
        _openapi_body(for_organization=False), admin_user
    )
    created.append(detail.id)
    plugin_id = str(detail.plugins[0].plugin_id)
    access_url = f"{API_SERVER_URL}/plugins/{plugin_id}/access"
    assert client.get(access_url, headers=basic_user.headers).status_code == 404

    shared = client.put(
        access_url,
        json={
            "user_shares": [{"user_id": basic_user.id, "permission": "VIEWER"}],
            "group_shares": [],
        },
        headers=admin_user.headers,
    )
    assert shared.status_code == 200, shared.text
    assert [share["email"] for share in shared.json()["user_shares"]] == [
        basic_user.email
    ]
    assert _plugin_enabled_for(basic_user, plugin_id) is False
    assert (
        client.post(
            f"{API_SERVER_URL}/plugins/{plugin_id}/publish", headers=basic_user.headers
        ).status_code
        == 403
    )

    published = client.post(
        f"{API_SERVER_URL}/plugins/{plugin_id}/publish", headers=admin_user.headers
    )
    assert published.status_code == 200, published.text
    assert published.json()["plugin_id"] == str(plugin_id)
    assert IntegrationManager.get_admin(detail.id, admin_user).plugins[0].scope == (
        "organization"
    )
