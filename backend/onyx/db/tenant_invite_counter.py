from sqlalchemy import func
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from onyx.db.models import TenantInviteCounter


def reserve_trial_invites(
    shared_session: Session,
    tenant_id: str,
    num_invites: int,
) -> int:
    """Atomically increment the tenant's invite counter by `num_invites`.

    Returns the post-increment total. The caller is expected to compare
    against the trial cap and rollback the session if the total exceeds
    it — the UPSERT's UPDATE leg holds a row-level lock on `tenant_id`
    for the duration of the transaction, serializing concurrent reservers
    for the same tenant.
    """
    stmt = pg_insert(TenantInviteCounter).values(
        tenant_id=tenant_id,
        total_invites_sent=num_invites,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[TenantInviteCounter.tenant_id],
        set_={
            "total_invites_sent": TenantInviteCounter.total_invites_sent
            + stmt.excluded.total_invites_sent,
            "updated_at": func.now(),
        },
    ).returning(TenantInviteCounter.total_invites_sent)
    return int(shared_session.execute(stmt).scalar_one())


def release_trial_invites(
    shared_session: Session,
    tenant_id: str,
    num_invites: int,
) -> None:
    """Compensating decrement of the counter by `num_invites`, clamped at 0.

    Only called when a downstream step (KV write, billing register, etc.)
    fails after the counter has already been incremented, so the counter
    tracks invites that actually reached the system rather than merely
    reserved. The counter is monotonic with respect to user actions — no
    user-facing endpoint decrements it — but it is reconciled downward by
    this function when the system fails mid-flow. No-op if the tenant has
    no counter row.
    """
    stmt = (
        update(TenantInviteCounter)
        .where(TenantInviteCounter.tenant_id == tenant_id)
        .values(
            total_invites_sent=func.greatest(
                TenantInviteCounter.total_invites_sent - num_invites, 0
            ),
            updated_at=func.now(),
        )
    )
    shared_session.execute(stmt)
