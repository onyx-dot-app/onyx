from typing import List
from uuid import UUID
from sqlalchemy.orm import Session

from onyx.db.models import (
    ConnectorCredentialPair,
    DocumentSet,
    DocumentSet__ConnectorCredentialPair,
    DocumentSet__User,
    DocumentSet__UserGroup,
    UserGroup,
    User__UserGroup,
)


def _clear_privacy_associations(session: Session, doc_set_id: int) -> None:
    """Удаляет все существующие ассоциации приватности для набора документов."""
    user_assoc_query = session.query(DocumentSet__User).filter(
        DocumentSet__User.document_set_id == doc_set_id
    )
    user_assoc_query.delete(synchronize_session="fetch")

    group_assoc_query = session.query(DocumentSet__UserGroup).filter(
        DocumentSet__UserGroup.document_set_id == doc_set_id
    )
    group_assoc_query.delete(synchronize_session="fetch")


def make_doc_set_private(
    document_set_id: int,
    user_ids: list[UUID] | None,
    group_ids: list[int] | None,
    db_session: Session,
) -> None:
    _clear_privacy_associations(db_session, document_set_id)

    if user_ids:
        for user_uuid in user_ids:
            db_session.add(
                DocumentSet__User(
                    document_set_id=document_set_id,
                    user_id=user_uuid,
                )
            )

    if group_ids:
        for group_id in group_ids:
            db_session.add(
                DocumentSet__UserGroup(
                    document_set_id=document_set_id,
                    user_group_id=group_id,
                )
            )


def delete_document_set_privacy__no_commit(
    document_set_id: int, db_session: Session
) -> None:
    _clear_privacy_associations(db_session, document_set_id)


def fetch_document_sets(
    user_id: UUID | None,
    db_session: Session,
    include_outdated: bool = True,  # Параметр для совместимости, не используется
) -> list[tuple[DocumentSet, list[ConnectorCredentialPair]]]:
    """
    Возвращает все доступные наборы документов для указанного пользователя.
    Включает публичные наборы, прямые шеры и шеры через группы пользователя.
    Для каждого набора извлекаются связанные ConnectorCredentialPair.
    """
    assert user_id is not None

    session = db_session

    # Сначала получаем группы пользователя
    belonging_groups = (
        session.query(UserGroup)
        .join(
            User__UserGroup,
            UserGroup.id == User__UserGroup.user_group_id,
        )
        .filter(User__UserGroup.user_id == user_id)
        .all()
    )

    # Шеры через группы
    indirect_shares: list[DocumentSet] = []
    for grp in belonging_groups:
        indirect_query = (
            session.query(DocumentSet)
            .join(
                DocumentSet__UserGroup,
                DocumentSet.id == DocumentSet__UserGroup.document_set_id,
            )
            .filter(DocumentSet__UserGroup.user_group_id == grp.id)
            .all()
        )
        indirect_shares.extend(indirect_query)

    # Прямые шеры
    direct_access = (
        session.query(DocumentSet)
        .join(
            DocumentSet__User,
            DocumentSet.id == DocumentSet__User.document_set_id,
        )
        .filter(DocumentSet__User.user_id == user_id)
        .all()
    )

    # Публичные наборы
    open_access_sets = (
        session.query(DocumentSet)
        .filter(DocumentSet.is_public == True)  # noqa
        .all()
    )

    # Дедупликация по ID с сохранением оригинальных объектов
    seen_ids: set[int] = set()
    deduped_sets: list[DocumentSet] = []

    for candidate_set in [*indirect_shares, *direct_access, *open_access_sets]:
        if candidate_set.id not in seen_ids:
            seen_ids.add(candidate_set.id)
            deduped_sets.append(candidate_set)

    # Извлечение связанных пар коннекторов
    final_result: list[tuple[DocumentSet, list[ConnectorCredentialPair]]] = []
    for doc_set in deduped_sets:
        related_pairs = (
            session.query(ConnectorCredentialPair)
            .join(
                DocumentSet__ConnectorCredentialPair,
                ConnectorCredentialPair.id
                == DocumentSet__ConnectorCredentialPair.connector_credential_pair_id,
            )
            .filter(
                DocumentSet__ConnectorCredentialPair.document_set_id == doc_set.id
            )
            .all()
        )
        final_result.append((doc_set, related_pairs))  # type: ignore

    return final_result
