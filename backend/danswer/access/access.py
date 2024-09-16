from sqlalchemy.orm import Session

from danswer.access.models import DocumentAccess
from danswer.access.utils import prefix_user
from danswer.configs.constants import PUBLIC_DOC_PAT
from danswer.db.document import get_access_info_for_document
from danswer.db.document import get_access_info_for_documents
from danswer.db.models import User
from danswer.utils.variable_functionality import fetch_versioned_implementation


def _get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    info = get_access_info_for_document(
        db_session=db_session,
        document_id=document_id,
    )

    if not info:
        return DocumentAccess.build(user_ids=[], user_groups=[], is_public=False)

    return DocumentAccess.build(user_ids=info[1], user_groups=[], is_public=info[2])


def get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    versioned_get_access_for_document_fn = fetch_versioned_implementation(
        "danswer.access.access", "_get_access_for_document"
    )
    return versioned_get_access_for_document_fn(document_id, db_session)  # type: ignore


def _get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    document_access_info = get_access_info_for_documents(
        db_session=db_session,
        document_ids=document_ids,
    )
    return {
        document_id: DocumentAccess.build(
            user_ids=user_ids, user_groups=[], is_public=is_public
        )
        for document_id, user_ids, is_public in document_access_info
    }


def get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    """Fetches all access information for the given documents."""
    versioned_get_access_for_documents_fn = fetch_versioned_implementation(
        "danswer.access.access", "_get_access_for_documents"
    )
    return versioned_get_access_for_documents_fn(
        document_ids, db_session
    )  # type: ignore


def _get_acl_for_user(user: User | None, db_session: Session) -> set[str]:
    """Returns a list of ACL entries that the user has access to. This is meant to be
    used downstream to filter out documents that the user does not have access to. The
    user should have access to a document if at least one entry in the document's ACL
    matches one entry in the returned set.
    """
    if user:
        return {prefix_user(str(user.id)), PUBLIC_DOC_PAT}
    return {PUBLIC_DOC_PAT}


def get_acl_for_user(user: User | None, db_session: Session | None = None) -> set[str]:
    versioned_acl_for_user_fn = fetch_versioned_implementation(
        "danswer.access.access", "_get_acl_for_user"
    )
    return versioned_acl_for_user_fn(user, db_session)  # type: ignore
