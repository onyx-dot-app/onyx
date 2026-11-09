from collections.abc import Generator
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    ExternalAppType,
    GrantSource,
    Permission,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.external_app import (
    associate_custom_skill_with_external_app__no_commit,
    replace_custom_skill_associations__no_commit,
)
from onyx.db.models import (
    ExternalApp,
    Marketplace,
    PermissionGrant,
    Skill,
    Skill__UserGroup,
    User,
    User__UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.skill import affected_user_ids_for_skills
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.features.skill.api import user_router
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_sandbox,
    make_skill,
    make_user,
)

pytestmark = pytest.mark.usefixtures("tenant_context", "enable_ee")


@pytest.fixture
def session(db_session: Session) -> Generator[Session, None, None]:
    engine = db_session.get_bind()
    assert isinstance(engine, Engine)
    with engine.connect() as connection, connection.begin():
        with Session(connection, join_transaction_mode="create_savepoint") as isolated:
            yield isolated
        connection.rollback()


def client_for(user: User, session: Session) -> TestClient:
    app = FastAPI()
    app.include_router(user_router)
    register_onyx_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: user
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def manager(session: Session, *, global_access: bool) -> tuple[User, int]:
    user = make_user(session, standard_account=True)
    group = make_group(session)
    session.add(
        User__UserGroup(
            user_id=user.id, user_group_id=group.id, is_manager=not global_access
        )
    )
    if global_access:
        session.add(
            PermissionGrant(
                group_id=group.id,
                permission=Permission.MANAGE_SKILLS,
                grant_source=GrantSource.USER,
            )
        )
    session.flush()
    recompute_user_permissions__no_commit(user.id, session)
    session.refresh(user)
    assert not has_global_permission(user, Permission.FULL_ADMIN_PANEL_ACCESS)
    return user, group.id


def group_grant(session: Session, skill: Skill, group_id: int) -> None:
    session.add(
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group_id,
            permission=SkillSharePermission.VIEWER,
            installation_policy=SkillInstallationPolicy.REQUIRED,
        )
    )
    session.flush()


@pytest.mark.parametrize("global_access", [True, False])
def test_company_policy_and_required_delete(
    session: Session, global_access: bool
) -> None:
    user, _ = manager(session, global_access=global_access)
    skill = make_skill(session, author_user_id=user.id)
    with client_for(user, session) as client:
        result = client.patch(
            f"/skills/custom/{skill.id}/share", json={"installation_policy": "REQUIRED"}
        )
        assert result.status_code == (200 if global_access else 403), result.text
        if not global_access:
            skill.installation_policy = SkillInstallationPolicy.REQUIRED
            session.flush()
        result = client.delete(f"/skills/custom/{skill.id}")
        assert result.status_code == (200 if global_access else 403), result.text


def test_scoped_group_settings_and_denials(session: Session) -> None:
    user, group_id = manager(session, global_access=False)
    skill = make_skill(session, author_user_id=user.id)
    group_grant(session, skill, group_id)
    other = make_group(session)
    with client_for(user, session) as client:

        def share(target: int, policy: str | None) -> dict[str, object]:
            return {
                "group_shares": [
                    {
                        "group_id": target,
                        "permission": "VIEWER",
                        "installation_policy": policy,
                    }
                ]
            }

        path = f"/skills/custom/{skill.id}/share"
        assert client.patch(path, json=share(group_id, "DEFAULT")).status_code == 200
        assert client.patch(path, json=share(other.id, "DEFAULT")).status_code == 403
        assert (
            client.patch(path, json={"public_permission": "VIEWER"}).status_code == 403
        )
        result = client.patch(path, json=share(group_id, None))
        assert result.status_code == 200, result.text
        grant = session.get(Skill__UserGroup, (skill.id, group_id))
        assert grant is not None and grant.installation_policy is None


def test_bulk_preserves_groups_and_pushes_once_after_commit(session: Session) -> None:
    user, group_id = manager(session, global_access=True)
    recipient = make_user(session)
    make_sandbox(session, user)
    make_sandbox(session, recipient)
    skills = [make_skill(session, author_user_id=user.id) for _ in range(100)]
    for skill in skills:
        group_grant(session, skill, group_id)
    other_group = make_group(session)
    group_grant(session, skills[0], other_group.id)
    calls: list[set[UUID]] = []

    def push(affected: set[UUID], db_session: Session) -> None:
        assert not db_session.in_transaction()
        calls.append(affected)

    with (
        client_for(user, session) as client,
        patch("onyx.server.features.skill.api.push_skills_for_users", side_effect=push),
        patch(
            "onyx.db.skill.affected_user_ids_for_skills",
            wraps=affected_user_ids_for_skills,
        ) as audiences,
    ):
        response = client.post(
            "/skills/bulk",
            json={
                "skill_ids": [str(skill.id) for skill in skills],
                "action": "share",
                "sharing": {
                    "user_shares": [
                        {"user_id": str(recipient.id), "permission": "VIEWER"}
                    ],
                    "group_shares": [{"group_id": group_id, "permission": "EDITOR"}],
                },
            },
        )
    assert response.status_code == 200, response.text
    assert len(response.json()["succeeded"]) == 100
    assert response.json()["failed"] == []
    assert calls == [{user.id, recipient.id}]
    assert audiences.call_count == 2
    policies = list(
        session.scalars(
            select(Skill__UserGroup.installation_policy).where(
                Skill__UserGroup.skill_id.in_([skill.id for skill in skills])
            )
        )
    )
    assert policies == [SkillInstallationPolicy.REQUIRED] * 101


