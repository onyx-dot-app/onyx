"""Marketplace defaults, overrides and reset against migrated PostgreSQL."""

import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from queue import Queue
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, func, select, text
from sqlalchemy.orm import Session

from ee.onyx.db.community_downgrade import remove_custom_user_groups__no_commit
from onyx.db.enums import SandboxStatus
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.enums import SkillSharePermission as Share
from onyx.db.marketplace_access import (
    MarketplaceAccessAdapter,
    materialize_marketplace_access__no_commit,
    reset_marketplace_skill_access__no_commit,
)
from onyx.db.models import (
    Marketplace,
    Sandbox,
    Skill__User,
    User,
    User__UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.resource_access import (
    AccessMutationResult,
    ResourceAccessChange,
    mutate_resource_access,
)
from onyx.db.skill import (
    SkillAccessAdapter,
    SkillManagementPolicy,
    fetch_skill,
)
from onyx.db.users import lock_group_membership
from onyx.error_handling.exceptions import OnyxError
from onyx.server.settings.models import Tier
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_sandbox,
    make_user,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply as reconcile,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    catalog,
    skills,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    client_for,
    manager,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

apply = reconcile

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


def share(
    session: Session, marketplace: Marketplace, user: User, change: ResourceAccessChange
) -> AccessMutationResult:
    return mutate_resource_access(
        [marketplace.id], change, user, session, MarketplaceAccessAdapter(Tier.BUSINESS)
    )


def test_inheritance_removes_access_and_captures_both_audiences(
    session: Session, marketplace: Marketplace
) -> None:
    admin, old_group = manager(session, global_access=True)
    member = make_user(session)
    outsider = make_user(session)
    new_group = make_group(session)
    session.add_all(
        [
            User__UserGroup(user_id=member.id, user_group_id=old_group),
            User__UserGroup(user_id=outsider.id, user_group_id=new_group.id),
        ]
    )
    for user in (member, outsider):
        make_sandbox(session, user)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(
            group_shares={old_group: Share.VIEWER},
            group_installation_policies={old_group: Policy.REQUIRED},
        ),
    )
    created = apply(session, marketplace, catalog("first", "second"))
    assert created.affected_user_ids == {member.id}

    def visible(user: User) -> set[UUID]:
        return {
            skill.id
            for skill in skills(session, marketplace)
            if fetch_skill(
                skill.id,
                policy=SkillManagementPolicy.VIEW,
                user=user,
                db_session=session,
            )
            is not None
        }

    assert visible(member) == set(created.changed_skill_ids)
    assert not visible(outsider)
    result = share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(group_shares={new_group.id: Share.VIEWER}),
    )
    assert result.affected == {member.id, outsider.id}
    for skill in skills(session, marketplace):
        assert skill.follows_marketplace_access
        assert SkillAccessAdapter().state(skill).group_installation_policies == {
            new_group.id: None
        }
    assert not visible(member)
    assert visible(outsider) == set(created.changed_skill_ids)


def test_policy_null_override_and_reset(
    session: Session, marketplace: Marketplace
) -> None:
    admin, group_id = manager(session, global_access=True)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(
            group_shares={group_id: Share.VIEWER},
            group_installation_policies={group_id: Policy.REQUIRED},
        ),
    )
    apply(session, marketplace, catalog("first", "second"))
    first, second = sorted(skills(session, marketplace), key=lambda row: row.name)
    mutate_resource_access(
        [first.id],
        ResourceAccessChange(user_shares={admin.id: Share.EDITOR}),
        admin,
        session,
        SkillAccessAdapter(),
    )
    assert not first.follows_marketplace_access
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(group_installation_policies={group_id: None}),
    )
    apply(session, marketplace, catalog("first", "second", "third", body=b"changed"))
    session.expire_all()
    assert first.group_shares[0].installation_policy == Policy.REQUIRED
    assert first.user_shares[0].user_id == admin.id
    assert second.group_shares[0].installation_policy is None
    assert not first.follows_marketplace_access
    reset_marketplace_skill_access__no_commit(first.id, admin, session)
    assert first.follows_marketplace_access and not first.user_shares
    assert SkillAccessAdapter().state(first) == SkillAccessAdapter().state(second)
    mutate_resource_access(
        [first.id],
        ResourceAccessChange(group_shares={group_id: Share.VIEWER}),
        admin,
        session,
        SkillAccessAdapter(),
    )
    assert first.follows_marketplace_access  # An identical save is not an override.


