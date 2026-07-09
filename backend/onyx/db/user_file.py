import datetime
from uuid import UUID

from sqlalchemy import exists
from sqlalchemy import func
from sqlalchemy import select
from sqlalchemy import update
from sqlalchemy.orm import joinedload
from sqlalchemy.orm import selectinload
from sqlalchemy.orm import Session

from onyx.db.enums import UserFileStatus
from onyx.db.models import Persona
from onyx.db.models import Project__UserFile
from onyx.db.models import User
from onyx.db.models import UserFile


def fetch_chunk_counts_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> list[tuple[str, int]]:
    """
    Return a list of (user_file_id, chunk_count) tuples.
    If a user_file_id is not found in the database, it will be returned with a chunk_count of 0.
    """
    stmt = select(UserFile.id, UserFile.chunk_count).where(
        UserFile.id.in_(user_file_ids)
    )

    results = db_session.execute(stmt).all()

    # Create a dictionary of user_file_id to chunk_count
    chunk_counts = {str(row.id): row.chunk_count or 0 for row in results}

    # Return a list of tuples, preserving `None` for documents not found or with
    # an unknown chunk count. Callers should handle the `None` case and fall
    # back to an existence check against the vector DB if necessary.
    return [
        (user_file_id, chunk_counts.get(user_file_id, 0))
        for user_file_id in user_file_ids
    ]


def calculate_user_files_token_count(file_ids: list[UUID], db_session: Session) -> int:
    """Calculate total token count for specified files"""
    total_tokens = 0

    # Get tokens from individual files
    if file_ids:
        file_tokens = (
            db_session.query(func.sum(UserFile.token_count))
            .filter(UserFile.id.in_(file_ids))
            .scalar()
            or 0
        )
        total_tokens += file_tokens

    return total_tokens


def fetch_user_project_ids_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, list[int]]:
    """Fetch user project ids for specified user files"""
    user_file_uuid_ids = [UUID(user_file_id) for user_file_id in user_file_ids]
    stmt = select(Project__UserFile.user_file_id, Project__UserFile.project_id).where(
        Project__UserFile.user_file_id.in_(user_file_uuid_ids)
    )
    rows = db_session.execute(stmt).all()

    user_file_id_to_project_ids: dict[str, list[int]] = {
        user_file_id: [] for user_file_id in user_file_ids
    }
    for user_file_id, project_id in rows:
        user_file_id_to_project_ids[str(user_file_id)].append(project_id)

    return user_file_id_to_project_ids


def fetch_persona_ids_for_user_files(
    user_file_ids: list[str],
    db_session: Session,
) -> dict[str, list[int]]:
    """Fetch persona (assistant) ids for specified user files."""
    stmt = (
        select(UserFile)
        .where(UserFile.id.in_(user_file_ids))
        .options(selectinload(UserFile.assistants))
    )
    results = db_session.execute(stmt).scalars().all()
    return {
        str(user_file.id): [persona.id for persona in user_file.assistants]
        for user_file in results
    }


def update_last_accessed_at_for_user_files(
    user_file_ids: list[UUID],
    db_session: Session,
) -> None:
    """Update `last_accessed_at` to now (UTC) for the given user files."""
    if not user_file_ids:
        return
    now = datetime.datetime.now(datetime.timezone.utc)
    (
        db_session.query(UserFile)
        .filter(UserFile.id.in_(user_file_ids))
        .update({UserFile.last_accessed_at: now}, synchronize_session=False)
    )
    db_session.commit()


def get_file_id_by_user_file_id(user_file_id: str, db_session: Session) -> str | None:
    """Resolve a `UserFile.id` to its underlying `FileRecord.file_id`.

    Returns None when the input is not a known `UserFile.id` (e.g. when the
    caller is already passing a storage `file_id`), so the caller can fall
    through to a direct file-store lookup.
    """
    user_file = db_session.query(UserFile).filter(UserFile.id == user_file_id).first()
    if user_file:
        return user_file.file_id
    return None


def get_file_ids_by_user_file_ids(
    user_file_ids: list[UUID], db_session: Session
) -> list[str]:
    user_files = db_session.query(UserFile).filter(UserFile.id.in_(user_file_ids)).all()
    return [user_file.file_id for user_file in user_files]


def fetch_user_files_with_access_relationships(
    user_file_ids: list[str],
    db_session: Session,
    eager_load_groups: bool = False,
) -> list[UserFile]:
    """Fetch user files with the owner and assistant relationships
    eagerly loaded (needed for computing access control).

    When eager_load_groups is True, Persona.groups is also loaded so that
    callers can extract user-group names without a second DB round-trip."""
    persona_sub_options = [
        selectinload(Persona.users),
        selectinload(Persona.user),
    ]
    if eager_load_groups:
        persona_sub_options.append(selectinload(Persona.groups))

    return (
        db_session.query(UserFile)
        .options(
            joinedload(UserFile.user),
            selectinload(UserFile.assistants).options(*persona_sub_options),
        )
        .filter(UserFile.id.in_(user_file_ids))
        .all()
    )


