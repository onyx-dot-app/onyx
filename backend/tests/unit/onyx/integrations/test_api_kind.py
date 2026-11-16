"""The ``api`` integration kind, with the DB getters patched."""

import json
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ActionPolicy,
    ExternalAppType,
    GatedAppKind,
    IntegrationActionPolicyValue,
    IntegrationActionSource,
    IntegrationAuthMethod,
    IntegrationAuthMode,
    IntegrationKind,
)
from onyx.db.models import ExternalApp, Integration, IntegrationAction, Tool
from onyx.external_apps.matching.engine import WHOLE_DOMAIN_ACTION_TYPE
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.integrations.kinds import api as api_kind
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.kinds.base import ChatToolContext
from onyx.integrations.models import ApiShape
from onyx.integrations.registry import get_kind_handler
from onyx.tools.models import ToolApprovalScope
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool

DB = MagicMock(spec=Session)
HANDLER = ApiKindHandler()

OPENAPI_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Orders", "description": "Orders API", "version": "1"},
    "servers": [{"url": "https://api.orders.example.com/v1"}],
    "paths": {
        "/orders": {
            "get": {"operationId": "listOrders", "summary": "List orders"},
            "post": {
                "operationId": "createOrder",
                "summary": "Create an order",
                "requestBody": {
                    "content": {
                        "application/json": {
                            "schema": {
                                "type": "object",
                                "properties": {"item": {"type": "string"}},
                            }
                        }
                    }
                },
            },
        },
        "/orders/{order_id}": {
            "get": {
                "operationId": "getOrder",
                "summary": "Get one order for USER_EMAIL",
                "parameters": [
                    {
                        "name": "order_id",
                        "in": "path",
                        "required": True,
                        "schema": {"type": "string"},
                    }
                ],
            },
            "delete": {"operationId": "deleteOrder", "description": "Delete"},
        },
    },
}


def _integration() -> Integration:
    return Integration(
        id=21,
        kind=IntegrationKind.API,
        name="Orders API",
        auth_mode=IntegrationAuthMode.NONE,
    )


def _use_openapi_tool(monkeypatch: pytest.MonkeyPatch) -> Tool:
    tool = Tool(id=5, name="orders", openapi_schema=OPENAPI_SPEC)
    monkeypatch.setattr(api_kind, "get_openapi_tool_for_integration", lambda *_: tool)
    monkeypatch.setattr(api_kind, "get_external_app_for_integration", lambda *_: None)
    return tool


def _use_external_app(
    monkeypatch: pytest.MonkeyPatch, app_type: ExternalAppType, patterns: list[str]
) -> ExternalApp:
    app = ExternalApp(
        id=9,
        name="old-name",
        app_type=app_type,
        upstream_url_patterns=patterns,
        auth_template={},
    )
    monkeypatch.setattr(api_kind, "get_openapi_tool_for_integration", lambda *_: None)
    monkeypatch.setattr(api_kind, "get_external_app_for_integration", lambda *_: app)
    return app


def _request(method: str, url: str, body: Any = None) -> ProxiedRequest:
    path = "/" + url.split("://", 1)[1].split("/", 1)[1] if "/" in url[8:] else "/"
    return ProxiedRequest(
        method=method,
        path=path,
        body=json.dumps(body).encode() if body is not None else None,
        url=url,
    )


def test_registry_returns_the_api_handler() -> None:
    assert isinstance(get_kind_handler(IntegrationKind.API), ApiKindHandler)


# OpenAPI


