"""Exact retirement approval against migrated PostgreSQL, with no bundle I/O."""

from pathlib import Path
from typing import Literal
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.marketplace import confirm_marketplace_retirement__no_commit
from onyx.db.models import Marketplace, SkillVersion, User, User__UserGroup, UserGroup
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.users import lock_group_membership
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.models import (
    GitHubMarketplaceConfig,
    MarketplaceProvider,
    MarketplaceRetirementProposal,
)
from onyx.skills.marketplace.read_models import (
    BlockedSkill,
    CompleteMarketplace,
    FailedMarketplace,
    UnsupportedPlugin,
)
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply,
    catalog,
    skills,
    stage,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")
NAMES = tuple(f"retirement-{i}" for i in range(8))


def propose(
    session: Session, marketplace: Marketplace
) -> MarketplaceRetirementProposal:
    apply(session, marketplace, catalog(*NAMES))
    session.commit()
    before = {s.id: s.current_version_id for s in skills(session, marketplace)}
    result = apply(
        session,
        marketplace,
        catalog(NAMES[-1], "new", body=b"changed"),
        revision="next",
    )
    session.commit()
    assert result.status == "needs_confirmation"
    assert not result.changed_skill_ids and not result.retired_skill_ids
    rows = skills(session, marketplace)
    assert {s.id: s.current_version_id for s in rows} == before
    assert all(s.retired_at is None for s in rows)
    assert marketplace.last_synced_revision == "revision-1"
    proposal = marketplace.retirement_proposal
    assert proposal == MarketplaceRetirementProposal(
        revision="next",
        skill_ids=tuple(sorted(s.id for s in rows if s.name != NAMES[-1])),
    )
    return proposal


def confirm(
    session: Session,
    marketplace: Marketplace,
    user: User,
    proposal: MarketplaceRetirementProposal,
) -> None:
    confirm_marketplace_retirement__no_commit(
        marketplace.id,
        expected_revision=proposal.revision,
        expected_skill_ids=proposal.skill_ids,
        user=user,
        db_session=session,
    )


@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize("actor_kind", ["owner", "other", "scoped", "global"])
def test_confirmation_authority(
    session: Session, marketplace: Marketplace, personal: bool, actor_kind: str
) -> None:
    owner = make_user(session, standard_account=True)
    marketplace.owner_user_id = owner.id if personal else None
    marketplace.login_user_id = owner.id
    proposal = propose(session, marketplace)
    if actor_kind in ("scoped", "global"):
        actor, _ = manager(session, global_access=actor_kind == "global")
    else:
        actor = (
            owner
            if actor_kind == "owner"
            else make_user(session, standard_account=True)
        )
    session.commit()
    allowed = (personal and actor_kind == "owner") or (
        not personal and actor_kind == "global"
    )
    if allowed:
        confirm(session, marketplace, actor, proposal)
        session.commit()
        session.refresh(marketplace)
        assert marketplace.retirement_proposal == proposal.model_copy(
            update={"approved": True}
        )
    else:
        with pytest.raises(OnyxError) as error:
            confirm(session, marketplace, actor, proposal)
        assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
        session.commit()
        assert marketplace.retirement_proposal == proposal


@pytest.mark.parametrize(
    "mismatch", ["revision", "missing", "extra", "duplicate", "absent"]
)
def test_confirmation_requires_exact_locked_proposal(
    session: Session, marketplace: Marketplace, mismatch: str
) -> None:
    actor = make_user(session, standard_account=True)
    marketplace.owner_user_id = actor.id
    proposal = propose(session, marketplace)
    expected_revision, expected_ids = proposal.revision, proposal.skill_ids
    if mismatch == "revision":
        expected_revision = "stale"
    elif mismatch == "missing":
        expected_ids = expected_ids[:-1]
    elif mismatch == "extra":
        expected_ids += (uuid4(),)
    elif mismatch == "duplicate":
        expected_ids += (expected_ids[0],)
    else:
        marketplace.retirement_proposal = None
        session.commit()
    with pytest.raises(OnyxError) as error:
        confirm_marketplace_retirement__no_commit(
            marketplace.id,
            expected_revision=expected_revision,
            expected_skill_ids=expected_ids,
            user=actor,
            db_session=session,
        )
    assert error.value.error_code == OnyxErrorCode.CONFLICT
    session.commit()
    assert marketplace.retirement_proposal == (
        None if mismatch == "absent" else proposal
    )


