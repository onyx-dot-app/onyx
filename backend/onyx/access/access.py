from collections.abc import Callable
from typing import cast
from uuid import UUID

from sqlalchemy.orm import Session

from onyx.access.cc_pair_access import get_cc_pair_access_mode
from onyx.access.models import DocumentAccess
from onyx.access.utils import (
    EXTERNAL_GROUP_ACL_PREFIX,
    USER_EMAIL_ACL_PREFIX,
    prefix_user_email,
)
from onyx.configs.constants import (
    CHAT_SESSION_ID_FILE_METADATA_KEY,
    PUBLIC_DOC_PAT,
    DocumentSource,
    FileOrigin,
)
from onyx.context.search.models import CCPairAccessMode, InferenceChunk
from onyx.db.access import (
    get_chat_output_file_row,
    get_document_ids_for_file,
    get_document_ids_from_file_connector_config,
    user_can_access_chat_message_file,
    user_can_access_persona_attached_file,
    user_can_read_chat_session,
    user_owns_user_file,
)
from onyx.db.connector_credential_pair import (
    get_cc_pair_access_sets_for_user,
    has_guarded_cc_pairs,
)
from onyx.db.document import (
    get_access_info_for_document,
    get_access_info_for_documents,
    get_cc_pair_ids_for_documents,
)
from onyx.db.models import User, UserFile
from onyx.db.user_file import fetch_user_files_with_access_relationships
from onyx.utils.variable_functionality import (
    fetch_ee_implementation_or_noop,
    fetch_versioned_implementation,
)


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


def _get_acl_for_user(
    user: User,
    db_session: Session,  # noqa: ARG001
) -> set[str]:  # noqa: ARG001
    """Returns a list of ACL entries that the user has access to. This is meant to be
    used downstream to filter out documents that the user does not have access to. The
    user should have access to a document if at least one entry in the document's ACL
    matches one entry in the returned set.

    Anonymous users only have access to public documents.

    Addresses the user was renamed away from match too. Indexed ACLs keep
    naming the old one until the source system re-syncs, and the alias is
    revoked as soon as the address belongs to somebody else.
    """
    if user.is_anonymous:
        return {PUBLIC_DOC_PAT}
    return {
        prefix_user_email(user.email),
        *(prefix_user_email(email) for email in user.prior_emails),
        PUBLIC_DOC_PAT,
    }


def get_acl_for_user(user: User, db_session: Session | None = None) -> set[str]:
    versioned_acl_for_user_fn = fetch_versioned_implementation(
        "onyx.access.access", "_get_acl_for_user"
    )
    return versioned_acl_for_user_fn(user, db_session)


def censor_chunks_for_user(
    chunks: list[InferenceChunk], user: User
) -> list[InferenceChunk]:
    """EE post-query censoring for sources whose access is decided per user at
    read time. Every path that hands chunk content to a user runs it, not only
    search, since the index ACL alone lets those chunks through."""
    return fetch_ee_implementation_or_noop(
        "onyx.external_permissions.post_query_censoring",
        "_post_query_chunk_censoring",
        chunks,
    )(chunks=chunks, user=user)


def get_censoring_enabled_sources() -> set[DocumentSource]:
    """Sources whose access EE decides per user at read time (see
    censor_chunks_for_user). Empty without EE."""
    return fetch_ee_implementation_or_noop(
        "onyx.external_permissions.sync_params",
        "get_all_censoring_enabled_sources",
        set(),
    )()


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


