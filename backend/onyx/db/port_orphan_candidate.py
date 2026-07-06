"""Tracking of docs deleted mid-port so a delete that races the reindex port isn't left
resurrected in the target index — the port's create-only write can't tell a just-deleted
chunk from a never-written one, so a copy landing after the delete re-adds the doc (which
then has no Postgres row and is never cleaned up). The port marks its writes; the sweep
deletes only those marked chunks for a recorded doc. See
docs/plans/reindexing/deleted-doc-resurrection-during-port.md.
"""

from sqlalchemy import delete
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.document import get_cc_pairs_for_document
from onyx.db.models import PortOrphanCandidate
from onyx.db.models import SearchSettings


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
    cc_pair_id: int,
    document_ids: list[str],
) -> None:
    """Record docs deleted while a port targets `search_settings_id`. Idempotent; caller
    commits before the index delete so the candidate is durable before any resurrection."""
    if not document_ids:
        return
    stmt = pg_insert(PortOrphanCandidate).values(
        [
            {
                "search_settings_id": search_settings_id,
                "cc_pair_id": cc_pair_id,
                "document_id": document_id,
            }
            for document_id in document_ids
        ]
    )
    stmt = stmt.on_conflict_do_nothing(
        index_elements=["search_settings_id", "cc_pair_id", "document_id"]
    )
    db_session.execute(stmt)


def record_port_orphan_candidates_for_document(
    db_session: Session,
    document_id: str,
    primary: SearchSettings,
    secondary: SearchSettings | None,
) -> int:
    """Record a candidate under each cc_pair owning `document_id`, if a port is active.
    The single choke point every index-delete entry point (connector cleanup, ingestion)
    funnels through. Returns rows recorded; caller commits (if > 0) before the index delete."""
    target_settings_id = port_target_settings_id(primary, secondary)
    if target_settings_id is None:
        return 0
    cc_pairs = get_cc_pairs_for_document(db_session, document_id)
    for cc_pair in cc_pairs:
        record_port_orphan_candidates(
            db_session, target_settings_id, cc_pair.id, [document_id]
        )
    return len(cc_pairs)


def delete_port_orphan_candidates_for_document(
    db_session: Session,
    document_id: str,
) -> None:
    """Drop a document's candidate rows — rolls back recording when the delete fails and
    the doc stays live, so the sweep doesn't treat the live doc's marked chunks as a
    resurrection. Caller commits."""
    db_session.execute(
        delete(PortOrphanCandidate).where(
            PortOrphanCandidate.document_id == document_id
        )
    )


def get_port_orphan_candidate_doc_ids(
    db_session: Session,
    search_settings_id: int,
    cc_pair_id: int,
) -> list[str]:
    """The sweep's work list for one cc_pair."""
    return list(
        db_session.scalars(
            select(PortOrphanCandidate.document_id).where(
                PortOrphanCandidate.search_settings_id == search_settings_id,
                PortOrphanCandidate.cc_pair_id == cc_pair_id,
            )
        )
    )


def clear_port_orphan_candidates(
    db_session: Session,
    search_settings_id: int,
    cc_pair_id: int,
    document_ids: list[str],
) -> None:
    """Delete exactly the swept ids (not the whole scope), so a candidate recorded during
    the sweep isn't dropped unswept."""
    if not document_ids:
        return
    db_session.execute(
        delete(PortOrphanCandidate).where(
            PortOrphanCandidate.search_settings_id == search_settings_id,
            PortOrphanCandidate.cc_pair_id == cc_pair_id,
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
