from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel

from ee.onyx.server.tenants.admin_api import router as admin_router
from ee.onyx.server.tenants.anonymous_users_api import router as anonymous_users_router
from ee.onyx.server.tenants.billing_api import router as billing_router
from ee.onyx.server.tenants.team_membership_api import router as team_membership_router
from ee.onyx.server.tenants.tenant_management_api import (
    router as tenant_management_router,
)
from ee.onyx.server.tenants.user_invitations_api import (
    router as user_invitations_router,
)
from onyx.auth.users import current_user
from onyx.auth.users import User
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

# from ee.onyx.server.tenants.provisioning import get_tenant_setup_status

logger = setup_logger()

# Create a main router to include all sub-routers
router = APIRouter()

# Include all the sub-routers
router.include_router(admin_router)
router.include_router(anonymous_users_router)
router.include_router(billing_router)
router.include_router(team_membership_router)
router.include_router(tenant_management_router)
router.include_router(user_invitations_router)


class TenantSetupStatusResponse(BaseModel):
    """Response model for tenant setup status."""

    tenant_id: str
    status: str
    is_complete: bool


# Add the setup status endpoint directly to the main router
@router.get("/tenants/setup-status", response_model=TenantSetupStatusResponse)
async def get_setup_status(
    current_user: User = Depends(current_user),
) -> TenantSetupStatusResponse:
    """
    Get the current setup status for the tenant.
    This is used by the frontend to determine if the tenant setup is complete.
    """
    tenant_id = get_current_tenant_id()
    if not tenant_id:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # status = get_tenant_setup_status(tenant_id)

    return TenantSetupStatusResponse(
        tenant_id=tenant_id, status="completed", is_complete=True
    )
