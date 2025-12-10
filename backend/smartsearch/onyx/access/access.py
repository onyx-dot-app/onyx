from sqlalchemy.orm import Session

from smartsearch.onyx.db.user_group import fetch_user_groups_for_documents
from smartsearch.onyx.db.user_group import fetch_user_groups_for_user
from onyx.access.access import (
    _get_access_for_documents as get_access_for_documents_without_groups,
)
from onyx.access.access import _get_acl_for_user as get_acl_for_user_without_groups
from onyx.access.models import DocumentAccess
from onyx.access.utils import prefix_external_group
from onyx.access.utils import prefix_user_group
from onyx.db.document import get_document_sources
from onyx.db.document import get_documents_by_ids
from onyx.db.models import User


def _get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    # Получаем права доступа пакетно для одного ID
    access_map = _get_access_for_documents([document_id], db_session)

    if not access_map:
        # Возвращаем "пустой" объект доступа, если запись не найдена
        return DocumentAccess.build(
            user_emails=[],
            user_groups=[],
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=False,
        )

    return access_map[document_id]


def _get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    # 1. Получаем базовые права доступа (без учета групп)
    base_access_map = get_access_for_documents_without_groups(
        document_ids=document_ids,
        db_session=db_session,
    )

    # 2. Извлекаем группы пользователей, привязанные к документам
    groups_by_doc = {
        doc_id: groups
        for doc_id, groups in fetch_user_groups_for_documents(
            db_session=db_session,
            document_ids=document_ids,
        )
    }

    # 3. Загружаем метаданные документов и информацию об источниках
    documents = get_documents_by_ids(
        db_session=db_session,
        document_ids=document_ids,
    )
    docs_lookup = {d.id: d for d in documents}

    sources_lookup = get_document_sources(
        db_session=db_session,
        document_ids=document_ids,
    )

    final_access = {}

    for doc_id, base_access in base_access_map.items():
        current_doc = docs_lookup[doc_id]
        source_type = sources_lookup.get(doc_id)

        # Проверяем, требуется ли цензурирование (censoring) для данного источника
        # Это актуально, если источник есть в списке цензурируемых, но нет специфичной карты прав
        requires_censoring = False

        # Формируем наборы внешних email и групп (если они есть)
        ext_emails = set(current_doc.external_user_emails or [])
        ext_groups = set(current_doc.external_user_group_ids or [])

        # Определение публичности документа.
        # Документ считается публичным, если:
        # - он помечен публичным в Onyx
        # - он помечен публичным в базовых правах
        # - он подлежит только цензурированию (доступен при поиске, права проверяются позже)
        is_public_access = (
            current_doc.is_public
            or base_access.is_public
            or requires_censoring
        )

        # Сборка финального объекта доступа.
        # Внешние группы и email-ы объединяются с внутренними.
        final_access[doc_id] = DocumentAccess.build(
            user_emails=list(base_access.user_emails),
            user_groups=groups_by_doc.get(doc_id, []),
            is_public=is_public_access,
            external_user_emails=list(ext_emails),
            external_user_group_ids=list(ext_groups),
        )

    return final_access


def _get_acl_for_user(user: User | None, db_session: Session) -> set[str]:
    """
    Возвращает набор ACL (Access Control List), доступный пользователю.
    Используется для фильтрации документов, к которым пользователь не имеет доступа.
    Доступ разрешен, если хотя бы одна запись в ACL документа совпадает с возвращаемым набором.

    ВАЖНО: Функция импортируется в `onyx.access.access` через `fetch_versioned_implementation`.
    НЕ УДАЛЯТЬ И НЕ МЕНЯТЬ СИГНАТУРУ.
    """
    if user:
        internal_groups = fetch_user_groups_for_user(db_session, user.id)
        external_groups = []
    else:
        internal_groups = []
        external_groups = []

    # Префиксы необходимы для предотвращения коллизий имен групп из разных источников
    acl_list = [prefix_user_group(g.name) for g in internal_groups]
    acl_list.extend(
        prefix_external_group(g.external_user_group_id) for g in external_groups
    )

    # Формируем итоговый сет прав
    user_acl = set(acl_list)

    # Добавляем права, не связанные с группами
    base_acl = get_acl_for_user_without_groups(user, db_session)
    user_acl.update(base_acl)

    return user_acl
