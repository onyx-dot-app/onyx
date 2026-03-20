import ipaddress
import socket
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Query
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import User
from onyx.db.constants import UNSET
from onyx.db.constants import UnsetType
from onyx.db.engine.sql_engine import get_session
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.hook import create_hook__no_commit
from onyx.db.hook import delete_hook__no_commit
from onyx.db.hook import get_hook_by_id
from onyx.db.hook import get_hook_execution_logs
from onyx.db.hook import get_hooks
from onyx.db.hook import update_hook__no_commit
from onyx.db.models import Hook
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.api_dependencies import require_hook_enabled
from onyx.hooks.models import HookCreateRequest
from onyx.hooks.models import HookFailureRecord
from onyx.hooks.models import HookPointMetaResponse
from onyx.hooks.models import HookResponse
from onyx.hooks.models import HookUpdateRequest
from onyx.hooks.models import HookValidateResponse
from onyx.hooks.models import HookValidateStatus
from onyx.hooks.registry import get_all_specs
from onyx.hooks.registry import get_hook_point_spec
from onyx.utils.logger import setup_logger

logger = setup_logger()

# ---------------------------------------------------------------------------
# SSRF protection
# ---------------------------------------------------------------------------

# RFC 1918 private ranges, loopback, link-local (IMDS at 169.254.169.254),
# shared address space, and IPv6 equivalents.
_BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    ipaddress.ip_network("127.0.0.0/8"),  # loopback
    ipaddress.ip_network("10.0.0.0/8"),  # RFC 1918
    ipaddress.ip_network("172.16.0.0/12"),  # RFC 1918
    ipaddress.ip_network("192.168.0.0/16"),  # RFC 1918
    ipaddress.ip_network("169.254.0.0/16"),  # link-local / cloud IMDS
    ipaddress.ip_network("100.64.0.0/10"),  # shared address space (RFC 6598)
    ipaddress.ip_network("0.0.0.0/8"),  # "this" network
    ipaddress.ip_network("::1/128"),  # IPv6 loopback
    ipaddress.ip_network("fc00::/7"),  # IPv6 ULA
    ipaddress.ip_network("fe80::/10"),  # IPv6 link-local
]


def _check_ssrf_safety(endpoint_url: str) -> None:
    """Raise OnyxError if endpoint_url could be used for SSRF.

    Checks:
    1. Scheme must be https.
    2. All IPs the hostname resolves to must be public — private/reserved
       ranges (RFC 1918, link-local, loopback, cloud IMDS) are blocked.

    Note: this provides a good-faith pre-flight check. DNS rebinding attacks
    (where the hostname re-resolves to a different IP after this check) are
    outside the threat model for a single-tenant, admin-only API.
    """
    parsed = urlparse(endpoint_url)

    scheme = (parsed.scheme or "").lower()
    if scheme != "https":
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Hook endpoint URL must use https, got: {scheme!r}",
        )

    hostname = parsed.hostname
    if not hostname:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Could not parse hostname from URL: {endpoint_url}",
        )

    try:
        resolved = socket.getaddrinfo(hostname, None)
    except socket.gaierror as e:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            f"Could not resolve hostname {hostname!r}: {e}",
        )

    for addr_info in resolved:
        ip_str = addr_info[4][0]
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            continue
        for blocked in _BLOCKED_NETWORKS:
            if ip in blocked:
                raise OnyxError(
                    OnyxErrorCode.INVALID_INPUT,
                    f"Hook endpoint URL resolves to a private or reserved IP address "
                    f"({ip}), which is not permitted.",
                )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _hook_to_response(hook: Hook, creator_email: str | None = None) -> HookResponse:
    return HookResponse(
        id=hook.id,
        name=hook.name,
        hook_point=hook.hook_point,
        endpoint_url=hook.endpoint_url,
        fail_strategy=hook.fail_strategy,
        timeout_seconds=hook.timeout_seconds,
        is_active=hook.is_active,
        is_reachable=hook.is_reachable,
        creator_email=(
            creator_email
            if creator_email is not None
            else (hook.creator.email if hook.creator else None)
        ),
        created_at=hook.created_at,
        updated_at=hook.updated_at,
    )


