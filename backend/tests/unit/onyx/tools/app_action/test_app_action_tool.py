"""The app action tool sends a request only when it is the action of the
tool, inside the URL scope of the app, and it adds the credential itself."""

import json
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from onyx.agents.tools import ToolInvocation
from onyx.db.enums import ExternalAppType, IntegrationAuthMethod
from onyx.external_apps.providers.registry import get_endpoint_catalog
from onyx.integrations.models import CallCredentials
from onyx.llm.cancellation import CancellationSignal
from onyx.llm.models import ToolResult
from onyx.server.security.models import SSRFProtectionLevel
from onyx.tools.models import CustomToolCallSummary, ToolContext
from onyx.tools.tool_implementations import http_request
from onyx.tools.tool_implementations.app_action.app_action_tool import (
    APP_ACTION_MAX_RESPONSE_BYTES,
    AppActionSettings,
    AppActionTool,
)

_SEND = "onyx.tools.tool_implementations.http_request.ssrf_safe_request"
_GITHUB_KEYS = ("github.issues.read", "github.issues.create", "unspecified")


@pytest.fixture(autouse=True)
def _self_hosted(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock()
    settings.ssrf_protection_level = SSRFProtectionLevel.VALIDATE_ALL
    monkeypatch.setattr(http_request, "get_security_settings", lambda: settings)
    monkeypatch.setattr(http_request, "MULTI_TENANT", False)


def _tool(
    action_key: str,
    app_type: ExternalAppType = ExternalAppType.GITHUB,
    regexes: tuple[str, ...] = (r"https://api\.github\.com/.*",),
    offered: tuple[str, ...] = _GITHUB_KEYS,
) -> AppActionTool:
    rules = {e.id.value: e.matches for e in get_endpoint_catalog(app_type)}
    return AppActionTool(
        AppActionSettings(
            integration_id=7,
            integration_name="GitHub",
            app_type=app_type,
            url_regexes=regexes,
            credentials=CallCredentials(
                integration_id=7,
                auth_method=None,
                connection_id=None,
                connection_user_id=None,
                headers={"Authorization": "Bearer real-token"},
            ),
            acting_user_id=None,
            offered_keys=frozenset(offered),
        ),
        action_key=action_key,
        display_name=action_key,
        description="Test action.",
        rules=rules.get(action_key, ()),
        approval=None,
    )


def _response(body: bytes = b'{"ok": true}', status: int = 200) -> MagicMock:
    response = MagicMock()
    response.is_redirect = False
    response.status_code = status
    response.headers = {"Content-Type": "application/json"}
    response.iter_content.return_value = [body]
    return response


def _run(tool: AppActionTool, **arguments: Any) -> ToolResult:
    result = tool.run(
        ToolInvocation(
            call_id="call",
            arguments=arguments,
            cancellation=CancellationSignal(),
            update=lambda _progress: None,
        ),
        ToolContext(),
    )
    assert isinstance(result, ToolResult)
    return result


def test_sends_the_request_of_its_action_with_the_credential() -> None:
    with patch(_SEND, return_value=_response()) as send:
        result = _run(
            _tool("github.issues.read"),
            method="get",
            url="https://api.github.com/repos/onyx/app/issues?state=open",
            headers={
                "Authorization": "Bearer from-the-model",
                "Cookie": "session=1",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )

    assert not result.is_error
    assert json.loads(result.content) == {"ok": True}
    args, kwargs = send.call_args
    assert args == ("https://api.github.com/repos/onyx/app/issues?state=open",)
    assert kwargs["method"] == "GET"
    assert kwargs["headers"] == {
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer real-token",
    }
    assert "real-token" not in result.content


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        # The request of a second action names the tool of that action.
        (
            {"method": "POST", "url": "https://api.github.com/repos/o/r/issues"},
            "app__7__github_issues_create",
        ),
        # A request that is no catalog action goes to the request tool.
        (
            {"method": "DELETE", "url": "https://api.github.com/repos/o/r"},
            "app__7__request",
        ),
        (
            {"method": "GET", "url": "https://api.github.com.evil.example/user"},
            "not a URL of GitHub",
        ),
        (
            {"method": "GET", "url": "http://api.github.com/repos/o/r/issues"},
            "not a URL of GitHub",
        ),
        (
            {"method": "GET", "url": "https://u:p@api.github.com/repos/o/r/issues"},
            "user info",
        ),
        (
            {
                "method": "GET",
                "url": "https://api.github.com/repos/o/r/issues/../../../../user",
            },
            "must not have",
        ),
        (
            {"method": "GET", "url": "https://api.github.com/repos/o/r/issues/%2e%2e"},
            "must not have",
        ),
        (
            {"method": "GET", "url": "https://api.github.com/repos/o/r%2Fx/issues"},
            "must not have",
        ),
        (
            {
                "method": "GET",
                "url": "https://api.github.com/repos/o/r/issues/%252e%252e",
            },
            "must not have",
        ),
    ],
)
def test_rejects_a_request_that_is_not_its_action(
    arguments: dict[str, Any], expected: str
) -> None:
    with patch(_SEND) as send:
        result = _run(_tool("github.issues.read"), **arguments)

    send.assert_not_called()
    assert result.is_error
    assert expected in result.content


