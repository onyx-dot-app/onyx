"""Group Skills routes against migrated PostgreSQL."""

from collections.abc import Callable
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from httpx import Response
from sqlalchemy import delete
from sqlalchemy.orm import Session

from ee.onyx.server.middleware.tier_gate import _required_tier
from ee.onyx.server.user_group.api import router
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import GrantSource, Permission
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.enums import SkillSharePermission as Share
from onyx.db.models import (
    Marketplace,
    Marketplace__UserGroup,
    PermissionGrant,
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    User__UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.resource_access import ResourceAccessChange, mutate_resource_access
from onyx.db.skill import SkillAccessAdapter
from onyx.db.users import lock_group_membership
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.auth_check import check_router_auth
from onyx.server.settings.models import Tier
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_group,
    make_sandbox,
    make_skill,
    make_user,
)
from tests.external_dependency_unit.db.test_marketplace_access import share
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    apply,
    catalog,
    skills,
)
from tests.external_dependency_unit.db.test_marketplace_reconciliation import (
    marketplace as marketplace,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")
API = "ee.onyx.server.user_group.api"
GROUPS = "/manage/admin/user-group"


def client_for(
    user: User, session: Session, scopes: list[Permission] | None = None
) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    register_onyx_exception_handlers(app)

    def actor(request: Request) -> User:
        request.state.token_scopes = scopes
        return user

    app.dependency_overrides[current_user] = actor
    app.dependency_overrides[get_session] = lambda: session
    check_router_auth(app)
    return TestClient(app)


def group_admin(session: Session) -> tuple[User, int]:
    user = make_user(session, standard_account=True)
    group = make_group(session)
    session.add(User__UserGroup(user_id=user.id, user_group_id=group.id))
    for permission in (Permission.MANAGE_SKILLS, Permission.MANAGE_USER_GROUPS):
        session.add(
            PermissionGrant(
                group_id=group.id, permission=permission, grant_source=GrantSource.USER
            )
        )
    session.flush()
    recompute_user_permissions__no_commit(user.id, session)
    session.refresh(user)
    return user, group.id


def grant(
    session: Session,
    skill: Skill,
    group_id: int,
    policy: Policy | None,
    permission: Share = Share.VIEWER,
) -> None:
    session.add(
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group_id,
            permission=permission,
            installation_policy=policy,
        )
    )
    session.flush()


def put(
    client: TestClient,
    group_id: int,
    resource: Skill | Marketplace,
    policy: str | None = "REQUIRED",
) -> Response:
    kind = "skills" if isinstance(resource, Skill) else "marketplaces"
    return client.put(
        f"{GROUPS}/{group_id}/{kind}/{resource.id}/installation-policy",
        json={"installation_policy": policy},
    )


def shares(session: Session, resource: Skill | Marketplace) -> dict[int, object]:
    session.expire_all()
    return {
        row.user_group_id: (row.permission, row.installation_policy)
        for row in resource.group_shares
    }


def recorder(pushes: list[set[UUID]]) -> Callable[[set[UUID], Session], None]:
    def push(affected: set[UUID], db_session: Session) -> None:
        assert not db_session.in_transaction()
        pushes.append(affected)

    return push


def member(session: Session, group_id: int) -> User:
    user = make_user(session)
    session.add(User__UserGroup(user_id=user.id, user_group_id=group_id))
    make_sandbox(session, user)
    return user


def personal_skill(session: Session, owner: User) -> Skill:
    source = Marketplace(
        name="Personal",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="me", repo="mine", ref="main"),
        owner_user_id=owner.id,
        webhook_id="secret-hook",
    )
    session.add(source)
    session.flush()
    skill = make_skill(session, name="personal", author_user_id=owner.id)
    skill.public_permission = None
    skill.marketplace_id = source.id
    skill.marketplace_entry_key = "plugin/personal"
    session.add(
        Marketplace__UserGroup(
            marketplace_id=source.id,
            user_group_id=make_group(session).id,
            permission=Share.VIEWER,
        )
    )
    session.flush()
    return skill


