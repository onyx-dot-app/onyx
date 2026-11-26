"""The ``api`` integration kind, with the DB getters patched."""

import json
import time
from typing import Any
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    ExternalAppType,
    IntegrationActionPolicyValue,
    IntegrationAuthMode,
    IntegrationKind,
)
from onyx.db.models import ExternalApp, Integration, IntegrationAction, Tool
from onyx.external_apps.matching.engine import WHOLE_DOMAIN_ACTION_TYPE
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.call_credentials import CallCredentials
from onyx.integrations.kinds import api as api_kind
from onyx.integrations.kinds.api import ApiKindHandler
from onyx.integrations.kinds.models import ChatToolContext
from onyx.integrations.models import ApiShape
from onyx.sandbox_proxy.resolvers.mcp_matching import IntegrationMatchTarget
from onyx.sandbox_proxy.usable_integrations import (
    app_match_target,
    openapi_match_target,
)
from onyx.tools.models import IntegrationActionRef, ToolApprovalScope
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from onyx.tools.tool_implementations.custom.openapi_parsing import (
    openapi_to_method_specs,
)

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


def _integration(tool_id: int | None, external_app_id: int | None) -> Integration:
    return Integration(
        id=21,
        kind=IntegrationKind.API,
        name="Orders API",
        auth_mode=IntegrationAuthMode.NONE,
        tool_id=tool_id,
        external_app_id=external_app_id,
    )


def _use_openapi_tool(
    monkeypatch: pytest.MonkeyPatch, spec: dict[str, Any] = OPENAPI_SPEC
) -> tuple[Integration, IntegrationMatchTarget]:
    """Patch the tool getter and the stored actions that the sync writes."""
    tool = Tool(id=5, name="orders", openapi_schema=spec)
    rows = [
        IntegrationAction(**action.model_dump())
        for action in (
            api_kind.openapi_action_spec(method_spec)
            for method_spec in openapi_to_method_specs(spec)
        )
    ]
    monkeypatch.setattr(api_kind, "get_openapi_tool_for_integration", lambda *_: tool)
    monkeypatch.setattr(api_kind, "list_integration_actions", lambda *_: rows)
    target = openapi_match_target(21, spec)
    assert target is not None
    return _integration(tool_id=tool.id, external_app_id=None), target


def _use_external_app(
    monkeypatch: pytest.MonkeyPatch, app_type: ExternalAppType, patterns: list[str]
) -> tuple[Integration, IntegrationMatchTarget]:
    app = ExternalApp(
        id=9,
        name="old-name",
        app_type=app_type,
        upstream_url_patterns=patterns,
        auth_template={},
    )
    monkeypatch.setattr(api_kind, "get_external_app_for_integration", lambda *_: app)
    return _integration(tool_id=None, external_app_id=app.id), app_match_target(21, app)


def _request(method: str, url: str, body: Any = None) -> ProxiedRequest:
    path = "/" + url.split("://", 1)[1].split("/", 1)[1] if "/" in url[8:] else "/"
    return ProxiedRequest(
        method=method,
        path=path,
        body=json.dumps(body).encode() if body is not None else None,
        url=url,
    )


# OpenAPI


def test_openapi_config(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, target = _use_openapi_tool(monkeypatch)
    config = HANDLER.load_config(integration, DB)
    assert config.shape is ApiShape.OPENAPI
    assert config.tool_id == 5
    assert config.base_url == "https://api.orders.example.com/v1"


def test_openapi_action_display_name_is_the_summary_else_the_operation_id() -> None:
    names = {
        spec.key: spec.display_name
        for spec in (
            api_kind.openapi_action_spec(method_spec)
            for method_spec in openapi_to_method_specs(OPENAPI_SPEC)
        )
    }
    assert names == {
        "listOrders": "List orders",
        "createOrder": "Create an order",
        "getOrder": "Get one order for USER_EMAIL",
        "deleteOrder": "deleteOrder",
    }


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
    integration, target = _use_openapi_tool(monkeypatch)

    matched = HANDLER.match_request(integration, target, _request(method, url), DB)

    assert matched is not None
    assert [m.action_key for m in matched.actions] == expected
    if expected == [WHOLE_DOMAIN_ACTION_TYPE]:
        assert matched.actions[0].default_policy is IntegrationActionPolicyValue.ASK


def test_openapi_match_policy_follows_the_method(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration, target = _use_openapi_tool(monkeypatch)
    get = HANDLER.match_request(
        integration,
        target,
        _request("GET", "https://api.orders.example.com/v1/orders/1"),
        DB,
    )
    delete = HANDLER.match_request(
        integration,
        target,
        _request("DELETE", "https://api.orders.example.com/v1/orders/1"),
        DB,
    )
    assert get is not None and delete is not None
    assert get.actions[0].default_policy is IntegrationActionPolicyValue.ALLOW
    assert delete.actions[0].default_policy is IntegrationActionPolicyValue.ASK


def _get(operation_id: str, *parameters: str) -> dict[str, Any]:
    return {
        "get": {
            "operationId": operation_id,
            "summary": operation_id,
            "parameters": [
                {
                    "name": name,
                    "in": "path",
                    "required": True,
                    "schema": {"type": "string"},
                }
                for name in parameters
            ],
        }
    }


FILES_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Files", "description": "Files API", "version": "1"},
    "servers": [{"url": "https://api.files.example.com/v1"}],
    "paths": {
        "/files/{id}.json": _get("downloadFile", "id"),
        "/files/v{version}-{id}": _get("getVersion", "version", "id"),
        "/files/mine": _get("listMyFiles"),
        "/files/{id}": _get("getFile", "id"),
    },
}


@pytest.mark.parametrize(
    "path,expected",
    [
        ("/files/42.json", ["downloadFile"]),
        ("/files/v2-42", ["getVersion"]),
        # A concrete path wins over a templated one.
        ("/files/mine", ["listMyFiles"]),
        ("/files/42", ["getFile"]),
        ("/files/.json", ["getFile"]),
    ],
)
def test_openapi_match_parameters_inside_a_segment_and_concrete_paths_first(
    monkeypatch: pytest.MonkeyPatch, path: str, expected: list[str]
) -> None:
    integration, target = _use_openapi_tool(monkeypatch, FILES_SPEC)

    matched = HANDLER.match_request(
        integration,
        target,
        _request("GET", f"https://api.files.example.com/v1{path}"),
        DB,
    )

    assert matched is not None
    assert [m.action_key for m in matched.actions] == expected


METHODS_SPEC: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Files", "description": "Files API", "version": "1"},
    "servers": [{"url": "https://api.files.example.com/team%20one"}],
    "paths": {
        "/files/mine": {"post": {"operationId": "uploadMine", "summary": "Upload"}},
        "/files/{id}": _get("getFile", "id"),
    },
}


