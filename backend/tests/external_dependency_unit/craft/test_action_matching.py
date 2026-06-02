"""Outbound-request → policy-verdict matching for connected external apps.

Exercises the real provider catalogs + a real DB (no structural mocking).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager
from contextlib import contextmanager
from typing import Callable

import pytest
from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.external_apps.matching import engine as matching_engine
from onyx.external_apps.matching.engine import ActionMatch
from onyx.external_apps.matching.engine import match_action
from onyx.external_apps.matching.engine import RequestMatch
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.sandbox_proxy import action_matcher as action_matcher_mod
from onyx.sandbox_proxy.action_matcher import ExternalAppActionMatcher
from tests.external_dependency_unit.craft._test_helpers import make_external_app
from tests.external_dependency_unit.craft._test_helpers import make_skill


def _connect_app(db_session: Session, app_type: ExternalAppType) -> ExternalApp:
    skill = make_skill(db_session)
    return make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {access_token}"},
        app_type=app_type,
    )


def _set_policy(
    db_session: Session,
    app: ExternalApp,
    action_id: str,
    policy: EndpointPolicy,
) -> None:
    db_session.add(
        ExternalAppPolicy(
            external_app_id=app.id,
            action_id=action_id,
            policy=policy,
        )
    )
    db_session.flush()


# ── match_action: per-provider recognition ────────────────────────


def test_match_slack_rest_uses_stored_override(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.ALWAYS)

    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    assert match_action(db_session, app, request) == RequestMatch(
        actions=(
            ActionMatch(
                action_type="slack.messages.write",
                display_name="Post a message",
                description="Post a message to a channel or conversation.",
                policy=EndpointPolicy.ALWAYS,
            ),
        ),
        app_name="Slack",
        external_app_id=app.id,
    )


def test_match_slack_rest_unset_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    # Real catalog action with no stored policy row → un-gated, since the
    # stored rows are the source of truth for what's gated.
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/conversations.list")
    assert match_action(db_session, app, request) is None


def test_match_google_calendar_method_and_path(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.GOOGLE_CALENDAR)
    _set_policy(db_session, app, "gcal.events.delete", EndpointPolicy.DENY)

    delete_req = ProxiedRequest(
        method="DELETE",
        path="/calendar/v3/calendars/primary/events/evt123",
    )
    matched = match_action(db_session, app, delete_req)
    assert matched is not None
    assert matched.app_name == "Google Calendar"
    assert [a.action_type for a in matched.actions] == ["gcal.events.delete"]
    assert matched.actions[0].policy == EndpointPolicy.DENY

    # Same path, read method → different action with no stored row → None.
    read_req = ProxiedRequest(
        method="GET",
        path="/calendar/v3/calendars/primary/events/evt123",
    )
    assert match_action(db_session, app, read_req) is None


def test_match_linear_graphql_body(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.issues.create", EndpointPolicy.DENY)

    body = json.dumps(
        {"query": "mutation { issueCreate(input: $i) { issue { id } } }"}
    ).encode()
    matched = match_action(
        db_session, app, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched is not None
    assert matched.app_name == "Linear"
    assert [a.action_type for a in matched.actions] == ["linear.issues.create"]
    assert matched.actions[0].policy == EndpointPolicy.DENY


def test_off_catalog_request_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/some.unknownMethod")
    assert match_action(db_session, app, request) is None


def test_match_action_app_name_falls_back_when_provider_unregistered(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    test_user: object,  # noqa: ARG001
) -> None:
    """A connected app whose provider isn't registered (catalog drift) still
    yields a match; ``app_name`` falls back to the raw enum value rather
    than crashing the gate."""
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.ASK)
    monkeypatch.setattr(matching_engine, "get_provider_for_app", lambda _app: None)

    matched = match_action(
        db_session, app, ProxiedRequest(method="POST", path="/api/chat.postMessage")
    )
    assert matched is not None
    assert matched.app_name == ExternalAppType.SLACK.value


def test_graphql_batched_sorts_strictest_first(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    """A batched request matching two actions (ALWAYS + DENY) returns both
    on ``RequestMatch.actions``, sorted strictest-first so ``actions[0]``
    drives the gate's verdict regardless of catalog order."""
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.viewer.read", EndpointPolicy.ALWAYS)
    _set_policy(db_session, app, "linear.issues.create", EndpointPolicy.DENY)

    body = json.dumps(
        [
            {"query": "query { viewer { id } }"},
            {"query": "mutation { issueCreate(input: $i) { issue { id } } }"},
        ]
    ).encode()
    matched = match_action(
        db_session, app, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched is not None
    assert matched.app_name == "Linear"
    assert [a.action_type for a in matched.actions] == [
        "linear.issues.create",
        "linear.viewer.read",
    ]
    assert [a.policy for a in matched.actions] == [
        EndpointPolicy.DENY,
        EndpointPolicy.ALWAYS,
    ]


# ── ExternalAppActionMatcher: full proxy-request → verdict bridge ───


def _session_factory(
    db_session: Session,
) -> "Callable[[str], AbstractContextManager[Session]]":
    """A ``get_session_with_tenant`` stand-in that hands the matcher the test's
    own session so flushed-but-uncommitted rows are visible; never closes it."""

    @contextmanager
    def factory(tenant_id: str) -> Iterator[Session]:  # noqa: ARG001
        yield db_session

    return factory


def _slack_request(
    method: str = "POST",
    url: str = "https://slack.com/api/chat.postMessage",
    body: bytes = b'{"channel": "C1", "text": "hi"}',
) -> http.Request:
    return http.Request.make(
        method, url, content=body, headers={"content-type": "application/json"}
    )


def test_external_app_matcher_resolves_app_and_verdict(
    db_session: Session,
    test_user: object,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_skill(db_session)
    app = make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {access_token}"},
        app_type=ExternalAppType.SLACK,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
    )
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.DENY)

    monkeypatch.setattr(
        action_matcher_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppActionMatcher()
    matched = matcher.match(_slack_request(), "public")

    assert matched is not None
    assert [a.action_type for a in matched.actions] == ["slack.messages.write"]
    assert matched.actions[0].policy == EndpointPolicy.DENY
    assert matched.app_name == "Slack"
    assert matched.external_app_id == app.id
    assert matched.payload == {"channel": "C1", "text": "hi"}


def test_external_app_matcher_unconnected_host_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        action_matcher_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppActionMatcher()
    request = http.Request.make("GET", "https://example.com/", headers={})
    assert matcher.match(request, "public") is None


def test_external_app_matcher_off_catalog_on_connected_host_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    skill = make_skill(db_session)
    make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {access_token}"},
        app_type=ExternalAppType.SLACK,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
    )

    monkeypatch.setattr(
        action_matcher_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppActionMatcher()
    request = _slack_request(url="https://slack.com/api/some.unknownMethod")
    assert matcher.match(request, "public") is None