# Port scope helpers. The port threads document ids as `str` (a user file's doc id is
# `str(UserFile.id)`), so these accept/return `str` and convert to UUID for the query;
# ordering is by UUID value and every bound converts the same way.


def fetch_port_scope_user_ids(db_session: Session) -> list[UUID]:
    """Users with at least one COMPLETED file — the port scheduler's work list, one
    scope per user (switchover-agnostic: users have no paused concept)."""
    return [
        user_id
        for user_id in db_session.scalars(
            select(UserFile.user_id)
            .where(UserFile.status == UserFileStatus.COMPLETED)
            .distinct()
        )
        if user_id is not None
    ]


def get_user_file_ids_for_user_batch(
    db_session: Session,
    user_id: UUID,
    after_id: str | None,
    limit: int,
    up_to_id: str | None,
) -> list[str]:
    """One ascending cursor page of a user's COMPLETED file ids for the port copy.
    `up_to_id` (the snapshot max id at attempt creation) bounds the scan so the attempt
    terminates and covers every file COMPLETED as of creation (all have id <= max). Ids
    are random UUIDs, not creation-ordered, so a file that completes later with id <=
    up_to may also be picked up — harmless (create-only write); guaranteeing mid-run
    files reach FUTURE is the dual-write's job, not this bound."""
    stmt = select(UserFile.id).where(
        UserFile.user_id == user_id,
        UserFile.status == UserFileStatus.COMPLETED,
    )
    if after_id is not None:
        stmt = stmt.where(UserFile.id > UUID(after_id))
    if up_to_id is not None:
        stmt = stmt.where(UserFile.id <= UUID(up_to_id))
    stmt = stmt.order_by(UserFile.id).limit(limit)
    return [str(uf_id) for uf_id in db_session.scalars(stmt)]


def get_max_user_file_id_for_user(db_session: Session, user_id: UUID) -> str | None:
    """The greatest COMPLETED file id for a user — the attempt's snapshot upper bound."""
    max_id = db_session.scalar(
        select(UserFile.id)
        .where(
            UserFile.user_id == user_id,
            UserFile.status == UserFileStatus.COMPLETED,
        )
        .order_by(UserFile.id.desc())
        .limit(1)
    )
    return str(max_id) if max_id is not None else None


def filter_existing_user_file_ids(
    db_session: Session, user_id: UUID, ids: list[str]
) -> set[str]:
    """The subset of `ids` still COMPLETED for this user — the survival filter the port
    applies before its create-only write so a file deleted mid-run isn't resurrected."""
    if not ids:
        return set()
    rows = db_session.scalars(
        select(UserFile.id).where(
            UserFile.user_id == user_id,
            UserFile.status == UserFileStatus.COMPLETED,
            UserFile.id.in_([UUID(i) for i in ids]),
        )
    )
    return {str(uf_id) for uf_id in rows}


def user_file_port_scope_active(db_session: Session, user_id: UUID) -> bool:
    """True while the user still exists — the user-scope analog of the cc_pair
    DELETING liveness guard. A hard-deleted user CASCADE-drops its port attempts, so
    this is a fast pre-check; per-file deletions are handled by the survival filter."""
    return db_session.get(User, user_id) is not None


def mark_user_file_reconcile_pending(db_session: Session, user_file_id: UUID) -> None:
    """Flag FUTURE as stale/missing for this file (deferred ACL or missing content).
    Owned by the sync/index path, never the port."""
    db_session.execute(
        update(UserFile)
        .where(UserFile.id == user_file_id)
        .values(secondary_reconcile_pending=True)
    )
    db_session.commit()


def clear_user_file_reconcile_pending(db_session: Session, user_file_id: UUID) -> None:
    """Clear the flag once FUTURE matches PRESENT. Owned by the reconciler."""
    db_session.execute(
        update(UserFile)
        .where(UserFile.id == user_file_id)
        .values(secondary_reconcile_pending=False)
    )
    db_session.commit()


def count_user_files_reconcile_pending(db_session: Session) -> int:
    """Count of user files whose FUTURE copy hasn't reconciled yet (swap progress)."""
    return db_session.execute(
        select(func.count()).where(UserFile.secondary_reconcile_pending.is_(True))
    ).scalar_one()


def any_user_file_reconcile_pending_for_users(
    db_session: Session, user_ids: list[UUID]
) -> bool:
    """Swap-gate check: any un-reconciled COMPLETED file among the port's users? Scoped to
    required_user_ids like the connector flag's required_cc_pairs. COMPLETED-only because only
    those are drainable — a flag stuck on a non-COMPLETED row must not wedge the swap."""
    if not user_ids:
        return False
    return bool(
        db_session.scalar(
            select(
                exists().where(
                    UserFile.user_id.in_(user_ids),
                    UserFile.status == UserFileStatus.COMPLETED,
                    UserFile.secondary_reconcile_pending.is_(True),
                )
            )
        )
    )
