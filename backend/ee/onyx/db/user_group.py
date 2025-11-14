from collections.abc import Sequence
from operator import and_
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import Session

from ee.onyx.server.user_group.models import SetCuratorRequest
from ee.onyx.server.user_group.models import UserGroupCreate
from ee.onyx.server.user_group.models import UserGroupUpdate
from onyx.db.connector_credential_pair import (
    get_connector_credential_pair_from_id,
)
from onyx.db.enums import AccessType
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ConnectorCredentialPair
from onyx.db.models import Credential__UserGroup
from onyx.db.models import Document
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import DocumentSet__UserGroup
from onyx.db.models import LLMProvider__UserGroup
from onyx.db.models import Persona__UserGroup
from onyx.db.models import TokenRateLimit__UserGroup
from onyx.db.models import User
from onyx.db.models import User__UserGroup
from onyx.db.models import UserGroup
from onyx.db.models import UserGroup__ConnectorCredentialPair
from onyx.db.models import UserRole
from onyx.db.users import fetch_user_by_id
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _clear_user_group_links__no_commit(
    db_session: Session,
    user_group_id: int,
    user_ids: list[UUID] | None = None,
) -> None:
    """Удаляет связи User__UserGroup. Не фиксирует транзакцию."""
    where_condition = User__UserGroup.user_group_id == user_group_id
    if user_ids:
        where_condition &= User__UserGroup.user_id.in_(user_ids)

    delete_stmt = delete(User__UserGroup).where(where_condition)
    db_session.execute(delete_stmt)