def _get_hook_or_404(
    db_session: Session,
    hook_id: int,
    include_creator: bool = False,
) -> Hook:
    hook = get_hook_by_id(
        db_session=db_session,
        hook_id=hook_id,
        include_creator=include_creator,
    )
    if hook is None:
        raise OnyxError(OnyxErrorCode.NOT_FOUND, f"Hook {hook_id} not found.")
    return hook


def _raise_for_validation_failure(validation: HookValidateResponse) -> None:
    """Raise an appropriate OnyxError for a non-passed validation result."""
    if validation.status == HookValidateStatus.auth_failed:
        raise OnyxError(OnyxErrorCode.CREDENTIAL_INVALID, validation.error_message)
    if validation.status == HookValidateStatus.timeout:
        raise OnyxError(
            OnyxErrorCode.GATEWAY_TIMEOUT,
            f"Endpoint validation failed: {validation.error_message}",
        )
    raise OnyxError(
        OnyxErrorCode.BAD_GATEWAY,
        f"Endpoint validation failed: {validation.error_message}",
    )


def _validate_endpoint(
    endpoint_url: str,
    api_key: str | None,
    timeout_seconds: float,
) -> HookValidateResponse:
    """Check whether endpoint_url is reachable by sending an empty POST request.

    We use POST since hook endpoints expect POST requests. The server will typically
    respond with 4xx (missing/invalid body) — that is fine. Any HTTP response means
    the server is up and routable. A 401/403 response returns auth_failed
    (not reachable — indicates the api_key is invalid).

    Timeout handling:
    - ConnectTimeout: TCP handshake never completed → cannot_connect.
    - ReadTimeout / WriteTimeout: TCP was established, server responded slowly → timeout
      (operator should consider increasing timeout_seconds).
    - All other exceptions → cannot_connect.
    """
    _check_ssrf_safety(endpoint_url)
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(endpoint_url, headers=headers)
        if response.status_code in (401, 403):
            return HookValidateResponse(
                status=HookValidateStatus.auth_failed,
                error_message=f"Authentication failed (HTTP {response.status_code})",
            )
        return HookValidateResponse(status=HookValidateStatus.passed)
    except httpx.TimeoutException as exc:
        # ConnectTimeout: TCP handshake never completed → cannot_connect.
        # ReadTimeout / WriteTimeout: TCP was established, server just responded slowly → timeout.
        if isinstance(exc, httpx.ConnectTimeout):
            logger.warning(
                "Hook endpoint validation: connect timeout for %s",
                endpoint_url,
                exc_info=exc,
            )
            return HookValidateResponse(
                status=HookValidateStatus.cannot_connect, error_message=str(exc)
            )
        logger.warning(
            "Hook endpoint validation: read/write timeout for %s",
            endpoint_url,
            exc_info=exc,
        )
        return HookValidateResponse(
            status=HookValidateStatus.timeout,
            error_message="Endpoint timed out — consider increasing timeout_seconds.",
        )
    except Exception as exc:
        logger.warning(
            "Hook endpoint validation: connection error for %s",
            endpoint_url,
            exc_info=exc,
        )
        return HookValidateResponse(
            status=HookValidateStatus.cannot_connect, error_message=str(exc)
        )


# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

router = APIRouter(prefix="/admin/hooks")


# ---------------------------------------------------------------------------
# Hook endpoints
# ---------------------------------------------------------------------------


@router.get("/specs")
def get_hook_point_specs(
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
) -> list[HookPointMetaResponse]:
    return [
        HookPointMetaResponse(
            hook_point=spec.hook_point,
            display_name=spec.display_name,
            description=spec.description,
            docs_url=spec.docs_url,
            input_schema=spec.input_schema,
            output_schema=spec.output_schema,
            default_timeout_seconds=spec.default_timeout_seconds,
            default_fail_strategy=spec.default_fail_strategy,
            fail_hard_description=spec.fail_hard_description,
        )
        for spec in get_all_specs()
    ]


