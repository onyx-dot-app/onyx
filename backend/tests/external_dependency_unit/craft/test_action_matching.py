"""Outbound-request → policy-verdict matching for connected external apps.

Exercises the real provider catalogs + a real DB (no structural mocking):

- ``resolve_policy``: stored override wins; an unset action falls back to ASK.
- ``match_action``: a Slack REST call, a Google Calendar method+path, and a
  Linear GraphQL body each resolve to their action's policy; an off-catalog
  request resolves to ``None``.
- most-restrictive-wins when one request matches several actions.
"""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from onyx.db.enums import EndpointPolicy
from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.db.models import ExternalAppPolicy
from onyx.external_apps.matching import match_action
from onyx.external_apps.matching import ProxiedRequest
from onyx.external_apps.policy import resolve_policy
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


# ── resolve_policy: the seam shared with the admin view ────────────


def test_resolve_policy_override_wins() -> None:
    stored = {"slack.messages.write": EndpointPolicy.DENY}
    assert resolve_policy("slack.messages.write", stored) == EndpointPolicy.DENY


def test_resolve_policy_unset_defaults_to_ask() -> None:
    assert resolve_policy("slack.messages.write", {}) == EndpointPolicy.ASK


# ── match_action: per-provider recognition ────────────────────────


def test_match_slack_rest_uses_stored_override(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.ALWAYS)

    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    assert match_action(db_session, app, request) == EndpointPolicy.ALWAYS


def test_match_slack_rest_unset_defaults_to_ask(
    db_session: Session,
    test_user: object,  # noqa: ARG001
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/conversations.list")
    assert match_action(db_session, app, request) == EndpointPolicy.ASK


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

    # Same path, read method → a different (unset) action → ASK, not DENY.
    read_req = ProxiedRequest(
        method="GET",
        path="/calendar/v3/calendars/primary/events/evt123",
    )
    assert match_action(db_session, app, read_req) == EndpointPolicy.ASK


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
