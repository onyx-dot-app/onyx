from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ee.onyx.db.user_group import fetch_user_groups
from ee.onyx.db.user_group import fetch_user_groups_for_user
from ee.onyx.db.user_group import insert_user_group
from ee.onyx.db.user_group import prepare_user_group_for_deletion
from ee.onyx.db.user_group import update_user_curator_relationship
from ee.onyx.db.user_group import update_user_group
from ee.onyx.server.user_group.models import SetCuratorRequest
from ee.onyx.server.user_group.models import UserGroup
from ee.onyx.server.user_group.models import UserGroupCreate
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.auth.users import current_admin_user
from onyx.auth.users import current_curator_or_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.models import User
from onyx.db.models import UserRole
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(prefix="/manage")


@router.get("/admin/user-group")
def list_user_groups(
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserGroup]:
    if user is None or user.role == UserRole.ADMIN:
        user_groups = fetch_user_groups(db_session, only_up_to_date=False)
    else:
        user_groups = fetch_user_groups_for_user(
            db_session=db_session,
            user_id=user.id,
            only_curator_groups=user.role == UserRole.CURATOR,
        )
    return [UserGroup.from_model(user_group) for user_group in user_groups]


@router.post("/admin/user-group")
def create_user_group(
    user_group: UserGroupCreate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        db_user_group = insert_user_group(db_session, user_group)
    except IntegrityError:
        raise HTTPException(
            400,
            f"User group with name '{user_group.name}' already exists. Please "
            + "choose a different name.",
        )
    return UserGroup.from_model(db_user_group)


@router.patch("/admin/user-group/{user_group_id}")
def patch_user_group(
    user_group_id: int,
    user_group_update: UserGroupUpdate,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        return UserGroup.from_model(
            update_user_group(
                db_session=db_session,
                user=user,
                user_group_id=user_group_id,
                user_group_update=user_group_update,
            )
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/admin/user-group/{user_group_id}/set-curator")
def set_user_curator(
    user_group_id: int,
    set_curator_request: SetCuratorRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        update_user_curator_relationship(
            db_session=db_session,
            user_group_id=user_group_id,
            set_curator_request=set_curator_request,
            user_making_change=user,
        )
    except ValueError as e:
        logger.error(f"Error setting user curator: {e}")
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/admin/user-group/{user_group_id}")
def delete_user_group(
    user_group_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        prepare_user_group_for_deletion(db_session, user_group_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
