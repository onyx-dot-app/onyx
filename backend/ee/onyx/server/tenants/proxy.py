"""Proxy endpoints for billing operations.

These endpoints run on the CLOUD DATA PLANE (cloud.onyx.app) and serve as a proxy
for self-hosted instances to reach the control plane.

Flow:
  Self-hosted backend → Cloud DP /proxy/* (license auth) → Control plane (JWT auth)

Self-hosted instances call these endpoints with their license in the Authorization
header. The cloud data plane validates the license signature and forwards the
request to the control plane using JWT authentication.

Auth levels by endpoint:
- /create-checkout-session: No auth (new customer) or expired license OK (renewal)
- /claim-license: Session ID based (one-time after Stripe payment)
- /create-customer-portal-session: Expired license OK (need portal to fix payment)
- /billing-information: Valid license required
- /license/{tenant_id}: Valid license required
- /seats/update: Valid license required
"""

from typing import Literal

import httpx
from fastapi import APIRouter
from fastapi import Depends
from fastapi import Header
from fastapi import HTTPException
from pydantic import BaseModel

from ee.onyx.configs.app_configs import LICENSE_ENFORCEMENT_ENABLED
from ee.onyx.db.license import update_license_cache
from ee.onyx.db.license import upsert_license
from ee.onyx.server.billing.models import SeatUpdateRequest
from ee.onyx.server.billing.models import SeatUpdateResponse
from ee.onyx.server.license.models import LicensePayload
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.utils.license import is_license_valid
from ee.onyx.utils.license import verify_license_signature
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/proxy")


def _check_license_enforcement_enabled() -> None:
    """Ensure LICENSE_ENFORCEMENT_ENABLED is true (proxy endpoints only work on cloud DP)."""
    if not LICENSE_ENFORCEMENT_ENABLED:
        raise HTTPException(
            status_code=501,
            detail="Proxy endpoints are only available on cloud data plane",
        )


def _extract_license_from_header(
    authorization: str | None,
    required: bool = True,
) -> str | None:
    """Extract license data from Authorization header.

    Self-hosted instances authenticate to these proxy endpoints by sending their
    license as a Bearer token: `Authorization: Bearer <base64-encoded-license>`.

    We use the Bearer scheme (RFC 6750) because:
    1. It's the standard HTTP auth scheme for token-based authentication
    2. The license blob is cryptographically signed (RSA), so it's self-validating
    3. No other auth schemes (Basic, Digest, etc.) are supported for license auth

    The license data is the base64-encoded signed blob that contains tenant_id,
    seats, expiration, etc. We verify the signature to authenticate the caller.

    Args:
        authorization: The Authorization header value (e.g., "Bearer <license>")
        required: If True, raise 401 when header is missing/invalid

    Returns:
        License data string (base64-encoded), or None if not required and missing

    Raises:
        HTTPException: 401 if required and header is missing/invalid
    """
    if not authorization or not authorization.startswith("Bearer "):
        if required:
            raise HTTPException(
                status_code=401, detail="Missing or invalid authorization header"
            )
        return None

    return authorization.split(" ", 1)[1]


def verify_license_auth(
    license_data: str,
    allow_expired: bool = False,
) -> LicensePayload:
    """Verify license signature and optionally check expiry.

    Args:
        license_data: Base64-encoded signed license blob
        allow_expired: If True, accept expired licenses (for renewal flows)

    Returns:
        LicensePayload if valid

    Raises:
        HTTPException: If license is invalid or expired (when not allowed)
    """
    _check_license_enforcement_enabled()

    try:
        payload = verify_license_signature(license_data)
    except ValueError as e:
        raise HTTPException(status_code=401, detail=f"Invalid license: {e}")

    if not allow_expired and not is_license_valid(payload):
        raise HTTPException(status_code=401, detail="License has expired")

    return payload


async def get_license_payload(
    authorization: str | None = Header(None, alias="Authorization"),
) -> LicensePayload:
    """Dependency: Require valid (non-expired) license.

    Used for endpoints that require an active subscription.
    """
    license_data = _extract_license_from_header(authorization, required=True)
    # license_data is guaranteed non-None when required=True
    assert license_data is not None
    return verify_license_auth(license_data, allow_expired=False)


async def get_license_payload_allow_expired(
    authorization: str | None = Header(None, alias="Authorization"),
) -> LicensePayload:
    """Dependency: Require license with valid signature, expired OK.

    Used for endpoints needed to fix payment issues (portal, renewal checkout).
    """
    license_data = _extract_license_from_header(authorization, required=True)
    # license_data is guaranteed non-None when required=True
    assert license_data is not None
    return verify_license_auth(license_data, allow_expired=True)


