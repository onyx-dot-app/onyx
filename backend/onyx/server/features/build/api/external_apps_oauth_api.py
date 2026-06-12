import base64
import uuid
from datetime import datetime
from datetime import timezone

from fastapi import APIRouter
from fastapi import Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import WEB_DOMAIN
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import Permission
from onyx.db.external_app import get_external_app_by_id
from onyx.db.external_app import upsert_external_app_user_credential
from onyx.db.models import ExternalApp
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.oauth_handler import OAuthFlowHandler
from onyx.external_apps.oauth_handler import TokenRequestError
from onyx.external_apps.providers.registry import resolve_oauth_handler
from onyx.external_apps.token_utils import stamp_expires_at
from onyx.redis.redis_pool import get_redis_client
from onyx.server.features.build.api.models import OAuthCallbackRequest
from onyx.server.features.build.api.models import OAuthCallbackResponse
from onyx.server.features.build.api.models import OAuthRedirectUriResponse
from onyx.server.features.build.api.models import OAuthStartResponse
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter()

# Must be registered as a redirect URI in each provider's developer
# console.
_FRONTEND_CALLBACK_PATH = "/craft/v1/apps/oauth/callback"

# Distinct from `da_oauth:` used by the Slack-connector OAuth flow.
_REDIS_KEY_PREFIX = "da_ea_oauth:"
_REDIS_STATE_TTL_SECONDS = 600


def _oauth_client_credentials(app: ExternalApp) -> tuple[str, str]:
    org_credentials = app.organization_credentials.get_value(apply_mask=False)
    client_id = org_credentials.get("client_id")
    client_secret = org_credentials.get("client_secret")
    if not client_id or not client_secret:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"{app.skill.name} is missing client_id or client_secret — "
            "ask an admin to fill them in on the Manage Apps page.",
        )
    return client_id, client_secret


def _frontend_callback_url() -> str:
    return f"{WEB_DOMAIN}{_FRONTEND_CALLBACK_PATH}"


def _oauth_handler_or_raise(app: ExternalApp) -> OAuthFlowHandler:
    """The app's OAuth handler (built-in provider or admin-defined custom
    config), or 400 for a static-credential app."""
    handler = resolve_oauth_handler(app)
    if handler is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"App '{app.skill.name}' does not use an OAuth flow.",
        )
    return handler


class _OAuthStateRecord(BaseModel):
    """Redis state — not part of the HTTP API."""

    user_id: str
    external_app_id: int


@router.get("/admin/apps/oauth/redirect-uri")
def get_oauth_redirect_uri(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> OAuthRedirectUriResponse:
    """The redirect URI the OAuth routes send, for the admin to register with
    the provider. See ``OAuthRedirectUriResponse``."""
    return OAuthRedirectUriResponse(redirect_uri=_frontend_callback_url())


@router.get("/apps/{external_app_id}/oauth/start")
def start_external_app_oauth(
    external_app_id: int,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> OAuthStartResponse:
    app = get_external_app_by_id(db_session, external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {external_app_id} not found.",
        )
    if not app.skill.enabled:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "This app is currently disabled by an admin.",
        )
    handler = _oauth_handler_or_raise(app)
    client_id, _client_secret = _oauth_client_credentials(app)

    oauth_uuid = uuid.uuid4()
    state = base64.urlsafe_b64encode(oauth_uuid.bytes).rstrip(b"=").decode("ascii")

    tenant_id = get_current_tenant_id()
    r = get_redis_client(tenant_id=tenant_id)
    record = _OAuthStateRecord(user_id=str(user.id), external_app_id=external_app_id)
    r.set(
        f"{_REDIS_KEY_PREFIX}{oauth_uuid}",
        record.model_dump_json(),
        ex=_REDIS_STATE_TTL_SECONDS,
    )

    authorize_url = handler.build_authorize_url(
        client_id=client_id,
        redirect_uri=_frontend_callback_url(),
        state=state,
    )
    return OAuthStartResponse(authorize_url=authorize_url)


@router.post("/apps/oauth/callback")
def handle_external_app_oauth_callback(
    request: OAuthCallbackRequest,
    user: User = Depends(require_permission(Permission.BASIC_ACCESS)),
    db_session: Session = Depends(get_session),
) -> OAuthCallbackResponse:
    tenant_id = get_current_tenant_id()
    r = get_redis_client(tenant_id=tenant_id)

    padded_state = request.state + "=" * (-len(request.state) % 4)
    try:
        uuid_bytes = base64.urlsafe_b64decode(padded_state)
        oauth_uuid = uuid.UUID(bytes=uuid_bytes)
    except (ValueError, TypeError):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Malformed OAuth state.")

    redis_key = f"{_REDIS_KEY_PREFIX}{oauth_uuid}"
    record_bytes = r.get(redis_key)
    if record_bytes is None:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "OAuth state expired or unknown — restart the connection flow.",
        )
    record = _OAuthStateRecord.model_validate_json(record_bytes.decode("utf-8"))

    # Prevent one user's state from being redeemed by another.
    if record.user_id != str(user.id):
        raise OnyxError(
            OnyxErrorCode.UNAUTHENTICATED,
            "OAuth state does not match the calling user.",
        )

    app = get_external_app_by_id(db_session, record.external_app_id)
    if app is None:
        raise OnyxError(
            OnyxErrorCode.NOT_FOUND,
            f"External app with id {record.external_app_id} no longer exists.",
        )

    handler = _oauth_handler_or_raise(app)
    # Re-read in case the admin rotated creds between /start and /callback.
    client_id, client_secret = _oauth_client_credentials(app)

    try:
        extracted = handler.exchange_authorization_code(
            code=request.code,
            redirect_uri=_frontend_callback_url(),
            client_id=client_id,
            client_secret=client_secret,
        )
    except TokenRequestError as exc:
        # Transport failures and provider error codes alike; an unmappable
        # success response raises OnyxError from extract_credentials directly.
        logger.warning(
            "%s OAuth token exchange failed for user %s, app %d: %s",
            app.skill.name,
            user.id,
            app.id,
            exc,
        )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            f"{app.skill.name} OAuth failed: {exc}",
        )

    # Stamp an absolute `expires_at` now so the lazy-refresh path can later
    # decide staleness without "when was this written" bookkeeping.
    stored_credentials = stamp_expires_at(extracted, datetime.now(timezone.utc))

    upsert_external_app_user_credential(
        db_session,
        external_app_id=app.id,
        user_id=user.id,
        user_credentials=stored_credentials,
    )

    # One-shot — prevent replay.
    r.delete(redis_key)

    return OAuthCallbackResponse(success=True, external_app_id=app.id)
