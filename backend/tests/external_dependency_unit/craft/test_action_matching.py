"""Outbound-request → policy-verdict matching for connected external apps.

Exercises the real provider catalogs + a real DB (no structural mocking).

Three layers are tested here:
- ``recognize_actions`` — pure recognition: which catalog action(s) a request invokes,
  each carrying its ``effective_policy`` (stored override else catalog default).
- ``app_is_available`` — the credential predicate: active + injectable (a
  credentialless allowlist-only app can be served; a missing required credential
  cannot).
- ``ExternalAppRequestEvaluator.evaluate`` — the end-to-end result: recognition +
  availability + the ``apply_credential_gate`` fork (synthesize / DENY-only / bare).

The pure ``apply_credential_gate`` fork itself is unit-tested in
``tests/unit/external_apps/matching/test_engine.py``.
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
from onyx.db.models import User
from onyx.external_apps.credentials import app_is_available
from onyx.external_apps.matching import engine as matching_engine
from onyx.external_apps.matching.engine import AllMatchedActions
from onyx.external_apps.matching.engine import MatchedAction
from onyx.external_apps.matching.engine import recognize_actions
from onyx.external_apps.matching.engine import WHOLE_DOMAIN_ACTION_TYPE
from onyx.external_apps.matching.request import ProxiedRequest
from onyx.sandbox_proxy import request_evaluator as request_evaluator_mod
from onyx.sandbox_proxy.request_evaluator import ExternalAppRequestEvaluator
from tests.external_dependency_unit.craft._test_helpers import make_external_app
from tests.external_dependency_unit.craft._test_helpers import make_skill


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


# ── recognize_actions: pure recognition (no credentials) ────────────────


def test_match_stored_override_wins(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.ALWAYS)

    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    assert recognize_actions(db_session, app, request) == AllMatchedActions(
        actions=(
            MatchedAction(
                action_type="slack.messages.write",
                display_name="Post a message",
                description="Post a message to a channel or conversation.",
                policy=EndpointPolicy.ALWAYS,
            ),
        ),
        app_name="Slack",
        external_app_id=app.id,
    )


def test_unset_read_action_uses_catalog_default_always(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    # Slack is all-POST, so the catalog default (not HTTP method) classifies reads.
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/conversations.list")
    matched_actions = recognize_actions(db_session, app, request)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["slack.channels.read"]
    assert matched_actions.actions[0].policy == EndpointPolicy.ALWAYS


def test_unset_write_action_uses_catalog_default_ask(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/chat.postMessage")
    matched_actions = recognize_actions(db_session, app, request)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["slack.messages.write"]
    assert matched_actions.actions[0].policy == EndpointPolicy.ASK


def test_match_google_calendar_method_distinguishes_actions(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.GOOGLE_CALENDAR)
    _set_policy(db_session, app, "gcal.events.delete", EndpointPolicy.DENY)
    item_path = "/calendar/v3/calendars/primary/events/evt123"

    delete_req = ProxiedRequest(method="DELETE", path=item_path)
    matched_actions = recognize_actions(db_session, app, delete_req)
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["gcal.events.delete"]
    assert matched_actions.actions[0].policy == EndpointPolicy.DENY

    # Same path, GET → the read action; no stored row → catalog default ALWAYS.
    read_req = ProxiedRequest(method="GET", path=item_path)
    read_matched_actions = recognize_actions(db_session, app, read_req)
    assert read_matched_actions is not None
    assert [a.action_type for a in read_matched_actions.actions] == ["gcal.events.read"]
    assert read_matched_actions.actions[0].policy == EndpointPolicy.ALWAYS


def test_match_linear_graphql_body(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.issues.create", EndpointPolicy.DENY)

    body = json.dumps(
        {"query": "mutation { issueCreate(input: $i) { issue { id } } }"}
    ).encode()
    matched_actions = recognize_actions(
        db_session, app, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched_actions is not None
    assert matched_actions.app_name == "Linear"
    assert [a.action_type for a in matched_actions.actions] == ["linear.issues.create"]
    assert matched_actions.actions[0].policy == EndpointPolicy.DENY


def test_graphql_batched_sorts_strictest_first(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    """A batched request matching two actions (ALWAYS + DENY) returns both on
    ``AllMatchedActions.actions``, sorted strictest-first so ``actions[0]`` drives
    the verdict regardless of catalog order."""
    app = _connect_app(db_session, ExternalAppType.LINEAR)
    _set_policy(db_session, app, "linear.viewer.read", EndpointPolicy.ALWAYS)
    _set_policy(db_session, app, "linear.issues.create", EndpointPolicy.DENY)

    body = json.dumps(
        [
            {"query": "query { viewer { id } }"},
            {"query": "mutation { issueCreate(input: $i) { issue { id } } }"},
        ]
    ).encode()
    matched_actions = recognize_actions(
        db_session, app, ProxiedRequest(method="POST", path="/graphql", body=body)
    )
    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == [
        "linear.issues.create",
        "linear.viewer.read",
    ]
    assert [a.policy for a in matched_actions.actions] == [
        EndpointPolicy.DENY,
        EndpointPolicy.ALWAYS,
    ]


def test_match_action_off_catalog_returns_none(
    db_session: Session,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    # Pure recognition: a request matching no catalog action returns None. The
    # whole-domain synthesize is the caller's job (apply_credential_gate), tested separately.
    app = _connect_app(db_session, ExternalAppType.SLACK)
    request = ProxiedRequest(method="POST", path="/api/some.unknownMethod")
    assert recognize_actions(db_session, app, request) is None


def test_match_action_app_name_falls_back_when_provider_unregistered(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    test_user: User,  # noqa: ARG001 — for tenant context
) -> None:
    """A connected app whose provider isn't registered (catalog drift) still
    yields a matched_actions; ``app_name`` falls back to the raw enum value rather than
    crashing the gate."""
    app = _connect_app(db_session, ExternalAppType.SLACK)
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.ASK)
    monkeypatch.setattr(matching_engine, "get_provider_for_app", lambda _app: None)

    matched_actions = recognize_actions(
        db_session, app, ProxiedRequest(method="POST", path="/api/chat.postMessage")
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


def test_not_available_when_disabled(db_session: Session, test_user: User) -> None:
    skill = make_skill(db_session, enabled=False)
    app = make_external_app(
        db_session, skill=skill, auth_template={}, app_type=ExternalAppType.CUSTOM
    )
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
    _set_policy(db_session, app, "slack.messages.write", EndpointPolicy.DENY)

    monkeypatch.setattr(
        request_evaluator_mod, "get_session_with_tenant", _session_factory(db_session)
    )
    matcher = ExternalAppRequestEvaluator()
    matched_actions = matcher.evaluate(_slack_request(), "public", test_user.id)

    assert matched_actions is not None
    assert [a.action_type for a in matched_actions.actions] == ["slack.messages.write"]
    assert matched_actions.actions[0].policy == EndpointPolicy.DENY
    assert matched_actions.app_name == "Slack"
    assert matched_actions.external_app_id == app.id
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


def test_external_app_matcher_no_credential_forwards_bare(
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
    # conversations.list is a read (catalog default ALWAYS), but with no usable
    # credential the request forwards bare instead of being gated.
    request = _slack_request(url="https://slack.com/api/conversations.list")
    assert matcher.evaluate(request, "public", test_user.id) is None


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
    assert matched_actions.actions[0].policy == EndpointPolicy.ASK
    assert matched_actions.external_app_id == app.id


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
    assert matched_actions.actions[0].policy == EndpointPolicy.ASK
    assert matched_actions.external_app_id == app.id
    # CUSTOM apps have no provider; the name comes from the linked skill.
    assert matched_actions.app_name == skill.name
