"""Queries behind the access decisions in `onyx.access.access`."""

from uuid import UUID

from sqlalchemy import and_, or_, select
from sqlalchemy import cast as sa_cast
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from onyx.configs.constants import CHAT_OUTPUT_FILE_ORIGINS, FileOrigin
from onyx.db.models import (
    ChatArtifact,
    ChatArtifactVersion,
    ChatMessage,
    ChatSession,
    ChatSessionSharedStatus,
    Connector,
    Document,
    DocumentByConnectorCredentialPair,
    FileRecord,
    Persona,
    Persona__User,
    Persona__UserFile,
    UserFile,
)
from onyx.utils.special_types import JSON_ro


def user_owns_user_file(db_session: Session, file_id: str, user_id: UUID) -> bool:
    return bool(
        db_session.query(
            select(UserFile.id)
            .where(UserFile.file_id == file_id, UserFile.user_id == user_id)
            .exists()
        ).scalar()
    )


def user_can_access_persona_attached_file(
    db_session: Session, file_id: str, user_id: UUID
) -> bool:
    """Return True if `file_id` belongs to a `UserFile` attached to a
    `Persona` the user can read (public, owned, or directly shared via
    `Persona.users`).
    """
    stmt = (
        select(UserFile.id)
        .join(Persona__UserFile, Persona__UserFile.user_file_id == UserFile.id)
        .join(Persona, Persona.id == Persona__UserFile.persona_id)
        .outerjoin(
            Persona__User,
            (Persona__User.persona_id == Persona.id)
            & (Persona__User.user_id == user_id),
        )
        .where(
            UserFile.file_id == file_id,
            Persona.deleted.is_(False),
            or_(
                Persona.is_public.is_(True),
                Persona.user_id == user_id,
                Persona__User.user_id.is_not(None),
            ),
        )
        .limit(1)
    )
    return db_session.execute(stmt).first() is not None


def user_can_access_chat_message_file(
    db_session: Session, file_id: str, user_id: UUID
) -> bool:
    """Return True if `file_id` is in `ChatMessage.files` of a session the
    user owns or that is shared as `ChatSessionSharedStatus.PUBLIC`.
    """
    chat_file_stmt = (
        select(ChatMessage.id)
        .join(ChatSession, ChatMessage.chat_session_id == ChatSession.id)
        .where(ChatSession.spawned_by_message_id.is_(None))
        .where(ChatMessage.files.op("@>")([{"id": file_id}]))
        .where(
            or_(
                ChatSession.user_id == user_id,
                and_(
                    ChatSession.shared_status == ChatSessionSharedStatus.PUBLIC,
                    ChatSession.deleted.is_(False),
                ),
            )
        )
        .limit(1)
    )
    return db_session.execute(chat_file_stmt).first() is not None


def get_chat_output_file_row(
    db_session: Session, file_id: str
) -> tuple[FileOrigin, JSON_ro, UUID | None] | None:
    """The origin, metadata and artifact's chat of a chat output file
    (`CHAT_OUTPUT_FILE_ORIGINS`); None for any other file. A published file
    and its thumbnail reach the chat through their version's artifact. The
    metadata itself can be NULL."""
    return (
        db_session.execute(
            select(
                FileRecord.file_origin,
                FileRecord.file_metadata,
                ChatArtifact.chat_session_id,
            )
            .select_from(FileRecord)
            # On the literal, so each column's unique index serves the match.
            .outerjoin(
                ChatArtifactVersion,
                or_(
                    ChatArtifactVersion.file_id == file_id,
                    ChatArtifactVersion.thumbnail_file_id == file_id,
                ),
            )
            .outerjoin(ChatArtifact, ChatArtifact.id == ChatArtifactVersion.artifact_id)
            .where(
                FileRecord.file_id == file_id,
                FileRecord.file_origin.in_(CHAT_OUTPUT_FILE_ORIGINS),
            )
        )
        .tuples()
        .first()
    )


def user_can_read_chat_session(
    db_session: Session, chat_session_id: UUID, user_id: UUID
) -> bool:
    """Return True if the user owns the session or it is shared as
    `ChatSessionSharedStatus.PUBLIC`.
    """
    stmt = (
        select(ChatSession.id)
        .where(ChatSession.id == chat_session_id)
        .where(
            or_(
                ChatSession.user_id == user_id,
                and_(
                    ChatSession.shared_status == ChatSessionSharedStatus.PUBLIC,
                    ChatSession.deleted.is_(False),
                ),
            )
        )
        .limit(1)
    )
    return db_session.execute(stmt).first() is not None


def get_document_ids_for_file(db_session: Session, file_id: str) -> list[str]:
    return list(
        db_session.execute(select(Document.id).where(Document.file_id == file_id))
        .scalars()
        .all()
    )


def get_document_ids_from_file_connector_config(
    db_session: Session, file_id: str
) -> list[str]:
    """Return one representative document per cc_pair (connector +
    credential) whose `Connector.connector_specific_config['file_locations']`
    lists `file_id`. Sampling per cc_pair (not per connector) is required
    because ACLs are scoped to the cc_pair: the same connector paired with
    different credentials can have different ACLs, and a user with access
    via one credential must not be denied because we sampled a doc from
    another.

    TODO(delete-me): exists only because the File connector leaves
    `Document.file_id=NULL` for non-tabular uploads (see comment in
    `onyx/connectors/file/connector.py`). The `@>` lookup also can't use
    a btree index, so every fast-path miss does a JSONB scan. Once the
    connector stamps `Document.file_id` unconditionally and a backfill
    runs, this helper and its caller branch can go away.
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
