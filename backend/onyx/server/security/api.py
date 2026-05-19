from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.permissions import require_permission
from onyx.configs.app_configs import AUTH_TYPE
from onyx.configs.app_configs import ENCRYPTION_KEY_SECRET
from onyx.configs.app_configs import JWT_PUBLIC_KEY_URL
from onyx.configs.app_configs import OAUTH_CLIENT_ID
from onyx.configs.app_configs import OIDC_PKCE_ENABLED
from onyx.configs.app_configs import OPENID_CONFIG_URL
from onyx.configs.app_configs import USER_AUTH_SECRET
from onyx.configs.constants import AuthType
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecurityStatus
from onyx.server.security.store import load_security_settings
from onyx.server.security.store import store_security_settings
from shared_configs.configs import CORS_ALLOWED_ORIGIN_ENV
from shared_configs.configs import MULTI_TENANT

admin_router = APIRouter(prefix="/admin/security")

# Fields a tenant admin is not allowed to override in multi-tenant mode.
# These are operator-controlled floors (anti-spam, baseline auth strength,
# uniform credential masking). The frontend hides them; this list is the
# authoritative server-side enforcement.
_OPERATOR_LOCKED_FIELDS = {
    "require_email_verification",
    "mask_credential_prefix",
    "valid_email_domains",
    "password_min_length",
    "password_max_length",
    "password_require_uppercase",
    "password_require_lowercase",
    "password_require_digit",
    "password_require_special_char",
}


@admin_router.get("")
def admin_get_security_settings(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SecuritySettings:
    return load_security_settings()


@admin_router.put("")
def admin_put_security_settings(
    settings: SecuritySettings,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> None:
    if MULTI_TENANT:
        incoming = settings.model_dump(exclude_unset=True)
        locked = _OPERATOR_LOCKED_FIELDS.intersection(incoming.keys())
        if locked:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                f"The following fields are managed by your operator and "
                f"cannot be changed: {', '.join(sorted(locked))}",
            )

    if (
        settings.password_min_length is not None
        and settings.password_max_length is not None
        and settings.password_min_length > settings.password_max_length
    ):
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Password minimum length cannot exceed maximum length.",
        )

    store_security_settings(settings)


@admin_router.get("/status")
def admin_get_security_status(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SecurityStatus:
    saml_configured = AUTH_TYPE == AuthType.SAML
    oidc_configured = bool(OPENID_CONFIG_URL) or AUTH_TYPE == AuthType.OIDC
    return SecurityStatus(
        auth_type=AUTH_TYPE.value,
        multi_tenant=MULTI_TENANT,
        encryption_key_configured=bool(ENCRYPTION_KEY_SECRET),
        user_auth_secret_configured=bool(USER_AUTH_SECRET),
        oauth_configured=bool(OAUTH_CLIENT_ID),
        oidc_configured=oidc_configured,
        oidc_pkce_enabled=OIDC_PKCE_ENABLED,
        saml_configured=saml_configured,
        jwt_public_key_configured=bool(JWT_PUBLIC_KEY_URL),
        cors_restricted=_is_cors_restricted(),
    )


def _is_cors_restricted() -> bool:
    # Unset / empty / "*" all mean "allow any origin"; treat anything else
    # as a real allowlist.
    return bool(CORS_ALLOWED_ORIGIN_ENV.strip()) and CORS_ALLOWED_ORIGIN_ENV.strip() != "*"
