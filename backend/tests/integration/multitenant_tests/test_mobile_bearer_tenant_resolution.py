"""Multi-tenant regression test for mobile bearer-token tenant resolution.

A mobile client authenticates with the opaque session token in the
``Authorization: Bearer`` header (no cookie). In multi-tenant cloud the EE tenant
middleware must resolve the tenant from that header — otherwise every authed
route falls back to the default schema and the user (who lives in their own
tenant schema) is not found.

This guards against that gap: it fails before the bearer-header path is added to
``_get_tenant_id_from_request`` and passes after. The single-tenant counterpart
(``tests/mobile_auth/test_mobile_bearer_auth.py``) can't catch it because the
middleware short-circuits to the default schema when ``MULTI_TENANT`` is off.
"""

from uuid import uuid4

from onyx.db.models import UserRole
from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.managers.user import UserManager
from tests.integration.common_utils.test_models import DATestUser
from tests.integration.tests.mobile_auth._helpers import bearer
from tests.integration.tests.mobile_auth._helpers import mobile_login


def test_mobile_bearer_resolves_tenant(reset_multitenant: None) -> None:  # noqa: ARG001
    # A fresh email provisions its own tenant; the first user is ADMIN and lives
    # in that tenant's schema, not the default/public schema.
    unique = uuid4().hex
    user: DATestUser = UserManager.create(
        name=f"mobile_{unique}", email=f"mobile_{unique}@example.com"
    )
    assert UserManager.is_role(user, UserRole.ADMIN)

    # Obtain a Bearer session token via the mobile login endpoint.
    resp = mobile_login(user.email, user.password)
    resp.raise_for_status()
    token = resp.json()["access_token"]
    assert token

    # Drop every cookie so the Bearer header is the ONLY tenant signal. Without
    # this, the leftover web session cookie from UserManager.create would resolve
    # the tenant and mask the bug we're guarding against.
    client.cookies.clear()

    # /me must resolve to this user's tenant. If the middleware can't read the
    # tenant from the Bearer header it falls back to the default schema, the user
    # lookup misses, and this returns 401/403 instead of the user.
    me = client.get(url=f"{API_SERVER_URL}/me", headers=bearer(token))
    me.raise_for_status()
    assert me.json()["email"] == user.email