async def get_optional_license_payload(
    authorization: str | None = Header(None, alias="Authorization"),
) -> LicensePayload | None:
    """Dependency: Optional license auth (for checkout - new customers have none).

    Returns None if no license provided, otherwise validates and returns payload.
    Expired licenses are allowed for renewal flows.
    """
    _check_license_enforcement_enabled()

    license_data = _extract_license_from_header(authorization, required=False)
    if license_data is None:
        return None

    return verify_license_auth(license_data, allow_expired=True)


async def forward_to_control_plane(
    method: str,
    path: str,
    body: dict | None = None,
    params: dict | None = None,
) -> dict:
    """Forward a request to the control plane with proper authentication."""
    token = generate_data_plane_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    url = f"{CONTROL_PLANE_API_BASE_URL}{path}"

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "GET":
                response = await client.get(url, headers=headers, params=params)
            elif method == "POST":
                response = await client.post(url, headers=headers, json=body)
            else:
                raise ValueError(f"Unsupported HTTP method: {method}")

            response.raise_for_status()
            return response.json()

    except httpx.HTTPStatusError as e:
        status_code = e.response.status_code
        detail = "Control plane request failed"
        try:
            error_data = e.response.json()
            detail = error_data.get("detail", detail)
        except Exception:
            pass
        logger.error(f"Control plane returned {status_code}: {detail}")
        raise HTTPException(status_code=status_code, detail=detail)
    except httpx.RequestError:
        logger.exception("Failed to connect to control plane")
        raise HTTPException(
            status_code=502, detail="Failed to connect to control plane"
        )


def fetch_and_store_license(tenant_id: str, license_data: str) -> None:
    """Store license in database and update Redis cache.

    Args:
        tenant_id: The tenant ID
        license_data: Base64-encoded signed license blob
    """
    try:
        # Verify before storing
        payload = verify_license_signature(license_data)

        # Store in database using the specific tenant's schema
        with get_session_with_tenant(tenant_id=tenant_id) as db_session:
            upsert_license(db_session, license_data)

        # Update Redis cache
        update_license_cache(
            payload,
            source=LicenseSource.AUTO_FETCH,
            tenant_id=tenant_id,
        )

    except ValueError as e:
        logger.error(f"Failed to verify license: {e}")
        raise
    except Exception:
        logger.exception("Failed to store license")
        raise


# -----------------------------------------------------------------------------
# Endpoints
# -----------------------------------------------------------------------------


class CreateCheckoutSessionRequest(BaseModel):
    billing_period: Literal["monthly", "annual"] = "monthly"
    email: str | None = None
    # Redirect URL after successful checkout - self-hosted passes their instance URL
    redirect_url: str | None = None
    # Cancel URL when user exits checkout - returns to upgrade page
    cancel_url: str | None = None


class CreateCheckoutSessionResponse(BaseModel):
    url: str


@router.post("/create-checkout-session")
async def proxy_create_checkout_session(
    request_body: CreateCheckoutSessionRequest,
    license_payload: LicensePayload | None = Depends(get_optional_license_payload),
) -> CreateCheckoutSessionResponse:
    """Proxy checkout session creation to control plane.

    Auth: Optional license (new customers don't have one yet).
    If license provided, expired is OK (for renewals).
    """
    # license_payload is None for new customers who don't have a license yet.
    # In that case, tenant_id is omitted from the request body and the control
    # plane will create a new tenant during checkout completion.
    tenant_id = license_payload.tenant_id if license_payload else None

    body: dict = {
        "billing_period": request_body.billing_period,
    }
    if tenant_id:
        body["tenant_id"] = tenant_id
    if request_body.email:
        body["email"] = request_body.email
    if request_body.redirect_url:
        body["redirect_url"] = request_body.redirect_url
    if request_body.cancel_url:
        body["cancel_url"] = request_body.cancel_url

    result = await forward_to_control_plane(
        "POST", "/create-checkout-session", body=body
    )
    return CreateCheckoutSessionResponse(url=result["url"])


class ClaimLicenseRequest(BaseModel):
    session_id: str


class ClaimLicenseResponse(BaseModel):
    tenant_id: str
    license: str
    message: str | None = None


@router.post("/claim-license")
async def proxy_claim_license(
    request_body: ClaimLicenseRequest,
) -> ClaimLicenseResponse:
    """Claim a license after successful Stripe checkout.

    Auth: Session ID based (one-time use after payment).
    The control plane verifies the session_id is valid and unclaimed.

    Returns the license to the caller. For self-hosted instances, they will
    store the license locally. The cloud DP doesn't need to store it.
    """
    _check_license_enforcement_enabled()

    result = await forward_to_control_plane(
        "POST",
        "/claim-license",
        body={"session_id": request_body.session_id},
    )

    tenant_id = result.get("tenant_id")
    license_data = result.get("license")

    if not tenant_id or not license_data:
        logger.error(f"Control plane returned incomplete claim response: {result}")
        raise HTTPException(
            status_code=502,
            detail="Control plane returned incomplete license data",
        )

    return ClaimLicenseResponse(
        tenant_id=tenant_id,
        license=license_data,
        message="License claimed successfully",
    )


