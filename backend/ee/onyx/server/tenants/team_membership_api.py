from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.server.tenants.provisioning import delete_user_from_control_plane
from ee.onyx.server.tenants.user_mapping import remove_all_users_from_tenant
from ee.onyx.server.tenants.user_mapping import remove_users_from_tenant
from onyx.auth.users import current_admin_user
from onyx.auth.users import User
from onyx.db.auth import get_user_count
from onyx.db.engine.sql_engine import get_session
from onyx.db.users import delete_user_from_db
from onyx.db.users import get_user_by_email
from onyx.server.manage.models import UserByEmail
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import get_current_tenant_id

logger = setup_logger()

router = APIRouter(prefix="/tenants")


@router.post("/leave-team")
async def leave_organization(
    user_email: UserByEmail,
    current_user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    tenant_id = get_current_tenant_id()

    if current_user is None or current_user.email != user_email.user_email:
        raise HTTPException(
            status_code=403, detail="You can only leave the organization as yourself"
        )

    user_to_delete = get_user_by_email(user_email.user_email, db_session)
    if user_to_delete is None:
        raise HTTPException(status_code=404, detail="User not found")

    num_admin_users = await get_user_count(only_admin_users=True)

    should_delete_tenant = num_admin_users == 1

    if should_delete_tenant:
        logger.info(
            "Last admin user is leaving the organization. Deleting tenant from control plane."
        )
        try:
            await delete_user_from_control_plane(tenant_id, user_to_delete.email)
            logger.debug("User deleted from control plane")
        except Exception as e:
            logger.exception(
                f"Failed to delete user from control plane for tenant {tenant_id}: {e}"
            )
            raise HTTPException(
                status_code=500,
                detail=f"Failed to remove user from control plane: {str(e)}",
            )

    db_session.expunge(user_to_delete)
    delete_user_from_db(user_to_delete, db_session)

    if should_delete_tenant:
        remove_all_users_from_tenant(tenant_id)
    else:
        remove_users_from_tenant([user_to_delete.email], tenant_id)
