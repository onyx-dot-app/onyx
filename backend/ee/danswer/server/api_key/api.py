from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

import danswer.db.models as db_models
from danswer.auth.users import current_admin_user
from danswer.db.engine import get_session
from ee.danswer.db.api_key import ApiKeyDescriptor
from ee.danswer.db.api_key import fetch_api_keys
from ee.danswer.db.api_key import insert_api_key
from ee.danswer.db.api_key import regenerate_api_key
from ee.danswer.db.api_key import remove_api_key
from ee.danswer.db.api_key import update_api_key
from ee.danswer.server.api_key.models import APIKeyArgs

router = APIRouter(prefix="/admin/api-key")


@router.get("")
def list_api_keys(
    _: db_models.User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ApiKeyDescriptor]:
    return fetch_api_keys(db_session)


@router.post("")
def create_api_key(
    api_key_args: APIKeyArgs,
    user: db_models.User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ApiKeyDescriptor:
    return insert_api_key(db_session, api_key_args, user.id if user else None)


@router.post("/{api_key_id}/regenerate")
def regenerate_existing_api_key(
    api_key_id: int,
    _: db_models.User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ApiKeyDescriptor:
    return regenerate_api_key(db_session, api_key_id)


@router.patch("/{api_key_id}")
def update_existing_api_key(
    api_key_id: int,
    api_key_args: APIKeyArgs,
    _: db_models.User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ApiKeyDescriptor:
    return update_api_key(db_session, api_key_id, api_key_args)


@router.delete("/{api_key_id}")
def delete_api_key(
    api_key_id: int,
    _: db_models.User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    remove_api_key(db_session, api_key_id)