class CreateCustomerPortalSessionRequest(BaseModel):
    return_url: str | None = None


class CreateCustomerPortalSessionResponse(BaseModel):
    url: str


@router.post("/create-customer-portal-session")
async def proxy_create_customer_portal_session(
    request_body: CreateCustomerPortalSessionRequest | None = None,
    license_payload: LicensePayload = Depends(get_license_payload_allow_expired),
) -> CreateCustomerPortalSessionResponse:
    """Proxy customer portal session creation to control plane.

    Auth: License required, expired OK (need portal to fix payment issues).
    """
    # tenant_id is a required field in LicensePayload (Pydantic validates this),
    # but we check explicitly for defense in depth
    if not license_payload.tenant_id:
        raise HTTPException(status_code=401, detail="License missing tenant_id")

    tenant_id = license_payload.tenant_id

    body: dict = {"tenant_id": tenant_id}
    if request_body and request_body.return_url:
        body["return_url"] = request_body.return_url

    result = await forward_to_control_plane(
        "POST", "/create-customer-portal-session", body=body
    )
    return CreateCustomerPortalSessionResponse(url=result["url"])


class BillingInformationResponse(BaseModel):
    tenant_id: str
    status: str | None = None
    plan_type: str | None = None
    seats: int | None = None
    billing_period: str | None = None
    current_period_start: str | None = None
    current_period_end: str | None = None
    cancel_at_period_end: bool = False
    canceled_at: str | None = None
    trial_start: str | None = None
    trial_end: str | None = None
    payment_method_enabled: bool = False
    stripe_subscription_id: str | None = None


@router.get("/billing-information")
async def proxy_billing_information(
    license_payload: LicensePayload = Depends(get_license_payload),
) -> BillingInformationResponse:
    """Proxy billing information request to control plane.

    Auth: Valid (non-expired) license required.
    """
    # tenant_id is a required field in LicensePayload (Pydantic validates this),
    # but we check explicitly for defense in depth
    if not license_payload.tenant_id:
        raise HTTPException(status_code=401, detail="License missing tenant_id")

    tenant_id = license_payload.tenant_id

    result = await forward_to_control_plane(
        "GET", "/billing-information", params={"tenant_id": tenant_id}
    )
    # Add tenant_id from license if not in response (control plane may not include it)
    if "tenant_id" not in result:
        result["tenant_id"] = tenant_id
    return BillingInformationResponse(**result)


class LicenseFetchResponse(BaseModel):
    license: str
    tenant_id: str


@router.get("/license/{tenant_id}")
async def proxy_license_fetch(
    tenant_id: str,
    license_payload: LicensePayload = Depends(get_license_payload),
) -> LicenseFetchResponse:
    """Proxy license fetch to control plane.

    Auth: Valid license required.
    The tenant_id in path must match the authenticated tenant.
    """
    # tenant_id is a required field in LicensePayload (Pydantic validates this),
    # but we check explicitly for defense in depth
    if not license_payload.tenant_id:
        raise HTTPException(status_code=401, detail="License missing tenant_id")

    if tenant_id != license_payload.tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot fetch license for a different tenant",
        )

    result = await forward_to_control_plane("GET", f"/license/{tenant_id}")

    # Auto-store the refreshed license
    license_data = result.get("license")
    if not license_data:
        logger.error(f"Control plane returned incomplete license response: {result}")
        raise HTTPException(
            status_code=502,
            detail="Control plane returned incomplete license data",
        )

    fetch_and_store_license(tenant_id, license_data)

    return LicenseFetchResponse(license=license_data, tenant_id=tenant_id)


@router.post("/seats/update")
async def proxy_seat_update(
    request_body: SeatUpdateRequest,
    license_payload: LicensePayload = Depends(get_license_payload),
) -> SeatUpdateResponse:
    """Proxy seat update to control plane.

    Auth: Valid (non-expired) license required.
    Handles Stripe proration and license regeneration.
    """
    if not license_payload.tenant_id:
        raise HTTPException(status_code=401, detail="License missing tenant_id")

    tenant_id = license_payload.tenant_id

    result = await forward_to_control_plane(
        "POST",
        "/seats/update",
        body={
            "tenant_id": tenant_id,
            "new_seat_count": request_body.new_seat_count,
        },
    )

    return SeatUpdateResponse(
        success=result.get("success", False),
        current_seats=result.get("current_seats", 0),
        used_seats=result.get("used_seats", 0),
        message=result.get("message"),
    )