def test_approval_rollback_retry_and_consumption(
    session: Session, marketplace: Marketplace
) -> None:
    actor = make_user(session, standard_account=True)
    marketplace.owner_user_id = actor.id
    proposal = propose(session, marketplace)
    confirm(session, marketplace, actor, proposal)
    session.rollback()
    assert marketplace.retirement_proposal == proposal
    confirm(session, marketplace, actor, proposal)
    session.commit()
    confirm(session, marketplace, actor, proposal)
    session.commit()
    approved = marketplace.retirement_proposal
    assert approved is not None and approved.approved
    before = {s.id: s.current_version_id for s in skills(session, marketplace)}
    read = catalog(NAMES[-1], "new", body=b"changed")
    staged = stage(read)
    staged.pop("tools/new")
    with pytest.raises(ValueError, match="needs a staged bundle"):
        apply(session, marketplace, read, revision="next", staged=staged)
    session.commit()  # The reconciliation savepoint must preserve approval too.
    assert marketplace.retirement_proposal == approved
    assert {s.id: s.current_version_id for s in skills(session, marketplace)} == before
    assert all(s.retired_at is None for s in skills(session, marketplace))
    assert marketplace.last_synced_revision == "revision-1"
    apply(session, marketplace, read, revision="next")
    session.rollback()
    assert marketplace.retirement_proposal == approved
    assert {s.id: s.current_version_id for s in skills(session, marketplace)} == before
    assert all(s.retired_at is None for s in skills(session, marketplace))
    result = apply(session, marketplace, read, revision="next")
    session.commit()
    assert set(result.retired_skill_ids) == set(proposal.skill_ids)
    assert len(result.changed_skill_ids) == 2
    assert marketplace.retirement_proposal is None
    assert marketplace.last_synced_revision == "next" and marketplace.last_error is None
    rows = skills(session, marketplace)
    retained = next(s for s in rows if s.name == NAMES[-1])
    assert retained.current_version_id != before[retained.id]
    versions = list(
        session.scalars(
            select(SkillVersion.id).where(
                SkillVersion.skill_id.in_([s.id for s in rows])
            )
        )
    )
    retry = apply(session, marketplace, read, revision="next", staged={})
    session.commit()
    assert (
        retry.status == "applied"
        and not retry.retired_skill_ids
        and not retry.changed_skill_ids
    )
    assert set(
        session.scalars(
            select(SkillVersion.id).where(
                SkillVersion.skill_id.in_([s.id for s in rows])
            )
        )
    ) == set(versions)
    with pytest.raises(OnyxError) as error:
        confirm(session, marketplace, actor, proposal)
    assert error.value.error_code == OnyxErrorCode.CONFLICT
    # A force push back creates new identities; consumed approval cannot retire them.
    apply(session, marketplace, catalog(*NAMES), revision="back")
    session.commit()
    assert (
        apply(session, marketplace, read, revision="next").status
        == "needs_confirmation"
    )
    session.commit()
    replacement = marketplace.retirement_proposal
    assert replacement is not None and not replacement.approved
    assert set(replacement.skill_ids).isdisjoint(proposal.skill_ids)


