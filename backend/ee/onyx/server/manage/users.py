from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.orm import Session

from ee.onyx.server.tenants.user_mapping import remove_users_from_tenant
from onyx.auth.users import current_admin_user
from onyx.db.engine import get_current_tenant_id
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.db.users import delete_user_from_db
from onyx.db.users import get_user_by_email
from onyx.server.manage.models import UserByEmail
from onyx.utils.logger import setup_logger

logger = setup_logger()
router = APIRouter()


@router.post("/manage/admin/leave-organization")
async def leave_organization(
    user_email: UserByEmail,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
    tenant_id: str = Depends(get_current_tenant_id),
) -> None:
    user_to_delete = get_user_by_email(
        email=user_email.user_email, db_session=db_session
    )
    if not user_to_delete:
        raise HTTPException(status_code=404, detail="User not found")

    delete_user_from_db(user_to_delete, db_session)
    remove_users_from_tenant([user_to_delete.email], tenant_id)
