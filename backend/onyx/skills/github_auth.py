from uuid import UUID

from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ExternalAppType
from onyx.db.external_app import (
    get_built_in_external_app,
    get_external_app_user_credential,
)
from onyx.db.users import fetch_user_by_id
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.external_apps.credentials import resolve_injection_headers
from onyx.external_apps.token_refresh import ensure_fresh_credentials
from onyx.skills.marketplace.models import MARKETPLACE_LOGIN_ERROR


def github_authorization_header(
    tenant_id: str, user_id: UUID | None, *, require_user_connection: bool = False
) -> str | None:
    if user_id is None:
        raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, MARKETPLACE_LOGIN_ERROR)
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        github_app = get_built_in_external_app(db_session, ExternalAppType.GITHUB)
        if require_user_connection:
            user = fetch_user_by_id(db_session, user_id)
            if (
                user is None
                or not user.is_active
                or github_app is None
                or not github_app.enabled
                or get_external_app_user_credential(
                    db_session, external_app_id=github_app.id, user_id=user_id
                )
                is None
            ):
                raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, MARKETPLACE_LOGIN_ERROR)
        if github_app is None or not github_app.enabled:
            return None
        github_app_id = github_app.id

    ensure_fresh_credentials(tenant_id, github_app_id, user_id)
    with get_session_with_tenant(tenant_id=tenant_id) as db_session:
        if (
            require_user_connection
            and get_external_app_user_credential(
                db_session, external_app_id=github_app_id, user_id=user_id
            )
            is None
        ):
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, MARKETPLACE_LOGIN_ERROR)
        authorization = resolve_injection_headers(
            db_session, github_app_id, user_id
        ).get("Authorization")
        if require_user_connection and not authorization:
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED, MARKETPLACE_LOGIN_ERROR)
        return authorization