@pytest.mark.parametrize("change", ["revision", "set", "no_retirements"])
def test_changed_source_or_retirement_set_needs_fresh_approval(
    session: Session, marketplace: Marketplace, change: str
) -> None:
    actor = make_user(session, standard_account=True)
    marketplace.owner_user_id = actor.id
    proposal = propose(session, marketplace)
    confirm(session, marketplace, actor, proposal)
    session.commit()
    names = [NAMES[-1], "new"] + ([NAMES[0]] if change == "set" else [])
    revision = "different" if change == "revision" else "next"
    if change == "no_retirements":
        names = list(NAMES)
        revision = "no-removals"
    result = apply(session, marketplace, catalog(*names), revision=revision)
    session.commit()
    replacement = marketplace.retirement_proposal
    if change == "no_retirements":
        assert result.status == "applied" and replacement is None
    else:
        assert result.status == "needs_confirmation"
        assert (
            replacement is not None
            and not replacement.approved
            and replacement != proposal
        )
    with pytest.raises(OnyxError) as error:
        confirm(session, marketplace, actor, proposal)
    assert error.value.error_code == OnyxErrorCode.CONFLICT
    # Returning to the old source does not restore its approval.
    assert (
        apply(session, marketplace, catalog(NAMES[-1], "new"), revision="next").status
        == "needs_confirmation"
    )
    session.commit()
    assert marketplace.retirement_proposal == proposal
    assert all(s.retired_at is None for s in skills(session, marketplace))


@pytest.mark.parametrize("approved", [False, True])
def test_failed_read_preserves_proposal_and_content(
    session: Session, marketplace: Marketplace, approved: bool
) -> None:
    actor = make_user(session, standard_account=True)
    marketplace.owner_user_id = actor.id
    proposal = propose(session, marketplace)
    if approved:
        confirm(session, marketplace, actor, proposal)
        session.commit()
    result = apply(
        session, marketplace, FailedMarketplace(reason="read failed"), revision="bad"
    )
    session.commit()
    assert result.status == "failed"
    assert marketplace.retirement_proposal == proposal.model_copy(
        update={"approved": approved}
    )
    assert marketplace.last_synced_revision == "revision-1"
    assert all(s.retired_at is None for s in skills(session, marketplace))


def test_approved_retirement_protects_blocked_and_unsupported_entries(
    session: Session, marketplace: Marketplace
) -> None:
    actor = make_user(session, standard_account=True)
    marketplace.owner_user_id = actor.id
    entries = list(catalog(*NAMES).entries)
    entries[-1] = entries[-1].model_copy(update={"entry_key": "protected/child"})
    apply(session, marketplace, CompleteMarketplace(entries=entries))
    session.commit()
    rows = skills(session, marketplace)
    retained = {s.id: s.current_version_id for s in rows if s.name in NAMES[-2:]}
    read = CompleteMarketplace(
        entries=[
            BlockedSkill(
                entry_key=f"tools/{NAMES[-2]}",
                path=f"skills/{NAMES[-2]}",
                reason="invalid",
            ),
            UnsupportedPlugin(entry_key="protected", reason="unsupported"),
        ]
    )
    assert (
        apply(session, marketplace, read, revision="next").status
        == "needs_confirmation"
    )
    session.commit()
    proposal = marketplace.retirement_proposal
    assert proposal is not None and set(proposal.skill_ids).isdisjoint(retained)
    confirm(session, marketplace, actor, proposal)
    session.commit()
    result = apply(session, marketplace, read, revision="next")
    session.commit()
    assert len(result.retired_skill_ids) == 6
    assert {
        s.id: s.current_version_id
        for s in skills(session, marketplace)
        if s.retired_at is None
    } == retained
    assert result.blocked_entries == {
        f"tools/{NAMES[-2]}": "invalid",
        "protected": "unsupported",
    }