def test_list_shows_marketplaces_and_direct_skills_only(
    session: Session, marketplace: Marketplace
) -> None:
    admin, _ = group_admin(session)
    target = make_group(session)
    other = make_group(session)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(
            group_shares={target.id: Share.VIEWER, other.id: Share.EDITOR},
            group_installation_policies={target.id: Policy.REQUIRED},
        ),
    )
    apply(session, marketplace, catalog("detached", "follower"))
    detached, follower = sorted(skills(session, marketplace), key=lambda s: s.name)
    mutate_resource_access(
        [detached.id],
        ResourceAccessChange(user_shares={admin.id: Share.EDITOR}),
        admin,
        session,
        SkillAccessAdapter(),
    )
    uploaded = make_skill(session, name="uploaded", author_user_id=admin.id)
    grant(session, uploaded, target.id, None, Share.EDITOR)
    grant(session, uploaded, other.id, Policy.NOT_AVAILABLE)
    personal = personal_skill(session, make_user(session, standard_account=True))
    grant(session, personal, target.id, Policy.DEFAULT)
    retired = make_skill(session, name="retired", author_user_id=admin.id)
    grant(session, retired, target.id, Policy.REQUIRED)
    retired.retired_at = datetime.now(timezone.utc)
    session.commit()

    with client_for(admin, session) as client:
        response = client.get(f"{GROUPS}/{target.id}/skills")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["marketplaces"] == [
        {
            "marketplace_id": str(marketplace.id),
            "name": marketplace.name,
            "permission": "VIEWER",
            "company_installation_policy": "AVAILABLE",
            "group_installation_policy": "REQUIRED",
            "effective_installation_policy": "REQUIRED",
            "following_skill_count": 1,
            "can_edit": True,
        }
    ]
    rows = {row["name"]: row for row in body["skills"]}
    assert set(rows) == {"detached", "personal", "uploaded"}
    assert str(follower.id) not in response.text
    assert rows["detached"]["source"] == "COMPANY_MARKETPLACE"
    assert rows["detached"]["marketplace_name"] == marketplace.name
    assert rows["personal"]["source"] == "PERSONAL_MARKETPLACE"
    assert rows["uploaded"] == {
        "skill_id": str(uploaded.id),
        "name": "uploaded",
        "description": "d",
        "source": "UPLOADED",
        "marketplace_id": None,
        "marketplace_name": None,
        "permission": "EDITOR",
        "company_installation_policy": "AVAILABLE",
        "group_installation_policy": None,
        "effective_installation_policy": "AVAILABLE",
        "can_edit": True,
    }
    for leaked in ("secret-hook", "NOT_AVAILABLE", "provider_config", "owner_user_id"):
        assert leaked not in response.text


def test_skill_setting_preserves_access_and_pushes_once(session: Session) -> None:
    admin, _ = group_admin(session)
    target = make_group(session)
    other = make_group(session)
    recipient = member(session, target.id)
    skill = make_skill(session, author_user_id=admin.id)
    skill.public_permission = None
    grant(session, skill, target.id, Policy.REQUIRED, Share.EDITOR)
    grant(session, skill, other.id, Policy.DEFAULT)
    session.add(
        Skill__User(skill_id=skill.id, user_id=recipient.id, permission=Share.VIEWER)
    )
    session.commit()
    pushes: list[set[UUID]] = []
    with (
        patch(f"{API}.push_skills_for_users", side_effect=recorder(pushes)),
        client_for(admin, session) as client,
    ):
        for policy in [*Policy, None]:
            value = policy.value if policy is not None else None
            response = put(client, target.id, skill, value)
            assert response.status_code == 200, response.text
            assert response.json()["skills"][0]["group_installation_policy"] == value
            assert shares(session, skill) == {
                target.id: (Share.EDITOR, policy),
                other.id: (Share.VIEWER, Policy.DEFAULT),
            }
            assert [row.user_id for row in skill.user_shares] == [recipient.id]
            assert skill.public_permission is None
            assert skill.installation_policy == Policy.AVAILABLE
        assert len(pushes) == 5 and all(recipient.id in sent for sent in pushes)

        unshared = make_skill(session, author_user_id=admin.id)
        session.commit()
        assert put(client, target.id, unshared).status_code == 400
        skill.retired_at = datetime.now(timezone.utc)
        session.commit()
        response = put(client, target.id, skill)
        assert response.status_code == 400 and "retired" in response.text
        assert len(pushes) == 5