def _clear_credential_group_links__no_commit(
    db_session: Session,
    user_group_id: int,
) -> None:
    """Удаляет связи Credential__UserGroup. Не фиксирует транзакцию."""
    db_session.query(Credential__UserGroup).filter(
        Credential__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _clear_llm_provider_group_links__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """Удаляет связи LLMProvider__UserGroup. Не фиксирует транзакцию."""
    db_session.query(LLMProvider__UserGroup).filter(
        LLMProvider__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _clear_persona_group_links__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """Удаляет связи Persona__UserGroup. Не фиксирует транзакцию."""
    db_session.query(Persona__UserGroup).filter(
        Persona__UserGroup.user_group_id == user_group_id
    ).delete(synchronize_session=False)


def _clear_token_limit_group_links__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """Удаляет связи TokenRateLimit__UserGroup. Не фиксирует транзакцию."""
    delete_stmt = delete(TokenRateLimit__UserGroup).where(
        TokenRateLimit__UserGroup.user_group_id == user_group_id
    )
    db_session.execute(delete_stmt)


def _clear_group_cc_pair_links__no_commit(
    db_session: Session, user_group_id: int, outdated_only: bool
) -> None:
    """Удаляет связи UserGroup__ConnectorCredentialPair. Не фиксирует транзакцию."""
    query = select(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.user_group_id == user_group_id
    )
    if outdated_only:
        query = query.where(
            UserGroup__ConnectorCredentialPair.is_current == False  # noqa: E712
        )

    relationships_to_delete = db_session.scalars(query).all()
    for rel in relationships_to_delete:
        db_session.delete(rel)


def _clear_doc_set_group_links__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """Удаляет связи DocumentSet__UserGroup. Не фиксирует транзакцию."""
    db_session.execute(
        delete(DocumentSet__UserGroup).where(
            DocumentSet__UserGroup.user_group_id == user_group_id
        )
    )


def validate_object_creation_for_user(
    db_session: Session,
    user: User | None,
    target_group_ids: list[int] | None = None,
    object_is_public: bool | None = None,
    object_is_perm_sync: bool | None = None,
) -> None:
    """
    Проверяет, имеет ли пользователь права на создание/редактирование объекта.
    - Админы могут все.
    - Пользователи могут управлять объектами с 'perm_sync', если не указаны группы.
    - Запрещает не-админам создавать публичные объекты или объекты без групп.
    - Запрещает кураторам управлять группами, которые они не курируют.
    """
    if not user or user.role == UserRole.ADMIN:
        return

    if object_is_perm_sync and not target_group_ids:
        return

    if object_is_public:
        error_message = (
            "User does not have permission to create public credentials"
        )
        logger.error(error_message)
        raise HTTPException(status_code=400, detail=error_message)

    if not target_group_ids:
        error_message = "Curators must specify 1+ groups"
        logger.error(error_message)
        raise HTTPException(status_code=400, detail=error_message)

    # Глобальные кураторы могут курировать все группы, в которых состоят
    is_global_curator = user.role == UserRole.GLOBAL_CURATOR
    user_curated_groups = fetch_user_groups_for_user(
        db_session=db_session,
        user_id=user.id,
        only_curator_groups=not is_global_curator,
    )

    user_curated_group_ids = {group.id for group in user_curated_groups}
    target_group_ids_set = set(target_group_ids)

    if not target_group_ids_set.issubset(user_curated_group_ids):
        error_message = "Curators cannot control groups they don't curate"
        logger.error(error_message)
        raise HTTPException(status_code=400, detail=error_message)


def fetch_user_group(
    db_session: Session, user_group_id: int
) -> UserGroup | None:
    query = select(UserGroup).where(UserGroup.id == user_group_id)
    return db_session.scalar(query)


def fetch_user_groups(
    db_session: Session, only_up_to_date: bool = True
) -> Sequence[UserGroup]:
    """
    Извлекает группы пользователей из базы данных.

    Args:
        db_session (Session): Сессия SQLAlchemy.
        only_up_to_date (bool, optional): Если True, возвращает только группы,
            помеченные как 'is_up_to_date'. По умолчанию True.

    Returns:
        Sequence[UserGroup]: Последовательность объектов UserGroup.
    """
    query = select(UserGroup)
    if only_up_to_date:
        query = query.where(UserGroup.is_up_to_date == True)  # noqa: E712
    return db_session.scalars(query).all()


def fetch_user_groups_for_user(
    db_session: Session, user_id: UUID, only_curator_groups: bool = False
) -> Sequence[UserGroup]:
    query = (
        select(UserGroup)
        .join(User__UserGroup, User__UserGroup.user_group_id == UserGroup.id)
        .join(User, User.id == User__UserGroup.user_id)  # type: ignore
        .where(User.id == user_id)  # type: ignore
    )
    if only_curator_groups:
        query = query.where(User__UserGroup.is_curator == True)  # noqa: E712
    return db_session.scalars(query).all()


def construct_document_id_select_by_usergroup(
    user_group_id: int,
) -> Select:
    """
    Возвращает запрос (Select) для ID документов, доступных группе.
    Этот запрос предназначен для потоковой обработки (yield_per)
    в фоновых задачах.
    """
    base_query = (
        select(Document.id)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .join(
            UserGroup__ConnectorCredentialPair,
            UserGroup__ConnectorCredentialPair.cc_pair_id
            == ConnectorCredentialPair.id,
        )
        .join(
            UserGroup,
            UserGroup__ConnectorCredentialPair.user_group_id == UserGroup.id,
        )
        .where(UserGroup.id == user_group_id)
        .order_by(Document.id)
    )
    base_query = base_query.distinct()
    return base_query


def fetch_documents_for_user_group_paginated(
    db_session: Session,
    user_group_id: int,
    last_document_id: str | None = None,
    limit: int = 100,
) -> tuple[Sequence[Document], str | None]:
    base_query = (
        select(Document)
        .join(
            DocumentByConnectorCredentialPair,
            Document.id == DocumentByConnectorCredentialPair.id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .join(
            UserGroup__ConnectorCredentialPair,
            UserGroup__ConnectorCredentialPair.cc_pair_id
            == ConnectorCredentialPair.id,
        )
        .join(
            UserGroup,
            UserGroup__ConnectorCredentialPair.user_group_id == UserGroup.id,
        )
        .where(UserGroup.id == user_group_id)
        .order_by(Document.id)
        .limit(limit)
    )
    if last_document_id is not None:
        base_query = base_query.where(Document.id > last_document_id)
    base_query = base_query.distinct()

    documents = db_session.scalars(base_query).all()
    next_page_cursor = documents[-1].id if documents else None
    return documents, next_page_cursor


def fetch_user_groups_for_documents(
    db_session: Session,
    document_ids: list[str],
) -> Sequence[tuple[str, list[str]]]:
    """
    Находит все группы, имеющие доступ к документам.
    ПРИМЕЧАНИЕ: Исключает группы, если cc_pair имеет тип доступа SYNC.
    """
    query = (
        select(Document.id, func.array_agg(UserGroup.name))
        .join(
            UserGroup__ConnectorCredentialPair,
            UserGroup.id == UserGroup__ConnectorCredentialPair.user_group_id,
        )
        .join(
            ConnectorCredentialPair,
            and_(
                ConnectorCredentialPair.id
                == UserGroup__ConnectorCredentialPair.cc_pair_id,
                ConnectorCredentialPair.access_type != AccessType.SYNC,
            ),
        )
        .join(
            DocumentByConnectorCredentialPair,
            and_(
                DocumentByConnectorCredentialPair.connector_id
                == ConnectorCredentialPair.connector_id,
                DocumentByConnectorCredentialPair.credential_id
                == ConnectorCredentialPair.credential_id,
            ),
        )
        .join(Document, Document.id == DocumentByConnectorCredentialPair.id)
        .where(Document.id.in_(document_ids))
        .where(UserGroup__ConnectorCredentialPair.is_current == True)  # noqa: E712
        # Исключаем пары CC, которые удаляются
        .where(
            ConnectorCredentialPair.status
            != ConnectorCredentialPairStatus.DELETING
        )
        .group_by(Document.id)
    )

    return db_session.execute(query).all()  # type: ignore


def _assert_group_is_not_syncing(user_group: UserGroup) -> None:
    """Проверяет, что группа не находится в процессе синхронизации."""
    if not user_group.is_up_to_date:
        raise ValueError(
            "Specified user group is currently syncing. Wait until the current "
            "sync has finished before editing."
        )


def _create_user_group_links__no_commit(
    db_session: Session, user_group_id: int, user_ids: list[UUID]
) -> list[User__UserGroup]:
    """Создает связи User__UserGroup. Не фиксирует транзакцию."""
    new_links = [
        User__UserGroup(user_id=uid, user_group_id=user_group_id)
        for uid in user_ids
    ]
    db_session.add_all(new_links)
    return new_links


def _create_group_cc_pair_links__no_commit(
    db_session: Session, user_group_id: int, cc_pair_ids: list[int]
) -> list[UserGroup__ConnectorCredentialPair]:
    """Создает связи UserGroup__ConnectorCredentialPair. Не фиксирует транзакцию."""
    new_bindings = [
        UserGroup__ConnectorCredentialPair(
            user_group_id=user_group_id, cc_pair_id=pid
        )
        for pid in cc_pair_ids
    ]
    db_session.add_all(new_bindings)
    return new_bindings


def insert_user_group(
    db_session: Session, user_group: UserGroupCreate
) -> UserGroup:
    new_group = UserGroup(
        name=user_group.name, time_last_modified_by_user=func.now()
    )
    db_session.add(new_group)
    # Получаем ID для новой группы перед созданием связей
    db_session.flush()

    _create_user_group_links__no_commit(
        db_session=db_session,
        user_group_id=new_group.id,
        user_ids=user_group.user_ids,
    )
    _create_group_cc_pair_links__no_commit(
        db_session=db_session,
        user_group_id=new_group.id,
        cc_pair_ids=user_group.cc_pair_ids,
    )

    db_session.commit()
    return new_group


def _flag_group_cc_pairs_as_stale__no_commit(
    db_session: Session, user_group_id: int
) -> None:
    """Помечает все текущие связи cc_pair для группы как устаревшие. Не фиксирует транзакцию."""
    links = db_session.scalars(
        select(UserGroup__ConnectorCredentialPair).where(
            UserGroup__ConnectorCredentialPair.user_group_id == user_group_id
        )
    )
    for link in links:
        link.is_current = False


def _update_user_role_based_on_curation__no_commit(
    db_session: Session,
    users: list[User],
) -> None:
    """
    Синхронизирует роль пользователя (CURATOR/BASIC) на основе
    того, курирует ли он хотя бы одну группу.
    """
    for user_instance in users:
        curator_links = (
            db_session.query(User__UserGroup)
            .filter(
                User__UserGroup.user_id == user_instance.id,
                User__UserGroup.is_curator == True,  # noqa: E712
            )
            .count()
        )

        if curator_links > 0:
            user_instance.role = UserRole.CURATOR
        elif user_instance.role == UserRole.CURATOR:
            # Понижаем роль до BASIC, только если он был CURATOR
            user_instance.role = UserRole.BASIC
        db_session.add(user_instance)


def _revoke_curator_role_for_user__no_commit(
    db_session: Session, user: User
) -> None:
    """Снимает флаг 'is_curator' со всех связей пользователя. Не фиксирует транзакцию."""
    stmt = (
        update(User__UserGroup)
        .where(User__UserGroup.user_id == user.id)
        .values(is_curator=False)
    )
    db_session.execute(stmt)
    _update_user_role_based_on_curation__no_commit(db_session, [user])


def _check_permission_to_modify_curator(
    db_session: Session,
    user_group_id: int,
    user_making_change: User | None = None,
) -> None:
    """
    Проверяет, имеет ли 'user_making_change' права (ADMIN, GLOBAL_CURATOR,
    или CURATOR этой группы) на изменение статуса куратора.
    """
    if user_making_change is None or user_making_change.role == UserRole.ADMIN:
        return

    is_curator_role = user_making_change.role == UserRole.CURATOR
    requester_curated_groups = fetch_user_groups_for_user(
        db_session=db_session,
        user_id=user_making_change.id,
        # GLOBAL_CURATOR может управлять любой группой, где он состоит
        only_curator_groups=is_curator_role,
    )

    requester_curator_group_ids = [
        group.id for group in requester_curated_groups
    ]
    if user_group_id not in requester_curator_group_ids:
        raise ValueError(
            f"User {user_making_change.email} is not a relevant curator "
            f"or admin for group '{user_group_id}'"
        )


def _check_validity_of_curator_update(
    db_session: Session,
    user_group_id: int,
    target_user: User,
) -> None:
    """Проверяет, что запрос на изменение статуса куратора допустим."""
    if target_user.role == UserRole.ADMIN:
        raise ValueError(
            f"User '{target_user.email}' is an admin. "
            "Admin role includes all curator permissions."
        )
    if target_user.role == UserRole.GLOBAL_CURATOR:
        raise ValueError(
            f"User '{target_user.email}' is a global_curator. "
            "This role includes curator permissions for all groups."
        )
    if target_user.role not in [UserRole.CURATOR, UserRole.BASIC]:
        raise ValueError(
            f"This endpoint only supports users with CURATOR or BASIC roles. "
            f"Target user: {target_user.email} (Role: {target_user.role})"
        )

    # Проверяем, состоит ли целевой пользователь в данной группе
    user_groups = fetch_user_groups_for_user(
        db_session=db_session,
        user_id=target_user.id,
        only_curator_groups=False,
    )
    group_ids = [group.id for group in user_groups]
    if user_group_id not in group_ids:
        raise ValueError(
            f"Target user {target_user.email} is not in group '{user_group_id}'"
        )


def update_user_curator_relationship(
    db_session: Session,
    user_group_id: int,
    set_curator_request: SetCuratorRequest,
    user_making_change: User | None = None,
) -> None:
    user_to_modify = fetch_user_by_id(
        db_session, set_curator_request.user_id
    )
    if not user_to_modify:
        raise ValueError(
            f"User with id '{set_curator_request.user_id}' not found"
        )

    # 1. Валидация запроса
    _check_validity_of_curator_update(
        db_session=db_session,
        user_group_id=user_group_id,
        target_user=user_to_modify,
    )

    # 2. Валидация прав исполнителя
    _check_permission_to_modify_curator(
        db_session=db_session,
        user_group_id=user_group_id,
        user_making_change=user_making_change,
    )

    logger.info(
        f"User '{user_making_change.email if user_making_change else 'System'}' "
        f"is setting is_curator={set_curator_request.is_curator} "
        f"for user='{user_to_modify.email}' in group={user_group_id}"
    )

    existing_link = (
        db_session.query(User__UserGroup)
        .filter(
            User__UserGroup.user_group_id == user_group_id,
            User__UserGroup.user_id == set_curator_request.user_id,
        )
        .first()
    )

    if existing_link:
        existing_link.is_curator = set_curator_request.is_curator
    else:
        # Этого не должно случиться, если _check_validity_of_curator_update
        # отработал, но для надежности
        new_link = User__UserGroup(
            user_group_id=user_group_id,
            user_id=set_curator_request.user_id,
            is_curator=True,
        )
        db_session.add(new_link)

    _update_user_role_based_on_curation__no_commit(
        db_session, [user_to_modify]
    )
    db_session.commit()


def update_user_group(
    db_session: Session,
    user: User | None,
    user_group_id: int,
    user_group_update: UserGroupUpdate,
) -> UserGroup:
    """
    Обновляет группу пользователей.
    Может установить 'is_up_to_date = False', что вызовет фоновую
    синхронизацию с Vespa.
    """
    group_to_update = db_session.scalar(
        select(UserGroup).where(UserGroup.id == user_group_id)
    )
    if group_to_update is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _assert_group_is_not_syncing(group_to_update)

    # Вычисляем изменения в пользователях
    existing_user_id_set = {user.id for user in group_to_update.users}
    new_user_id_set = set(user_group_update.user_ids)
    users_to_add_ids = list(new_user_id_set - existing_user_id_set)
    users_to_remove_ids = list(existing_user_id_set - new_user_id_set)

    if users_to_remove_ids:
        _clear_user_group_links__no_commit(
            db_session=db_session,
            user_group_id=user_group_id,
            user_ids=users_to_remove_ids,
        )

    if users_to_add_ids:
        _create_user_group_links__no_commit(
            db_session=db_session,
            user_group_id=user_group_id,
            user_ids=users_to_add_ids,
        )

    # Вычисляем изменения в парах коннекторов
    existing_cc_pair_ids = {
        cc_pair.id for cc_pair in group_to_update.cc_pairs
    }
    connector_pairs_changed = (
        existing_cc_pair_ids != set(user_group_update.cc_pair_ids)
    )

    if connector_pairs_changed:
        _flag_group_cc_pairs_as_stale__no_commit(
            db_session=db_session, user_group_id=user_group_id
        )
        _create_group_cc_pair_links__no_commit(
            db_session=db_session,
            user_group_id=group_to_update.id,
            cc_pair_ids=user_group_update.cc_pair_ids,
        )
        # Требуется синхронизация с Vespa
        group_to_update.is_up_to_date = False

    # Перепроверяем роли удаленных пользователей
    if users_to_remove_ids:
        users_removed = db_session.scalars(
            select(User).where(User.id.in_(users_to_remove_ids))  # type: ignore
        ).unique()

        users_for_role_check = [
            u
            for u in users_removed
            if u.role not in [UserRole.ADMIN, UserRole.GLOBAL_CURATOR]
        ]

        if users_for_role_check:
            _update_user_role_based_on_curation__no_commit(
                db_session, users_for_role_check
            )

    group_to_update.time_last_modified_by_user = func.now()
    db_session.commit()
    return group_to_update


def prepare_user_group_for_deletion(
    db_session: Session, user_group_id: int
) -> None:
    group_to_delete = db_session.scalar(
        select(UserGroup).where(UserGroup.id == user_group_id)
    )
    if group_to_delete is None:
        raise ValueError(f"UserGroup with id '{user_group_id}' not found")

    _assert_group_is_not_syncing(group_to_delete)

    # Помечаем все связи cc_pair как устаревшие (для очистки Vespa)
    _flag_group_cc_pairs_as_stale__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )

    # Очищаем все FK-связи перед удалением
    _clear_credential_group_links__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _clear_user_group_links__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _clear_token_limit_group_links__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _clear_doc_set_group_links__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _clear_persona_group_links__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )
    _clear_group_cc_pair_links__no_commit(
        db_session=db_session,
        user_group_id=user_group_id,
        outdated_only=False,
    )
    _clear_llm_provider_group_links__no_commit(
        db_session=db_session, user_group_id=user_group_id
    )

    group_to_delete.is_up_to_date = False
    group_to_delete.is_up_for_deletion = True
    db_session.commit()


def delete_user_group(db_session: Session, user_group: UserGroup) -> None:
    """
    Окончательно удаляет группу.
    Предполагается, что 'prepare_user_group_for_deletion' уже вызван,
    и Vespa обработала удаление.
    """
    db_session.delete(user_group)
    db_session.commit()


def mark_user_group_as_synced(
    db_session: Session, user_group: UserGroup
) -> None:
    """
    Вызывается после завершения синхронизации Vespa.
    Очищает устаревшие связи cc_pair.
    """
    _clear_group_cc_pair_links__no_commit(
        db_session=db_session,
        user_group_id=user_group.id,
        outdated_only=True,
    )
    user_group.is_up_to_date = True
    db_session.commit()


def delete_user_group_cc_pair_relationship__no_commit(
    cc_pair_id: int, db_session: Session
) -> None:
    """
    Удаляет все связи UserGroup__ConnectorCredentialPair для данного cc_pair_id.
    ИСПОЛЬЗОВАТЬ С ОСТОРОЖНОСТЬЮ: только при удалении коннектора.
    """
    connector_pair = get_connector_credential_pair_from_id(
        db_session=db_session,
        cc_pair_id=cc_pair_id,
    )
    if not connector_pair:
        raise ValueError(
            f"Connector Credential Pair '{cc_pair_id}' does not exist"
        )

    if connector_pair.status != ConnectorCredentialPairStatus.DELETING:
        raise ValueError(
            f"Connector Credential Pair '{cc_pair_id}' is not in the DELETING "
            f"state. status={connector_pair.status}"
        )

    stmt_delete = delete(UserGroup__ConnectorCredentialPair).where(
        UserGroup__ConnectorCredentialPair.cc_pair_id == cc_pair_id,
    )
    db_session.execute(stmt_delete)
