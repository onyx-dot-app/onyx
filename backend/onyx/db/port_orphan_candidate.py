"""Tracking of docs deleted mid-port so a delete that races the reindex port isn't left
resurrected in the target index — the port's create-only write can't tell a just-deleted
chunk from a never-written one, so a copy landing after the delete re-adds the doc (which
then has no Postgres row and is never cleaned up). The port marks its writes; the sweep
deletes only those marked chunks for a recorded doc. See
docs/plans/reindexing/deleted-doc-resurrection-during-port.md.
"""

from uuid import UUID

from sqlalchemy import ColumnElement
from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.document import get_cc_pairs_for_document
from onyx.db.models import PortOrphanCandidate
from onyx.db.models import SearchSettings


def _require_one_scope(cc_pair_id: int | None, port_user_id: UUID | None) -> None:
    if (cc_pair_id is None) == (port_user_id is None):
        raise ValueError("exactly one of cc_pair_id / port_user_id must be set")


def _scope_filter(
    cc_pair_id: int | None, port_user_id: UUID | None
) -> ColumnElement[bool]:
    _require_one_scope(cc_pair_id, port_user_id)
    if cc_pair_id is not None:
        return PortOrphanCandidate.cc_pair_id == cc_pair_id
    return PortOrphanCandidate.port_user_id == port_user_id


def port_target_settings_id(
    primary: SearchSettings,
    secondary: SearchSettings | None,
) -> int | None:
    """The settings id a port currently targets, or None. Reindex targets the FUTURE
    (secondary.use_port_flow); INSTANT backfills the promoted live PRESENT
    (primary.port_backfill_source_id). Mirrors _resolve_port_target_settings."""
    if secondary is not None and secondary.use_port_flow:
        return secondary.id
    if primary.use_port_flow and primary.port_backfill_source_id is not None:
        return primary.id
    return None


def record_port_orphan_candidates(
    db_session: Session,
    search_settings_id: int,
    cc_pair_id: int | None,
    document_ids: list[str],
    *,
    port_user_id: UUID | None = None,
) -> list[int]:
    """Record docs deleted while a port targets `search_settings_id`, under exactly one
    scope. Idempotent; returns the ids of the rows this call actually inserted (empty when
    a row already existed), so a failed delete rolls back exactly its own recording. Caller
    commits before the index delete so the candidate is durable before any resurrection."""
    if not document_ids:
        return []
    _require_one_scope(cc_pair_id, port_user_id)
    scope_col = "cc_pair_id" if cc_pair_id is not None else "port_user_id"
    scope_val = cc_pair_id if cc_pair_id is not None else port_user_id
    stmt = (
        pg_insert(PortOrphanCandidate)
        .values(
            [
                {
                    "search_settings_id": search_settings_id,
                    scope_col: scope_val,
                    "document_id": document_id,
                }
                for document_id in document_ids
            ]
        )
        .on_conflict_do_nothing(
            # Infer the matching per-scope partial-unique index.
            index_elements=["search_settings_id", scope_col, "document_id"],
            index_where=text(f"{scope_col} IS NOT NULL"),
        )
        .returning(PortOrphanCandidate.id)
    )
    return list(db_session.scalars(stmt))


def record_port_orphan_candidates_for_document(
    db_session: Session,
    document_id: str,
    primary: SearchSettings,
    secondary: SearchSettings | None,
) -> list[int]:
    """Record a candidate under each cc_pair owning `document_id`, if a port is active.
    The single choke point every index-delete entry point (connector cleanup, ingestion)
    funnels through. Returns the ids of the rows this call inserted (empty when none), so a
    failed delete rolls back only its own recording — never a candidate another cc_pair or
    delete path recorded for the same doc. Caller commits (if non-empty) before the index
    delete."""
    target_settings_id = port_target_settings_id(primary, secondary)
    if target_settings_id is None:
        return []
    recorded_ids: list[int] = []
    for cc_pair in get_cc_pairs_for_document(db_session, document_id):
        recorded_ids += record_port_orphan_candidates(
            db_session, target_settings_id, cc_pair.id, [document_id]
        )
    return recorded_ids


def record_port_orphan_candidates_for_user_file(
    db_session: Session,
    port_user_id: UUID,
    document_id: str,
    primary: SearchSettings,
    secondary: SearchSettings | None,
) -> list[int]:
    """User-file analog of _for_document: record the deleted file under its user scope
    if a port is active. User files have no cc_pair, so the _for_document recorder (keyed
    on get_cc_pairs_for_document) never covers them — this is their choke point. Caller
    commits before the index delete."""
    target_settings_id = port_target_settings_id(primary, secondary)
    if target_settings_id is None:
        return []
    return record_port_orphan_candidates(
        db_session,
        target_settings_id,
        None,
        [document_id],
        port_user_id=port_user_id,
    )


def delete_port_orphan_candidates_by_id(
    db_session: Session,
    candidate_ids: list[int],
) -> None:
    """Drop exactly the given candidate rows — rolls back a failed delete's own recording
    (the rows it inserted) when the doc stays live, so the sweep doesn't treat the live doc's
    marked chunks as a resurrection. Scoped by id so it never removes a candidate another
    cc_pair or delete path recorded for the same document. Caller commits."""
    if not candidate_ids:
        return
    db_session.execute(
        delete(PortOrphanCandidate).where(PortOrphanCandidate.id.in_(candidate_ids))
    )


def get_port_orphan_candidate_doc_ids(
    db_session: Session,
    search_settings_id: int,
    cc_pair_id: int | None,
    *,
    port_user_id: UUID | None = None,
) -> list[str]:
    """The sweep's work list for one scope."""
    return list(
        db_session.scalars(
            select(PortOrphanCandidate.document_id).where(
                PortOrphanCandidate.search_settings_id == search_settings_id,
                _scope_filter(cc_pair_id, port_user_id),
            )
        )
    )


def clear_port_orphan_candidates(
    db_session: Session,
    search_settings_id: int,
    cc_pair_id: int | None,
    document_ids: list[str],
    *,
    port_user_id: UUID | None = None,
) -> None:
    """Delete exactly the swept ids (not the whole scope), so a candidate recorded during
    the sweep isn't dropped unswept."""
    if not document_ids:
        return
    db_session.execute(
        delete(PortOrphanCandidate).where(
            PortOrphanCandidate.search_settings_id == search_settings_id,
            _scope_filter(cc_pair_id, port_user_id),
            PortOrphanCandidate.document_id.in_(document_ids),
        )
    )


def cleanup_stale_port_orphan_candidates(
    db_session: Session,
    active_target_settings_id: int | None,
) -> int:
    """Drop candidate rows for any settings that is no longer the port target (all rows
    when None). Runs each check_for_port tick to GC a superseded / FAILED port that never
    reached the backstop (the FK cascades only fire on settings/cc_pair deletion). Returns
    rows deleted."""
    query = db_session.query(PortOrphanCandidate)
    if active_target_settings_id is not None:
        query = query.filter(
            PortOrphanCandidate.search_settings_id != active_target_settings_id
        )
    deleted = query.delete(synchronize_session=False)
    db_session.commit()
    return deleted
