"""Outbound-request → policy-verdict matching for connected external apps.

Exercises the real provider catalogs + a real DB (no structural mocking):

- ``match_action``: a Slack REST call, a Google Calendar method+path, and a
  Linear GraphQL body each resolve to their action's stored policy; an action
  with no stored row (and an off-catalog request) resolves to ``None``.
- most-restrictive-wins when one request matches several actions.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager

from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.external_apps.matching.engine import match_action
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.sandbox_proxy.action_matcher import DBSessionFactory
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
    assert match_action(db_session, app, request) == EndpointPolicy.ALWAYS


def test_match_slack_rest_unset_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    # A real catalog action, but with no stored policy row → un-gated (None),
    # since the stored rows are the source of truth for what's gated.
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
    assert match_action(db_session, app, delete_req) == EndpointPolicy.DENY

    # Same path, read method → a different action with no stored row → None
    # (un-gated), not DENY.
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
    request = ProxiedRequest(method="POST", path="/graphql", body=body)
    assert match_action(db_session, app, request) == EndpointPolicy.DENY


def test_off_catalog_request_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/some.unknownMethod")
    assert match_action(db_session, app, request) is None


def test_graphql_batched_most_restrictive_wins(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.viewer.read", EndpointPolicy.ALWAYS)
    _set_policy(db_session, app, "linear.issues.create", EndpointPolicy.DENY)

    # A batched request invoking both a read (ALWAYS) and a write (DENY) in one
    # POST: the strictest verdict (DENY) must govern the whole request.
    body = json.dumps(
        [
            {"query": "query { viewer { id } }"},
            {"query": "mutation { issueCreate(input: $i) { issue { id } } }"},
        ]
    ).encode()
    request = ProxiedRequest(method="POST", path="/graphql", body=body)
    assert match_action(db_session, app, request) == EndpointPolicy.DENY


# ── ExternalAppActionMatcher: full proxy-request → verdict bridge ───


def _session_factory(db_session: Session) -> DBSessionFactory:
    """A ``DBSessionFactory`` that hands the matcher the test's own session
    (so flushed-but-uncommitted rows are visible) and never closes it."""

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

    matcher = ExternalAppActionMatcher(db_session_factory=_session_factory(db_session))
    match = matcher.match(_slack_request(), "public")

    assert match is not None
    # `match_action` returns only the verdict, so the recorded action is the
    # owning app's type, not the specific catalog endpoint.
    assert match.action_type == ExternalAppType.SLACK.value
    assert match.policy == EndpointPolicy.DENY
    assert match.payload == {"channel": "C1", "text": "hi"}
    # The app id is threaded through for the gate's credential-injection seam.
    assert match.external_app_id == app.id


def test_external_app_matcher_unconnected_host_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    matcher = ExternalAppActionMatcher(db_session_factory=_session_factory(db_session))
    request = http.Request.make("GET", "https://example.com/", headers={})
    assert matcher.match(request, "public") is None


def test_external_app_matcher_off_catalog_on_connected_host_returns_none(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    skill = make_skill(db_session)
    make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {access_token}"},
        app_type=ExternalAppType.SLACK,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
    )

    matcher = ExternalAppActionMatcher(db_session_factory=_session_factory(db_session))
    request = _slack_request(url="https://slack.com/api/some.unknownMethod")
    assert matcher.match(request, "public") is None
