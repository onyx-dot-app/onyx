"""Durable requested work and expiring ownership, scoped by the session's tenant."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.orm import Session, SessionTransaction

from onyx.db.models import Marketplace
from onyx.db.users import lock_group_membership
from onyx.skills.marketplace.models import (
    MARKETPLACE_LOGIN_ERROR,
    MarketplaceSyncStatus,
)

LEASE_SECONDS = 60
MAX_RUN_SECONDS = 300
DISPATCH_SECONDS = 60
MESSAGE_SECONDS = 15 * 60
MAX_ATTEMPTS = 3
SYNC_FAILED = "Marketplace sync failed. Check the login and source, then retry."
SYNC_INTERRUPTED = (
    "Marketplace sync stopped or exceeded its time limit. Retry the sync."
)


class MarketplaceSyncLeaseLost(RuntimeError):
    pass


@dataclass(frozen=True)
class MarketplaceSyncPublication:
    """Ownership fenced for the transaction that holds the marketplace row lock."""

    marketplace: Marketplace
    _owner: UUID
    _session: Session
    _transaction: SessionTransaction

    def finish__no_commit(
        self,
        *,
        status: MarketplaceSyncStatus,
        error: str | None = None,
        retry: bool = False,
        resolved_revision: str | None = None,
    ) -> bool:
        session, row = self._session, self.marketplace
        transaction = session.get_nested_transaction() or session.get_transaction()
        if (
            transaction is not self._transaction
            or not self._transaction.is_active
            or row.sync_owner != self._owner
        ):
            raise MarketplaceSyncLeaseLost("Marketplace publication lock released")
        now = session.execute(select(func.clock_timestamp())).scalar_one()
        if (
            row.sync_started_at is None
            or row.sync_started_at + timedelta(seconds=MAX_RUN_SECONDS) <= now
        ):
            raise MarketplaceSyncLeaseLost(
                "Marketplace sync operation deadline expired"
            )
        if (
            resolved_revision is not None
            and row.retirement_proposal is not None
            and row.retirement_proposal.revision != resolved_revision
        ):
            row.retirement_proposal = None
        _finish(row, now, status, error, retry=retry)
        return row.sync_requested and row.sync_retry_after is None


def request_marketplace_sync__no_commit(marketplace_id: UUID, session: Session) -> None:
    session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .values(
            sync_requested=True,
            sync_attempts=0,
            sync_retry_after=None,
            sync_dispatch_after=None,
        )
    )


def request_marketplace_sync(marketplace_id: UUID, session: Session) -> None:
    request_marketplace_sync__no_commit(marketplace_id, session)
    session.commit()


def _lock(marketplace_id: UUID, session: Session) -> Marketplace | None:
    return session.scalar(
        select(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def claim_marketplace_sync(marketplace_id: UUID, session: Session) -> UUID | None:
    row = _lock(marketplace_id, session)
    now = session.execute(select(func.clock_timestamp())).scalar_one()
    if (
        row is None
        or (
            row.sync_owner is not None
            and row.sync_lease_expires_at is not None
            and row.sync_lease_expires_at > now
        )
        or (not row.sync_requested and row.sync_owner is None)
    ):
        return None
    if row.sync_owner is not None:
        _finish(row, now, MarketplaceSyncStatus.FAILED, SYNC_INTERRUPTED, retry=True)
    if not row.sync_requested or (
        row.sync_retry_after is not None and row.sync_retry_after > now
    ):
        session.commit()
        return None
    owner = uuid4()
    row.sync_owner = owner
    row.sync_attempts += 1
    row.sync_requested = False
    row.sync_dispatch_after = None
    row.sync_started_at = now
    row.sync_lease_expires_at = now + timedelta(seconds=LEASE_SECONDS)
    session.commit()
    return owner


def fence_marketplace_sync(
    marketplace_id: UUID, owner: UUID, session: Session
) -> MarketplaceSyncPublication:
    # Publication follows the same lock order as access and reconciliation.
    lock_group_membership(session)
    row = _lock(marketplace_id, session)
    now = session.execute(select(func.clock_timestamp())).scalar_one()
    if (
        row is None
        or row.sync_owner != owner
        or row.sync_lease_expires_at is None
        or row.sync_lease_expires_at <= now
    ):
        raise MarketplaceSyncLeaseLost("Marketplace sync ownership expired")
    transaction = session.get_nested_transaction() or session.get_transaction()
    if transaction is None:
        raise MarketplaceSyncLeaseLost("Marketplace publication has no transaction")
    return MarketplaceSyncPublication(row, owner, session, transaction)


def renew_marketplace_sync(marketplace_id: UUID, owner: UUID, session: Session) -> bool:
    row = _lock(marketplace_id, session)
    now = session.execute(select(func.clock_timestamp())).scalar_one()
    if (
        row is None
        or row.sync_owner != owner
        or row.sync_lease_expires_at is None
        or row.sync_started_at is None
        or row.sync_lease_expires_at <= now
        or row.sync_started_at + timedelta(seconds=MAX_RUN_SECONDS) <= now
    ):
        return False
    row.sync_lease_expires_at = min(
        now + timedelta(seconds=LEASE_SECONDS),
        row.sync_started_at + timedelta(seconds=MAX_RUN_SECONDS),
    )
    session.commit()
    return True


def _finish(
    row: Marketplace,
    now: datetime,
    status: MarketplaceSyncStatus,
    error: str | None,
    *,
    retry: bool,
) -> None:
    if row.login_user_id is None:
        status, error, retry = (
            MarketplaceSyncStatus.FAILED,
            MARKETPLACE_LOGIN_ERROR,
            False,
        )
    row.sync_status, row.last_error = status, error
    row.sync_owner = None
    row.sync_lease_expires_at = row.sync_started_at = None
    row.sync_dispatch_after = row.sync_retry_after = None
    # An explicit request during the run owns a fresh budget and bypasses backoff.
    if not row.sync_requested and retry and row.sync_attempts < MAX_ATTEMPTS:
        row.sync_requested = True
        row.sync_retry_after = now + timedelta(
            seconds=60 * 2 ** (row.sync_attempts - 1)
        )


def finish_marketplace_sync__no_commit(
    marketplace_id: UUID,
    owner: UUID,
    session: Session,
    *,
    status: MarketplaceSyncStatus,
    error: str | None = None,
    retry: bool = False,
    resolved_revision: str | None = None,
) -> bool:
    return fence_marketplace_sync(marketplace_id, owner, session).finish__no_commit(
        status=status,
        error=error,
        retry=retry,
        resolved_revision=resolved_revision,
    )


def finish_marketplace_sync(
    marketplace_id: UUID,
    owner: UUID,
    session: Session,
    *,
    status: MarketplaceSyncStatus,
    error: str | None = None,
    retry: bool = False,
) -> bool:
    pending = finish_marketplace_sync__no_commit(
        marketplace_id, owner, session, status=status, error=error, retry=retry
    )
    # Request writers take this row lock too: release cannot erase a new request.
    session.commit()
    return pending


def reserve_marketplace_dispatches(
    session: Session, marketplace_id: UUID | None = None
) -> tuple[list[UUID], bool]:
    """Reserve deliveries and report remaining work after reaping expired owners."""
    now = session.execute(select(func.clock_timestamp())).scalar_one()
    query = select(Marketplace).where(
        or_(Marketplace.sync_requested, Marketplace.sync_owner.is_not(None)),
        or_(Marketplace.sync_owner.is_(None), Marketplace.sync_lease_expires_at <= now),
        or_(
            Marketplace.sync_retry_after.is_(None), Marketplace.sync_retry_after <= now
        ),
        or_(
            Marketplace.sync_dispatch_after.is_(None),
            Marketplace.sync_dispatch_after <= now,
        ),
    )
    if marketplace_id is not None:
        query = query.where(Marketplace.id == marketplace_id)
    rows = list(
        session.scalars(
            query.order_by(Marketplace.id).limit(32).with_for_update(skip_locked=True)
        )
    )
    ids: list[UUID] = []
    for row in rows:
        if row.sync_owner is not None:
            _finish(
                row, now, MarketplaceSyncStatus.FAILED, SYNC_INTERRUPTED, retry=True
            )
            if not row.sync_requested or row.sync_retry_after is not None:
                continue
        row.sync_dispatch_after = now + timedelta(seconds=DISPATCH_SECONDS)
        ids.append(row.id)
    active = any(row.sync_requested for row in rows)
    session.commit()
    return ids, active
