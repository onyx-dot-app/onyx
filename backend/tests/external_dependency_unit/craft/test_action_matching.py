"""Provider recognition of external app requests."""

from __future__ import annotations

import json

from sqlalchemy.orm import Session

from onyx.db.enums import ActionPolicy, ExternalAppType
from onyx.db.models import ExternalApp, User
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    recognize_actions,
)
from onyx.external_apps.matching.request import ProxiedRequest
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
)


def _connect_app(
    db_session: Session,
    app_type: ExternalAppType,
    *,
    upstream_url_patterns: list[str] | None = None,
) -> ExternalApp:
    skill = make_skill(db_session)
    return make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {access_token}"},
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns,
    )


def test_unset_read_action_uses_catalog_default_always(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    # Slack is all-POST, so the catalog default (not HTTP method) classifies reads.
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/conversations.list")
    matched_actions = recognize_actions(app.app_type, request)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions] == ["slack.channels.read"]
    assert matched_actions[0].policy == ActionPolicy.ALWAYS


def test_unset_write_action_uses_catalog_default_ask(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    matched_actions = recognize_actions(app.app_type, request)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions] == ["slack.messages.write"]
    assert matched_actions[0].policy == ActionPolicy.ASK


def test_match_google_calendar_method_distinguishes_actions(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.GOOGLE_CALENDAR)
    item_path = "/calendar/v3/calendars/primary/events/evt123"

    delete_req = ProxiedRequest(method="DELETE", path=item_path)
    matched_actions = recognize_actions(app.app_type, delete_req)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions] == ["gcal.events.delete"]
    assert matched_actions[0].policy == ActionPolicy.ASK

    # Same path, GET → the read action; no stored row → catalog default ALWAYS.
    read_req = ProxiedRequest(method="GET", path=item_path)
    read_matched_actions = recognize_actions(app.app_type, read_req)
    assert read_matched_actions is not None
    assert [a.action_type for a in read_matched_actions] == ["gcal.events.read"]
    assert read_matched_actions[0].policy == ActionPolicy.ALWAYS


def test_match_linear_graphql_body(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.LINEAR)

    body = json.dumps(
        {"query": "mutation { issueCreate(input: $i) { issue { id } } }"}
    ).encode()
    matched_actions = recognize_actions(
        app.app_type, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions] == ["linear.issues.create"]
    assert matched_actions[0].policy == ActionPolicy.ASK


def test_graphql_batched_sorts_strictest_first(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    """A batched request matching two actions (ALWAYS + ASK) returns both on
    the result, sorted strictest-first so ``actions[0]`` drives
    the verdict regardless of catalog order."""
    app = _connect_app(db_session, ExternalAppType.LINEAR)

    body = json.dumps(
        [
            {"query": "query { viewer { id } }"},
            {"query": "mutation { issueCreate(input: $i) { issue { id } } }"},
        ]
    ).encode()
    matched_actions = recognize_actions(
        app.app_type, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions] == [
        "linear.issues.create",
        "linear.viewer.read",
    ]
    assert [a.policy for a in matched_actions] == [
        ActionPolicy.ASK,
        ActionPolicy.ALWAYS,
    ]


def test_match_action_off_catalog_requires_approval(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    # Unknown managed actions still require approval.
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/some.unknownMethod")
    assert (
        recognize_actions(app.app_type, request)[0].action_type
        == WHOLE_DOMAIN_ACTION_TYPE
    )
