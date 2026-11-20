"""Unit tests for the proxy's request attribution: URL patterns of an app,
the cached match targets, and the pick between integrations that match.

CUSTOM apps author globs; built-in providers author regexes.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, IntegrationKind
from onyx.db.models import ExternalApp, Integration
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.matching.engine import url_matches_patterns
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.integrations.models import RequestMatch
from onyx.sandbox_proxy.request_evaluator import _matches, _pick
from onyx.sandbox_proxy.resolvers.mcp_matching import (
    IntegrationMatchTarget,
    may_match,
    parse_target,
)
from onyx.sandbox_proxy.usable_integrations import (
    load_match_targets,
    openapi_match_target,
)


def _regexes(
    patterns: list[str], app_type: ExternalAppType = ExternalAppType.CUSTOM
) -> list[str]:
    return ExternalApp(
        name=app_type.value, app_type=app_type, upstream_url_patterns=patterns
    ).upstream_url_regexes


def test_custom_glob_matches_deep_path() -> None:
    # `/api/*` must cover deep paths (the Discord 401 regression).
    regexes = _regexes(["https://discord.com/api/*"])
    assert url_matches_patterns("https://discord.com/api/v10/users/@me", regexes)
    # The dot is literal, so a look-alike host must not match.
    assert not url_matches_patterns("https://discordxcom/api/x", regexes)


def test_builtin_regex_used_as_is() -> None:
    regexes = _regexes(["https://slack\\.com/api/.*"], ExternalAppType.SLACK)
    assert url_matches_patterns("https://slack.com/api/chat.postMessage", regexes)


def test_no_pattern_matches_returns_false() -> None:
    regexes = _regexes(["https://slack.com/api/*"])
    assert not url_matches_patterns("https://example.com/", regexes)


def test_empty_patterns_never_match() -> None:
    assert not url_matches_patterns("https://slack.com/api/x", [])


def test_malformed_builtin_regex_is_skipped_not_fatal() -> None:
    regexes = ["(", "https://slack\\.com/api/.*"]
    assert url_matches_patterns("https://slack.com/api/x", regexes)


def _mcp_target(integration_id: int, url: str) -> IntegrationMatchTarget:
    return IntegrationMatchTarget(
        integration_id=integration_id,
        kind=IntegrationKind.MCP,
        endpoint=parse_target(integration_id, url),
    )


def test_a_target_may_match_only_its_host_or_its_app_urls() -> None:
    mcp = _mcp_target(1, "https://mcp.example.com/linear/mcp")
    app = IntegrationMatchTarget(
        integration_id=2,
        kind=IntegrationKind.API,
        app_type=ExternalAppType.CUSTOM,
        url_regexes=tuple(_regexes(["https://api.example.com/*"])),
    )
    broken = IntegrationMatchTarget(
        integration_id=3, kind=IntegrationKind.API, load_error="bad spec"
    )
    other_path = http.Request.make("POST", "https://mcp.example.com/other")
    app_request = http.Request.make("GET", "https://api.example.com/v1/x")
    unrelated = http.Request.make("GET", "https://pypi.org/simple")

    assert may_match(mcp, other_path)
    assert not may_match(mcp, app_request)
    assert may_match(app, app_request)
    assert not may_match(app, other_path)
    assert all(
        may_match(broken, request) for request in (other_path, app_request, unrelated)
    )


def test_a_target_that_did_not_load_blocks_the_request() -> None:
    broken = IntegrationMatchTarget(
        integration_id=1, kind=IntegrationKind.API, load_error="bad spec"
    )
    handler = MagicMock()
    with (
        patch(
            "onyx.sandbox_proxy.request_evaluator.get_kind_handler",
            return_value=handler,
        ),
        pytest.raises(OnyxError),
    ):
        _matches(
            [(Integration(id=1, kind=IntegrationKind.API), broken)],
            ProxiedRequest(method="GET", path="/x"),
            MagicMock(),
        )
    handler.match_request.assert_not_called()


def test_a_failed_integration_match_blocks_the_request() -> None:
    """A broader integration must not claim a request that a more specific
    one failed to match, so the error reaches the gate, which blocks."""
    broken = Integration(id=1, kind=IntegrationKind.MCP)
    broad = Integration(id=2, kind=IntegrationKind.MCP)

    def match(
        integration: Integration,
        _target: IntegrationMatchTarget,
        _request: ProxiedRequest,
        _db: Session,
    ) -> RequestMatch:
        if integration is broken:
            raise ValueError("bad stored settings")
        return RequestMatch(actions=[], path_prefix_length=1)

    handler = MagicMock()
    handler.match_request.side_effect = match
    request = ProxiedRequest(method="POST", path="/mcp/x")
    with (
        patch(
            "onyx.sandbox_proxy.request_evaluator.get_kind_handler",
            return_value=handler,
        ),
        pytest.raises(ValueError),
    ):
        _matches(
            [
                (broken, _mcp_target(1, "https://mcp.example.com/mcp/x")),
                (broad, _mcp_target(2, "https://mcp.example.com/mcp")),
            ],
            request,
            MagicMock(),
        )


def _match(
    integration_id: int, kind: IntegrationKind, prefix_length: int
) -> tuple[Integration, RequestMatch]:
    return (
        Integration(id=integration_id, kind=kind),
        RequestMatch(actions=[], path_prefix_length=prefix_length),
    )


def test_pick_gives_no_owner_on_an_mcp_prefix_tie() -> None:
    """Two MCP servers at the same endpoint: picking one would gate as, and
    inject the credential of, an arbitrary server."""
    assert (
        _pick(
            [
                _match(1, IntegrationKind.MCP, 4),
                _match(2, IntegrationKind.MCP, 4),
                _match(3, IntegrationKind.MCP, 1),
            ]
        )
        is None
    )


def test_pick_takes_the_longest_mcp_prefix_and_an_api_over_mcp() -> None:
    longest = _pick(
        [_match(1, IntegrationKind.MCP, 4), _match(2, IntegrationKind.MCP, 8)]
    )
    assert longest is not None and longest[0].id == 2
    api = _pick(
        [
            _match(1, IntegrationKind.MCP, 8),
            _match(5, IntegrationKind.API, 0),
            _match(3, IntegrationKind.API, 0),
        ]
    )
    assert api is not None and api[0].id == 3


def test_an_openapi_spec_that_does_not_parse_gives_a_load_error() -> None:
    two_servers = {"servers": [{"url": "https://a.example.com"}, {"url": "https://b"}]}
    for schema in (None, two_servers):
        target = openapi_match_target(1, schema)
        assert target is not None and target.load_error is not None
    parsed = openapi_match_target(1, {"servers": [{"url": "https://a.example.com/v1"}]})
    assert parsed is not None and parsed.endpoint is not None
    assert parsed.endpoint.path_prefix == "/v1"


def test_a_malformed_url_gives_a_load_error_and_keeps_the_valid_targets() -> None:
    module = "onyx.sandbox_proxy.usable_integrations"
    with (
        patch(
            f"{module}.list_enabled_mcp_server_urls",
            return_value=[(1, "https://x:invalid/mcp"), (2, "https://ok.example/mcp")],
        ),
        patch(
            f"{module}.list_enabled_openapi_schemas",
            return_value=[
                (3, {"servers": [{"url": "https://y:invalid/v1"}]}),
                (4, {"servers": [{"url": "https://api.example/v1"}]}),
            ],
        ),
        patch(f"{module}.list_enabled_external_apps", return_value=[]),
    ):
        targets = {t.integration_id: t for t in load_match_targets(MagicMock())}

    assert set(targets) == {1, 2, 3, 4}
    assert targets[1].kind is IntegrationKind.MCP
    assert targets[1].load_error is not None
    assert targets[3].kind is IntegrationKind.API
    assert targets[3].load_error is not None
    for valid in (targets[2], targets[4]):
        assert valid.load_error is None and valid.endpoint is not None
