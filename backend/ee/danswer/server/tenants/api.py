from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException

from danswer.auth.users import control_plane_dep
from danswer.configs.app_configs import MULTI_TENANT
from danswer.db.engine import get_session_with_tenant
from danswer.setup import setup_danswer
from danswer.utils.logger import setup_logger
from ee.danswer.server.tenants.models import CreateTenantRequest
from ee.danswer.server.tenants.provisioning import ensure_schema_exists
from ee.danswer.server.tenants.provisioning import run_alembic_migrations

logger = setup_logger()
router = APIRouter(prefix="/tenants")


@router.post("/create")
def create_tenant(
    create_tenant_request: CreateTenantRequest, _: None = Depends(control_plane_dep)
) -> dict[str, str]:
    try:
        tenant_id = create_tenant_request.tenant_id

        if not MULTI_TENANT:
            raise HTTPException(status_code=403, detail="Multi-tenancy is not enabled")

        if not ensure_schema_exists(tenant_id):
            logger.info(f"Created schema for tenant {tenant_id}")
        else:
            logger.info(f"Schema already exists for tenant {tenant_id}")

        run_alembic_migrations(tenant_id)
        with get_session_with_tenant(tenant_id) as db_session:
            setup_danswer(db_session)

        logger.info(f"Tenant {tenant_id} created successfully")
        return {
            "status": "success",
            "message": f"Tenant {tenant_id} created successfully",
        }
    except Exception as e:
        logger.exception(f"Failed to create tenant {tenant_id}: {str(e)}")
        raise HTTPException(
            status_code=500, detail=f"Failed to create tenant: {str(e)}"
        )