def test_marketplace_setting_updates_followers_only(
    session: Session, marketplace: Marketplace
) -> None:
    admin, _ = group_admin(session)
    target = make_group(session)
    other = make_group(session)
    recipient = member(session, target.id)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(
            group_shares={target.id: Share.EDITOR, other.id: Share.VIEWER},
            group_installation_policies={other.id: Policy.NOT_AVAILABLE},
        ),
    )
    apply(session, marketplace, catalog("detached", "follower"))
    detached, follower = sorted(skills(session, marketplace), key=lambda s: s.name)
    mutate_resource_access(
        [detached.id],
        ResourceAccessChange(group_installation_policies={target.id: Policy.DEFAULT}),
        admin,
        session,
        SkillAccessAdapter(),
    )
    session.commit()
    pushes: list[set[UUID]] = []
    with (
        patch(f"{API}.push_skills_for_users", side_effect=recorder(pushes)),
        patch(f"{API}.get_current_tier", return_value=Tier.BUSINESS),
        client_for(admin, session) as client,
    ):
        for policy in (Policy.REQUIRED, None):
            value = policy.value if policy is not None else None
            response = put(client, target.id, marketplace, value)
            assert response.status_code == 200, response.text
            row = response.json()["marketplaces"][0]
            assert row["group_installation_policy"] == value
            expected = {
                target.id: (Share.EDITOR, policy),
                other.id: (Share.VIEWER, Policy.NOT_AVAILABLE),
            }
            assert shares(session, marketplace) == expected
            assert shares(session, follower) == expected
            assert follower.follows_marketplace_access
            assert shares(session, detached)[target.id] == (
                Share.EDITOR,
                Policy.DEFAULT,
            )
            assert marketplace.public_permission is None
        assert len(pushes) == 2 and all(recipient.id in sent for sent in pushes)

        response = put(client, target.id, follower)
        assert response.status_code == 400 and "marketplace" in response.text
        session.expire_all()
        assert follower.follows_marketplace_access
        personal = personal_skill(session, admin)
        session.commit()
        source = session.get(Marketplace, personal.marketplace_id)
        assert source is not None
        assert put(client, target.id, source).status_code == 400
        assert len(pushes) == 2


def test_group_and_skill_authority(session: Session, marketplace: Marketplace) -> None:
    admin, _ = group_admin(session)
    scoped, managed = manager(session, global_access=False)
    skills_only, _ = manager(session, global_access=True)
    basic = make_user(session, standard_account=True)
    unmanaged = make_group(session)
    private = make_skill(session, name="private", author_user_id=admin.id)
    private.public_permission = None
    grant(session, private, managed, None)
    wide = make_skill(session, name="wide", author_user_id=admin.id)
    wide.public_permission = None
    grant(session, wide, managed, None)
    grant(session, wide, unmanaged.id, None)
    share(
        session,
        marketplace,
        admin,
        ResourceAccessChange(group_shares={managed: Share.VIEWER}),
    )
    session.commit()
    with (
        patch(f"{API}.push_skills_for_users"),
        patch(f"{API}.get_current_tier", return_value=Tier.BUSINESS),
    ):
        with client_for(scoped, session) as client:
            body = client.get(f"{GROUPS}/{managed}/skills").json()
            assert {row["name"]: row["can_edit"] for row in body["skills"]} == {
                "private": True,
                "wide": False,
            }
            assert body["marketplaces"][0]["can_edit"] is True
            assert client.get(f"{GROUPS}/{unmanaged.id}/skills").status_code == 404
            assert put(client, managed, private, "DEFAULT").status_code == 200
            # A1 hides a Skill outside the manager's scope.
            assert put(client, managed, wide).status_code == 404
            assert put(client, unmanaged.id, wide).status_code == 403
            assert put(client, managed, marketplace).status_code == 200
        with client_for(skills_only, session) as client:
            assert client.get(f"{GROUPS}/{managed}/skills").status_code == 200
            assert put(client, managed, private, "DEFAULT").status_code == 200
            assert put(client, managed, marketplace).status_code == 200
        with client_for(basic, session) as client:
            assert client.get(f"{GROUPS}/{managed}/skills").status_code == 403
        with client_for(admin, session) as client:
            assert client.get(f"{GROUPS}/999999/skills").status_code == 404
    assert shares(session, wide) == {
        managed: (Share.VIEWER, None),
        unmanaged.id: (Share.VIEWER, None),
    }
    assert shares(session, private)[managed] == (Share.VIEWER, Policy.DEFAULT)
    assert _required_tier(f"{GROUPS}/{managed}/skills") == Tier.BUSINESS


