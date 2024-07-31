from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from danswer.auth.users import current_admin_user
from danswer.db.engine import get_session
from danswer.db.models import User
from ee.danswer.db.user_group import fetch_user_groups
from ee.danswer.db.user_group import insert_user_group
from ee.danswer.db.user_group import prepare_user_group_for_deletion
from ee.danswer.db.user_group import update_user_group
from ee.danswer.server.user_group.models import UserGroup
from ee.danswer.server.user_group.models import UserGroupCreate
from ee.danswer.server.user_group.models import UserGroupUpdate

router = APIRouter(prefix="/manage")


@router.get("/admin/user-group")
def list_user_groups(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[UserGroup]:
    user_groups = fetch_user_groups(db_session, only_current=False)
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
    user_group: UserGroupUpdate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    try:
        return UserGroup.from_model(
            update_user_group(db_session, user_group_id, user_group)
        )
    except ValueError as e:
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
