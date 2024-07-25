from sqlalchemy.orm import Session

from danswer.access.models import DocumentAccess
from danswer.access.utils import prefix_user
from danswer.configs.constants import PUBLIC_DOC_PAT
from danswer.db.document import get_acccess_info_for_documents
from danswer.db.models import User
from danswer.server.documents.models import ConnectorCredentialPairIdentifier
from danswer.utils.variable_functionality import fetch_versioned_implementation


def _get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
    cc_pair_to_delete: ConnectorCredentialPairIdentifier | None = None,
) -> dict[str, DocumentAccess]:
    document_access_info = get_acccess_info_for_documents(
        db_session=db_session,
        document_ids=document_ids,
        cc_pair_to_delete=cc_pair_to_delete,
    )
    return {
        document_id: DocumentAccess.build(user_ids, [], is_public)
        for document_id, user_ids, is_public in document_access_info
    }


def get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
    cc_pair_to_delete: ConnectorCredentialPairIdentifier | None = None,
) -> dict[str, DocumentAccess]:
    """Fetches all access information for the given documents."""
    versioned_get_access_for_documents_fn = fetch_versioned_implementation(
        "danswer.access.access", "_get_access_for_documents"
    )
    return versioned_get_access_for_documents_fn(
        document_ids, db_session, cc_pair_to_delete
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
