from fastapi import APIRouter
from fastapi import Depends

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import SecuritySettings
from onyx.server.security.store import load_security_settings
from onyx.server.security.store import store_security_settings
from shared_configs.configs import MULTI_TENANT

admin_router = APIRouter(prefix="/admin/security")

# Fields a tenant admin is not allowed to override in multi-tenant mode.
# These are operator-controlled floors (anti-spam, baseline auth strength,
# uniform credential masking). The frontend hides them; this list is the
# authoritative server-side enforcement.
_OPERATOR_LOCKED_FIELDS = {
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
