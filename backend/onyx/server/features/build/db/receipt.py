"""Action receipt DAL.

The shared persistence primitive receipts flow through, independent of which
layer records them. The lifecycle contract lives on ActionReceipt. Helpers
flush and never commit, the caller owns the transaction.
"""

from datetime import timedelta
from typing import Any, NamedTuple
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from onyx.db.enums import ReceiptStatus
from onyx.db.models import ActionReceipt

# A PENDING row older than this lost its recorder mid-flight. The sweeper
# moves it to UNKNOWN so it can never linger as an implied in-progress send.
PENDING_RECEIPT_TTL = timedelta(minutes=10)


class InsertReceiptResult(NamedTuple):
    receipt: ActionReceipt
    # False when the operation key coalesced onto an existing row: the caller
    # must not announce it as new.
    created: bool


def insert_pending_receipt(
    db_session: Session,
    *,
    session_id: UUID,
    action_type: str,
    effect: str,
    destination: str,
    gated_app_id: int | None,
    approval_id: UUID | None,
    operation_key: str | None,
) -> InsertReceiptResult:
    """Record the attempt before the action executes.

    A repeated operation_key returns the existing row instead of a duplicate,
    which is how multi-request provider flows coalesce into one receipt. NULL
    keys always insert, the conflict target is the partial unique index.
    """
    stmt = (
        pg_insert(ActionReceipt)
        .values(
            session_id=session_id,
            action_type=action_type,
            effect=effect,
            destination=destination,
            gated_app_id=gated_app_id,
            approval_id=approval_id,
            operation_key=operation_key,
            status=ReceiptStatus.PENDING,
        )
        .on_conflict_do_nothing(
            index_elements=[ActionReceipt.session_id, ActionReceipt.operation_key],
            index_where=ActionReceipt.operation_key.isnot(None),
        )
        .returning(ActionReceipt)
    )
    receipt = db_session.execute(
        select(ActionReceipt)
        .from_statement(stmt)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
    if receipt is not None:
        return InsertReceiptResult(receipt, created=True)
    existing = db_session.execute(
        select(ActionReceipt)
        .where(
            ActionReceipt.session_id == session_id,
            ActionReceipt.operation_key == operation_key,
        )
        .execution_options(populate_existing=True)
    ).scalar_one()
    return InsertReceiptResult(existing, created=False)


class FinalizeReceiptResult(NamedTuple):
    # None when the row does not exist.
    receipt: ActionReceipt | None
    # True when this call performed the transition. A row that already
    # carried a terminal verdict comes back changed=False.
    changed: bool


def finalize_receipt(
    db_session: Session,
    *,
    receipt_id: UUID,
    status: ReceiptStatus,
    link: str | None = None,
    allow_failed_downgrade: bool = False,
) -> FinalizeReceiptResult:
    """Move a PENDING row to its terminal state.

    CONFIRMED and FAILED come from the origin's verdict, UNKNOWN when the
    outcome is genuinely unknowable (headers arrived but the body did not).
    The conditional UPDATE is the race arbiter: concurrent finalizes cannot
    flip an already-recorded verdict. allow_failed_downgrade lets a FAILED
    verdict overturn CONFIRMED: a coalesced multi-step flow confirms on its
    early steps, and a later step's failure is the truer outcome.
    """
    if status is ReceiptStatus.PENDING:
        raise ValueError("finalize_receipt records terminal states only")
    values: dict[str, Any] = {"status": status}
    if link is not None:
        values["link"] = link
    replaceable = [ReceiptStatus.PENDING]
    if allow_failed_downgrade and status is ReceiptStatus.FAILED:
        replaceable.append(ReceiptStatus.CONFIRMED)
    row = db_session.execute(
        update(ActionReceipt)
        .where(
            ActionReceipt.id == receipt_id,
            ActionReceipt.status.in_(replaceable),
        )
        .values(**values)
        .returning(ActionReceipt)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    db_session.flush()
    if row is None:
        # Lost the race or already terminal. Read fresh, an identity-map hit
        # here could still say PENDING.
        current = db_session.execute(
            select(ActionReceipt)
            .where(ActionReceipt.id == receipt_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
        return FinalizeReceiptResult(current, changed=False)
    db_session.refresh(row)
    return FinalizeReceiptResult(row, changed=True)


def set_receipt_operation_key(
    db_session: Session,
    *,
    receipt_id: UUID,
    operation_key: str,
) -> bool:
    """Attach a late-learned coalescing key to a keyless row.

    False when the key is already claimed by another row (the flow already
    coalesced there), the row already has one, or the row is gone. The
    partial unique index arbitrates the race.
    """
    try:
        with db_session.begin_nested():
            claimed = db_session.execute(
                update(ActionReceipt)
                .where(
                    ActionReceipt.id == receipt_id,
                    ActionReceipt.operation_key.is_(None),
                )
                .values(operation_key=operation_key)
                .returning(ActionReceipt.id)
                .execution_options(synchronize_session=False)
            ).scalar_one_or_none()
    except IntegrityError:
        return False
    db_session.flush()
    return claimed is not None


def sweep_stale_pending_receipts(
    db_session: Session, *, session_id: UUID | None = None
) -> int:
    """Mark orphaned PENDING rows UNKNOWN. Returns the number swept.

    Scope to one session on user-facing reads: the tenant-wide form has no
    supporting index and belongs to maintenance paths.
    """
    # DB clock on both sides, created_at is server-generated.
    cutoff = func.now() - PENDING_RECEIPT_TTL
    conditions = [
        ActionReceipt.status == ReceiptStatus.PENDING,
        ActionReceipt.created_at < cutoff,
    ]
    if session_id is not None:
        conditions.append(ActionReceipt.session_id == session_id)
    swept_ids = (
        db_session.execute(
            update(ActionReceipt)
            .where(*conditions)
            .values(status=ReceiptStatus.UNKNOWN)
            .returning(ActionReceipt.id)
            .execution_options(synchronize_session=False)
        )
        .scalars()
        .all()
    )
    db_session.flush()
    return len(swept_ids)


def get_session_receipts(
    db_session: Session,
    *,
    session_id: UUID,
    statuses: list[ReceiptStatus] | None = None,
) -> list[ActionReceipt]:
    query = select(ActionReceipt).where(ActionReceipt.session_id == session_id)
    if statuses is not None:
        query = query.where(ActionReceipt.status.in_(statuses))
    return list(db_session.scalars(query.order_by(desc(ActionReceipt.created_at))))
