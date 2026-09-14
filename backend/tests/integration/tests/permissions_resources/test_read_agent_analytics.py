"""Integration tests for the READ_AGENT_ANALYTICS permission gate.

Covers the per-agent analytics routes in ``backend/ee/onyx/server/analytics/api.py``.
Org-wide analytics (``/analytics/admin/query|user|onyxbot``) stay FULL_ADMIN and are
not this permission's business.

Routes are ``ScopeEndpoint``s because each is built from a concrete agent, but the
principals come from ``USER_KINDS``, not ``SCOPE_USER_KINDS`` — GATE 2 here is
ownership, not managed scope.
"""

import os
from typing import Any

import pytest

from onyx.db.enums import Permission
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import (
    DATestAPIKey,
    DATestPersona,
    DATestUser,
)
from tests.integration.tests.permissions._access_matrix import (
    USER_KINDS,
    ScopeEndpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

pytestmark = pytest.mark.skipif(
    os.environ.get("ENABLE_PAID_ENTERPRISE_EDITION_FEATURES", "").lower() != "true",
    reason="Analytics is an enterprise-only feature",
)

PERMISSION = Permission.READ_AGENT_ANALYTICS.value

_START = "2020-01-01T00:00:00Z"
_END = "2030-01-01T00:00:00Z"

ENDPOINTS: list[ScopeEndpoint] = [
    ScopeEndpoint(
        method="GET",
        path=lambda agent: f"/analytics/admin/persona/messages?persona_id={agent.id}",
        label="persona-messages",
    ),
    ScopeEndpoint(
        method="GET",
        path=lambda agent: (
            f"/analytics/admin/persona/unique-users"
            f"?persona_id={agent.id}&start={_START}&end={_END}"
        ),
        label="persona-unique-users",
    ),
    ScopeEndpoint(
        method="GET",
        path=lambda agent: f"/analytics/assistant/{agent.id}/stats",
        label="assistant-stats",
    ),
]

# The shared matrix with one row moved: the fixture agent belongs to holder_user, and
# service_account_holder holds the token but owns nothing, so GATE 2 refuses it.
# Derived, not retyped, so a new principal in USER_KINDS reaches this file too.
_USER_KINDS: list[tuple[str, str]] = [
    (kind, "denied" if kind == "service_account_holder" else expected)
    for kind, expected in USER_KINDS
]


@pytest.fixture(scope="module")
def holder_user(permission_holder_user_factory: Any) -> DATestUser:
    return permission_holder_user_factory(PERMISSION)


@pytest.fixture(scope="module")
def holder_service_account(
    permission_holder_service_account_factory: Any,
) -> DATestAPIKey:
    return permission_holder_service_account_factory(PERMISSION)


@pytest.fixture(scope="module")
def holder_agent(
    permission_admin_user: DATestUser, holder_user: DATestUser
) -> DATestPersona:
    """Owned by the holder, so GATE 2 admits them and refuses everyone else. Created by
    the admin and handed over: the token alone can't create an agent."""
    agent = PersonaManager.create(
        user_performing_action=permission_admin_user, is_public=False
    )
    resp = call_endpoint(
        "POST",
        f"/persona/{agent.id}/transfer-ownership",
        {"new_owner_user_id": holder_user.id},
        permission_admin_user.headers,
        permission_admin_user.cookies,
    )
    assert resp.status_code == 200, resp.text
    return agent


def _assert_agent_case(
    endpoint: ScopeEndpoint,
    agent: DATestPersona,
    user_kind: str,
    expected: str,
    request: pytest.FixtureRequest,
) -> None:
    """``assert_scope_case`` over USER_KINDS credentials."""
    headers, cookies = resolve_credentials(user_kind, request)
    path = endpoint.path(agent)
    resp = call_endpoint(endpoint.method, path, endpoint.body(agent), headers, cookies)
    assert_response(resp, endpoint.method, path, user_kind, expected)


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.label)
@pytest.mark.parametrize("user_kind,expected", _USER_KINDS)
def test_access_matrix(
    endpoint: ScopeEndpoint,
    user_kind: str,
    expected: str,
    holder_agent: DATestPersona,
    request: pytest.FixtureRequest,
) -> None:
    _assert_agent_case(endpoint, holder_agent, user_kind, expected, request)


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.label)
def test_holder_is_refused_an_agent_it_does_not_own(
    endpoint: ScopeEndpoint,
    permission_admin_user: DATestUser,
    request: pytest.FixtureRequest,
) -> None:
    other = PersonaManager.create(
        user_performing_action=permission_admin_user, is_public=False
    )
    _assert_agent_case(endpoint, other, "holder", "denied", request)


@pytest.mark.parametrize("endpoint", ENDPOINTS, ids=lambda e: e.label)
def test_manage_agents_holder_reads_any_agent(
    endpoint: ScopeEndpoint,
    permission_holder_user_factory: Any,
    holder_agent: DATestPersona,
) -> None:
    # MANAGE_AGENTS implies the token and clears GATE 2 for someone else's agent.
    manager = permission_holder_user_factory(Permission.MANAGE_AGENTS.value)
    path = endpoint.path(holder_agent)
    resp = call_endpoint(
        endpoint.method,
        path,
        endpoint.body(holder_agent),
        manager.headers,
        manager.cookies,
    )
    assert_response(resp, endpoint.method, path, "manage_agents_holder", "allowed")


@pytest.mark.parametrize(
    "path",
    ["/analytics/admin/query", "/analytics/admin/user", "/analytics/admin/onyxbot"],
)
def test_org_wide_analytics_stays_admin_only(
    path: str,
    holder_user: DATestUser,
    permission_admin_user: DATestUser,
) -> None:
    # Loosening the per-agent routes must not open the org-wide dashboards.
    assert_response(
        call_endpoint("GET", path, None, holder_user.headers, holder_user.cookies),
        "GET",
        path,
        "holder",
        "denied",
    )
    assert_response(
        call_endpoint(
            "GET",
            path,
            None,
            permission_admin_user.headers,
            permission_admin_user.cookies,
        ),
        "GET",
        path,
        "admin",
        "allowed",
    )