@pytest.mark.parametrize(
    "method,path,expected",
    [
        ("GET", "/files/42", ["getFile"]),
        ("POST", "/files/mine", ["uploadMine"]),
        # The concrete path wins first. It has no GET, so the request asks.
        ("GET", "/files/mine", [WHOLE_DOMAIN_ACTION_TYPE]),
    ],
)
def test_openapi_match_picks_the_path_before_the_method_under_an_encoded_server_path(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, expected: list[str]
) -> None:
    integration, target = _use_openapi_tool(monkeypatch, METHODS_SPEC)

    matched = HANDLER.match_request(
        integration,
        target,
        _request(method, f"https://api.files.example.com/team%20one{path}"),
        DB,
    )

    assert matched is not None
    assert [m.action_key for m in matched.actions] == expected
    if expected == [WHOLE_DOMAIN_ACTION_TYPE]:
        assert matched.actions[0].default_policy is IntegrationActionPolicyValue.ASK


@pytest.mark.parametrize(
    "template,path,expected",
    [
        ("/files/{a}-{b}-{c}.json", "/files/x-y-z.json", True),
        ("/files/{a}-{b}-{c}.json", "/files/x--z.json", False),
        ("/files/{a}-{b}", "/files/x-y-z", True),
        ("/files/v{version}", "/files/v", False),
        ("/files/{id}", "/files/a/b", False),
        ("/", "/", True),
        ("/files/team%20one", "/files/team one", True),
        ("/files/team%20{id}", "/files/team one", True),
        ("/files/%7Bid%7D", "/files/{id}", True),
        ("/files/%7Bid%7D", "/files/x", False),
    ],
)
def test_openapi_path_matches(template: str, path: str, expected: bool) -> None:
    assert api_kind._openapi_path_matches(template, path) is expected


def test_openapi_path_match_takes_linear_time_on_a_long_segment() -> None:
    started = time.monotonic()

    matched = api_kind._openapi_path_matches(
        "/files/{a}-{b}-{c}.json", "/files/" + "-" * 5000
    )

    assert matched is False
    assert time.monotonic() - started < 1


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
    integration, target = _use_openapi_tool(monkeypatch)
    assert HANDLER.match_request(integration, target, _request("GET", url), DB) is None