def test_rejects_a_graphql_document_with_a_second_action() -> None:
    """A read tool must not carry a mutation in the same document."""
    tool = _tool(
        "linear.issues.read",
        ExternalAppType.LINEAR,
        (r"https://api\.linear\.app/.*",),
        ("linear.issues.read", "linear.issues.create", "unspecified"),
    )
    url = "https://api.linear.app/graphql"
    with patch(_SEND, return_value=_response()) as send:
        read = _run(
            tool, method="POST", url=url, body={"query": "{ issues { nodes { id } } }"}
        )
        mixed = _run(
            tool,
            method="POST",
            url=url,
            body={
                "query": "mutation { issueCreate(input: {}) { success } }"
                " query { issues { nodes { id } } }"
            },
        )
        unknown = _run(
            tool,
            method="POST",
            url=url,
            body={"query": "{ issues { nodes { id } } secretThing { id } }"},
        )

    assert not read.is_error
    assert send.call_count == 1
    assert mixed.is_error and unknown.is_error


def test_request_tool_takes_only_a_request_that_is_no_other_action() -> None:
    tool = _tool("unspecified")
    with patch(_SEND, return_value=_response()) as send:
        other = _run(tool, method="DELETE", url="https://api.github.com/repos/o/r")
        known = _run(tool, method="GET", url="https://api.github.com/repos/o/r/issues")

    assert not other.is_error
    assert send.call_count == 1
    assert known.is_error
    assert "app__7__github_issues_read" in known.content


def test_a_blocked_action_is_not_named() -> None:
    tool = _tool("unspecified", offered=("unspecified",))
    with patch(_SEND) as send:
        result = _run(tool, method="GET", url="https://api.github.com/repos/o/r/issues")
    send.assert_not_called()
    assert "not available" in result.content


def test_a_long_response_is_cut() -> None:
    body = b"x" * (APP_ACTION_MAX_RESPONSE_BYTES + 10)
    with patch(_SEND, return_value=_response(body)):
        result = _run(
            _tool("github.issues.read"),
            method="GET",
            url="https://api.github.com/repos/o/r/issues",
        )
    assert "response cut" in result.content
    assert len(result.content) < APP_ACTION_MAX_RESPONSE_BYTES + 100


def test_a_redirect_is_refused() -> None:
    response = _response(status=302)
    response.is_redirect = True
    with patch(_SEND, return_value=response):
        result = _run(
            _tool("github.issues.read"),
            method="GET",
            url="https://api.github.com/repos/o/r/issues",
        )
    assert result.is_error
    assert "redirect" in result.content


@pytest.mark.parametrize(
    ("status", "auth_method", "expected"),
    [
        (401, IntegrationAuthMethod.API_KEY, True),
        # A missing permission is not a sign-in problem.
        (403, IntegrationAuthMethod.API_KEY, False),
        # An app with no sign-in has nothing to connect.
        (401, None, False),
    ],
)
def test_only_a_rejected_sign_in_asks_the_user_to_connect(
    status: int, auth_method: IntegrationAuthMethod | None, expected: bool
) -> None:
    tool = _tool("github.issues.read")
    tool._credentials = tool._credentials.model_copy(
        update={"auth_method": auth_method}
    )
    with (
        patch(_SEND, return_value=_response(status=status)),
        patch("onyx.tools.tool_implementations.http_request.mark_api_key_rejected"),
    ):
        result = _run(tool, method="GET", url="https://api.github.com/repos/o/r/issues")

    assert isinstance(result.details, CustomToolCallSummary)
    assert (result.details.error is not None) is expected
