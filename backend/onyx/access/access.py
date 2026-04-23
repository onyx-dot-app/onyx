from collections.abc import Callable
from typing import cast

from sqlalchemy import or_
from sqlalchemy import select
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
from onyx.db.models import Document
from onyx.db.models import FileRecord
from onyx.db.models import Persona
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


def _get_acl_for_user(
    user: User, db_session: Session  # noqa: ARG001
) -> set[str]:  # noqa: ARG001
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


def user_can_access_chat_file(file_id: str, user: User, db_session: Session) -> bool:
    """Return True if `user` is allowed to read the raw `file_id` served by
    `GET /chat/file/{file_id}`. Access is granted when any of:

    - The `file_id` is the storage id of a `UserFile` owned by the user.
    - The `file_id` is a persona avatar (`Persona.uploaded_image_id`); avatars
      are visible to any authenticated user.
    - The `file_id` appears in a `ChatMessage.files` descriptor of a chat
      session the user owns or a session publicly shared via
      `ChatSessionSharedStatus.PUBLIC`.
    - The `file_id` is the storage id of a connector-ingested document
      (`FileOrigin.CONNECTOR` or `FileOrigin.CONNECTOR_FILE_UPLOAD`) whose
      associated `Document` grants access to this user via the standard
      ACL. This allows users to preview cited files returned from indexed
      connector sources (e.g. the `File` connector, or admin-uploaded
      files via the connector upload API) through `PreviewModal`.
    - TODO: An CHAT_IMAGE_GEN file is uploaded to the file store before a
      tool call database entry is added. This the file is there and the FE can
      request it despite us not having the linking tool call. We currently
      hackily get around this by making these files public, but this will need
      to change with a larger refactor.
    """
    owns_user_file = db_session.query(
        select(UserFile.id)
        .where(UserFile.file_id == file_id, UserFile.user_id == user.id)
        .exists()
    ).scalar()
    if owns_user_file:
        return True

    # TODO: move persona avatars to a dedicated endpoint (e.g.
    # /assistants/{id}/avatar) so this branch can be removed. /chat/file is
    # currently overloaded with multiple asset classes (user files, chat
    # attachments, tool outputs, avatars), forcing this access-check fan-out.
    #
    # Restrict the avatar path to CHAT_UPLOAD-origin files so an attacker
    # cannot bind another user's USER_FILE (or any other origin) to their
    # own persona and read it through this check.
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

    if _user_can_access_connector_file(file_id, user, db_session):
        return True

    # TODO: Chat image generated images are currently public
    # We will want to make this private but it requires a larger
    # refactor.
    is_chat_image_gen = db_session.query(
        select(FileRecord.file_id)
        .where(
            FileRecord.file_id == file_id,
            FileRecord.file_origin == FileOrigin.CHAT_IMAGE_GEN,
        )
        .exists()
    ).scalar()
    return bool(is_chat_image_gen)


def _user_can_access_connector_file(
    file_id: str, user: User, db_session: Session
) -> bool:
    """Grant access when `file_id` corresponds to a connector-ingested file
    (`FileOrigin.CONNECTOR` or `FileOrigin.CONNECTOR_FILE_UPLOAD`) and the
    user's ACL overlaps the ACL of at least one `Document` that references
    that `file_id`. Mirrors the access-control layer applied during retrieval
    so preview access stays consistent with search result access."""
    is_connector_file = db_session.query(
        select(FileRecord.file_id)
        .where(
            FileRecord.file_id == file_id,
            FileRecord.file_origin.in_(
                [FileOrigin.CONNECTOR, FileOrigin.CONNECTOR_FILE_UPLOAD]
            ),
        )
        .exists()
    ).scalar()
    if not is_connector_file:
        return False

    document_ids = (
        db_session.execute(select(Document.id).where(Document.file_id == file_id))
        .scalars()
        .all()
    )
    if not document_ids:
        return False

    user_acl = get_acl_for_user(user, db_session)
    doc_access = get_access_for_documents(list(document_ids), db_session)
    return any(
        not user_acl.isdisjoint(access.to_acl()) for access in doc_access.values()
    )
