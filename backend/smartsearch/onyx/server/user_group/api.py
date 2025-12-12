from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from smartsearch.onyx.db.user_group import (
    fetch_user_groups,
    fetch_user_groups_for_user,
    insert_user_group,
    prepare_user_group_for_deletion,
    update_user_curator_relationship,
    update_user_group,
)
from smartsearch.onyx.server.user_group.models import (
    SetCuratorRequest,
    UserGroup,
    UserGroupCreate,
    UserGroupUpdate,
)
from onyx.auth.users import (
    current_admin_user,
    current_curator_or_admin_user,
    current_user,
)
from onyx.db.engine import get_session
from onyx.db.models import (
    User,
    UserRole,
)
from onyx.utils.logger import setup_logger

logger = setup_logger()

router = APIRouter(tags=["Управление группой пользователей"])


@router.get(
    "/manage/admin/user-group",
    summary="Получение списка групп пользователей",
    response_model=list[UserGroup],
)
def list_user_groups(
    user: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> list[UserGroup]:
    """Получение списка групп пользователей в зависимости
    от роли текущего пользователя.

    Администраторы получают полный список всех групп.
    Кураторы и обычные пользователи получают только те группы,
    к которым у них есть доступ или в которых они являются кураторами.

    Returns:
        Список групп пользователей в соответствии с правами доступа
    """
    if user is None or user.role == UserRole.ADMIN:
        user_groups = fetch_user_groups(db_session, only_up_to_date=False)
    else:
        user_id = user.id

        if user.role == UserRole.CURATOR:
            is_curator_only = True
        else:
            is_curator_only = False

        user_groups = fetch_user_groups_for_user(
            db_session=db_session,
            user_id=user_id,
            only_curator_groups=is_curator_only,
        )

    result_groups = []
    for group in user_groups:
        result_groups.append(
            UserGroup.from_model(group)
        )

    return result_groups


@router.post(
    "/manage/admin/user-group",
    summary="Создание группы пользователей",
    response_model=UserGroup,
)
def create_user_group(
    user_group: UserGroupCreate,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    """Создание новой группы пользователей.

    Группа создается с заданным именем, списком пользователей и связями с
    коннектор-креденшиал парами. Требует прав администратора.

    Args:
        user_group: Данные для создания новой группы

    Returns:
        Созданная группа пользователей
    """
    try:
        db_user_group = insert_user_group(db_session, user_group)
    except IntegrityError:
        detail_text = f"""
            Группа пользователей с именем '{user_group.name}' уже существует. 
            Пожалуйста, выберите другое название.
        """
        raise HTTPException(
            status_code=400,
            detail=detail_text,
        )

    return UserGroup.from_model(db_user_group)


@router.patch(
    "/manage/admin/user-group/{user_group_id}",
    summary="Обновление группы пользователей",
    response_model=UserGroup,
)
def patch_user_group(
    user_group_id: int,
    user_group_update: UserGroupUpdate,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> UserGroup:
    """Частичное обновление параметров группы пользователей.

    Позволяет изменить состав пользователей и связанные коннектор-креденшиал пары.
    При изменении связей с CC парами автоматически помечает
    группу для синхронизации с Vespa.

    Args:
        user_group_id: Идентификатор обновляемой группы
        user_group_update: Данные для обновления группы

    Returns:
        Обновленная модель группы пользователей
    """
    try:
        updated_group = update_user_group(
            db_session=db_session,
            user=user,
            user_group_id=user_group_id,
            user_group_update=user_group_update,
        )
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))

    return UserGroup.from_model(updated_group)


@router.post(
    "/manage/admin/user-group/{user_group_id}/set-curator",
    summary="Назначение куратора группе пользователей",
)
def set_user_curator(
    user_group_id: int,
    set_curator_request: SetCuratorRequest,
    user: User | None = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Управление правами куратора для пользователя в группе.

    Позволяет назначить или снять права куратора с пользователя
    в указанной группе. Требует прав администратора или куратора группы.

    Args:
        user_group_id: Идентификатор группы пользователей
        curator_assignment: Данные для назначения куратора
    """
    try:
        update_user_curator_relationship(
            db_session=db_session,
            user_group_id=user_group_id,
            set_curator_request=set_curator_request,
            user_making_change=user,
        )
    except ValueError as error:
        logger.error(f"Ошибка при изменении прав куратора: {error}")
        raise HTTPException(status_code=404, detail=str(error))


@router.delete(
    "/manage/admin/user-group/{user_group_id}",
    summary="Удаление группы пользователей",
)
def delete_user_group(
    user_group_id: int,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    """Выполняет подготовку и удаление группы пользователей из системы.

    Включает очистку всех связанных сущностей и пометку группы для удаления.
    При отсутствии группы с указанным ID возвращает 404 ошибку.

    Args:
        user_group_id: Идентификатор группы пользователей для удаления
    """
    try:
        prepare_user_group_for_deletion(db_session, user_group_id)
    except ValueError as error:
        raise HTTPException(status_code=404, detail=str(error))
