"""License API endpoints."""

import requests
from fastapi import APIRouter
from fastapi import Depends
from fastapi import File
from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy.orm import Session

from ee.onyx.auth.users import current_admin_user
from ee.onyx.db.license import delete_license as db_delete_license
from ee.onyx.db.license import get_license_metadata
from ee.onyx.db.license import invalidate_license_cache
from ee.onyx.db.license import refresh_license_cache
from ee.onyx.db.license import update_license_cache
from ee.onyx.db.license import upsert_license
from ee.onyx.server.license.models import LicenseResponse
from ee.onyx.server.license.models import LicenseSource
from ee.onyx.server.license.models import LicenseStatusResponse
from ee.onyx.server.license.models import LicenseUploadResponse
from ee.onyx.server.license.models import SeatUsageResponse
from ee.onyx.server.tenants.access import generate_data_plane_token
from ee.onyx.utils.license import verify_license_signature
from onyx.auth.users import User
from onyx.configs.app_configs import CONTROL_PLANE_API_BASE_URL
from onyx.db.engine.sql_engine import get_session
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/license")


@router.get("")
async def get_license_status(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> LicenseStatusResponse:
    """Get current license status and seat usage."""
    metadata = get_license_metadata(db_session)

    if not metadata:
        return LicenseStatusResponse(has_license=False)

    return LicenseStatusResponse(
        has_license=True,
        seats=metadata.seats,
        used_seats=metadata.used_seats,
        plan_type=metadata.plan_type,
        issued_at=metadata.issued_at,
        expires_at=metadata.expires_at,
        grace_period_end=metadata.grace_period_end,
        status=metadata.status,
        source=metadata.source,
    )


@router.get("/seats")
async def get_seat_usage(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> SeatUsageResponse:
    """Get detailed seat usage information."""
    metadata = get_license_metadata(db_session)

    if not metadata:
        return SeatUsageResponse(
            total_seats=0,
            used_seats=0,
            available_seats=0,
        )

    return SeatUsageResponse(
        total_seats=metadata.seats,
        used_seats=metadata.used_seats,
        available_seats=max(0, metadata.seats - metadata.used_seats),
    )


@router.post("/fetch")
async def fetch_license(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> LicenseResponse:
    """
    Fetch license from control plane.
    Used after Stripe checkout completion to retrieve the new license.
    """
    tenant_id = get_current_tenant_id()

    try:
        token = generate_data_plane_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        url = f"{CONTROL_PLANE_API_BASE_URL}/license/{tenant_id}"
        response = requests.get(url, headers=headers, timeout=10)

        if not response.ok:
            raise HTTPException(
                status_code=response.status_code,
                detail="Failed to fetch license from control plane",
            )

        data = response.json()
        license_data = data.get("license")
        if not license_data:
            raise HTTPException(status_code=404, detail="No license found")

        payload = verify_license_signature(license_data)
        upsert_license(db_session, license_data)
        update_license_cache(payload, source=LicenseSource.AUTO_FETCH)

        return LicenseResponse(success=True, license=payload)

    except ValueError as e:
        logger.error(f"License verification failed: {e}")
        raise HTTPException(status_code=400, detail=str(e))
    except requests.RequestException as e:
        logger.exception("Failed to fetch license from control plane")
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/upload")
async def upload_license(
    license_file: UploadFile = File(...),
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> LicenseUploadResponse:
    """
    Upload a license file manually.
    Used for air-gapped deployments where control plane is not accessible.
    """
    try:
        content = await license_file.read()
        license_data = content.decode("utf-8").strip()
        payload = verify_license_signature(license_data)

        tenant_id = get_current_tenant_id()
        if payload.tenant_id != tenant_id:
            raise HTTPException(
                status_code=400,
                detail=f"License tenant ID mismatch. Expected {tenant_id}, got {payload.tenant_id}",
            )

        upsert_license(db_session, license_data)
        update_license_cache(payload, source=LicenseSource.MANUAL_UPLOAD)

        return LicenseUploadResponse(
            success=True,
            message=f"License uploaded successfully. {payload.seats} seats, expires {payload.expires_at.date()}",
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UnicodeDecodeError:
        raise HTTPException(status_code=400, detail="Invalid license file format")


@router.post("/refresh")
async def refresh_license_cache_endpoint(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> LicenseStatusResponse:
    """
    Force refresh the license cache from the database.
    Useful after manual database changes or to verify license validity.
    """
    metadata = refresh_license_cache(db_session)

    if not metadata:
        return LicenseStatusResponse(has_license=False)

    return LicenseStatusResponse(
        has_license=True,
        seats=metadata.seats,
        used_seats=metadata.used_seats,
        plan_type=metadata.plan_type,
        issued_at=metadata.issued_at,
        expires_at=metadata.expires_at,
        grace_period_end=metadata.grace_period_end,
        status=metadata.status,
        source=metadata.source,
    )


@router.delete("")
async def delete_license(
    _: User = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> dict[str, bool]:
    """
    Delete the current license.
    Admin only - removes license and invalidates cache.
    """
    deleted = db_delete_license(db_session)
    invalidate_license_cache()

    return {"deleted": deleted}