@pytest.mark.parametrize(
    ("scopes", "read", "write"),
    [
        ([Permission.BASIC_ACCESS], 403, 403),
        ([Permission.MANAGE_SKILLS], 200, 200),
        ([Permission.MANAGE_USER_GROUPS], 403, 403),
        ([Permission.MANAGE_SKILLS, Permission.READ_USER_GROUPS], 200, 200),
        ([Permission.MANAGE_SKILLS, Permission.MANAGE_USER_GROUPS], 200, 200),
        (None, 200, 200),
    ],
)
@pytest.mark.parametrize("kind", ["skill", "marketplace"])
def test_token_scopes(
    session: Session,
    marketplace: Marketplace,
    scopes: list[Permission] | None,
    read: int,
    write: int,
    kind: str,
) -> None:
    admin, _ = group_admin(session)
    target = make_group(session)
    resource: Skill | Marketplace
    if kind == "skill":
        resource = make_skill(session, author_user_id=admin.id)
        grant(session, resource, target.id, None)
    else:
        resource = marketplace
        session.add(
            Marketplace__UserGroup(
                marketplace_id=resource.id,
                user_group_id=target.id,
                permission=Share.VIEWER,
            )
        )
    session.commit()
    with (
        patch(f"{API}.push_skills_for_users"),
        patch(f"{API}.get_current_tier", return_value=Tier.BUSINESS),
        client_for(admin, session, scopes) as client,
    ):
        response = client.get(f"{GROUPS}/{target.id}/skills")
        assert response.status_code == read, response.text
        if read == 200:
            assert response.json()["skills" if kind == "skill" else "marketplaces"][0][
                "can_edit"
            ] is (write == 200)
        assert put(client, target.id, resource).status_code == write
    expected = Policy.REQUIRED if write == 200 else None
    assert shares(session, resource) == {target.id: (Share.VIEWER, expected)}


def test_fresh_authority_under_lock_and_lock_free_read(session: Session) -> None:
    admin, admin_group = group_admin(session)
    target = make_group(session)
    skill = make_skill(session, author_user_id=admin.id)
    grant(session, skill, target.id, None)
    session.commit()

    def revoke_then_lock(db_session: Session) -> None:
        with Session(
            db_session.connection(), join_transaction_mode="create_savepoint"
        ) as other:
            other.execute(
                delete(User__UserGroup).where(
                    User__UserGroup.user_id == admin.id,
                    User__UserGroup.user_group_id == admin_group,
                )
            )
            recompute_user_permissions__no_commit(admin.id, other)
            other.commit()
        lock_group_membership(db_session)

    lock = "onyx.db.resource_access.lock_group_membership"
    with (
        patch(lock, side_effect=AssertionError("read took the membership lock")),
        client_for(admin, session) as client,
    ):
        assert client.get(f"{GROUPS}/{target.id}/skills").status_code == 200
    with (
        patch(lock, side_effect=revoke_then_lock),
        patch(f"{API}.push_skills_for_users") as push,
        client_for(admin, session) as client,
    ):
        assert put(client, target.id, skill).status_code == 403
        push.assert_not_called()
    assert shares(session, skill) == {target.id: (Share.VIEWER, None)}


@pytest.mark.parametrize("outside_scope", ["public", "other_group"])
def test_scoped_marketplace_policy_keeps_resource_scope(
    session: Session, marketplace: Marketplace, outside_scope: str
) -> None:
    scoped, managed = manager(session, global_access=False)
    session.add(
        Marketplace__UserGroup(
            marketplace_id=marketplace.id,
            user_group_id=managed,
            permission=Share.VIEWER,
        )
    )
    if outside_scope == "public":
        marketplace.public_permission = Share.VIEWER
    else:
        session.add(
            Marketplace__UserGroup(
                marketplace_id=marketplace.id,
                user_group_id=make_group(session).id,
                permission=Share.VIEWER,
            )
        )
    session.commit()
    with (
        patch(f"{API}.push_skills_for_users") as push,
        patch(f"{API}.get_current_tier", return_value=Tier.BUSINESS),
        client_for(scoped, session, [Permission.MANAGE_SKILLS]) as client,
    ):
        response = client.get(f"{GROUPS}/{managed}/skills")
        assert response.status_code == 200
        assert response.json()["marketplaces"][0]["can_edit"] is False
        assert put(client, managed, marketplace).status_code == 403
        push.assert_not_called()
    assert shares(session, marketplace)[managed] == (Share.VIEWER, None)


def test_builtin_group_row_is_read_only(session: Session) -> None:
    admin, _ = group_admin(session)
    target = make_group(session)
    skill = make_built_in_skill_row(session, built_in_skill_id="g4-seeded-builtin")
    grant(session, skill, target.id, None)
    session.commit()
    with client_for(admin, session) as client:
        response = client.get(f"{GROUPS}/{target.id}/skills")
        assert response.status_code == 200
        row = response.json()["skills"][0]
        assert row["source"] == "BUILT_IN"
        assert row["can_edit"] is False
        assert put(client, target.id, skill).status_code == 404
