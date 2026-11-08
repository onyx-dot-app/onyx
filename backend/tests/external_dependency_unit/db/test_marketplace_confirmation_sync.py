"""Approved retirements reach the durable worker; rollback leaves no queued work."""

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.marketplace import confirm_marketplace_retirement__no_commit
from onyx.db.models import Marketplace, Skill, User
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.models import MarketplaceSyncStatus
from onyx.skills.sync import sync_marketplace
from tests.external_dependency_unit.db.test_marketplace_sync import (
    GitHub,
    catalog_bytes,
)
from tests.external_dependency_unit.db.test_marketplace_sync import github as github
from tests.external_dependency_unit.db.test_marketplace_sync import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_marketplace_sync import session as session
from tests.external_dependency_unit.db.test_marketplace_sync import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user


def test_confirmation_and_requested_work_commit_together(
    session: Session, marketplace: Marketplace, tenant: str, github: GitHub, user: User
) -> None:
    marketplace.owner_user_id = marketplace.login_user_id = user.id
    session.commit()
    github.archive = catalog_bytes(*(f"skill-{i}" for i in range(8)))
    sync_marketplace(marketplace.id, tenant)
    github.archive, github.revision = catalog_bytes("skill-7"), "b" * 40
    result = sync_marketplace(marketplace.id, tenant)
    assert result is not None and result.status == "needs_confirmation"
    session.refresh(marketplace)
    proposal = marketplace.retirement_proposal
    assert proposal is not None and len(proposal.skill_ids) == 7
    assert not marketplace.sync_requested
    for commit in (False, True):
        confirm_marketplace_retirement__no_commit(
            marketplace.id,
            expected_revision=proposal.revision,
            expected_skill_ids=proposal.skill_ids,
            user=user,
            db_session=session,
        )
        assert marketplace.sync_requested
        if commit:
            session.commit()
        else:
            session.rollback()
            assert marketplace.retirement_proposal == proposal
            assert not marketplace.sync_requested
            count = len(github.urls)
            assert sync_marketplace(marketplace.id, tenant, request_work=False) is None
            assert len(github.urls) == count
    result = sync_marketplace(marketplace.id, tenant, request_work=False)
    assert result is not None and set(result.retired_skill_ids) == set(
        proposal.skill_ids
    )
    session.refresh(marketplace)
    assert marketplace.retirement_proposal is None and not marketplace.sync_requested
    assert marketplace.last_synced_revision == github.revision
    live = list(session.scalars(select(Skill).where(Skill.retired_at.is_(None))))
    assert [skill.name for skill in live] == ["skill-7"]


@pytest.mark.parametrize("approved", [False, True])
@pytest.mark.parametrize("reverted", [False, True])
def test_changed_source_invalidates_retirement_approval(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
    approved: bool,
    reverted: bool,
) -> None:
    marketplace.owner_user_id = marketplace.login_user_id = user.id
    session.commit()
    original = catalog_bytes(*(f"skill-{i}" for i in range(8)))
    github.archive = original
    sync_marketplace(marketplace.id, tenant)
    github.archive, github.revision = catalog_bytes("skill-7"), "b" * 40
    sync_marketplace(marketplace.id, tenant)
    session.refresh(marketplace)
    proposal = marketplace.retirement_proposal
    assert proposal is not None
    if approved:
        confirm_marketplace_retirement__no_commit(
            marketplace.id,
            expected_revision=proposal.revision,
            expected_skill_ids=proposal.skill_ids,
            user=user,
            db_session=session,
        )
        session.commit()
    # Both a no-op revert and a different failed read invalidate the old prompt.
    github.archive, github.revision = (
        (original, "a" * 40) if reverted else (b"invalid archive", "c" * 40)
    )
    sync_marketplace(marketplace.id, tenant)
    session.refresh(marketplace)
    assert marketplace.retirement_proposal is None
    assert marketplace.sync_status == (
        MarketplaceSyncStatus.APPLIED if reverted else MarketplaceSyncStatus.FAILED
    )
    with pytest.raises(OnyxError) as error:
        confirm_marketplace_retirement__no_commit(
            marketplace.id,
            expected_revision=proposal.revision,
            expected_skill_ids=proposal.skill_ids,
            user=user,
            db_session=session,
        )
    assert error.value.error_code == OnyxErrorCode.CONFLICT
    session.rollback()
    github.archive, github.revision = catalog_bytes("skill-7"), "b" * 40
    result = sync_marketplace(marketplace.id, tenant)
    assert result is not None and result.status == "needs_confirmation"
    session.refresh(marketplace)
    assert marketplace.retirement_proposal == proposal
    assert session.scalar(select(Skill.id).where(Skill.retired_at.is_not(None))) is None


@pytest.mark.parametrize(
    "status", [None, MarketplaceSyncStatus.APPLIED, MarketplaceSyncStatus.FAILED]
)
def test_confirmation_requires_pending_status(
    session: Session,
    marketplace: Marketplace,
    tenant: str,
    github: GitHub,
    user: User,
    status: MarketplaceSyncStatus | None,
) -> None:
    marketplace.owner_user_id = marketplace.login_user_id = user.id
    session.commit()
    github.archive = catalog_bytes(*(f"skill-{i}" for i in range(8)))
    sync_marketplace(marketplace.id, tenant)
    github.archive, github.revision = catalog_bytes("skill-7"), "b" * 40
    sync_marketplace(marketplace.id, tenant)
    session.refresh(marketplace)
    proposal = marketplace.retirement_proposal
    assert proposal is not None
    marketplace.sync_status = status
    session.commit()
    with pytest.raises(OnyxError) as error:
        confirm_marketplace_retirement__no_commit(
            marketplace.id,
            expected_revision=proposal.revision,
            expected_skill_ids=proposal.skill_ids,
            user=user,
            db_session=session,
        )
    assert error.value.error_code == OnyxErrorCode.CONFLICT
    assert not marketplace.sync_requested
    assert error.value.detail == (
        "Sync the marketplace again before confirming retirement"
    )
