"""Action receipt DAL.

The shared persistence primitive receipts flow through, independent of which
layer records them. The lifecycle contract lives on ActionReceipt. Helpers
flush and never commit, the caller owns the transaction.
"""

from datetime import timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import desc, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.enums import ReceiptStatus
from onyx.db.models import ActionReceipt

# A PENDING row older than this lost its recorder mid-flight. The sweeper
# moves it to UNKNOWN so it can never linger as an implied in-progress send.
PENDING_RECEIPT_TTL = timedelta(minutes=10)


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
) -> ActionReceipt:
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
        return receipt
    return db_session.execute(
        select(ActionReceipt)
        .where(
            ActionReceipt.session_id == session_id,
            ActionReceipt.operation_key == operation_key,
        )
        .execution_options(populate_existing=True)
    ).scalar_one()


def finalize_receipt(
    db_session: Session,
    *,
    receipt_id: UUID,
    status: ReceiptStatus,
    link: str | None = None,
) -> ActionReceipt | None:
    """Move a PENDING row to its terminal state.

    The conditional UPDATE is the race arbiter: concurrent finalizes cannot
    flip an already-recorded verdict. Returns the row (already-terminal
    included) or None when it does not exist.
    """
    if status not in (ReceiptStatus.CONFIRMED, ReceiptStatus.FAILED):
        raise ValueError("finalize_receipt only records CONFIRMED or FAILED")
    values: dict[str, Any] = {"status": status}
    if link is not None:
        values["link"] = link
    row = db_session.execute(
        update(ActionReceipt)
        .where(
            ActionReceipt.id == receipt_id,
            ActionReceipt.status == ReceiptStatus.PENDING,
        )
        .values(**values)
        .returning(ActionReceipt)
        .execution_options(synchronize_session=False)
    ).scalar_one_or_none()
    db_session.flush()
    if row is None:
        # Lost the race or already terminal. Read fresh, an identity-map hit
        # here could still say PENDING.
        return db_session.execute(
            select(ActionReceipt)
            .where(ActionReceipt.id == receipt_id)
            .execution_options(populate_existing=True)
        ).scalar_one_or_none()
    db_session.refresh(row)
    return row


def sweep_stale_pending_receipts(db_session: Session) -> int:
    """Mark orphaned PENDING rows UNKNOWN. Returns the number swept."""
    # DB clock on both sides, created_at is server-generated.
    cutoff = func.now() - PENDING_RECEIPT_TTL
    swept_ids = (
        db_session.execute(
            update(ActionReceipt)
            .where(
                ActionReceipt.status == ReceiptStatus.PENDING,
                ActionReceipt.created_at < cutoff,
            )
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
