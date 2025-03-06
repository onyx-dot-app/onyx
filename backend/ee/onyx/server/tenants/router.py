import logging

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from pydantic import BaseModel

from ee.onyx.server.tenants.provisioning import complete_tenant_setup
from onyx.auth.users import optional_minimal_user
from onyx.db.models import MinimalUser
from shared_configs.contextvars import get_current_tenant_id

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/tenants", tags=["tenants"])


class CompleteTenantSetupRequest(BaseModel):
    email: str


@router.post("/complete-setup")
async def api_complete_tenant_setup(
    request: CompleteTenantSetupRequest,
    user: MinimalUser = Depends(optional_minimal_user),
) -> None:
    """Complete the tenant setup process for a user.

    This endpoint is called from the frontend after user creation to complete
    the tenant setup process (migrations, seeding, etc.).
    """

    tenant_id = get_current_tenant_id()

    try:
        await complete_tenant_setup(tenant_id)
        return {"status": "success"}
    except Exception as e:
        logger.error(f"Failed to complete tenant setup: {e}")
        raise HTTPException(status_code=500, detail="Failed to complete tenant setup")
