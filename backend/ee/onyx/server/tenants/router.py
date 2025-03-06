import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel

from ee.onyx.server.tenants.provisioning import complete_tenant_setup
from ee.onyx.server.tenants.user_mapping import get_tenant_id_for_email
from onyx.auth.users import current_user
from onyx.auth.users import exceptions
from onyx.db.models import User

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])


class CompleteTenantSetupRequest(BaseModel):
    email: str


@router.post("/complete-setup")
async def api_complete_tenant_setup(
    request: CompleteTenantSetupRequest,
    user: User = Depends(current_user),
) -> dict:
    """Complete the tenant setup process for a user.

    This endpoint is called from the frontend after user creation to complete
    the tenant setup process (migrations, seeding, etc.).
    """
    if not user.is_admin and user.email != request.email:
        raise HTTPException(
            status_code=403, detail="You can only complete setup for your own tenant"
        )

    try:
        tenant_id = get_tenant_id_for_email(request.email)
    except exceptions.UserNotExists:
        raise HTTPException(status_code=404, detail="User or tenant not found")

    try:
        await complete_tenant_setup(tenant_id, request.email)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to complete tenant setup: {e}")
        raise HTTPException(status_code=500, detail="Failed to complete tenant setup")