@pytest.mark.parametrize("revocation", ["manager", "basic", "inactive"])
@pytest.mark.parametrize("personal", [False, True])
def test_confirmation_refreshes_separate_auth_session_actor(
    db_session: Session,
    revocation: Literal["manager", "basic", "inactive"],
    personal: bool,
) -> None:
    actor = make_user(db_session, is_admin=True)
    actor_id = actor.id
    basic_id = db_session.scalar(select(UserGroup.id).where(UserGroup.name == "Basic"))
    assert basic_id is not None
    db_session.add(User__UserGroup(user_id=actor_id, user_group_id=basic_id))
    row = Marketplace(
        name="Revoke",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
        owner_user_id=actor_id if personal else None,
    )
    proposal = MarketplaceRetirementProposal(revision="next", skill_ids=(uuid4(),))
    row.retirement_proposal = proposal
    db_session.add(row)
    db_session.commit()
    with get_session_with_current_tenant() as auth_session:
        auth_user = auth_session.get(User, actor_id)
        assert auth_user is not None and auth_user is not actor
        with get_session_with_current_tenant() as writer:
            lock_group_membership(writer)
            if revocation == "inactive":
                fresh = writer.get(User, actor_id)
                assert fresh is not None
                fresh.is_active = False
            else:
                statement = delete(User__UserGroup).where(
                    User__UserGroup.user_id == actor_id
                )
                if revocation == "manager":
                    statement = statement.where(
                        User__UserGroup.user_group_id != basic_id
                    )
                writer.execute(statement)
                recompute_user_permissions__no_commit(actor_id, writer)
            writer.commit()
        assert has_global_permission(auth_user, Permission.MANAGE_SKILLS)
        if personal and revocation == "manager":
            confirm(db_session, row, auth_user, proposal)
            expected = proposal.model_copy(update={"approved": True})
        else:
            with pytest.raises(OnyxError) as error:
                confirm(db_session, row, auth_user, proposal)
            assert error.value.error_code == OnyxErrorCode.INSUFFICIENT_PERMISSIONS
            expected = proposal
        db_session.commit()
        assert row.retirement_proposal == expected


@pytest.mark.parametrize("change", ["proposal", "owner"])
def test_confirmation_refreshes_cached_marketplace(
    db_session: Session, change: str
) -> None:
    actor = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    proposal = MarketplaceRetirementProposal(revision="next", skill_ids=(uuid4(),))
    row = Marketplace(
        name="Changed",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
        owner_user_id=actor.id,
        retirement_proposal=proposal,
    )
    db_session.add(row)
    db_session.commit()
    row_id, other_id = row.id, other.id
    assert row.retirement_proposal == proposal
    with get_session_with_current_tenant() as writer:
        lock_group_membership(writer)
        current = writer.scalar(
            select(Marketplace).where(Marketplace.id == row_id).with_for_update()
        )
        assert current is not None
        if change == "owner":
            current.owner_user_id = other_id
        else:
            current.retirement_proposal = proposal.model_copy(
                update={"revision": "newer"}
            )
        writer.commit()
    assert row.retirement_proposal == proposal and row.owner_user_id == actor.id
    with pytest.raises(OnyxError) as error:
        confirm(db_session, row, actor, proposal)
    assert error.value.error_code == (
        OnyxErrorCode.CONFLICT
        if change == "proposal"
        else OnyxErrorCode.INSUFFICIENT_PERMISSIONS
    )
    db_session.commit()
    assert row.retirement_proposal is not None and not row.retirement_proposal.approved


def test_migration_round_trip_with_existing_row(
    session: Session, marketplace: Marketplace
) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    revision = scripts.get_revision("0194658d026d")
    assert revision is not None
    marketplace_id, name = marketplace.id, marketplace.name
    with Operations.context(MigrationContext.configure(session.connection())):
        revision.module.downgrade()
        assert (
            session.scalar(
                text("SELECT name FROM marketplace WHERE id = :id"),
                {"id": marketplace_id},
            )
            == name
        )
        revision.module.upgrade()
    session.commit()
    session.refresh(marketplace)
    assert marketplace.retirement_proposal is None
    assert (
        session.scalar(
            text("SELECT retirement_proposal IS NULL FROM marketplace WHERE id = :id"),
            {"id": marketplace_id},
        )
        is True
    )
