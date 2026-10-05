"""Artifact index DAL.

One mutable row per (session, path), upserted at turn end. Content-hash
comparison decides whether an upsert is a content change (version bump,
archive invalidated) or a metadata touch. Helpers flush and never commit,
the caller owns the transaction so rows land before the turn's terminal
event.
"""

from uuid import UUID

from sqlalchemy import case, desc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.enums import ArtifactType
from onyx.db.models import Artifact


def upsert_artifact(
    db_session: Session,
    *,
    session_id: UUID,
    artifact_type: ArtifactType,
    path: str,
    name: str,
    turn_index: int | None,
    size_bytes: int | None,
    content_hash: str | None,
) -> Artifact:
    """Insert or update the row for (session, path).

    A changed content hash bumps the version and clears the archive reference
    (the archived bytes no longer match). An unchanged hash only refreshes
    metadata. Either way the row is undeleted, a resurrected path is live
    again.
    """
    changed = Artifact.content_hash.is_distinct_from(content_hash)
    stmt = (
        pg_insert(Artifact)
        .values(
            session_id=session_id,
            type=artifact_type,
            path=path,
            name=name,
            turn_index=turn_index,
            size_bytes=size_bytes,
            content_hash=content_hash,
            version=1,
            deleted=False,
        )
        .on_conflict_do_update(
            index_elements=[Artifact.session_id, Artifact.path],
            set_={
                "type": artifact_type,
                "name": name,
                "turn_index": turn_index,
                "size_bytes": size_bytes,
                "content_hash": content_hash,
                "deleted": False,
                "version": case(
                    (changed, Artifact.version + 1), else_=Artifact.version
                ),
                "archive_file_id": case(
                    (changed, None), else_=Artifact.archive_file_id
                ),
                # ON CONFLICT bypasses the column's onupdate, so bump manually.
                "updated_at": func.now(),
            },
        )
        .returning(Artifact)
    )
    # populate_existing: the row changes via Core SQL, so an identity-map hit
    # must be refreshed rather than returned with stale attributes.
    return db_session.execute(
        select(Artifact).from_statement(stmt).execution_options(populate_existing=True)
    ).scalar_one()


def mark_artifact_deleted(
    db_session: Session,
    *,
    session_id: UUID,
    path: str,
) -> Artifact | None:
    """Flag the row for a path the manifest no longer contains."""
    artifact = db_session.scalar(
        select(Artifact).where(Artifact.session_id == session_id, Artifact.path == path)
    )
    if artifact is None or artifact.deleted:
        return artifact
    artifact.deleted = True
    db_session.flush()
    return artifact


def get_session_artifacts(
    db_session: Session,
    *,
    session_id: UUID,
    include_deleted: bool = False,
) -> list[Artifact]:
    query = select(Artifact).where(Artifact.session_id == session_id)
    if not include_deleted:
        query = query.where(Artifact.deleted.is_(False))
    return list(db_session.scalars(query.order_by(desc(Artifact.created_at))))