def user_can_access_chat_file(file_id: str, user: User, db_session: Session) -> bool:
    """Return True if `user` can read `file_id` via `GET /chat/file/{file_id}`.

    The endpoint is overloaded across several asset classes, so we check
    each in turn (cheapest first, so common paths short-circuit before the
    JSONB scan in `get_document_ids_from_file_connector_config`):

    - `UserFile` owned by the user.
    - `UserFile` attached to a `Persona` the user can read (public, owned,
      or directly shared via `Persona.users`).
    - `ChatMessage.files` of a session the user owns or that is shared as
      `ChatSessionSharedStatus.PUBLIC`.
    - A chat output file (`CHAT_OUTPUT_FILE_ORIGINS`: generated images and
      published files) whose stamped chat session the user may read (owned,
      or shared as `PUBLIC`). The stamp grants nothing on other origins.
    - `Document` whose ACL grants access (covers connector-ingested files).

    TODO(auth-perf): split `/chat/file` into per-asset-class endpoints so the
    URL carries the access context and one indexed lookup suffices, instead
    of fanning out 4–5 queries across unrelated classes on every request.
    """
    if user_owns_user_file(db_session, file_id, user.id):
        return True

    if user_can_access_persona_attached_file(db_session, file_id, user.id):
        return True

    if user_can_access_chat_message_file(db_session, file_id, user.id):
        return True

    # Generated images never reach ChatMessage.files, a code-interpreter file
    # reaches it only when the reply cites the id, and a published file only
    # when its response is saved, so the stamp is the real access path for
    # them. Kept above the connector branch so previews hit a PK lookup.
    record = get_chat_output_file_row(db_session, file_id)
    if record is not None:
        origin, file_metadata = record
        raw_session_id = (
            file_metadata.get(CHAT_SESSION_ID_FILE_METADATA_KEY)
            if isinstance(file_metadata, dict)
            else None
        )
        if raw_session_id is None:
            # Generated images written before files were stamped with their
            # session.
            return origin == FileOrigin.CHAT_IMAGE_GEN
        try:
            chat_session_id = UUID(str(raw_session_id))
        except ValueError:
            return False
        return user_can_read_chat_session(db_session, chat_session_id, user.id)

    return _user_can_access_connector_file(file_id, user, db_session)


def _user_can_access_connector_file(
    file_id: str, user: User, db_session: Session
) -> bool:
    """Mirror retrieval-time ACL: grant access if any `Document` referencing
    `file_id` has an ACL the user satisfies.

    Two lookup paths:
    1. `Document.file_id == file_id` — fast path; set by most connectors
       and by tabular File-connector uploads.
    2. `Connector.connector_specific_config['file_locations']` — fallback
       for non-tabular File-connector uploads (which leave
       `Document.file_id=NULL`). Documents under one cc_pair share its
       ACL, so any one representative document answers the question.

    `FileRecord.file_origin` is deliberately not consulted: the stamp has
    varied across releases and any origin filter would either miss legacy
    files or sprawl.
    """
    document_ids: list[str] = get_document_ids_for_file(db_session, file_id)
    if not document_ids:
        document_ids = get_document_ids_from_file_connector_config(db_session, file_id)
    if not document_ids:
        return False

    user_acl = get_acl_for_user(user, db_session)
    doc_access = get_access_for_documents(document_ids, db_session)
    if get_cc_pair_access_mode(db_session) != CCPairAccessMode.ENFORCE:
        if not has_guarded_cc_pairs(db_session):
            return any(
                not user_acl.isdisjoint(access.to_acl())
                for access in doc_access.values()
            )
        # The old ACL rule, without guarded pairs that grant the user nothing
        # (see the OpenSearch restricted cc-pair guard).
        access_sets = get_cc_pair_access_sets_for_user(db_session, user)
        granting_cc_pair_ids = (
            access_sets.open_cc_pair_ids | access_sets.acl_cc_pair_ids
        )
        doc_id_to_cc_pair_ids = get_cc_pair_ids_for_documents(db_session, document_ids)
        for document_id, access in doc_access.items():
            cc_pair_ids = set(doc_id_to_cc_pair_ids.get(document_id, []))
            if not access_sets.hidden_restricted_cc_pair_ids.isdisjoint(
                cc_pair_ids
            ) and granting_cc_pair_ids.isdisjoint(cc_pair_ids):
                continue
            if not user_acl.isdisjoint(access.to_acl()):
                return True
        return False

    # The query-time cc-pair rule of the OpenSearch filter, applied in Python.
    access_sets = get_cc_pair_access_sets_for_user(db_session, user)
    doc_id_to_cc_pair_ids = get_cc_pair_ids_for_documents(db_session, document_ids)
    user_acl_without_groups = {
        entry
        for entry in user_acl
        if entry.startswith((USER_EMAIL_ACL_PREFIX, EXTERNAL_GROUP_ACL_PREFIX))
    }
    for document_id, access in doc_access.items():
        cc_pair_ids = set(doc_id_to_cc_pair_ids.get(document_id, []))
        if not cc_pair_ids:
            if not user_acl.isdisjoint(access.to_acl()):
                return True
            continue
        if not access_sets.open_cc_pair_ids.isdisjoint(cc_pair_ids):
            return True
        if not access_sets.acl_cc_pair_ids.isdisjoint(cc_pair_ids) and (
            access.is_public or not user_acl_without_groups.isdisjoint(access.to_acl())
        ):
            return True
    return False
