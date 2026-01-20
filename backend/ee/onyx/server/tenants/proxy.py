"""Proxy endpoints for self-hosted data planes to reach control plane.

Self-hosted deployments call these endpoints on the cloud data plane (api.onyx.app),
which forwards requests to the internal control plane.

Authentication flow:
1. Self-hosted generates JWT token signed with DATA_PLANE_SECRET
2. Cloud data plane validates the token
3. Cloud data plane generates a new token for control plane
4. Request is forwarded to control plane
"""

from typing import Literal

import jwt
import requests
from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from pydantic import BaseModel

from ee.onyx.server.tenants.access import generate_data_plane_token
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.configs.app_configs import DATA_PLANE_SECRET
from onyx.configs.app_configs import JWT_ALGORITHM
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/proxy")


async def verify_self_hosted_token(request: Request) -> str:
    """Verify JWT token from self-hosted data plane and extract tenant_id.

    Returns the tenant_id from the X-Tenant-ID header after validating the token.
    """
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=401, detail="Missing or invalid authorization header"
        )

    token = auth_header.split(" ")[1]

    if DATA_PLANE_SECRET is None:
        raise HTTPException(status_code=500, detail="Proxy not configured")

    try:
        jwt.decode(token, DATA_PLANE_SECRET, algorithms=[JWT_ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token has expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")

    # Extract tenant_id from header
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(status_code=400, detail="Missing X-Tenant-ID header")

    return tenant_id


def forward_to_control_plane(
    method: str,
    path: str,
    tenant_id: str | None = None,
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
        if method == "GET":
            response = requests.get(url, headers=headers, params=params, timeout=30)
        elif method == "POST":
            response = requests.post(url, headers=headers, json=body, timeout=30)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")

        response.raise_for_status()
        return response.json()

    except requests.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 502
        detail = "Control plane request failed"
        try:
            error_data = e.response.json() if e.response is not None else {}
            detail = error_data.get("detail", detail)
        except Exception:
            pass
        logger.error(f"Control plane returned {status_code}: {detail}")
        raise HTTPException(status_code=status_code, detail=detail)
    except requests.RequestException:
        logger.exception("Failed to connect to control plane")
        raise HTTPException(
            status_code=502, detail="Failed to connect to control plane"
        )


class CreateCheckoutSessionRequest(BaseModel):
    billing_period: Literal["monthly", "annual"] = "monthly"
    email: str | None = None


@router.post("/create-checkout-session")
async def proxy_create_checkout_session(
    request_body: CreateCheckoutSessionRequest,
    tenant_id: str = Depends(verify_self_hosted_token),
) -> dict:
    """Proxy checkout session creation to control plane."""
    logger.info(f"Proxying create-checkout-session for tenant {tenant_id}")

    body = {
        "tenant_id": tenant_id,
        "billing_period": request_body.billing_period,
    }
    if request_body.email:
        body["email"] = request_body.email

    return forward_to_control_plane("POST", "/create-checkout-session", body=body)


@router.get("/billing-information")
async def proxy_billing_information(
    tenant_id: str = Depends(verify_self_hosted_token),
) -> dict:
    """Proxy billing information request to control plane."""
    logger.info(f"Proxying billing-information for tenant {tenant_id}")

    return forward_to_control_plane(
        "GET", "/billing-information", params={"tenant_id": tenant_id}
    )


class CreateCustomerPortalSessionRequest(BaseModel):
    return_url: str | None = None


@router.post("/create-customer-portal-session")
async def proxy_create_customer_portal_session(
    request_body: CreateCustomerPortalSessionRequest | None = None,
    tenant_id: str = Depends(verify_self_hosted_token),
) -> dict:
    """Proxy customer portal session creation to control plane."""
    logger.info(f"Proxying create-customer-portal-session for tenant {tenant_id}")

    body: dict = {"tenant_id": tenant_id}
    if request_body and request_body.return_url:
        body["return_url"] = request_body.return_url

    return forward_to_control_plane(
        "POST", "/create-customer-portal-session", body=body
    )


@router.get("/license/{tenant_id}")
async def proxy_license_fetch(
    tenant_id: str,
    verified_tenant_id: str = Depends(verify_self_hosted_token),
) -> dict:
    """Proxy license fetch to control plane.

    Note: The tenant_id in the path must match the tenant_id from the auth token.
    This prevents tenants from fetching other tenants' licenses.
    """
    if tenant_id != verified_tenant_id:
        raise HTTPException(
            status_code=403,
            detail="Cannot fetch license for a different tenant",
        )

    logger.info(f"Proxying license fetch for tenant {tenant_id}")

    return forward_to_control_plane("GET", f"/license/{tenant_id}")
