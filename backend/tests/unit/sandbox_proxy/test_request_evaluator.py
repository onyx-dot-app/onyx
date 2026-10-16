"""Unit tests for the proxy's URL → ExternalApp resolution.

``resolve_app_for_url`` binds a request to a connected app before deferring to
``external_apps.matching.recognize_actions``. Transient (un-flushed)
``ExternalApp`` objects suffice — it only reads ``upstream_url_patterns``, never
the DB. CUSTOM apps author globs; built-in providers author regexes.
"""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from mitmproxy import http

from onyx.db.enums import EndpointPolicy, ExternalAppType
from onyx.db.models import ExternalApp, Tool
from onyx.external_apps.matching.engine import (
    AmbiguousExternalAppTargetError,
    resolve_app_for_url,
)
from onyx.sandbox_proxy import request_evaluator
from onyx.sandbox_proxy.request_evaluator import (
    ExternalAppRequestEvaluator,
)
from onyx.sandbox_proxy.resolvers.mcp_matching import match_request, parse_target


def _app(
    patterns: list[str],
    app_type: ExternalAppType = ExternalAppType.CUSTOM,
) -> ExternalApp:
    return ExternalApp(
        name=app_type.value,
        app_type=app_type,
        upstream_url_patterns=patterns,
    )


def test_custom_glob_matches_deep_path() -> None:
    # `/api/*` must cover deep paths (the Discord 401 regression).
    app = _app(["https://discord.com/api/*"])
    assert resolve_app_for_url("https://discord.com/api/v10/users/@me", [app]) is app
    # The dot is literal, so a look-alike host must not match.
    assert resolve_app_for_url("https://discordxcom/api/x", [app]) is None


def test_builtin_regex_used_as_is() -> None:
    slack = _app(["https://slack\\.com/api/.*"], ExternalAppType.SLACK)
    assert (
        resolve_app_for_url("https://slack.com/api/chat.postMessage", [slack]) is slack
    )


def test_no_pattern_matches_returns_none() -> None:
    app = _app(["https://slack.com/api/*"])
    assert resolve_app_for_url("https://example.com/", [app]) is None


def test_empty_patterns_never_match() -> None:
    assert resolve_app_for_url("https://slack.com/api/x", [_app([])]) is None


def test_first_app_in_order_wins_on_overlap() -> None:
    broad = _app(["https://slack.com/*"])
    narrow = _app(["https://slack.com/api/*"])
    # Caller passes apps id-ordered; the earlier one wins.
    assert resolve_app_for_url("https://slack.com/api/x", [broad, narrow]) is broad


def test_malformed_builtin_regex_is_skipped_not_fatal() -> None:
    bad = _app(["("], ExternalAppType.SLACK)  # invalid regex
    good = _app(["https://slack\\.com/api/.*"], ExternalAppType.SLACK)
    assert resolve_app_for_url("https://slack.com/api/x", [bad, good]) is good


@pytest.mark.parametrize("source_first", [True, False])
def test_openapi_overlap_denies_before_resolving_credentials(
    monkeypatch: pytest.MonkeyPatch, source_first: bool
) -> None:
    source = _app(["https://slack.com/api/*"])
    source.id = 2
    source.openapi_tool_id = 1
    builtin = _app([r"https://slack\.com/api/.*"], ExternalAppType.SLACK)
    builtin.id = 1
    apps = [source, builtin] if source_first else [builtin, source]
    monkeypatch.setattr(request_evaluator, "get_session_with_tenant", MagicMock())
    monkeypatch.setattr(request_evaluator, "get_external_apps", lambda *_a, **_k: apps)
    credentials = MagicMock()
    monkeypatch.setattr(request_evaluator, "app_is_available", credentials)
    result = ExternalAppRequestEvaluator().evaluate(
        http.Request.make("GET", "https://slack.com/api/test"), "tenant", uuid4()
    )
    assert result is not None
    assert result.governing_action.policy is EndpointPolicy.DENY
    credentials.assert_not_called()


