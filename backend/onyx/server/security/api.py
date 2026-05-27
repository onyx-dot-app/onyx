import json
from typing import Any

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from pydantic import ValidationError

from onyx.auth.permissions import require_permission
from onyx.cache.factory import get_cache_backend
from onyx.configs.constants import OnyxRedisLocks
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.security.models import SecuritySettings
from onyx.server.security.models import SecuritySettingsOverrides
from onyx.server.security.store import get_security_settings
from onyx.server.security.store import is_multi_tenant
from onyx.server.security.store import load_raw_overrides
from onyx.server.security.store import merge_with_env
from onyx.server.security.store import OPERATOR_LOCKED_FIELDS
from onyx.server.security.store import store_overrides
from onyx.utils.logger import setup_logger

logger = setup_logger()

admin_router = APIRouter(prefix="/admin/security")


# Lock lifetime if the handler crashes mid-write. PUT itself is fast (a
# read + merge + KV write), so 30s is generous.
_LOCK_LEASE_SECONDS = 30.0
# How long a competing PUT will wait for the in-progress one to finish
# before giving up with a 5xx. 10s is plenty for a single KV roundtrip.
_LOCK_WAIT_SECONDS = 10.0

# Sanity cap for password length: env default is 64 today, so a 256 ceiling
# does not change any current behavior.
_PASSWORD_LENGTH_CAP = 256


def _parse_put_body(raw: bytes) -> tuple[SecuritySettingsOverrides, dict[str, Any]]:
    """Parse and validate the PUT body, mapping every error shape to
    OnyxErrorCode.INVALID_INPUT so callers see one envelope.

    Returns (parsed model, raw dict) so the caller can distinguish absent
    fields from explicit nulls without going back through Pydantic.
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

    return overrides, payload_dict


def _validate_effective(effective: SecuritySettings) -> None:
    if effective.password_min_length < 0:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "password_min_length must be >= 0",
        )
    if effective.password_max_length < 1:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "password_max_length must be >= 1",
        )
    if effective.password_max_length > _PASSWORD_LENGTH_CAP:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"password_max_length must be <= {_PASSWORD_LENGTH_CAP}",
        )
    if effective.password_min_length > effective.password_max_length:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "password_min_length must be <= password_max_length",
        )


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
    overrides, raw_dict = _parse_put_body(raw)

    # Track which keys the caller actually sent. Distinguishing "absent" from
    # "explicit null" is required for PATCH semantics — model_dump can't.
    present_keys = set(raw_dict.keys())

    # Operator-locked field rejection — primary boundary. The storage layer
    # also strips these, but failing fast here gives the admin a clear 403.
    if is_multi_tenant():
        locked_in_payload = present_keys & OPERATOR_LOCKED_FIELDS
        if locked_in_payload:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "These fields are operator-controlled in multi-tenant deployments: "
                + ", ".join(sorted(locked_in_payload)),
            )

    # The merge + KV write is sync I/O (KV store + cache lock). Offload to a
    # threadpool so the event loop is never blocked on Postgres/Redis.
    return await run_in_threadpool(
        _persist_overrides, overrides, raw_dict, present_keys
    )


def _persist_overrides(
    overrides: SecuritySettingsOverrides,
    raw_dict: dict[str, Any],
    present_keys: set[str],
) -> SecuritySettings:
    """Synchronous lock-acquire + merge + KV write. Uses ``get_cache_backend()``
    so it works in deployments without Redis (e.g. Onyx Lite, which runs only
    frontend, backend, Postgres, and nginx)."""
    cache = get_cache_backend()
    lock = cache.lock(OnyxRedisLocks.SECURITY_SETTINGS, timeout=_LOCK_LEASE_SECONDS)
    if not lock.acquire(blocking=True, blocking_timeout=_LOCK_WAIT_SECONDS):
        raise OnyxError(
            OnyxErrorCode.INTERNAL_ERROR,
            "Another security settings save is in progress, please retry.",
        )

    try:
        existing_dict = load_raw_overrides().model_dump(exclude_none=True)

        # Manual merge: explicit null in the request removes the key (falls
        # back to env), an explicit value sets it, an absent key is left
        # alone. model_copy(update=...) can't distinguish absent from None.
        for key in present_keys:
            value = raw_dict.get(key)
            if value is None:
                existing_dict.pop(key, None)
            else:
                # Use the Pydantic-validated value (handles normalization
                # like the valid_email_domains lowercasing).
                existing_dict[key] = getattr(overrides, key)

        merged = SecuritySettingsOverrides.model_validate(existing_dict)
        effective = merge_with_env(merged)
        _validate_effective(effective)
        store_overrides(merged)
        return effective
    finally:
        if lock.owned():
            lock.release()
