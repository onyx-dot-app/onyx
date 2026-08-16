"""Integration tests for the BASIC_ACCESS permission gate.

BASIC_ACCESS covers ~200 routes and is non-toggleable, so the only principals
without it are group-less service accounts, BOT / EXT_PERM_USER, and anonymous.
Endpoints are sampled one per BASIC-gated router to stay proportional.
"""

from typing import Any

import pytest

from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.permissions._access_matrix import (
    Endpoint,
    assert_response,
    call_endpoint,
    resolve_credentials,
)

# Replaces USER_KINDS: BASIC has no distinct "holder", every STANDARD user holds it.
BASIC_USER_KINDS: list[tuple[str, str]] = [
    ("admin", "allowed"),
    ("basic", "allowed"),
    ("service_account", "denied"),
    ("bot", "denied"),
    ("ext_perm", "denied"),
    ("anonymous", "anon_denied"),
]

# One per BASIC-gated router. Bogus ids are fine: the gate runs before the
# handler, so an allowed caller's 404 still proves it admitted them.
ENDPOINTS: list[Endpoint] = [
    ("GET", "/manage/credential", None),
    ("GET", "/users", None),
    ("GET", "/settings", None),
    ("GET", "/input_prompt", None),
    ("GET", "/notifications", None),
    ("GET", "/search-settings/get-all-search-settings", None),
    ("GET", "/user/pats", None),
    ("GET", "/skills", None),
    ("GET", "/user/projects", None),
    ("GET", "/persona/labels", None),
    ("GET", "/tool", None),
    ("GET", "/manage/document-set", None),
    ("GET", "/hierarchy-nodes", None),
    ("GET", "/voice/status", None),
    ("GET", "/federated", None),
    ("GET", "/user-oauth-token/status", None),
    ("GET", "/manage/indexed-sources", None),
    ("GET", "/document/document-size-info", None),
    # BASIC + GATE 2: the gate admits anyone, update_persona_* enforces ownership.
    ("PATCH", "/persona/999999/public", {"is_public": True}),
    ("PATCH", "/persona/999999/share", {"user_ids": []}),
]


# Routes on a token BASIC implies — the only HTTP-level check of the implication
# edge. Limited to tokens the limited service account lacks: it holds write:chat
# (⇒ read:chat), so READ_CHAT routes wouldn't be denied for it.
IMPLIED_ENDPOINTS: list[Endpoint] = [
    # basic ⇒ read:search
    ("GET", "/query/valid-tags", None),
]


@pytest.mark.parametrize("user_kind,expected", BASIC_USER_KINDS)
@pytest.mark.parametrize("method,path,body", ENDPOINTS)
def test_access_matrix(
    user_kind: str,
    expected: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    request: pytest.FixtureRequest,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures reset ran
) -> None:
    headers, cookies = resolve_credentials(user_kind, request)
    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)


@pytest.mark.parametrize("user_kind,expected", BASIC_USER_KINDS)
@pytest.mark.parametrize("method,path,body", IMPLIED_ENDPOINTS)
def test_implied_token_access_matrix(
    user_kind: str,
    expected: str,
    method: str,
    path: str,
    body: dict[str, Any] | None,
    request: pytest.FixtureRequest,
    permission_admin_user: DATestUser,  # noqa: ARG001 -- ensures reset ran
) -> None:
    headers, cookies = resolve_credentials(user_kind, request)
    resp = call_endpoint(method, path, body, headers, cookies)
    assert_response(resp, method, path, user_kind, expected)
