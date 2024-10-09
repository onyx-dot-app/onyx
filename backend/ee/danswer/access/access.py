from sqlalchemy.orm import Session

from danswer.access.access import (
    _get_access_for_documents as get_access_for_documents_without_groups,
)
from danswer.access.access import _get_acl_for_user as get_acl_for_user_without_groups
from danswer.access.models import DocumentAccess
from danswer.access.utils import prefix_external_group
from danswer.access.utils import prefix_user_group
from danswer.db.document import get_documents_by_ids
from danswer.db.models import User
from ee.danswer.db.external_perm import fetch_external_groups_for_user
from ee.danswer.db.user_group import fetch_user_groups_for_documents
from ee.danswer.db.user_group import fetch_user_groups_for_user


def _get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    id_to_access = _get_access_for_documents([document_id], db_session)
    if len(id_to_access) == 0:
        return DocumentAccess.build(
            user_emails=[],
            user_groups=[],
            external_user_emails=[],
            external_user_group_ids=[],
            is_public=False,
        )

    return next(iter(id_to_access.values()))


def _get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    non_ee_access_dict = get_access_for_documents_without_groups(
        document_ids=document_ids,
        db_session=db_session,
    )
    user_group_info: dict[str, list[str]] = {
        document_id: group_names
        for document_id, group_names in fetch_user_groups_for_documents(
            db_session=db_session,
            document_ids=document_ids,
        )
    }
    documents = get_documents_by_ids(
        db_session=db_session,
        document_ids=document_ids,
    )
    doc_id_map = {doc.id: doc for doc in documents}

    access_map = {}
    for document_id, non_ee_access in non_ee_access_dict.items():
        document = doc_id_map[document_id]

        ext_u_emails = (
            set(document.external_user_emails)
            if document.external_user_emails
            else set()
        )

        ext_u_groups = (
            set(document.external_user_group_ids)
            if document.external_user_group_ids
            else set()
        )

        # If the document is determined to be "public" externally (through a SYNC connector)
        # then it's given the same access level as if it were marked public within Danswer
        is_public_anywhere = document.is_public or non_ee_access.is_public

        # To avoid collisions of group namings between connectors, they need to be prefixed
        access_map[document_id] = DocumentAccess(
            user_emails=non_ee_access.user_emails,
            user_groups=set(user_group_info.get(document_id, [])),
            is_public=is_public_anywhere,
            external_user_emails=ext_u_emails,
            external_user_group_ids=ext_u_groups,
        )
    return access_map


def _get_acl_for_user(user: User | None, db_session: Session) -> set[str]:
    """Returns a list of ACL entries that the user has access to. This is meant to be
    used downstream to filter out documents that the user does not have access to. The
    user should have access to a document if at least one entry in the document's ACL
    matches one entry in the returned set.

    NOTE: is imported in danswer.access.access by `fetch_versioned_implementation`
    DO NOT REMOVE."""
    db_user_groups = fetch_user_groups_for_user(db_session, user.id) if user else []
    prefixed_user_groups = [
        prefix_user_group(db_user_group.name) for db_user_group in db_user_groups
    ]

    db_external_groups = (
        fetch_external_groups_for_user(db_session, user.id) if user else []
    )
    prefixed_external_groups = [
        prefix_external_group(db_external_group.external_user_group_id)
        for db_external_group in db_external_groups
    ]

    user_acl = set(prefixed_user_groups + prefixed_external_groups)
    user_acl.update(get_acl_for_user_without_groups(user, db_session))

    return user_acl
