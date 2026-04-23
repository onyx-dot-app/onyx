from collections.abc import Callable
from typing import cast

from sqlalchemy import cast as sa_cast
from sqlalchemy import or_
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import Session

from onyx.access.models import DocumentAccess
from onyx.access.utils import prefix_user_email
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.configs.constants import PUBLIC_DOC_PAT
from onyx.db.document import get_access_info_for_document
from onyx.db.document import get_access_info_for_documents
from onyx.db.models import ChatMessage
from onyx.db.models import ChatSession
from onyx.db.models import ChatSessionSharedStatus
from onyx.db.models import Connector
from onyx.db.models import DocumentByConnectorCredentialPair
from onyx.db.models import FileRecord
from onyx.db.models import Persona
from onyx.db.models import User
from onyx.db.models import UserFile
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
    user_files = (
        db_session.query(UserFile)
        .options(joinedload(UserFile.user))  # Eager load the user relationship
        .filter(UserFile.id.in_(user_file_ids))
        .all()
    )
    return {
        str(user_file.id): DocumentAccess.build(
            user_emails=[user_file.user.email] if user_file.user else [],
            user_groups=[],
            is_public=True if user_file.user is None else False,
            external_user_emails=[],
            external_user_group_ids=[],
        )
        for user_file in user_files
    }


def user_can_access_chat_file(file_id: str, user: User, db_session: Session) -> bool:
    """Return True if `user` can read `file_id` via `GET /chat/file/{file_id}`.

    The endpoint is overloaded across several asset classes, so we check
    each in turn (cheapest first, so common paths short-circuit before the
    JSONB scan in `_documents_from_file_connector_config`):

    - `UserFile` owned by the user.
    - `Persona.uploaded_image_id` (avatars are public to authenticated users).
    - `ChatMessage.files` of a session the user owns or that is shared as
      `ChatSessionSharedStatus.PUBLIC`.
    - `FileRecord` with origin `CHAT_IMAGE_GEN` (see inline TODO).
    - `Document` whose ACL grants access (covers connector-ingested files).

    TODO(auth-perf): split `/chat/file` into per-asset-class endpoints so the
    URL carries the access context and one indexed lookup suffices, instead
    of fanning out 4–5 queries across unrelated classes on every request.
    """
    owns_user_file = db_session.query(
        select(UserFile.id)
        .where(UserFile.file_id == file_id, UserFile.user_id == user.id)
        .exists()
    ).scalar()
    if owns_user_file:
        return True

    # TODO: move persona avatars to a dedicated endpoint so this branch
    # can go away. Restrict to CHAT_UPLOAD-origin for now so an attacker
    # cannot bind another user's USER_FILE to their persona and read it
    # through this check.
    is_persona_avatar = db_session.query(
        select(Persona.id)
        .join(FileRecord, FileRecord.file_id == Persona.uploaded_image_id)
        .where(
            Persona.uploaded_image_id == file_id,
            FileRecord.file_origin == FileOrigin.CHAT_UPLOAD,
        )
        .exists()
    ).scalar()
    if is_persona_avatar:
        return True

    chat_file_stmt = (
        select(ChatMessage.id)
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .where(ChatMessage.files.op("@>")([{"id": file_id}]))
        .where(
            or_(
                ChatSession.user_id == user.id,
                ChatSession.shared_status == ChatSessionSharedStatus.PUBLIC,
            )
        )
        .limit(1)
    )
    if db_session.execute(chat_file_stmt).first() is not None:
        return True

    # TODO: CHAT_IMAGE_GEN files are public because the bytes land in the
    # store before the linking tool-call row is written; tightening this
    # requires reordering the streaming/tool-call writes. Kept above the
    # connector branch so previews hit a PK lookup, not the JSONB scan.
    is_chat_image_gen = db_session.query(
        select(FileRecord.file_id)
        .where(
            FileRecord.file_id == file_id,
            FileRecord.file_origin == FileOrigin.CHAT_IMAGE_GEN,
        )
        .exists()
    ).scalar()
    if is_chat_image_gen:
        return True

    return _user_can_access_connector_file(file_id, user, db_session)


def _user_can_access_connector_file(
    file_id: str, user: User, db_session: Session
) -> bool:
    """Mirror retrieval-time ACL: grant access if any `Document` referencing
    `file_id` has an ACL the user satisfies.

    v3.0 covers only File-connector uploads via
    `Connector.connector_specific_config['file_locations']`. Other connector
    files (Google Drive / SharePoint / Confluence images) have no
    Postgres-level linkage from `file_id` to a document on this branch
    (`Document.file_id` does not exist until #10299), so previews of those
    still fail closed. Documents under one cc_pair share its ACL, so any
    one representative document answers the question.
    """
    document_ids = _documents_from_file_connector_config(file_id, db_session)
    if not document_ids:
        return False

    user_acl = get_acl_for_user(user, db_session)
    doc_access = get_access_for_documents(document_ids, db_session)
    return any(
        not user_acl.isdisjoint(access.to_acl()) for access in doc_access.values()
    )


def _documents_from_file_connector_config(
    file_id: str, db_session: Session
) -> list[str]:
    """Return one representative document per cc_pair (connector +
    credential) whose `Connector.connector_specific_config['file_locations']`
    lists `file_id`. Sampling per cc_pair (not per connector) is required
    because ACLs are scoped to the cc_pair: the same connector paired with
    different credentials can have different ACLs, and a user with access
    via one credential must not be denied because we sampled a doc from
    another.

    The `@>` lookup can't use a btree index, so every call is a JSONB scan.
    """
    cc_pair_keys = db_session.execute(
        select(
            DocumentByConnectorCredentialPair.connector_id,
            DocumentByConnectorCredentialPair.credential_id,
        )
        .join(
            Connector,
            Connector.id == DocumentByConnectorCredentialPair.connector_id,
        )
        .where(
            Connector.connector_specific_config["file_locations"].op("@>")(
                sa_cast([file_id], postgresql.JSONB)
            )
        )
        .distinct()
    ).all()
    if not cc_pair_keys:
        return []

    document_ids: list[str] = []
    for connector_id, credential_id in cc_pair_keys:
        doc_id = db_session.execute(
            select(DocumentByConnectorCredentialPair.id)
            .where(
                DocumentByConnectorCredentialPair.connector_id == connector_id,
                DocumentByConnectorCredentialPair.credential_id == credential_id,
            )
            .limit(1)
        ).scalar()
        if doc_id is not None:
            document_ids.append(doc_id)
    return document_ids
