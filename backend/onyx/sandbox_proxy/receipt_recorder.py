"""Records receipts for egress actions at the proxy.

A receipt is the user-facing proof of an external side effect: written PENDING
before the action executes, finalized from the proxy's response and error
hooks, swept to UNKNOWN when orphaned (a finalize landing after the sweep is
dropped, so a response outliving the ten-minute TTL records UNKNOWN).
Write-effect catalog actions always leave one, and so does anything that went
through an approval. Reads that auto-pass leave nothing. Multi-request
provider flows coalesce into one receipt through operation keys the
extractors derive: request-side where the step carries the id, response-side
where step one's response reveals it, and via a token map for the raw-bytes
step that carries neither.

Recording and finalizing announce the row to the session's live SSE stream,
best-effort: the receipt listing is the durable record, so a lost announce
loses nothing.
"""

from collections.abc import Callable
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.enums import ActionEffect, ReceiptStatus
from onyx.db.gated_app import get_or_create_gated_app_id
from onyx.db.models import ActionReceipt
from onyx.external_apps.matching.engine import AllMatchedActions, MatchedAction
from onyx.sandbox_proxy.receipt_extractors import (
    SLACK_UPLOAD_KEY_PREFIX,
    ResponseFacts,
    parse_json_object,
    request_facts,
    response_facts,
    slack_upload_key,
    slack_upload_url_token,
    upload_url_token,
)
from onyx.server.features.build.db.receipt import (
    finalize_receipt,
    insert_pending_receipt,
    set_receipt_operation_key,
)
from onyx.server.features.build.packets import ReceiptPacket
from onyx.utils.logger import setup_logger

logger = setup_logger()

_ANNOUNCE_TTL_S = 60
_MAX_DESTINATION_LEN = 256


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
    request_path: str = "",
    request_body: bytes | None = None,
) -> list[tuple[UUID, str]]:
    """Insert PENDING rows for this request and announce the new ones.

    Called after the gate's verdict and credential injection, immediately
    before the request leaves for the origin, so the record exists even when
    the proxy dies mid-flight (the sweep then marks it UNKNOWN). Returns
    ``(receipt_id, action_type)`` pairs for the flow's finalize hooks.
    """
    actions = receipt_worthy_actions(matched_actions, approval_id)
    if not actions:
        return []
    facts_by_action = [
        (action, request_facts(action.action_type, request_body)) for action in actions
    ]
    # Cache lookups stay outside the DB transaction.
    token_keys = [
        facts.operation_key
        or _upload_token_key(
            action.action_type, request_path, tenant_id, session_id, cache_factory
        )
        for action, facts in facts_by_action
    ]
    target = matched_actions.target
    entries: list[tuple[UUID, str]] = []
    packets: list[ReceiptPacket] = []
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        gated_app_id = get_or_create_gated_app_id(db, target.kind, target.id)
        for (action, facts), operation_key in zip(
            facts_by_action, token_keys, strict=True
        ):
            destination = (facts.destination or matched_actions.app_name)[
                :_MAX_DESTINATION_LEN
            ]
            row, created = insert_pending_receipt(
                db,
                session_id=session_id,
                action_type=action.action_type,
                effect=action.effect.value,
                destination=destination,
                gated_app_id=gated_app_id,
                approval_id=approval_id,
                operation_key=operation_key,
            )
            entries.append((row.id, action.action_type))
            if created:
                packets.append(_packet_for(row))
        db.commit()
    _announce_best_effort(tenant_id, session_id, packets, cache_factory)
    return entries


