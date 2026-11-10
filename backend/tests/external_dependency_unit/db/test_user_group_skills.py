"""Group Skills routes against migrated PostgreSQL."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

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
    Skill__UserGroup,
    User,
    User__UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.resource_access import ResourceAccessChange, mutate_resource_access
from onyx.db.skill import SkillAccessAdapter
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.auth_check import check_router_auth
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    make_built_in_skill_row,
    make_group,
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
def test_read_token_scopes(
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
    with client_for(admin, session, scopes) as client:
        response = client.get(f"{GROUPS}/{target.id}/skills")
        assert response.status_code == read, response.text
        if read == 200:
            assert response.json()["skills" if kind == "skill" else "marketplaces"][0][
                "can_edit"
            ] is (write == 200)


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


def test_read_requires_group_scope_without_membership_lock(session: Session) -> None:
    scoped, managed = manager(session, global_access=False)
    global_manager, _ = manager(session, global_access=True)
    basic = make_user(session, standard_account=True)
    other = make_group(session)
    session.commit()
    with patch(
        "onyx.db.resource_access.lock_group_membership",
        side_effect=AssertionError("read took the membership lock"),
    ):
        with client_for(scoped, session) as client:
            assert client.get(f"{GROUPS}/{managed}/skills").status_code == 200
            assert client.get(f"{GROUPS}/{other.id}/skills").status_code == 404
        with client_for(global_manager, session) as client:
            assert client.get(f"{GROUPS}/{other.id}/skills").status_code == 200
        with client_for(basic, session) as client:
            assert client.get(f"{GROUPS}/{managed}/skills").status_code == 403
