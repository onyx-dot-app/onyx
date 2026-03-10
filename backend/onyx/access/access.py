from collections.abc import Callable
from typing import cast

from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.db.document import get_access_info_for_document
from onyx.db.document import get_access_info_for_documents
from onyx.db.models import User
from onyx.db.models import UserFile
from onyx.db.user_file import fetch_user_files_with_access_relationships
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop
from onyx.utils.variable_functionality import fetch_versioned_implementation


def _get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    info = get_access_info_for_document(
        db_session=db_session,
        document_id=document_id,
    )

    doc_access = DocumentAccess.build(
        user_emails=info[1] if info and info[1] else [],
        user_groups=[],
        external_user_emails=[],
        external_user_group_ids=[],
        is_public=info[2] if info else False,
    )

    return doc_access


def get_access_for_document(
    document_id: str,
    db_session: Session,
) -> DocumentAccess:
    versioned_get_access_for_document_fn = fetch_versioned_implementation(
        "onyx.access.access", "_get_access_for_document"
    )
    return versioned_get_access_for_document_fn(document_id, db_session)


def get_null_document_access() -> DocumentAccess:
    return DocumentAccess.build(
        user_emails=[],
        user_groups=[],
        is_public=False,
        external_user_emails=[],
        external_user_group_ids=[],
    )


def _get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    document_access_info = get_access_info_for_documents(
        db_session=db_session,
        document_ids=document_ids,
    )
    doc_access = {}
    for document_id, user_emails, is_public in document_access_info:
        doc_access[document_id] = DocumentAccess.build(
            user_emails=[email for email in user_emails if email],
            # MIT version will wipe all groups and external groups on update
            user_groups=[],
            is_public=is_public,
            external_user_emails=[],
            external_user_group_ids=[],
        )

    # Sometimes the document has not been indexed by the indexing job yet, in those cases
    # the document does not exist and so we use least permissive. Specifically the EE version
    # checks the MIT version permissions and creates a superset. This ensures that this flow
    # does not fail even if the Document has not yet been indexed.
    for doc_id in document_ids:
        if doc_id not in doc_access:
            doc_access[doc_id] = get_null_document_access()
    return doc_access


def get_access_for_documents(
    document_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    """Fetches all access information for the given documents."""
    versioned_get_access_for_documents_fn = fetch_versioned_implementation(
        "onyx.access.access", "_get_access_for_documents"
    )
    return versioned_get_access_for_documents_fn(document_ids, db_session)


def _get_acl_for_user(user: User, db_session: Session) -> set[str]:  # noqa: ARG001
    """Returns a list of ACL entries that the user has access to. This is meant to be
    used downstream to filter out documents that the user does not have access to. The
    user should have access to a document if at least one entry in the document's ACL
    matches one entry in the returned set.

    Anonymous users only have access to public documents.
    """
    if user.is_anonymous:
        return {PUBLIC_DOC_PAT}
    return {prefix_user_email(user.email), PUBLIC_DOC_PAT}


def get_acl_for_user(user: User, db_session: Session | None = None) -> set[str]:
    versioned_acl_for_user_fn = fetch_versioned_implementation(
        "onyx.access.access", "_get_acl_for_user"
    )
    return versioned_acl_for_user_fn(user, db_session)


def source_should_fetch_permissions_during_indexing(source: DocumentSource) -> bool:
    _source_should_fetch_permissions_during_indexing_func = cast(
        Callable[[DocumentSource], bool],
        fetch_ee_implementation_or_noop(
            "onyx.external_permissions.sync_params",
            "source_should_fetch_permissions_during_indexing",
            False,
        ),
    )
    return _source_should_fetch_permissions_during_indexing_func(source)


def get_access_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    versioned_fn = fetch_versioned_implementation(
        "onyx.access.access", "get_access_for_user_files_impl"
    )
    return versioned_fn(user_file_ids, db_session)


def get_access_for_user_files_impl(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, DocumentAccess]:
    user_files = fetch_user_files_with_access_relationships(user_file_ids, db_session)
    return build_access_for_user_files_impl(user_files)


def build_access_for_user_files(
    user_files: list[UserFile],
) -> dict[str, DocumentAccess]:
    """Compute access from pre-loaded UserFile objects (with relationships).
    Callers must ensure UserFile.user, Persona.users, and Persona.user are
    eagerly loaded (and Persona.groups for the EE path)."""
    versioned_fn = fetch_versioned_implementation(
        "onyx.access.access", "build_access_for_user_files_impl"
    )
    return versioned_fn(user_files)


def build_access_for_user_files_impl(
    user_files: list[UserFile],
) -> dict[str, DocumentAccess]:
    result: dict[str, DocumentAccess] = {}
    for user_file in user_files:
        emails, is_public = collect_user_file_access(user_file)
        result[str(user_file.id)] = DocumentAccess.build(
            user_emails=list(emails),
            user_groups=[],
            is_public=is_public,
            external_user_emails=[],
            external_user_group_ids=[],
        )
    return result


def collect_user_file_access(user_file: UserFile) -> tuple[set[str], bool]:
    """Collect all user emails that should have access to this user file.
    Includes the owner plus any users who have access via shared personas.
    Returns (emails, is_public)."""
    emails: set[str] = {user_file.user.email}
    is_public = False
    for persona in user_file.assistants:
        if persona.deleted:
            continue
        if persona.is_public:
            is_public = True
        if persona.user_id is not None and persona.user:
            emails.add(persona.user.email)
        for shared_user in persona.users:
            emails.add(shared_user.email)
    return emails, is_public