@pytest.mark.parametrize("failure_point", ["recognize_actions", "app_is_available"])
@pytest.mark.parametrize("source_owned", [True, False])
def test_evaluation_failure_denies_only_source_owned_apps(
    monkeypatch: pytest.MonkeyPatch, failure_point: str, source_owned: bool
) -> None:
    app = _app(["https://example.com/api/*"])
    app.id = 1
    app.openapi_tool_id = 2 if source_owned else None
    monkeypatch.setattr(request_evaluator, "get_session_with_tenant", MagicMock())
    monkeypatch.setattr(request_evaluator, "get_external_apps", lambda *_a, **_k: [app])
    monkeypatch.setattr(
        request_evaluator, "recognize_actions", MagicMock(return_value=None)
    )
    monkeypatch.setattr(
        request_evaluator, "app_is_available", MagicMock(return_value=True)
    )
    monkeypatch.setattr(
        request_evaluator, failure_point, MagicMock(side_effect=RuntimeError("failure"))
    )
    request = http.Request.make("GET", "https://example.com/api/items")
    evaluator = ExternalAppRequestEvaluator()
    if not source_owned:
        with pytest.raises(RuntimeError, match="failure"):
            evaluator.evaluate(request, "tenant", uuid4())
        return
    result = evaluator.evaluate(request, "tenant", uuid4())
    assert result is not None
    assert result.target.id == app.id
    assert result.governing_action.policy is EndpointPolicy.DENY
    assert result.governing_action.action_type == "openapi.unclassifiable"


def test_legacy_invalid_openapi_schema_denies_before_credential_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _app(["https://example.com/api/*"])
    app.id = 1
    app.openapi_tool_id = 2
    app.openapi_tool = Tool(openapi_schema={}, available_in_craft=True)
    monkeypatch.setattr(request_evaluator, "get_session_with_tenant", MagicMock())
    monkeypatch.setattr(request_evaluator, "get_external_apps", lambda *_a, **_k: [app])
    credentials = MagicMock(return_value=True)
    monkeypatch.setattr(request_evaluator, "app_is_available", credentials)
    result = ExternalAppRequestEvaluator().evaluate(
        http.Request.make("GET", "https://example.com/api/items"), "tenant", uuid4()
    )
    assert result is not None
    assert result.governing_action.policy is EndpointPolicy.DENY
    credentials.assert_not_called()


@pytest.mark.parametrize(
    "path",
    [
        "/api/../outside",
        "/api/%2e%2e/outside",
        "/api/.%2e/outside",
        "/api/%2E./outside",
        "/api%2f..%2foutside",
        "/api/a/../../outside",
        r"/api/..\outside",
        "/api/%5c..%5coutside",
        "/api%5c..%5coutside",
        "/api%3Foutside",
        "/api%23outside",
    ],
)
def test_openapi_scope_does_not_match_paths_outside_resolved_base(path: str) -> None:
    app = _app(
        [
            "https://example.com/api",
            "https://example.com/api?*",
            "https://example.com/api/*",
        ]
    )
    app.openapi_tool_id = 1
    assert resolve_app_for_url(f"https://example.com{path}", [app]) is None


def test_openapi_scope_matches_normalized_path_with_query() -> None:
    app = _app(
        [
            "https://example.com/api",
            "https://example.com/api?*",
            "https://example.com/api/*",
        ]
    )
    app.openapi_tool_id = 1
    assert (
        resolve_app_for_url("https://example.com/api/a/../items?q=hello%20world", [app])
        is app
    )


def test_non_openapi_regex_semantics_stay_unchanged() -> None:
    app = _app([r"https://example\.com/api/.*"], ExternalAppType.SLACK)
    assert resolve_app_for_url("https://example.com/api/../outside", [app]) is app


def test_shared_attribution_rejects_openapi_overlap() -> None:
    source = _app(["https://example.com/api/*"])
    source.openapi_tool_id = 1
    other = _app(["https://example.com/*"])
    with pytest.raises(AmbiguousExternalAppTargetError):
        resolve_app_for_url("https://example.com/api/items", [other, source])


@pytest.mark.parametrize("path", [r"/api/..\outside", "/api/%5c..%5coutside"])
def test_mcp_scope_reuses_separator_normalization(path: str) -> None:
    target = parse_target(1, "https://example.com/api")
    assert target is not None
    assert (
        match_request((target,), http.Request.make("GET", f"https://example.com{path}"))
        is None
    )
