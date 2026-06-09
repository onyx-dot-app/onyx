import json
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from onyx.auth.permissions import require_permission
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import OPERATOR_LOCKED_FIELDS
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.server.security.store import apply_patch
from onyx.server.security.store import get_security_settings
from onyx.utils.logger import setup_logger
from shared_configs.configs import MULTI_TENANT

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/security")


def _parse_put_body(raw: bytes) -> tuple[SecuritySettingsOverrides, set[str]]:
    """Parse the PUT body. Returns (parsed model, present_keys).

    ``present_keys`` is the set of keys the caller actually included — needed
    downstream to distinguish absent (keep existing) from explicit-null (clear
    → env fallback), which Pydantic collapses to ``None`` on the model.
    """
    try:
        payload_dict = json.loads(raw) if raw else {}
    except json.JSONDecodeError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, f"Malformed JSON: {e}")

    if not isinstance(payload_dict, dict):
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Body must be a JSON object")

    try:
        overrides = SecuritySettingsOverrides.model_validate(payload_dict)
    except ValidationError as e:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, str(e))

    payload_dict_typed: dict[str, Any] = payload_dict
    return overrides, set(payload_dict_typed.keys())


@admin_router.get("")
def get_security_settings_endpoint(
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SecuritySettings:
    return get_security_settings()


@admin_router.put("")
async def put_security_settings_endpoint(
    request: Request,
    _: User = Depends(require_permission(Permission.FULL_ADMIN_PANEL_ACCESS)),
) -> SecuritySettings:
    raw = await request.body()
    overrides, present_keys = _parse_put_body(raw)

    # Primary boundary for operator-locked fields. The storage layer also
    # strips them; this gives admins a clear 403 instead of a silent no-op.
    if MULTI_TENANT:
        locked_in_payload = present_keys & OPERATOR_LOCKED_FIELDS
        if locked_in_payload:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "These fields are operator-controlled in multi-tenant deployments: "
                + ", ".join(sorted(locked_in_payload)),
            )

    # Sync DB + Redis IO — offload so the event loop isn't blocked.
    return await run_in_threadpool(apply_patch, overrides, present_keys)
