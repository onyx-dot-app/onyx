from collections.abc import Sequence
from uuid import UUID
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.db.models import User, User__ExternalUserGroupId
from onyx.db.users import batch_add_ext_perm_user_if_not_exists, get_user_by_email
from onyx.utils.logger import setup_logger

logger = setup_logger()


class ExternalUserGroup(BaseModel):
    id: str
    user_emails: list[str]


def delete_user__ext_group_for_user__no_commit(
    db_session: Session,
    user_id: UUID,
) -> None:
    """Удаляет связи внешних групп для пользователя без коммита."""
    stmt = delete(User__ExternalUserGroupId).where(
        User__ExternalUserGroupId.user_id == user_id
    )
    db_session.execute(stmt)


def delete_user__ext_group_for_cc_pair__no_commit(
    db_session: Session,
    cc_pair_id: int,
) -> None:
    """Удаляет связи внешних групп для cc_pair без коммита."""
    stmt = delete(User__ExternalUserGroupId).where(
        User__ExternalUserGroupId.cc_pair_id == cc_pair_id
    )
    db_session.execute(stmt)


def _collect_unique_emails(groups: list[ExternalUserGroup]) -> set[str]:
    """Собирает уникальные email из всех групп."""
    unique_emails: set[str] = set()
    idx = 0
    while idx < len(groups):
        grp_emails = groups[idx].user_emails
        jdx = 0
        while jdx < len(grp_emails):
            unique_emails.add(grp_emails[jdx])
            jdx += 1
        idx += 1
    return unique_emails


def _build_prefixed_group_id(group_id: str, source: DocumentSource) -> str:
    """Формирует префиксованное имя группы для внешнего доступа."""
    return build_ext_group_name_for_onyx(ext_group_name=group_id, source=source)


def replace_user__ext_group_for_cc_pair(
    db_session: Session,
    cc_pair_id: int,
    group_defs: list[ExternalUserGroup],
    source: DocumentSource,
) -> None:
    """
    Очищает существующие связи внешних групп для cc_pair и заменяет их новыми.
    Коммитит изменения.
    """
    session = db_session
    pair_id = cc_pair_id
    source_type = source

    # Собираем все email для пакетного добавления пользователей
    member_emails = _collect_unique_emails(group_defs)

    # Добавляем пользователей, если не существуют, и получаем их ID
    existing_users: list[User] = batch_add_ext_perm_user_if_not_exists(
        db_session=session,
        emails=list(member_emails),
    )

    # Удаляем старые связи
    delete_user__ext_group_for_cc_pair__no_commit(
        db_session=session,
        cc_pair_id=pair_id,
    )

    # Создаем маппинг email -> ID (с учетом lower для case-insensitivity)
    email_to_id: dict[str, UUID] = {}
    for usr in existing_users:
        email_to_id[usr.email.lower()] = usr.id

    # Формируем новые связи
    new_relations = []
    for grp_def in group_defs:
        prefixed_grp_id = _build_prefixed_group_id(grp_def.id, source_type)
        for email in grp_def.user_emails:
            usr_uuid = email_to_id.get(email.lower())
            if usr_uuid is None:
                logger.warning(
                    f"Пользователь с email {email} в группе {grp_def.id} не найден"
                )
                continue
            relation = User__ExternalUserGroupId(
                user_id=usr_uuid,
                external_user_group_id=prefixed_grp_id,
                cc_pair_id=pair_id,
            )
            new_relations.append(relation)

    session.add_all(new_relations)
    session.commit()


def fetch_external_groups_for_user(
    db_session: Session,
    user_id: UUID,
) -> Sequence[User__ExternalUserGroupId]:
    """Извлекает внешние группы для пользователя."""
    query = select(User__ExternalUserGroupId).where(
        User__ExternalUserGroupId.user_id == user_id
    )
    return db_session.scalars(query).all()


def fetch_external_groups_for_user_email_and_group_ids(
    db_session: Session,
    user_email: str,
    group_ids: list[str],
) -> list[User__ExternalUserGroupId]:
    """Извлекает внешние группы для email и указанных ID групп."""
    session = db_session
    target_email = user_email
    target_groups = group_ids

    # Получаем пользователя по email
    target_user = get_user_by_email(db_session=session, email=target_email)
    if not target_user:
        return []

    target_uuid = target_user.id

    # Запрос с фильтром по ID пользователя и группам
    query = (
        select(User__ExternalUserGroupId)
        .where(
            User__ExternalUserGroupId.user_id == target_uuid,
            User__ExternalUserGroupId.external_user_group_id.in_(target_groups),
        )
    )
    relations = session.scalars(query).all()
    return list(relations)
