from fastapi import APIRouter
from fastapi import Depends
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.db.api_key import ApiKeyDescriptor
from onyx.db.api_key import fetch_api_keys
from onyx.db.api_key import insert_api_key
from onyx.db.api_key import regenerate_api_key
from onyx.db.api_key import remove_api_key
from onyx.db.api_key import update_api_key
from onyx.db.engine import get_session
from onyx.db.models import User
from onyx.server.api_key.models import APIKeyArgs, APIKeyUpdateArgs


router = APIRouter(
    prefix="/admin/api-key",
    tags=["api-key"]
)


@router.get(
    path="",
    summary="Получение списка всех api ключей",
    description="Получение списка всех api ключей",
    response_model=list[ApiKeyDescriptor],
)
def list_api_keys(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> list[ApiKeyDescriptor]:
    return fetch_api_keys(db_session)


@router.post(
    path="",
    summary="Создание апи ключа",
    description="Если передать user_id, то ключ будет создан для существующего пользователя и в таком случае"
                "нет необходимости передавать поле role. Если не передать user_id, то будет создан новый пользователь"
                "с той ролью, которую вы передали",
    response_model=ApiKeyDescriptor,
)
def create_api_key(
    api_key_args: APIKeyArgs,
    user: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ApiKeyDescriptor:
    return insert_api_key(
        db_session,
        user,
        api_key_args,
        api_key_args.user_id if api_key_args.user_id else None
    )


@router.post(
    path="/{api_key_id}/regenerate",
    summary="Перегенерировать api ключ.",
    description="Перегенерирация существующего api ключа, не забудьте его сохранить, "
                "потому что повторно его не получиться увидеть",
    response_model=ApiKeyDescriptor,
)
def regenerate_existing_api_key(
    api_key_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ApiKeyDescriptor:
    return regenerate_api_key(db_session, api_key_id)


@router.patch(
    path="/{api_key_id}",
    summary="Частичное обновление поле api ключа",
    description="Если обновлять api ключ с is_new_user=True, то можно обновить поля name и role. Если обновлять "
                "api ключ с is_new_user=False, то можно обновить только поле name, поле role нельзя будет обновить",
    response_model=ApiKeyDescriptor,
)
def update_existing_api_key(
    api_key_id: int,
    api_key_args: APIKeyUpdateArgs,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> ApiKeyDescriptor:
    return update_api_key(db_session, api_key_id, api_key_args)


@router.delete(
    path="/{api_key_id}",
    summary="Удаление api ключа",
    description="Удаляет существующий api ключ. Если ключ с is_new_user=True, то удалит еще привязанного пользователя. "
                "Если ключ с is_new_user=False, то удалит только api ключ"
)
def delete_api_key(
    api_key_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    remove_api_key(db_session, api_key_id)