def test_personal_sync_preserves_owner_shares(
    session: Session, marketplace: Marketplace
) -> None:
    owner = make_user(session, standard_account=True)
    other = make_user(session)
    marketplace.owner_user_id = owner.id
    marketplace.public_permission = Share.EDITOR  # Personal defaults never propagate.
    apply(session, marketplace, catalog("first"))
    skill = skills(session, marketplace)[0]
    assert skill.author_user_id == owner.id and skill.public_permission is None
    mutate_resource_access(
        [skill.id],
        ResourceAccessChange(user_shares={other.id: Share.VIEWER}),
        owner,
        session,
        SkillAccessAdapter(),
    )
    apply(session, marketplace, catalog("first", "new", body=b"changed"))
    session.expire_all()
    assert skill.user_shares[0].user_id == other.id
    assert skill.public_permission is None
    assert all(row.author_user_id == owner.id for row in skills(session, marketplace))
    admin, _ = manager(session, global_access=True)
    with pytest.raises(OnyxError, match="Personal marketplace"):
        reset_marketplace_skill_access__no_commit(skill.id, admin, session)


def test_scoped_company_skill_and_marketplace_changes(
    session: Session, marketplace: Marketplace
) -> None:
    admin, _ = manager(session, global_access=True)
    scoped, group_id = manager(session, global_access=False)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(group_shares={group_id: Share.VIEWER}),
    )
    apply(session, marketplace, catalog("first"))
    skill = skills(session, marketplace)[0]
    share(
        session,
        marketplace,
        scoped,
        ResourceAccessChange(group_installation_policies={group_id: Policy.DEFAULT}),
    )
    mutate_resource_access(
        [skill.id],
        ResourceAccessChange(
            user_shares={}, group_installation_policies={group_id: Policy.REQUIRED}
        ),
        scoped,
        session,
        SkillAccessAdapter(),
    )
    assert not skill.follows_marketplace_access
    for change in (
        ResourceAccessChange(
            public_permission=Share.VIEWER, set_public_permission=True
        ),
        ResourceAccessChange(installation_policy=Policy.REQUIRED),
        ResourceAccessChange(group_shares={make_group(session).id: Share.VIEWER}),
        ResourceAccessChange(user_shares={make_user(session).id: Share.EDITOR}),
        ResourceAccessChange(user_shares={scoped.id: Share.VIEWER}),
    ):
        with pytest.raises(OnyxError):
            share(session, marketplace, scoped, change)
        with pytest.raises(OnyxError):
            mutate_resource_access(
                [skill.id], change, scoped, session, SkillAccessAdapter()
            )
    with pytest.raises(OnyxError):
        reset_marketplace_skill_access__no_commit(skill.id, scoped, session)


@pytest.mark.parametrize("clear", [False, True])
def test_community_preserves_saved_marketplace_groups(
    session: Session, marketplace: Marketplace, clear: bool
) -> None:
    admin, group_id = manager(session, global_access=True)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(group_shares={group_id: Share.VIEWER}),
    )
    apply(session, marketplace, catalog("first"))

    def update() -> None:
        mutate_resource_access(
            [marketplace.id],
            ResourceAccessChange(
                group_shares={} if clear else {group_id: Share.VIEWER}
            ),
            admin,
            session,
            MarketplaceAccessAdapter(Tier.COMMUNITY),
        )

    if clear:
        with pytest.raises(OnyxError, match="Group access requires a paid tier"):
            update()
    else:
        update()
    session.expire_all()
    assert {share.user_group_id for share in marketplace.group_shares} == {group_id}
    follower = skills(session, marketplace)[0]
    assert {share.user_group_id for share in follower.group_shares} == {group_id}
    assert follower.follows_marketplace_access