def test_openapi_discover_actions_defaults(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_openapi_tool(monkeypatch)

    specs = HANDLER.discover_actions(_integration(), DB)

    assert [
        (s.key, s.http_method, s.path_template, s.read_only, s.default_policy)
        for s in specs
    ] == [
        ("listOrders", "GET", "/orders", True, IntegrationActionPolicyValue.ALLOW),
        ("createOrder", "POST", "/orders", False, IntegrationActionPolicyValue.ASK),
        (
            "getOrder",
            "GET",
            "/orders/{order_id}",
            True,
            IntegrationActionPolicyValue.ALLOW,
        ),
        (
            "deleteOrder",
            "DELETE",
            "/orders/{order_id}",
            False,
            IntegrationActionPolicyValue.ASK,
        ),
    ]
    assert all(s.source is IntegrationActionSource.OPENAPI for s in specs)
    create = specs[1]
    assert create.display_name == "createOrder"
    assert create.description == "Create an order"
    assert create.input_schema == {
        "type": "object",
        "properties": {
            "requestBody": {
                "type": "object",
                "properties": {"item": {"type": "string"}},
            }
        },
    }


def test_openapi_config_and_auth_methods(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_openapi_tool(monkeypatch)
    config = HANDLER.load_config(_integration(), DB)
    assert config.shape is ApiShape.OPENAPI
    assert config.tool_id == 5
    assert config.base_url == "https://api.orders.example.com/v1"
    assert HANDLER.auth_methods(_integration(), DB) == frozenset(
        {
            IntegrationAuthMethod.OAUTH2,
            IntegrationAuthMethod.API_KEY,
            IntegrationAuthMethod.ONYX_LOGIN,
        }
    )


@pytest.mark.parametrize(
    "method,url,expected",
    [
        ("GET", "https://api.orders.example.com/v1/orders", ["listOrders"]),
        ("post", "https://api.orders.example.com/v1/orders/", ["createOrder"]),
        ("GET", "https://api.orders.example.com/v1/orders/42?x=1", ["getOrder"]),
        ("DELETE", "https://api.orders.example.com/v1/orders/42", ["deleteOrder"]),
        # On the server, but no operation: one whole-domain action that asks.
        ("PUT", "https://api.orders.example.com/v1/orders/42", ["unspecified"]),
        ("GET", "https://api.orders.example.com/v1/orders/42/x", ["unspecified"]),
    ],
)
def test_openapi_match_method_and_path_template(
    monkeypatch: pytest.MonkeyPatch, method: str, url: str, expected: list[str]
) -> None:
    _use_openapi_tool(monkeypatch)

    matched = HANDLER.match_request(_integration(), _request(method, url), DB)

    assert matched is not None
    assert [m.action_key for m in matched] == expected
    if expected == [WHOLE_DOMAIN_ACTION_TYPE]:
        assert matched[0].default_policy is IntegrationActionPolicyValue.ASK


def test_openapi_match_policy_follows_the_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_openapi_tool(monkeypatch)
    get = HANDLER.match_request(
        _integration(),
        _request("GET", "https://api.orders.example.com/v1/orders/1"),
        DB,
    )
    delete = HANDLER.match_request(
        _integration(),
        _request("DELETE", "https://api.orders.example.com/v1/orders/1"),
        DB,
    )
    assert get is not None and delete is not None
    assert get[0].default_policy is IntegrationActionPolicyValue.ALLOW
    assert delete[0].default_policy is IntegrationActionPolicyValue.ASK


@pytest.mark.parametrize(
    "url",
    [
        "https://other.example.com/v1/orders",
        "https://api.orders.example.com/v2/orders",
        "https://api.orders.example.com/v1x/orders",
        "http://api.orders.example.com/v1/orders",
        "https://api.orders.example.com/v1/../admin",
    ],
)
def test_openapi_match_outside_the_server_url_is_none(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    _use_openapi_tool(monkeypatch)
    assert HANDLER.match_request(_integration(), _request("GET", url), DB) is None


def test_openapi_build_chat_tools_keeps_names_placeholders_and_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_openapi_tool(monkeypatch)
    scope = ToolApprovalScope(
        app_kind=GatedAppKind.MCP_SERVER, target_id=21, action_id="getOrder"
    )
    actions = [
        IntegrationAction(key="getOrder"),
        IntegrationAction(key="createOrder"),
    ]
    ctx = ChatToolContext(
        user_id=uuid4(),
        user_email="pat@example.com",
        chat_session_id=uuid4(),
        custom_headers={"X-Key": "secret"},
        approval_for=lambda key: scope if key == "getOrder" else None,
    )

    tools = HANDLER.build_chat_tools(_integration(), actions, ctx, DB)

    assert all(isinstance(t, CustomTool) for t in tools)
    by_key = {t.display_name: t for t in tools}
    assert set(by_key) == {"getOrder", "createOrder"}
    get_order = by_key["getOrder"]
    assert get_order.name == "custom__5__getOrder"
    assert get_order.approval == scope
    assert by_key["createOrder"].approval is None
    assert get_order.description == "Get one order for pat@example.com"
    assert isinstance(get_order, CustomTool)
    assert get_order.headers == {"X-Key": "secret"}
    assert get_order.bind(MagicMock()).approval_required == frozenset({get_order.name})


def test_openapi_build_chat_tools_with_no_actions_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_openapi_tool(monkeypatch)
    assert HANDLER.build_chat_tools(_integration(), [], ChatToolContext(), DB) == []


# Presets


def test_preset_discover_actions_follow_the_catalog(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.LINEAR, [r"https://api\.linear\.app/.*"]
    )

    specs = HANDLER.discover_actions(_integration(), DB)
    catalog = get_endpoint_catalog(ExternalAppType.LINEAR)

    assert [s.key for s in specs] == [e.id.value for e in catalog]
    for spec, endpoint in zip(specs, catalog, strict=True):
        assert spec.source is IntegrationActionSource.EXTERNAL_APP
        assert spec.display_name == endpoint.normalised_name
        assert spec.description == endpoint.description
        assert spec.read_only is (endpoint.default_policy is ActionPolicy.ALWAYS)
        assert (
            spec.default_policy
            == {
                ActionPolicy.ALWAYS: IntegrationActionPolicyValue.ALLOW,
                ActionPolicy.ASK: IntegrationActionPolicyValue.ASK,
                ActionPolicy.DENY: IntegrationActionPolicyValue.BLOCKED,
            }[endpoint.default_policy]
        )
    assert HANDLER.load_config(_integration(), DB).shape is ApiShape.PRESET
    assert HANDLER.auth_methods(_integration(), DB) == frozenset(
        {IntegrationAuthMethod.OAUTH2}
    )


def test_preset_match_graphql(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.LINEAR, [r"https://api\.linear\.app/.*"]
    )

    matched = HANDLER.match_request(
        _integration(),
        _request(
            "POST",
            "https://api.linear.app/graphql",
            {"query": "query { viewer { id } }"},
        ),
        DB,
    )

    assert matched is not None
    assert [(m.action_key, m.default_policy) for m in matched] == [
        ("linear.viewer.read", IntegrationActionPolicyValue.ALLOW)
    ]
    assert matched[0].integration_id == 21


def test_preset_match_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.GITHUB, [r"https://api\.github\.com/.*"]
    )

    matched = HANDLER.match_request(
        _integration(),
        _request("GET", "https://api.github.com/repos/onyx/app/issues/3?page=2"),
        DB,
    )

    assert matched is not None
    assert [m.action_key for m in matched] == ["github.issues.read"]


def test_preset_match_on_another_host_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.GITHUB, [r"https://api\.github\.com/.*"]
    )
    assert (
        HANDLER.match_request(
            _integration(), _request("GET", "https://api.gitlab.com/user"), DB
        )
        is None
    )


def test_preset_build_chat_tools_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.GITHUB, [r"https://api\.github\.com/.*"]
    )
    actions = [IntegrationAction(key="github.user.read")]
    assert (
        HANDLER.build_chat_tools(_integration(), actions, ChatToolContext(), DB) == []
    )


# Custom apps


def test_custom_discover_one_whole_domain_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )

    (spec,) = HANDLER.discover_actions(_integration(), DB)

    assert spec.key == WHOLE_DOMAIN_ACTION_TYPE
    assert spec.display_name == "Orders API"
    assert spec.default_policy is IntegrationActionPolicyValue.ASK
    assert HANDLER.load_config(_integration(), DB).shape is ApiShape.CUSTOM
    assert HANDLER.auth_methods(_integration(), DB) == frozenset(
        {IntegrationAuthMethod.API_KEY}
    )


def test_custom_match_whole_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )

    matched = HANDLER.match_request(
        _integration(), _request("DELETE", "https://internal.example.com/a/b"), DB
    )
    other = HANDLER.match_request(
        _integration(), _request("GET", "https://elsewhere.example.com/a"), DB
    )

    assert matched is not None
    assert [(m.action_key, m.default_policy) for m in matched] == [
        (WHOLE_DOMAIN_ACTION_TYPE, IntegrationActionPolicyValue.ASK)
    ]
    assert other is None


def test_match_request_without_url_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    _use_external_app(
        monkeypatch, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )
    request = ProxiedRequest(method="GET", path="/a")
    assert HANDLER.match_request(_integration(), request, DB) is None
