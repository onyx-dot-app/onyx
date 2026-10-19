"""Provider recognition and credential availability remain independent of saved policies."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from typing import Callable

import pytest
from mitmproxy import http
from sqlalchemy.orm import Session

from onyx.db.action_policy import get_or_create_gated_app_id
from onyx.db.enums import ActionPolicy, ExternalAppType, GatedAppKind
from onyx.db.models import ExternalApp, User, WorkspaceActionPolicy
from onyx.external_apps.credentials import app_is_available
from onyx.external_apps.matching import engine as matching_engine
from onyx.external_apps.matching.engine import (
    WHOLE_DOMAIN_ACTION_TYPE,
    AllMatchedActions,
    GatedTarget,
    MatchedAction,
    recognize_actions,
)
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.sandbox_proxy import request_evaluator as request_evaluator_mod
from onyx.sandbox_proxy.request_evaluator import ExternalAppRequestEvaluator
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
)


def _connect_app(
    db_session: Session,
    app_type: ExternalAppType,
    *,
    with_credential: bool = True,
    upstream_url_patterns: list[str] | None = None,
) -> ExternalApp:
    """A connected app whose ``auth_template`` is fillable (``with_credential``)
    or not (org credentials empty → ``resolve_injection_headers`` returns {})."""
    skill = make_skill(db_session)
    return make_external_app(
        db_session,
        skill=skill,
        auth_template={"Authorization": "Bearer {access_token}"},
        organization_credentials=(
            {"access_token": "test-token"} if with_credential else None
        ),
        app_type=app_type,
        upstream_url_patterns=upstream_url_patterns,
    )


def _set_policy(
    db_session: Session,
    app: ExternalApp,
    action_id: str,
    policy: ActionPolicy,
) -> None:
    gated_app_id = get_or_create_gated_app_id(
        db_session, GatedAppKind.EXTERNAL_APP, app.id
    )
    db_session.add(
        WorkspaceActionPolicy(
            gated_app_id=gated_app_id,
            action_id=action_id,
            policy=policy,
        )
    )
    db_session.flush()


# ── recognize_actions: pure recognition (no credentials) ────────────────


def test_recognition_is_independent_of_stored_override(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", ActionPolicy.ALWAYS)

    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    assert recognize_actions(app, request) == AllMatchedActions(
        actions=(
            MatchedAction(
                action_type="slack.messages.write",
                display_name="Post a message",
                description="Post a message to a channel or conversation.",
                policy=ActionPolicy.ASK,
            ),
        ),
        target=GatedTarget(kind=GatedAppKind.EXTERNAL_APP, id=app.id, app_name="Slack"),
    )


def test_unset_read_action_uses_catalog_default_always(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    # Slack is all-POST, so the catalog default (not HTTP method) classifies reads.
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/conversations.list")
    matched_actions = recognize_actions(app, request)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["slack.channels.read"]
    assert matched_actions.actions[0].policy == ActionPolicy.ALWAYS


def test_unset_write_action_uses_catalog_default_ask(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    matched_actions = recognize_actions(app, request)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["slack.messages.write"]
    assert matched_actions.actions[0].policy == ActionPolicy.ASK


def test_match_google_calendar_method_distinguishes_actions(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.GOOGLE_CALENDAR)
    _set_policy(db_session, app, "gcal.events.delete", ActionPolicy.DENY)
    item_path = "/calendar/v3/calendars/primary/events/evt123"

    delete_req = ProxiedRequest(method="DELETE", path=item_path)
    matched_actions = recognize_actions(app, delete_req)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["gcal.events.delete"]
    assert matched_actions.actions[0].policy == ActionPolicy.ASK

    # Same path, GET → the read action; no stored row → catalog default ALWAYS.
    read_req = ProxiedRequest(method="GET", path=item_path)
    read_matched_actions = recognize_actions(app, read_req)
    assert read_matched_actions is not None
    assert [a.action_type for a in read_matched_actions.actions] == ["gcal.events.read"]
    assert read_matched_actions.actions[0].policy == ActionPolicy.ALWAYS


def test_match_linear_graphql_body(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.issues.create", ActionPolicy.DENY)

    body = json.dumps(
        {"query": "mutation { issueCreate(input: $i) { issue { id } } }"}
    ).encode()
    matched_actions = recognize_actions(
        app, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched_actions is not None
    assert matched_actions.app_name == "Linear"
    assert [a.action_type for a in matched_actions.actions] == ["linear.issues.create"]
    assert matched_actions.actions[0].policy == ActionPolicy.ASK


def test_graphql_batched_sorts_strictest_first(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    """A batched request matching two actions (ALWAYS + ASK) returns both on
    ``AllMatchedActions.actions``, sorted strictest-first so ``actions[0]`` drives
    the verdict regardless of catalog order."""
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.viewer.read", ActionPolicy.ALWAYS)
    _set_policy(db_session, app, "linear.issues.create", ActionPolicy.DENY)

    body = json.dumps(
        [
            {"query": "query { viewer { id } }"},
            {"query": "mutation { issueCreate(input: $i) { issue { id } } }"},
        ]
    ).encode()
    matched_actions = recognize_actions(
        app, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == [
        "linear.issues.create",
        "linear.viewer.read",
    ]
    assert [a.policy for a in matched_actions.actions] == [
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
        recognize_actions(app, request).governing_action.action_type
        == WHOLE_DOMAIN_ACTION_TYPE
    )


def test_match_action_app_name_falls_back_when_provider_unregistered(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    """A connected app whose provider isn't registered (catalog drift) still
    yields a matched_actions; ``app_name`` falls back to the raw enum value rather than
    crashing the gate."""
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", ActionPolicy.ASK)
    monkeypatch.setattr(matching_engine, "get_provider_for_app", lambda _app: None)

    matched_actions = recognize_actions(
        app, ProxiedRequest(method="POST", path="/api/chat.postMessage")
    )
    assert matched_actions is not None
    assert matched_actions.app_name == ExternalAppType.SLACK.value


# ── app_is_available: the credential predicate ─────────────────────


def test_available_credentialless_app(db_session: Session, test_user: User) -> None:
    # Empty auth_template = "no credential required" → available (still gated).
    skill = make_skill(db_session)
    app = make_external_app(
        db_session, skill=skill, auth_template={}, app_type=ExternalAppType.CUSTOM
    )
    assert app_is_available(db_session, app, test_user.id) is True


def test_available_with_fillable_credential(
    db_session: Session, test_user: User
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK, with_credential=True)
    assert app_is_available(db_session, app, test_user.id) is True


def test_not_available_required_credential_missing(
    db_session: Session, test_user: User
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK, with_credential=False)
    assert app_is_available(db_session, app, test_user.id) is False


# ── ExternalAppRequestEvaluator: full proxy-request → verdict bridge ───


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
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _connect_app(
        db_session,
        ExternalAppType.SLACK,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
    )
    _set_policy(db_session, app, "slack.messages.write", ActionPolicy.DENY)

    monkeypatch.setattr(
        request_evaluator_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppRequestEvaluator()
    matched_actions = matcher.evaluate(_slack_request(), "public", test_user.id)

    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["slack.messages.write"]
    assert matched_actions.actions[0].policy == ActionPolicy.ASK
    assert matched_actions.app_name == "Slack"
    assert matched_actions.target.key == (GatedAppKind.EXTERNAL_APP, app.id)
    assert matched_actions.payload == {"channel": "C1", "text": "hi"}


def test_external_app_matcher_unconnected_host_returns_none(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        request_evaluator_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppRequestEvaluator()
    request = http.Request.make("GET", "https://example.com/", headers={})
    assert matcher.evaluate(request, "public", test_user.id) is None


def test_external_app_matcher_preserves_recognition_without_credentials(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _connect_app(
        db_session,
        ExternalAppType.SLACK,
        with_credential=False,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
    )
    monkeypatch.setattr(
        request_evaluator_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppRequestEvaluator()
    # A missing credential cannot remove an action from permission enforcement.
    request = _slack_request(url="https://slack.com/api/conversations.list")
    matched = matcher.evaluate(request, "public", test_user.id)
    assert matched is not None
    assert matched.governing_action.action_type == "slack.channels.read"


def test_external_app_matcher_off_catalog_synthesizes_whole_domain(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = _connect_app(
        db_session,
        ExternalAppType.SLACK,
        upstream_url_patterns=["https://slack\\.com/api/.*"],
    )

    monkeypatch.setattr(
        request_evaluator_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppRequestEvaluator()
    request = _slack_request(url="https://slack.com/api/some.unknownMethod")
    matched_actions = matcher.evaluate(request, "public", test_user.id)

    assert matched_actions is not None
    assert matched_actions.actions[0].action_type == WHOLE_DOMAIN_ACTION_TYPE
    assert matched_actions.actions[0].policy == ActionPolicy.ASK
    assert matched_actions.target.key == (GatedAppKind.EXTERNAL_APP, app.id)


def test_external_app_matcher_credentialless_app_is_gated(
    db_session: Session,
    test_user: User,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Regression guard: an enabled allowlist-only app (empty auth_template) is
    # available and so its whole domain is gated under a synthesized ASK.
    # CUSTOM apps author URL *globs* (``*`` wildcard), not regexes.
    skill = make_skill(db_session)
    app = make_external_app(
        db_session,
        skill=skill,
        auth_template={},
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=["https://example.com/*"],
    )
    monkeypatch.setattr(
        request_evaluator_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppRequestEvaluator()
    request = http.Request.make("POST", "https://example.com/anything", headers={})
    matched_actions = matcher.evaluate(request, "public", test_user.id)

    assert matched_actions is not None
    assert matched_actions.actions[0].action_type == WHOLE_DOMAIN_ACTION_TYPE
    assert matched_actions.actions[0].policy == ActionPolicy.ASK
    assert matched_actions.target.key == (GatedAppKind.EXTERNAL_APP, app.id)
    # CUSTOM apps have no provider; the name comes from app display metadata.
    assert matched_actions.app_name == app.name
