"""Database ownership and deadlines, independent of worker dispatch."""

from datetime import timedelta
from uuid import UUID

import pytest
from sqlalchemy import func, update
from sqlalchemy.orm import Session

from onyx.db import marketplace_sync as ownership
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import Marketplace
from onyx.skills.marketplace.models import MarketplaceSyncStatus
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant


def expire(session: Session, marketplace_id: UUID) -> None:
    session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace_id)
        .values(
            sync_lease_expires_at=func.clock_timestamp() - timedelta(seconds=1),
            sync_dispatch_after=None,
        )
    )
    session.commit()


def test_lease_renewal_cannot_exceed_operation_deadline(
    session: Session,
    marketplace: Marketplace,
) -> None:
    ownership.request_marketplace_sync(marketplace.id, session)
    owner = ownership.claim_marketplace_sync(marketplace.id, session)
    assert owner is not None
    marketplace.sync_started_at = func.clock_timestamp() - timedelta(
        seconds=ownership.MAX_RUN_SECONDS - 1
    )
    session.commit()
    assert ownership.renew_marketplace_sync(marketplace.id, owner, session)
    session.refresh(marketplace)
    assert marketplace.sync_started_at is not None
    assert marketplace.sync_lease_expires_at is not None
    assert marketplace.sync_lease_expires_at == marketplace.sync_started_at + timedelta(
        seconds=ownership.MAX_RUN_SECONDS
    )
    expire(session, marketplace.id)
    assert not ownership.renew_marketplace_sync(marketplace.id, owner, session)
    with pytest.raises(ownership.MarketplaceSyncLeaseLost):
        ownership.finish_marketplace_sync(
            marketplace.id,
            owner,
            session,
            status=MarketplaceSyncStatus.APPLIED,
        )
    session.rollback()


def test_recovery_budget_and_explicit_restart(
    session: Session, marketplace: Marketplace
) -> None:
    marketplace.login_user_id = make_user(session).id
    session.commit()
    ownership.request_marketplace_sync(marketplace.id, session)
    for attempt in range(1, ownership.MAX_ATTEMPTS + 1):
        assert ownership.claim_marketplace_sync(marketplace.id, session) is not None
        expire(session, marketplace.id)
        assert ownership.reserve_marketplace_dispatches(session) == (
            [],
            attempt < ownership.MAX_ATTEMPTS,
        )
        session.refresh(marketplace)
        assert marketplace.sync_status == MarketplaceSyncStatus.FAILED
        assert marketplace.last_error == ownership.SYNC_INTERRUPTED
        assert marketplace.sync_attempts == attempt
        assert marketplace.sync_owner is None
        if attempt < ownership.MAX_ATTEMPTS:
            assert ownership.claim_marketplace_sync(marketplace.id, session) is None
            marketplace.sync_retry_after = func.clock_timestamp() - timedelta(seconds=1)
            session.commit()
            assert ownership.reserve_marketplace_dispatches(session) == (
                [marketplace.id],
                True,
            )
    assert not marketplace.sync_requested
    assert ownership.claim_marketplace_sync(marketplace.id, session) is None
    ownership.request_marketplace_sync(marketplace.id, session)
    assert ownership.reserve_marketplace_dispatches(session) == ([marketplace.id], True)
    assert ownership.claim_marketplace_sync(marketplace.id, session) is not None
    session.refresh(marketplace)
    assert marketplace.sync_attempts == 1


def test_recovery_refreshes_a_request_committed_by_another_session(
    session: Session, marketplace: Marketplace
) -> None:
    marketplace.login_user_id = make_user(session).id
    session.commit()
    ownership.request_marketplace_sync(marketplace.id, session)
    owner = ownership.claim_marketplace_sync(marketplace.id, session)
    assert owner is not None
    expire(session, marketplace.id)
    assert marketplace.sync_owner == owner
    assert not marketplace.sync_requested

    with get_session_with_current_tenant() as requester:
        ownership.request_marketplace_sync(marketplace.id, requester)

    assert ownership.reserve_marketplace_dispatches(session) == ([marketplace.id], True)
    session.refresh(marketplace)
    assert marketplace.sync_requested
    assert marketplace.sync_retry_after is None
    assert marketplace.sync_attempts == 0


@pytest.mark.parametrize("release", ["commit", "rollback", "savepoint_rollback"])
def test_publication_cannot_reuse_a_released_transaction(
    session: Session, marketplace: Marketplace, release: str
) -> None:
    marketplace.login_user_id = make_user(session).id
    session.commit()
    ownership.request_marketplace_sync(marketplace.id, session)
    owner = ownership.claim_marketplace_sync(marketplace.id, session)
    assert owner is not None
    savepoint = session.begin_nested() if release == "savepoint_rollback" else None
    publication = ownership.fence_marketplace_sync(marketplace.id, owner, session)
    if savepoint is not None:
        savepoint.rollback()
    elif release == "commit":
        session.commit()
    else:
        session.rollback()
    with pytest.raises(ownership.MarketplaceSyncLeaseLost, match="lock released"):
        publication.finish__no_commit(status=MarketplaceSyncStatus.APPLIED)
    session.rollback()
    ownership.finish_marketplace_sync(
        marketplace.id, owner, session, status=MarketplaceSyncStatus.APPLIED
    )
    session.refresh(marketplace)
    assert marketplace.sync_status == MarketplaceSyncStatus.APPLIED
    assert marketplace.sync_owner is None


def test_publication_keeps_the_operation_deadline(
    session: Session, marketplace: Marketplace
) -> None:
    ownership.request_marketplace_sync(marketplace.id, session)
    owner = ownership.claim_marketplace_sync(marketplace.id, session)
    assert owner is not None
    publication = ownership.fence_marketplace_sync(marketplace.id, owner, session)
    session.execute(
        update(Marketplace)
        .where(Marketplace.id == marketplace.id)
        .values(
            sync_started_at=func.clock_timestamp()
            - timedelta(seconds=ownership.MAX_RUN_SECONDS + 1)
        )
    )
    with pytest.raises(ownership.MarketplaceSyncLeaseLost, match="operation deadline"):
        publication.finish__no_commit(status=MarketplaceSyncStatus.APPLIED)
    session.rollback()
    session.refresh(marketplace)
    assert marketplace.sync_owner == owner
    assert marketplace.sync_status is None