def test_community_and_downgrade_cannot_recreate_group_grants(
    session: Session, marketplace: Marketplace, monkeypatch: pytest.MonkeyPatch
) -> None:
    admin, group_id = manager(session, global_access=True)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(group_shares={group_id: Share.VIEWER}),
    )
    apply(session, marketplace, catalog("first"))
    # An expired license or failed tier read cannot erase stored access.
    for tier in (Tier.COMMUNITY, Tier.BUSINESS):
        mutate_resource_access(
            [marketplace.id],
            ResourceAccessChange(),
            admin,
            session,
            MarketplaceAccessAdapter(tier),
        )
        materialize_marketplace_access__no_commit(marketplace.id, session)
        assert marketplace.public_permission is None
        assert skills(session, marketplace)[0].public_permission is None
        assert skills(session, marketplace)[0].group_shares[0].user_group_id == group_id
    remove_custom_user_groups__no_commit(session)
    session.expire_all()
    assert (
        marketplace.public_permission == Share.VIEWER and not marketplace.group_shares
    )
    skill = skills(session, marketplace)[0]
    assert skill.public_permission == Share.VIEWER and not skill.group_shares
    # Persisted defaults remain public even if a later caller still sees the paid tier.
    apply(session, marketplace, catalog("first", "second"))
    assert all(
        row.public_permission == Share.VIEWER and not row.group_shares
        for row in skills(session, marketplace)
    )
    marketplace.public_permission = None
    monkeypatch.setattr("onyx.db.marketplace_access.IS_ENTERPRISE_BUILD", False)
    materialize_marketplace_access__no_commit(marketplace.id, session)
    assert marketplace.public_permission is None
    assert all(
        row.public_permission == Share.VIEWER for row in skills(session, marketplace)
    )


@pytest.mark.parametrize("revoke", [False, True])
def test_reset_endpoint_pushes_once_after_commit_and_rejects_retired(
    session: Session, marketplace: Marketplace, revoke: bool
) -> None:
    admin, group_id = manager(session, global_access=True)
    make_sandbox(session, admin)
    marketplace.public_permission = Share.VIEWER
    apply(session, marketplace, catalog("first"))
    skill = skills(session, marketplace)[0]
    skill.follows_marketplace_access = False
    session.add(
        Skill__User(skill_id=skill.id, user_id=admin.id, permission=Share.EDITOR)
    )
    expected_recipients = set(
        session.scalars(
            select(Sandbox.user_id).where(Sandbox.status == SandboxStatus.RUNNING)
        )
    )
    assert admin.id in expected_recipients
    session.commit()

    def pushed(recipients: set[UUID], db_session: Session) -> None:
        assert not db_session.in_transaction()
        assert recipients == expected_recipients

    def lock_after_revocation(db_session: Session) -> None:
        if revoke:
            with Session(
                db_session.connection(), join_transaction_mode="create_savepoint"
            ) as other:
                other.execute(
                    delete(User__UserGroup).where(
                        User__UserGroup.user_id == admin.id,
                        User__UserGroup.user_group_id == group_id,
                    )
                )
                recompute_user_permissions__no_commit(admin.id, other)
                other.commit()
        lock_group_membership(db_session)

    with (
        patch(
            "onyx.db.resource_access.lock_group_membership",
            side_effect=lock_after_revocation,
        ),
        patch(
            "onyx.server.features.skill.api.push_skills_for_users", side_effect=pushed
        ) as push,
        client_for(admin, session) as client,
    ):
        response = client.post(f"/skills/custom/{skill.id}/reset-marketplace-access")
        if revoke:
            assert response.status_code == 403, response.text
            session.refresh(skill)
            assert not skill.follows_marketplace_access and skill.user_shares
            push.assert_not_called()
            return
        assert response.status_code == 200, response.text
        push.assert_called_once()
        assert not skill.user_shares and skill.follows_marketplace_access
        skill.retired_at = datetime.now(timezone.utc)
        session.commit()
        assert (
            client.post(
                f"/skills/custom/{skill.id}/reset-marketplace-access"
            ).status_code
            == 400
        )
        assert push.call_count == 1


def test_default_update_rolls_back_on_bad_group(
    session: Session, marketplace: Marketplace
) -> None:
    admin, _ = manager(session, global_access=True)
    apply(session, marketplace, catalog("first"))
    with pytest.raises(OnyxError, match="do not exist"):
        share(
            session,
            marketplace,
            admin,
            ResourceAccessChange(
                public_permission=Share.EDITOR,
                set_public_permission=True,
                group_shares={-99: Share.VIEWER},
            ),
        )
    assert marketplace.public_permission is None
    assert skills(session, marketplace)[0].public_permission is None


def test_access_defaults_migration_round_trip(
    isolated_engine: Engine,
) -> None:
    revision = ScriptDirectory(
        str(Path(__file__).resolve().parents[3] / "alembic")
    ).get_revision("703815651f00")
    assert revision is not None
    with Session(isolated_engine) as session:
        source = Marketplace(
            name="Migration catalog",
            provider=MarketplaceProvider.GITHUB,
            provider_config=GitHubMarketplaceConfig(
                owner="acme", repo="tools", ref="main"
            ),
        )
        session.add(source)
        session.flush()
        with Operations.context(MigrationContext.configure(session.connection())):
            revision.module.downgrade()
            revision.module.upgrade()
        session.expire(source)
        assert source.public_permission is None
        assert source.installation_policy == Policy.AVAILABLE