def test_openapi_build_chat_tools_keeps_names_placeholders_and_approval(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration, target = _use_openapi_tool(monkeypatch)
    scope = ToolApprovalScope(integration_id=21, action_id="getOrder")
    actions = [
        IntegrationAction(key="getOrder"),
        IntegrationAction(key="createOrder"),
    ]
    ctx = ChatToolContext(
        user_id=uuid4(),
        user_email="pat@example.com",
        chat_session_id=uuid4(),
        credentials=_credentials({"X-Key": "secret"}),
        additional_headers={"X-Key": "request", "X-Trace": "1"},
        approval_for=lambda key: scope if key == "getOrder" else None,
    )

    tools = HANDLER.build_chat_tools(integration, actions, ctx, DB)

    assert all(isinstance(t, CustomTool) for t in tools)
    by_key = {t.display_name: t for t in tools}
    assert set(by_key) == {"getOrder", "createOrder"}
    get_order = by_key["getOrder"]
    assert get_order.name == "custom__21__getOrder"
    assert get_order.approval == scope
    assert by_key["createOrder"].approval is None
    assert get_order.description == "Get one order for pat@example.com"
    assert isinstance(get_order, CustomTool)
    # The credential wins over a request header of the same name.
    assert get_order.headers == {"X-Key": "secret", "X-Trace": "1"}
    assert get_order.id is None
    assert get_order.bind(MagicMock()).approval_required == frozenset({get_order.name})


def test_openapi_build_chat_tools_keys_actions_by_the_unsubstituted_operation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec: dict[str, Any] = {
        "openapi": "3.0.0",
        "info": {"title": "Me", "description": "Me API", "version": "1"},
        "servers": [{"url": "https://api.me.example.com"}],
        "paths": {"/me": {"get": {"operationId": "get_USER_ID", "summary": "Me"}}},
    }
    tool = Tool(id=6, name="me", openapi_schema=spec)
    monkeypatch.setattr(api_kind, "get_openapi_tool_for_integration", lambda *_: tool)
    integration = _integration(tool_id=tool.id, external_app_id=None)
    scope = ToolApprovalScope(integration_id=21, action_id="get_USER_ID")
    ctx = ChatToolContext(
        user_id=uuid4(),
        credentials=_credentials({}),
        approval_for=lambda key: scope if key == "get_USER_ID" else None,
    )

    tools = HANDLER.build_chat_tools(
        integration, [IntegrationAction(key="get_USER_ID")], ctx, DB
    )

    assert len(tools) == 1
    assert isinstance(tools[0], CustomTool)
    assert tools[0].approval == scope
    assert tools[0].integration_action == IntegrationActionRef(
        integration_id=integration.id, action="get_USER_ID"
    )


def test_openapi_build_chat_tools_with_no_actions_is_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration, target = _use_openapi_tool(monkeypatch)
    assert (
        HANDLER.build_chat_tools(
            integration, [], ChatToolContext(credentials=_credentials({})), DB
        )
        == []
    )


def _credentials(headers: dict[str, str]) -> CallCredentials:
    return CallCredentials(
        integration_id=5,
        auth_method=None,
        connection_id=None,
        connection_user_id=None,
        headers=headers,
    )


# Presets


def test_preset_match_graphql(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, target = _use_external_app(
        monkeypatch, ExternalAppType.LINEAR, [r"https://api\.linear\.app/.*"]
    )

    matched = HANDLER.match_request(
        integration,
        target,
        _request(
            "POST",
            "https://api.linear.app/graphql",
            {"query": "query { viewer { id } }"},
        ),
        DB,
    )

    assert matched is not None
    assert [(m.action_key, m.default_policy) for m in matched.actions] == [
        ("linear.viewer.read", IntegrationActionPolicyValue.ALLOW)
    ]
    assert matched.actions[0].integration_id == 21
    assert HANDLER.load_config(integration, DB).shape is ApiShape.PRESET


def test_preset_match_rest(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, target = _use_external_app(
        monkeypatch, ExternalAppType.GITHUB, [r"https://api\.github\.com/.*"]
    )

    matched = HANDLER.match_request(
        integration,
        target,
        _request("GET", "https://api.github.com/repos/onyx/app/issues/3?page=2"),
        DB,
    )

    assert matched is not None
    assert [m.action_key for m in matched.actions] == ["github.issues.read"]


def test_preset_match_on_another_host_is_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    integration, target = _use_external_app(
        monkeypatch, ExternalAppType.GITHUB, [r"https://api\.github\.com/.*"]
    )
    assert (
        HANDLER.match_request(
            integration, target, _request("GET", "https://api.gitlab.com/user"), DB
        )
        is None
    )


def test_preset_build_chat_tools_is_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, target = _use_external_app(
        monkeypatch, ExternalAppType.GITHUB, [r"https://api\.github\.com/.*"]
    )
    actions = [IntegrationAction(key="github.user.read")]
    assert (
        HANDLER.build_chat_tools(
            integration, actions, ChatToolContext(credentials=_credentials({})), DB
        )
        == []
    )


# Custom apps


def test_custom_match_whole_domain(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, target = _use_external_app(
        monkeypatch, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )

    matched = HANDLER.match_request(
        integration, target, _request("DELETE", "https://internal.example.com/a/b"), DB
    )
    other = HANDLER.match_request(
        integration, target, _request("GET", "https://elsewhere.example.com/a"), DB
    )

    assert matched is not None
    assert [(m.action_key, m.default_policy) for m in matched.actions] == [
        (WHOLE_DOMAIN_ACTION_TYPE, IntegrationActionPolicyValue.ASK)
    ]
    assert other is None
    assert HANDLER.load_config(integration, DB).shape is ApiShape.CUSTOM


def test_match_request_without_url_is_none(monkeypatch: pytest.MonkeyPatch) -> None:
    integration, target = _use_external_app(
        monkeypatch, ExternalAppType.CUSTOM, ["https://internal.example.com/**"]
    )
    request = ProxiedRequest(method="GET", path="/a")
    assert HANDLER.match_request(integration, target, request, DB) is None