@router.get("")
def list_hooks(
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> list[HookResponse]:
    hooks = get_hooks(db_session=db_session, include_creator=True)
    return [_hook_to_response(h) for h in hooks]


@router.post("")
def create_hook(
    req: HookCreateRequest,
    user: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> HookResponse:
    """Create a new hook. The endpoint is validated before persisting — creation fails if
    the endpoint cannot be reached or the api_key is invalid. Hooks are created inactive;
    use POST /{hook_id}/activate once ready to receive traffic."""
    spec = get_hook_point_spec(req.hook_point)
    api_key = req.api_key.get_secret_value() if req.api_key else None
    validation = _validate_endpoint(
        endpoint_url=req.endpoint_url,
        api_key=api_key,
        timeout_seconds=req.timeout_seconds or spec.default_timeout_seconds,
    )
    if validation.status != HookValidateStatus.passed:
        _raise_for_validation_failure(validation)

    hook = create_hook__no_commit(
        db_session=db_session,
        name=req.name,
        hook_point=req.hook_point,
        endpoint_url=req.endpoint_url,
        api_key=api_key,
        fail_strategy=req.fail_strategy or spec.default_fail_strategy,
        timeout_seconds=req.timeout_seconds or spec.default_timeout_seconds,
        creator_id=user.id,
    )
    hook.is_reachable = True
    db_session.commit()
    return _hook_to_response(hook, creator_email=user.email)


@router.get("/{hook_id}")
def get_hook(
    hook_id: int,
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> HookResponse:
    hook = _get_hook_or_404(db_session, hook_id, include_creator=True)
    return _hook_to_response(hook)


@router.patch("/{hook_id}")
def update_hook(
    hook_id: int,
    req: HookUpdateRequest,
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> HookResponse:
    """Update hook fields. If endpoint_url, api_key, or timeout_seconds changes, the
    endpoint is re-validated using the effective values. For active hooks the update is
    rejected on validation failure, keeping live traffic unaffected. For inactive hooks
    the update goes through regardless and is_reachable is updated to reflect the result.

    Note: if an active hook's endpoint is currently down, even a timeout_seconds-only
    increase will be rejected. The recovery flow is: deactivate → update → reactivate.
    """
    # api_key: UNSET = no change, None = clear, value = update
    api_key: str | None | UnsetType
    if "api_key" not in req.model_fields_set:
        api_key = UNSET
    elif req.api_key is None:
        api_key = None
    else:
        api_key = req.api_key.get_secret_value()

    endpoint_url_changing = "endpoint_url" in req.model_fields_set
    api_key_changing = not isinstance(api_key, UnsetType)
    timeout_changing = "timeout_seconds" in req.model_fields_set

    validated_is_reachable: bool | None = None
    if endpoint_url_changing or api_key_changing or timeout_changing:
        existing = _get_hook_or_404(db_session, hook_id)
        effective_url: str = (
            req.endpoint_url if endpoint_url_changing else existing.endpoint_url  # type: ignore[assignment]  # endpoint_url is required on create and cannot be cleared on update
        )
        effective_api_key: str | None = (
            (api_key if not isinstance(api_key, UnsetType) else None)
            if api_key_changing
            else (
                existing.api_key.get_value(apply_mask=False)
                if existing.api_key
                else None
            )
        )
        effective_timeout: float = (
            req.timeout_seconds if timeout_changing else existing.timeout_seconds  # type: ignore[assignment]  # req.timeout_seconds is non-None when timeout_changing (validated by HookUpdateRequest)
        )
        validation = _validate_endpoint(
            endpoint_url=effective_url,
            api_key=effective_api_key,
            timeout_seconds=effective_timeout,
        )
        if existing.is_active and validation.status != HookValidateStatus.passed:
            _raise_for_validation_failure(validation)
        validated_is_reachable = validation.status == HookValidateStatus.passed

    hook = update_hook__no_commit(
        db_session=db_session,
        hook_id=hook_id,
        name=req.name,
        endpoint_url=(req.endpoint_url if endpoint_url_changing else UNSET),
        api_key=api_key,
        fail_strategy=req.fail_strategy,
        timeout_seconds=req.timeout_seconds,
        is_reachable=validated_is_reachable,
        include_creator=True,
    )
    db_session.commit()
    return _hook_to_response(hook)


@router.delete("/{hook_id}")
def delete_hook(
    hook_id: int,
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> None:
    delete_hook__no_commit(db_session=db_session, hook_id=hook_id)
    db_session.commit()


@router.post("/{hook_id}/activate")
def activate_hook(
    hook_id: int,
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> HookResponse:
    hook = _get_hook_or_404(db_session, hook_id)
    if not hook.endpoint_url:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Hook has no endpoint URL configured."
        )

    api_key = hook.api_key.get_value(apply_mask=False) if hook.api_key else None
    validation = _validate_endpoint(
        endpoint_url=hook.endpoint_url,
        api_key=api_key,
        timeout_seconds=hook.timeout_seconds,
    )
    if validation.status != HookValidateStatus.passed:
        # Persist is_reachable=False in a separate session so the request
        # session has no commits on the failure path and the transaction
        # boundary stays clean.
        if hook.is_reachable is not False:
            with get_session_with_current_tenant() as side_session:
                update_hook__no_commit(
                    db_session=side_session, hook_id=hook_id, is_reachable=False
                )
                side_session.commit()
        _raise_for_validation_failure(validation)

    hook = update_hook__no_commit(
        db_session=db_session,
        hook_id=hook_id,
        is_active=True,
        is_reachable=True,
        include_creator=True,
    )
    db_session.commit()
    return _hook_to_response(hook)


@router.post("/{hook_id}/validate")
def validate_hook(
    hook_id: int,
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> HookValidateResponse:
    hook = _get_hook_or_404(db_session, hook_id)
    if not hook.endpoint_url:
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT, "Hook has no endpoint URL configured."
        )

    api_key = hook.api_key.get_value(apply_mask=False) if hook.api_key else None
    validation = _validate_endpoint(
        endpoint_url=hook.endpoint_url,
        api_key=api_key,
        timeout_seconds=hook.timeout_seconds,
    )
    validation_passed = validation.status == HookValidateStatus.passed
    if hook.is_reachable != validation_passed:
        update_hook__no_commit(
            db_session=db_session, hook_id=hook_id, is_reachable=validation_passed
        )
        db_session.commit()
    return validation


@router.post("/{hook_id}/deactivate")
def deactivate_hook(
    hook_id: int,
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> HookResponse:
    hook = update_hook__no_commit(
        db_session=db_session,
        hook_id=hook_id,
        is_active=False,
        include_creator=True,
    )
    db_session.commit()
    return _hook_to_response(hook)


# ---------------------------------------------------------------------------
# Execution log endpoints
# ---------------------------------------------------------------------------


@router.get("/{hook_id}/execution-logs")
def list_hook_execution_logs(
    hook_id: int,
    limit: int = Query(default=50, ge=1, le=100),
    _: User = Depends(current_admin_user),
    _hook_enabled: None = Depends(require_hook_enabled),
    db_session: Session = Depends(get_session),
) -> list[HookFailureRecord]:
    _get_hook_or_404(db_session, hook_id)
    logs = get_hook_execution_logs(db_session=db_session, hook_id=hook_id, limit=limit)
    return [
        HookFailureRecord(
            error_message=log.error_message,
            status_code=log.status_code,
            duration_ms=log.duration_ms,
            created_at=log.created_at,
        )
        for log in logs
    ]