def wait_until_blocked(engine: Engine, pid: int) -> None:
    with engine.connect() as observer:
        deadline = time.monotonic() + 5
        while not observer.scalar(select(func.cardinality(func.pg_blocking_pids(pid)))):
            assert time.monotonic() < deadline
            time.sleep(0.01)


@pytest.mark.parametrize("reset_first", [False, True])
def test_downgrade_serializes_with_marketplace_access(
    isolated_engine: Engine, reset_first: bool
) -> None:
    with Session(isolated_engine) as writer:
        admin, group_id = manager(writer, global_access=True)
        marketplace = Marketplace(
            name="Race",
            provider=MarketplaceProvider.GITHUB,
            provider_config=GitHubMarketplaceConfig(
                owner="acme", repo="tools", ref="main"
            ),
        )
        writer.add(marketplace)
        writer.flush()
        share(
            writer,
            marketplace,
            admin,
            ResourceAccessChange(group_shares={group_id: Share.VIEWER}),
        )
        apply(writer, marketplace, catalog(f"race-{uuid4().hex}"))
        skill = skills(writer, marketplace)[0]
        writer.commit()
        if reset_first:
            skill.follows_marketplace_access = False
            writer.commit()
            reset_marketplace_skill_access__no_commit(skill.id, admin, writer)
        else:
            share(
                writer,
                marketplace,
                admin,
                ResourceAccessChange(
                    group_installation_policies={group_id: Policy.DEFAULT}
                ),
            )
        waiting: Queue[int] = Queue()

        def downgrade() -> None:
            with Session(isolated_engine) as worker:
                worker.execute(text("SET LOCAL statement_timeout = '10s'"))
                pid = worker.scalar(select(func.pg_backend_pid()))
                assert isinstance(pid, int)
                waiting.put(pid)
                remove_custom_user_groups__no_commit(worker)
                worker.commit()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(downgrade)
            try:
                pid = waiting.get(timeout=5)
                wait_until_blocked(isolated_engine, pid)
                writer.commit()
            finally:
                writer.rollback()
            future.result(timeout=15)
        writer.expire_all()
        assert marketplace.public_permission == skill.public_permission == Share.VIEWER
        assert not marketplace.group_shares and not skill.group_shares
        # Repeat with no custom groups: company defaults still become public.
        marketplace.public_permission = None
        skill.public_permission = None
        assert remove_custom_user_groups__no_commit(writer) == 0
        writer.expire_all()
        assert marketplace.public_permission == skill.public_permission == Share.VIEWER
        writer.rollback()
        writer.delete(marketplace)
        writer.commit()


@pytest.mark.parametrize("tier", [Tier.BUSINESS, Tier.COMMUNITY])
def test_not_available_defaults_materialize_with_tier_guards(
    session: Session, marketplace: Marketplace, tier: Tier
) -> None:
    actor, group_id = manager(session, global_access=True)
    apply(session, marketplace, catalog("policy-default"))
    change = ResourceAccessChange(
        installation_policy=Policy.NOT_AVAILABLE,
        group_shares={group_id: Share.VIEWER},
        group_installation_policies={group_id: Policy.NOT_AVAILABLE},
    )
    if tier == Tier.COMMUNITY:
        with pytest.raises(OnyxError, match="paid tier"):
            mutate_resource_access(
                [marketplace.id], change, actor, session, MarketplaceAccessAdapter(tier)
            )
        return
    mutate_resource_access(
        [marketplace.id], change, actor, session, MarketplaceAccessAdapter(tier)
    )
    following = skills(session, marketplace)[0]
    assert following.installation_policy == Policy.NOT_AVAILABLE
    assert following.group_shares[0].installation_policy == Policy.NOT_AVAILABLE
    assert following.follows_marketplace_access
    mutate_resource_access(
        [following.id],
        ResourceAccessChange(installation_policy=Policy.AVAILABLE),
        actor,
        session,
        SkillAccessAdapter(),
    )
    assert not following.follows_marketplace_access
    reset_marketplace_skill_access__no_commit(following.id, actor, session)
    assert following.installation_policy == Policy.NOT_AVAILABLE
    assert following.follows_marketplace_access
