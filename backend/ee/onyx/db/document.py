from datetime import datetime
from datetime import timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from onyx.access.models import ExternalAccess
from onyx.access.utils import build_ext_group_name_for_onyx
from onyx.configs.constants import DocumentSource
from onyx.db.models import Document as DbDocument


def _prepare_prefixed_groups(
    group_ids: list[str], source: DocumentSource
) -> list[str]:
    """Преобразует ID групп в префиксованные имена для внешнего доступа."""
    result: list[str] = []
    idx = 0
    while idx < len(group_ids):
        result.append(
            build_ext_group_name_for_onyx(
                ext_group_name=group_ids[idx], source=source
            )
        )
        idx += 1
    return result


def upsert_document_external_perms__no_commit(
    db_session: Session,
    doc_id: str,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> None:
    """
    Устанавливает разрешения для документа в PostgreSQL.
    Заменяет существующий внешний доступ полностью, без объединения.
    """
    session = db_session
    query = select(DbDocument).where(DbDocument.id == doc_id)
    doc_record = session.scalars(query).first()

    prefixed_groups = _prepare_prefixed_groups(
        external_access.external_user_group_ids, source_type
    )

    if not doc_record:
        new_doc = DbDocument(
            id=doc_id,
            semantic_id="",
            external_user_emails=external_access.external_user_emails,
            external_user_group_ids=prefixed_groups,
            is_public=external_access.is_public,
        )
        session.add(new_doc)
        return

    doc_record.external_user_emails = list(external_access.external_user_emails)
    doc_record.external_user_group_ids = prefixed_groups
    doc_record.is_public = external_access.is_public


def upsert_document_external_perms(
    db_session: Session,
    doc_id: str,
    external_access: ExternalAccess,
    source_type: DocumentSource,
) -> bool:
    """
    Устанавливает разрешения для документа в PostgreSQL.
    Возвращает True, если создан новый документ, иначе False.
    Заменяет существующий внешний доступ полностью, без объединения.
    """
    session = db_session
    query = select(DbDocument).where(DbDocument.id == doc_id)
    doc_record = session.scalars(query).first()

    prefixed_groups_set = set(
        _prepare_prefixed_groups(
            external_access.external_user_group_ids, source_type
        )
    )

    if not doc_record:
        new_doc = DbDocument(
            id=doc_id,
            semantic_id="",
            external_user_emails=external_access.external_user_emails,
            external_user_group_ids=list(prefixed_groups_set),
            is_public=external_access.is_public,
        )
        session.add(new_doc)
        session.commit()
        return True

    existing_emails = set(doc_record.external_user_emails or [])
    existing_groups = set(doc_record.external_user_group_ids or [])

    if (
        external_access.external_user_emails != existing_emails
        or prefixed_groups_set != existing_groups
        or external_access.is_public != doc_record.is_public
    ):
        doc_record.external_user_emails = list(external_access.external_user_emails)
        doc_record.external_user_group_ids = list(prefixed_groups_set)
        doc_record.is_public = external_access.is_public
        doc_record.last_modified = datetime.now(timezone.utc)
        session.commit()
        return False

    return False
