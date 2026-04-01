"""LTI 1.3 endpoints for Canvas (and other LMS) integration.

Implements the OIDC login initiation and launch callback required by the
LTI 1.3 spec, following the same session-issuance pattern as the SAML flow.
"""

import secrets
import uuid
from urllib.parse import urlencode

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import Request
from fastapi.responses import JSONResponse
from fastapi.responses import RedirectResponse
from fastapi_users.authentication import Strategy

from onyx.auth.users import auth_backend
from onyx.auth.users import get_user_manager
from onyx.auth.users import UserManager
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.configs.lti_configs import LTI_AUTH_LOGIN_URL
from onyx.configs.lti_configs import LTI_CLIENT_ID
from onyx.configs.lti_configs import LTI_DEPLOYMENT_ID
from onyx.configs.lti_configs import LTI_ISSUER
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.redis.redis_pool import get_async_redis_connection
from onyx.server.lti.jwks import get_public_jwks
from onyx.server.lti.utils import _extract_email_from_claims
from onyx.server.lti.utils import store_lti_state
from onyx.server.lti.utils import upsert_lti_user
from onyx.server.lti.utils import validate_and_consume_state
from onyx.server.lti.utils import validate_lti_jwt
from onyx.utils.logger import setup_logger


logger = setup_logger()
router = APIRouter(prefix="/auth/lti")


@router.get("/jwks")
async def lti_jwks() -> JSONResponse:
    """Serve Onyx's public JWKS for LTI 1.3.

    Canvas requires a Public JWK URL during Developer Key setup.
    This key would be used for signing service requests back to
    Canvas (LTI Advantage), but is also required for basic setup.
    """
    return JSONResponse(content=get_public_jwks())


@router.api_route("/login", methods=["GET", "POST"])
async def lti_login(
    request: Request,
) -> RedirectResponse:
    """OIDC Login Initiation (Step 1 of LTI 1.3 launch).

    Canvas sends this as a POST (form-encoded) or GET (query params).
    We accept both and read parameters from whichever source is available.
    """
    # Read params from form body (POST) or query string (GET)
    if request.method == "POST":
        form_data = await request.form()
        params_dict = dict(form_data)
    else:
        params_dict = dict(request.query_params)

    iss = str(params_dict.get("iss", ""))
    login_hint = str(params_dict.get("login_hint", ""))
    str(params_dict.get("target_link_uri", ""))
    lti_message_hint = params_dict.get("lti_message_hint")
    if lti_message_hint is not None:
        lti_message_hint = str(lti_message_hint)
    client_id = params_dict.get("client_id")
    if client_id is not None:
        client_id = str(client_id)

    if not iss or not login_hint:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Missing required LTI login parameters (iss, login_hint)",
        )

    # Validate the issuer matches our configured platform
    if iss != LTI_ISSUER:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown LTI issuer: {iss}",
        )

    if client_id and client_id != LTI_CLIENT_ID:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Unknown LTI client_id: {client_id}",
        )

    if not LTI_AUTH_LOGIN_URL or not LTI_CLIENT_ID:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "LTI is not fully configured on this Onyx instance",
        )

    # Generate nonce and state for OIDC flow
    nonce = secrets.token_urlsafe(32)
    state = secrets.token_urlsafe(32)

    # Store in Redis for validation on callback
    redis = await get_async_redis_connection()
    await store_lti_state(redis, state, nonce)

    # Build the redirect URL back to the LMS authorization endpoint
    redirect_uri = f"{WEB_DOMAIN}/auth/lti/launch"
    params = {
        "scope": "openid",
        "response_type": "id_token",
        "client_id": LTI_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "login_hint": login_hint,
        "state": state,
        "response_mode": "form_post",
        "nonce": nonce,
        "prompt": "none",
    }
    if lti_message_hint is not None:
        params["lti_message_hint"] = lti_message_hint

    auth_url = f"{LTI_AUTH_LOGIN_URL}?{urlencode(params)}"
    return RedirectResponse(url=auth_url, status_code=302)


@router.post("/launch")
async def lti_launch(
    request: Request,
    id_token: str = Form(...),
    state: str = Form(...),
    user_manager: UserManager = Depends(get_user_manager),
    strategy: Strategy[User, uuid.UUID] = Depends(auth_backend.get_strategy),
) -> RedirectResponse:
    """LTI 1.3 Launch Callback (Step 2).

    Canvas auto-submits a form POST with the signed JWT (id_token) and
    state. We validate everything, provision the user, issue a session,
    and redirect into the embedded chat UI.
    """
    # Validate and consume the state (atomic -- prevents replay)
    redis = await get_async_redis_connection()
    expected_nonce = await validate_and_consume_state(redis, state)

    # Validate the JWT
    claims = await validate_lti_jwt(id_token, expected_nonce)

    # Verify deployment ID if present
    deployment_id = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/deployment_id"
    )
    if deployment_id and LTI_DEPLOYMENT_ID and deployment_id != LTI_DEPLOYMENT_ID:
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            f"LTI deployment ID mismatch: {deployment_id}",
        )

    # Extract user info
    email = _extract_email_from_claims(claims)
    lti_roles = claims.get("https://purl.imsglobal.org/spec/lti/claim/roles", [])

    logger.info("LTI launch for user %s with roles %s", email, lti_roles)

    # JIT provision or retrieve the user
    user = await upsert_lti_user(email, lti_roles)

    # Issue a session (same pattern as SAML)
    response = await auth_backend.login(strategy, user)
    await user_manager.on_after_login(user, request, response)

    # Override cookie attributes for iframe embedding
    _patch_cookie_for_embedding(response)

    # Build redirect URL
    redirect_url = f"{WEB_DOMAIN}/app?embedded=true"

    # Check for custom assistant_id parameter
    custom_claims = claims.get("https://purl.imsglobal.org/spec/lti/claim/custom", {})
    assistant_id = custom_claims.get("assistant_id")
    if assistant_id:
        redirect_url += f"&assistantId={assistant_id}"

    # Transfer cookies from the login response to the redirect
    redirect_response = RedirectResponse(url=redirect_url, status_code=302)
    for header_name, header_value in response.headers.items():
        if header_name.lower() == "set-cookie":
            redirect_response.headers.append("set-cookie", header_value)

    return redirect_response


def _patch_cookie_for_embedding(response: object) -> None:
    """Rewrite Set-Cookie headers so the session cookie works inside an iframe.

    The CookieTransport from fastapi-users sets SameSite=Lax by default,
    which blocks the cookie in a cross-origin iframe. We need
    SameSite=None; Secure; Partitioned for CHIPS support.
    """
    from starlette.responses import Response as StarletteResponse

    if not isinstance(response, StarletteResponse):
        return

    patched_raw: list[tuple[bytes, bytes]] = []
    for key, value in response.headers.raw:
        if key.lower() == b"set-cookie":
            cookie_str = value.decode("latin-1")
            # Replace SameSite=Lax with SameSite=None
            cookie_str = cookie_str.replace("SameSite=lax", "SameSite=None")
            cookie_str = cookie_str.replace("SameSite=Lax", "SameSite=None")
            # Ensure Secure flag is present (required for SameSite=None)
            if "Secure" not in cookie_str:
                cookie_str += "; Secure"
            # Add Partitioned for CHIPS support
            if "Partitioned" not in cookie_str:
                cookie_str += "; Partitioned"
            patched_raw.append((key, cookie_str.encode("latin-1")))
        else:
            patched_raw.append((key, value))

    # Replace the raw header list in-place
    response.headers.raw.clear()
    response.headers.raw.extend(patched_raw)