def test_removed_group_audience_and_omitted_policy(session: Session) -> None:
    user, group_id = manager(session, global_access=True)
    removed = make_user(session)
    other = make_group(session)
    session.add(User__UserGroup(user_id=removed.id, user_group_id=other.id))
    make_sandbox(session, removed)
    skill = make_skill(session, author_user_id=user.id)
    group_grant(session, skill, group_id)
    group_grant(session, skill, other.id)
    with (
        client_for(user, session) as client,
        patch("onyx.server.features.skill.api.push_skills_for_users") as push,
    ):
        response = client.patch(
            f"/skills/custom/{skill.id}/share",
            json={"group_shares": [{"group_id": group_id, "permission": "EDITOR"}]},
        )
    assert response.status_code == 200, response.text
    assert removed.id in push.call_args.args[0]
    grant = session.get(Skill__UserGroup, (skill.id, group_id))
    assert (
        grant is not None
        and grant.installation_policy == SkillInstallationPolicy.REQUIRED
    )
    assert session.get(Skill__UserGroup, (skill.id, other.id)) is None


@pytest.mark.parametrize("replace_links", [False, True])
@pytest.mark.parametrize("public_permission", [None, "VIEWER"])
@pytest.mark.parametrize("bulk", [False, True])
def test_company_marketplace_override_and_app_link(
    session: Session, replace_links: bool, public_permission: str | None, bulk: bool
) -> None:
    user, _ = manager(session, global_access=True)
    market = Marketplace(
        name="Company",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(
            owner="acme", repo="skills", ref="main"
        ),
    )
    session.add(market)
    session.flush()
    skill = make_skill(session, author_user_id=user.id)
    skill.author_user_id = None
    skill.marketplace_id = market.id
    skill.marketplace_entry_key = skill.name
    app = ExternalApp(
        name="Company app",
        app_type=ExternalAppType.CUSTOM,
        auth_template={},
        upstream_url_patterns=[],
    )
    session.add(app)
    session.flush()
    if replace_links:
        replace_custom_skill_associations__no_commit(
            session, external_app_id=app.id, skill_ids=[skill.id]
        )
    else:
        associate_custom_skill_with_external_app__no_commit(
            session, external_app_id=app.id, skill_id=skill.id
        )
    assert skill.public_permission is None
    assert skill.follows_marketplace_access
    with client_for(user, session) as client:
        sharing = {"public_permission": public_permission}
        response = (
            client.post(
                "/skills/bulk",
                json={
                    "action": "share",
                    "skill_ids": [str(skill.id)],
                    "sharing": sharing,
                },
            )
            if bulk
            else client.patch(f"/skills/custom/{skill.id}/share", json=sharing)
        )
    assert response.status_code == 200, response.text
    session.refresh(skill)
    assert skill.follows_marketplace_access == (public_permission is None)
    assert skill.public_permission == public_permission


@pytest.mark.parametrize(
    "operation", ["share", "enable", "patch", "transfer", "delete"]
)
def test_retired_mutations(session: Session, operation: str) -> None:
    user, _ = manager(session, global_access=True)
    skill = make_skill(session, author_user_id=user.id)
    skill.retired_at = datetime.now(timezone.utc)
    session.flush()
    with client_for(user, session) as client:
        path = f"/skills/custom/{skill.id}"
        if operation == "share":
            response = client.patch(
                path + "/share", json={"installation_policy": "AVAILABLE"}
            )
        elif operation == "enable":
            response = client.put(f"/skills/{skill.id}/enabled", json={"enabled": True})
        elif operation == "patch":
            response = client.patch(path, json={"public_permission": "VIEWER"})
        elif operation == "transfer":
            response = client.post(
                path + "/transfer-ownership", json={"new_owner_user_id": str(user.id)}
            )
        else:
            response = client.delete(path)
    assert response.status_code == (200 if operation == "delete" else 400), (
        response.text
    )
    if operation != "delete":
        assert response.json()["detail"] == "retired"


def test_bulk_null_and_retired_partial_failure(session: Session) -> None:
    user, group_id = manager(session, global_access=True)
    live = make_skill(session, author_user_id=user.id)
    retired = make_skill(session, author_user_id=user.id)
    retired.retired_at = datetime.now(timezone.utc)
    group_grant(session, live, group_id)
    group_grant(session, retired, group_id)
    with client_for(user, session) as client:
        response = client.post(
            "/skills/bulk",
            json={
                "action": "share",
                "skill_ids": [str(live.id), str(retired.id)],
                "sharing": {
                    "group_shares": [
                        {
                            "group_id": group_id,
                            "permission": "VIEWER",
                            "installation_policy": None,
                        }
                    ]
                },
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] == [str(live.id)]
    assert response.json()["failed"] == [
        {"skill_id": str(retired.id), "detail": "retired"}
    ]
    grant = session.get(Skill__UserGroup, (live.id, group_id))
    assert grant is not None and grant.installation_policy is None
    grant = session.get(Skill__UserGroup, (retired.id, group_id))
    assert (
        grant is not None
        and grant.installation_policy == SkillInstallationPolicy.REQUIRED
    )