def finalize_recorded_flow(
    *,
    tenant_id: str,
    session_id: UUID,
    entries: list[tuple[UUID, str]],
    transport_status: ReceiptStatus,
    response_body: bytes | None,
    cache_factory: Callable[[str], CacheBackend],
) -> None:
    """Finalize a flow's receipts with whatever the response reveals.

    Each entry is ``(receipt_id, action_type)``. The extractor may refine the
    verdict (a provider error inside a 200), attach a deep link, and claim a
    late-learned coalescing key. Best-effort per receipt: a failure costs
    only that receipt's finalize, and the sweep covers whatever is left
    PENDING.
    """
    packets: list[ReceiptPacket] = []
    with get_session_with_tenant(tenant_id=tenant_id) as db:
        for receipt_id, action_type in entries:
            try:
                packet = _finalize_one(
                    db, receipt_id, action_type, transport_status, response_body
                )
            except Exception:
                logger.exception(
                    "receipt_finalize_error receipt=%s action_type=%s",
                    receipt_id,
                    action_type,
                )
                continue
            if packet is not None:
                packets.append(packet)
        db.commit()
    _announce_best_effort(tenant_id, session_id, packets, cache_factory)
    if response_body is not None:
        _remember_upload_tokens(
            tenant_id, session_id, entries, response_body, cache_factory
        )


def _finalize_one(
    db: Session,
    receipt_id: UUID,
    action_type: str,
    transport_status: ReceiptStatus,
    response_body: bytes | None,
) -> ReceiptPacket | None:
    facts = ResponseFacts()
    if response_body is not None:
        try:
            facts = response_facts(action_type, response_body)
        except Exception:
            logger.warning(
                "receipt_extract_error action_type=%s", action_type, exc_info=True
            )
    if facts.operation_key is not None:
        claimed = set_receipt_operation_key(
            db, receipt_id=receipt_id, operation_key=facts.operation_key
        )
        if not claimed:
            # The flow already coalesced onto another row. This one stays a
            # visible duplicate rather than being silently merged.
            logger.info(
                "receipt_operation_key_lost receipt=%s key=%s",
                receipt_id,
                facts.operation_key,
            )
    status = facts.status_override or transport_status
    row, changed = finalize_receipt(
        db,
        receipt_id=receipt_id,
        status=status,
        link=facts.link,
        allow_failed_downgrade=status is ReceiptStatus.FAILED,
    )
    if row is not None and changed:
        return _packet_for(row)
    return None


_UPLOAD_TOKEN_TTL_S = 30 * 60


def _upload_token_map_key(session_id: UUID, token: str) -> str:
    return f"craft:receipt:upload-token:{session_id}:{token}"


def _remember_upload_tokens(
    tenant_id: str,
    session_id: UUID,
    entries: list[tuple[UUID, str]],
    response_body: bytes,
    cache_factory: Callable[[str], CacheBackend],
) -> None:
    """Map a Slack upload URL token to its coalescing key, so the raw-bytes
    step of the flow (which carries only the token) lands on the same
    receipt. Best-effort."""
    if not any(a == "slack.files.write" for _r, a in entries):
        return
    body = parse_json_object(response_body)
    if body is None:
        return
    key = slack_upload_key(body)
    token = slack_upload_url_token(body)
    if key is None or token is None:
        return
    try:
        cache_factory(tenant_id).set(
            _upload_token_map_key(session_id, token), key, ex=_UPLOAD_TOKEN_TTL_S
        )
    except Exception:
        logger.warning("receipt_upload_token_map_error", exc_info=True)


def _upload_token_key(
    action_type: str,
    request_path: str,
    tenant_id: str,
    session_id: UUID,
    cache_factory: Callable[[str], CacheBackend],
) -> str | None:
    """The coalescing key for the upload flow's raw-bytes step, resolved from
    the token map step one populated. Best-effort."""
    if action_type != "slack.files.write" or "/upload/" not in request_path:
        return None
    token = upload_url_token(request_path)
    if token is None:
        return None
    try:
        value = cache_factory(tenant_id).get(_upload_token_map_key(session_id, token))
    except Exception:
        logger.warning("receipt_upload_token_lookup_error", exc_info=True)
        return None
    if isinstance(value, bytes):
        value = value.decode()
    if isinstance(value, str) and value.startswith(SLACK_UPLOAD_KEY_PREFIX):
        return value
    return None


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
