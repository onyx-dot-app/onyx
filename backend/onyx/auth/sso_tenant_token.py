"""Signed workspace pin for an in-flight cloud SSO login.

Cloud serves every workspace from one domain, so the SSO login routes have no
tenant until the user identifies themselves. Discovery resolves the workspace
from the catalog and returns this token. The authorize call presents it to
select the schema holding the provider row. Signed because the tenant it names
decides which workspace's IdP configuration is read, and short-lived because it
only has to survive the click between discovery and authorize.
"""

from typing import Any

import jwt
from fastapi_users.jwt import decode_jwt, generate_jwt

from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.db.engine.sql_engine import is_valid_schema_name
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError

SSO_TENANT_TOKEN_AUDIENCE = "onyx:sso-login-tenant"
SSO_TENANT_TOKEN_LIFETIME_SECONDS = 600
SSO_TENANT_TOKEN_PARAM = "workspace_token"

_TENANT_CLAIM = "tenant_id"


def generate_sso_tenant_token(tenant_id: str) -> str:
    data: dict[str, Any] = {
        _TENANT_CLAIM: tenant_id,
        "aud": SSO_TENANT_TOKEN_AUDIENCE,
    }
    return generate_jwt(data, USER_AUTH_SECRET, SSO_TENANT_TOKEN_LIFETIME_SECONDS)


def decode_sso_tenant_token(token: str) -> str:
    """The tenant this login step is pinned to. Raises when the token is
    unsigned by us, expired, or names something that is not a schema."""
    try:
        payload = decode_jwt(token, USER_AUTH_SECRET, [SSO_TENANT_TOKEN_AUDIENCE])
    except jwt.PyJWTError as e:
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Sign-in link has expired. Return to the login page and try again.",
        ) from e

    tenant_id = payload.get(_TENANT_CLAIM)
    if not isinstance(tenant_id, str) or not is_valid_schema_name(tenant_id):
        raise OnyxError(
            OnyxErrorCode.UNAUTHORIZED,
            "Sign-in link is not valid for any workspace.",
        )
    return tenant_id
