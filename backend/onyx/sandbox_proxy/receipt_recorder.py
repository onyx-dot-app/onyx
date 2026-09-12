"""Records receipts for egress actions at the proxy.

A receipt is the user-facing proof of an external side effect: written PENDING
before the action executes, finalized from the proxy's response and error
hooks, swept to UNKNOWN when orphaned (a finalize landing after the sweep is
dropped, so a response outliving the ten-minute TTL records UNKNOWN).
Write-effect catalog actions always leave one, and so does anything that went
through an approval. Reads that auto-pass leave nothing. Multi-request
provider flows each leave their own receipt until the extractor PR derives
operation keys, so ``insert_pending_receipt`` coalesces nothing yet.

Recording and finalizing announce the row to the session's live SSE stream,
best-effort: the receipt listing is the durable record, so a lost announce
loses nothing.
"""

from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError

from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ActionEffect, ReceiptStatus
from onyx.db.gated_app import get_or_create_gated_app_id
from onyx.db.models import ActionReceipt
from onyx.external_apps.matching.engine import AllMatchedActions, MatchedAction
from onyx.server.features.build.db.receipt import (
    finalize_receipt,
    insert_pending_receipt,
)
from onyx.server.features.build.packets import ReceiptPacket
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ANNOUNCE_TTL_S = 60


def _announce_key(session_id: UUID) -> str:
    return f"craft:receipt:announce:{session_id}"


def announce_receipts(
    session_id: UUID, packets: list[ReceiptPacket], cache: CacheBackend
) -> None:
    """Hand receipt transitions to the SSE stream attached to this session."""
    if not packets:
        return
    key = _announce_key(session_id)
    for packet in packets:
        cache.rpush(key, packet.model_dump_json())
    cache.expire(key, _ANNOUNCE_TTL_S)


def pop_receipt_announcement(
    session_id: UUID, timeout_s: int, cache: CacheBackend
) -> ReceiptPacket | None:
    """BLPOP one announced receipt. None on timeout or unparseable payload."""
    result = cache.blpop([_announce_key(session_id)], timeout_s)
    if result is None:
        return None
    _key, value = result
    if isinstance(value, bytes):
        value = value.decode()
    try:
        return ReceiptPacket.model_validate_json(value)
    except ValidationError:
        logger.warning("receipt: unparseable announce %r for %s", value, session_id)
        return None


def receipt_worthy_actions(
    matched_actions: AllMatchedActions, approval_id: UUID | None
) -> list[MatchedAction]:
    """The actions this request must leave receipts for.

    Every write-effect action gets its own receipt. A request with no write
    actions still gets one for its governing action when the user approved
    it, so approved reads stay visible in the activity record.
    """
    writes = [
        action
        for action in matched_actions.actions
        if action.effect is ActionEffect.WRITE
    ]
    if writes:
        return writes
    if approval_id is not None:
        return [matched_actions.governing_action]
    return []


def record_pending_receipts(
    *,
    tenant_id: str,
    session_id: UUID,
    matched_actions: AllMatchedActions,
    approval_id: UUID | None,
    cache_factory: Callable[[str], CacheBackend],
) -> list[UUID]:
    """Insert PENDING rows for this request, announce them, return their ids.

    Called after the gate's verdict and credential injection, immediately
    before the request leaves for the origin, so the record exists even when
    the proxy dies mid-flight (the sweep then marks it UNKNOWN).
    """
    actions = receipt_worthy_actions(matched_actions, approval_id)
    if not actions:
        return []
    target = matched_actions.target
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        gated_app_id = get_or_create_gated_app_id(db, target.kind, target.id)
        rows = [
            insert_pending_receipt(
                db,
                session_id=session_id,
                action_type=action.action_type,
                effect=action.effect.value,
                destination=matched_actions.app_name,
                gated_app_id=gated_app_id,
                approval_id=approval_id,
                operation_key=None,
            )
            for action in actions
        ]
        db.commit()
        receipt_ids = [row.id for row in rows]
        packets = [_packet_for(row) for row in rows]
    _announce_best_effort(tenant_id, session_id, packets, cache_factory)
    return receipt_ids


def finalize_receipts(
    *,
    tenant_id: str,
    session_id: UUID,
    receipt_ids: list[UUID],
    status: ReceiptStatus,
    cache_factory: Callable[[str], CacheBackend],
) -> None:
    """Move recorded rows to their terminal state and announce the outcome.

    Only rows that carry the requested verdict announce: a row that lost the
    race to an earlier verdict already announced that one.
    """
    packets: list[ReceiptPacket] = []
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        for receipt_id in receipt_ids:
            row = finalize_receipt(db, receipt_id=receipt_id, status=status)
            if row is not None and row.status is status:
                packets.append(_packet_for(row))
        db.commit()
    _announce_best_effort(tenant_id, session_id, packets, cache_factory)


def _announce_best_effort(
    tenant_id: str,
    session_id: UUID,
    packets: list[ReceiptPacket],
    cache_factory: Callable[[str], CacheBackend],
) -> None:
    """The cache backend is built in here so cache trouble of any kind costs
    an announce, never the recorded row."""
    if not packets:
        return
    try:
        announce_receipts(session_id, packets, cache_factory(tenant_id))
    except Exception:
        logger.warning(
            "receipt_announce_error session=%s count=%d",
            session_id,
            len(packets),
            exc_info=True,
        )


def _packet_for(row: ActionReceipt) -> ReceiptPacket:
    return ReceiptPacket(
        receipt_id=row.id,
        session_id=row.session_id,
        action_type=row.action_type,
        effect=row.effect,
        destination=row.destination,
        link=row.link,
        status=row.status,
        created_at=row.created_at,
    )
