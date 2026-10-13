"""Artifact index DAL.

One mutable row per (session, path), upserted at turn end. The source revision
identifies changes that advance the version and owning turn.
Unchanged observations preserve both. Helpers flush and never commit,
the caller owns the transaction so rows land before the turn's terminal
event.
"""

from uuid import UUID

from sqlalchemy import case, desc, func, or_, select, update
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
    source_revision: str,
) -> Artifact:
    """Insert or update the row for (session, path).

    A changed source identity advances the owning turn and version, and clears
    the archive. Unchanged observations only refresh metadata. Restoring a
    deleted path counts as a new version even if its source identity matches.
    """
    changed = or_(
        Artifact.deleted,
        Artifact.source_revision.is_distinct_from(source_revision),
    )
    stmt = (
        pg_insert(Artifact)
        .values(
            session_id=session_id,
            type=artifact_type,
            path=path,
            name=name,
            turn_index=turn_index,
            size_bytes=size_bytes,
            source_revision=source_revision,
            version=1,
            deleted=False,
        )
        .on_conflict_do_update(
            index_elements=[Artifact.session_id, Artifact.path],
            set_={
                "type": artifact_type,
                "name": name,
                "turn_index": case((changed, turn_index), else_=Artifact.turn_index),
                "size_bytes": size_bytes,
                "source_revision": source_revision,
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


def get_output_card_rows(db_session: Session, *, session_id: UUID) -> list[Artifact]:
    """Read card metadata without waking the sandbox."""
    return list(
        db_session.scalars(
            select(Artifact)
            .where(Artifact.session_id == session_id, Artifact.turn_index.is_not(None))
            .order_by(Artifact.turn_index, Artifact.path)
        )
    )


def mark_output_viewed(
    db_session: Session,
    *,
    session_id: UUID,
    artifact_id: UUID,
    revision: int,
) -> Artifact | None:
    artifact = db_session.scalar(
        select(Artifact)
        .where(Artifact.id == artifact_id, Artifact.session_id == session_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if artifact is None or artifact.turn_index is None:
        return None
    if revision > artifact.version:
        raise ValueError("Output revision is newer than the current file")
    statement = (
        update(Artifact)
        .where(Artifact.id == artifact_id)
        .values(
            viewed_revision=func.greatest(Artifact.viewed_revision, revision),
            # Opening a file does not change its last modification time.
            updated_at=Artifact.updated_at,
        )
        .returning(Artifact)
        .execution_options(populate_existing=True)
    )
    return db_session.execute(statement).scalar_one()


def mark_outputs_viewed(
    db_session: Session,
    *,
    session_id: UUID,
    revisions: dict[UUID, int],
) -> list[Artifact]:
    """Acknowledge only supplied revisions; concurrent edits stay unread."""
    if not revisions:
        return []
    # Lock before validating so the complete request succeeds or fails together.
    rows = db_session.execute(
        select(Artifact.id, Artifact.version)
        .where(
            Artifact.session_id == session_id,
            Artifact.id.in_(revisions),
            Artifact.turn_index.is_not(None),
            Artifact.deleted.is_(False),
        )
        .order_by(Artifact.id)
        .with_for_update()
    ).all()
    if any(revisions[artifact_id] > version for artifact_id, version in rows):
        raise ValueError("Output revision is newer than the current file")
    if not rows:
        return []
    viewed = case(revisions, value=Artifact.id)
    return list(
        db_session.scalars(
            update(Artifact)
            .where(
                Artifact.session_id == session_id,
                Artifact.id.in_([artifact_id for artifact_id, _ in rows]),
            )
            .values(
                viewed_revision=func.greatest(Artifact.viewed_revision, viewed),
                updated_at=Artifact.updated_at,
            )
            .returning(Artifact)
            .execution_options(populate_existing=True, synchronize_session=False)
        )
    )
