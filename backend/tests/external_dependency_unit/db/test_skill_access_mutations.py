from collections.abc import Generator
from unittest.mock import patch
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from ee.onyx.server.user_group.api import list_minimal_user_groups
from onyx.auth.permissions import has_global_permission
from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import (
    GrantSource,
    Permission,
    SkillInstallationPolicy,
    SkillSharePermission,
)
from onyx.db.models import (
    PermissionGrant,
    Skill,
    Skill__User,
    Skill__UserGroup,
    User,
    User__UserGroup,
)
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.db.skill import affected_user_ids_for_skills, skill_ownership_is_vacant
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.features.skill.api import user_router
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


def test_scoped_group_shares_and_denials(session: Session) -> None:
    user, group_id = manager(session, global_access=False)
    skill = make_skill(session, author_user_id=user.id)
    group_grant(session, skill, group_id)
    other = make_group(session)
    with client_for(user, session) as client:

        def share(target: int) -> dict[str, object]:
            return {"group_shares": [{"group_id": target, "permission": "EDITOR"}]}

        path = f"/skills/custom/{skill.id}/share"
        result = client.patch(path, json=share(group_id))
        assert result.status_code == 200, result.text
        assert client.patch(path, json=share(other.id)).status_code == 403
        assert (
            client.patch(path, json={"public_permission": "VIEWER"}).status_code == 403
        )
        grant = session.get(Skill__UserGroup, (skill.id, group_id))
        assert grant is not None and grant.permission == SkillSharePermission.EDITOR


def test_skill_shareable_groups_follow_manage_scope(session: Session) -> None:
    def group_ids(user: User, permission: Permission | None) -> set[int]:
        return {
            group.id
            for group in list_minimal_user_groups(
                permission=permission, user=user, db_session=session
            )
        }

    scoped, managed_id = manager(session, global_access=False)
    member_only = make_group(session)
    plain = make_user(session, standard_account=True)
    for user in (scoped, plain):
        session.add(
            User__UserGroup(
                user_id=user.id, user_group_id=member_only.id, is_manager=False
            )
        )
    session.flush()
    for user in (scoped, plain):
        recompute_user_permissions__no_commit(user.id, session)
        session.refresh(user)
    global_manager, _ = manager(session, global_access=True)

    assert group_ids(scoped, Permission.MANAGE_SKILLS) == {managed_id}
    assert group_ids(plain, Permission.MANAGE_SKILLS) == set()
    assert {managed_id, member_only.id} <= group_ids(
        global_manager, Permission.MANAGE_SKILLS
    )
    # Without a permission the route keeps listing the caller's groups.
    assert member_only.id in group_ids(plain, None)


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
    grants = session.execute(
        select(Skill__UserGroup.user_group_id, Skill__UserGroup.permission).where(
            Skill__UserGroup.skill_id.in_([skill.id for skill in skills])
        )
    ).all()
    assert sorted(grants) == sorted(
        [(group_id, SkillSharePermission.EDITOR)] * 100
        + [(other_group.id, SkillSharePermission.VIEWER)]
    )


def test_removed_group_audience(session: Session) -> None:
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
    assert grant is not None and grant.permission == SkillSharePermission.EDITOR
    assert session.get(Skill__UserGroup, (skill.id, other.id)) is None


def test_bulk_uneditable_partial_failure(session: Session) -> None:
    user, group_id = manager(session, global_access=False)
    live = make_skill(session, author_user_id=user.id)
    hidden = make_skill(session, author_user_id=make_user(session).id)
    group_grant(session, live, group_id)
    with client_for(user, session) as client:
        response = client.post(
            "/skills/bulk",
            json={
                "action": "share",
                "skill_ids": [str(live.id), str(hidden.id)],
                "sharing": {
                    "group_shares": [{"group_id": group_id, "permission": "EDITOR"}]
                },
            },
        )
    assert response.status_code == 200, response.text
    assert response.json()["succeeded"] == [str(live.id)]
    assert [item["skill_id"] for item in response.json()["failed"]] == [str(hidden.id)]
    grant = session.get(Skill__UserGroup, (live.id, group_id))
    assert grant is not None and grant.permission == SkillSharePermission.EDITOR
    assert session.get(Skill__UserGroup, (hidden.id, group_id)) is None


def test_share_uses_actor_permissions_read_after_the_lock(session: Session) -> None:
    user, group_id = manager(session, global_access=True)
    skill = make_skill(session, author_user_id=user.id)
    # The request authenticated before the permission removal committed.
    session.expunge(user)
    revoked = session.scalars(
        select(PermissionGrant).where(PermissionGrant.group_id == group_id)
    ).one()
    session.delete(revoked)
    session.flush()
    recompute_user_permissions__no_commit(user.id, session)
    assert has_global_permission(user, Permission.MANAGE_SKILLS)
    with client_for(user, session) as client:
        result = client.patch(
            f"/skills/custom/{skill.id}/share", json={"public_permission": "VIEWER"}
        )
    assert result.status_code == 403, result.text
    session.refresh(skill)
    assert skill.public_permission is None


@pytest.mark.parametrize("owner", ["none", "inactive"])
@pytest.mark.parametrize("global_access", [False, True])
def test_vacant_skill_user_grants_need_global_permission(
    session: Session, global_access: bool, owner: str
) -> None:
    editor, _ = manager(session, global_access=global_access)
    other = make_user(session, standard_account=True)
    if owner == "none":
        skill = make_skill(session, is_public=True)
    else:
        author = make_user(session, standard_account=True)
        author.is_active = False
        skill = make_skill(session, author_user_id=author.id)
    assert skill_ownership_is_vacant(skill)
    session.add(
        Skill__User(
            skill_id=skill.id,
            user_id=editor.id,
            permission=SkillSharePermission.EDITOR,
        )
    )
    session.flush()
    current = [{"user_id": str(editor.id), "permission": "EDITOR"}]
    path = f"/skills/custom/{skill.id}/share"
    with client_for(editor, session) as client:
        kept = client.patch(path, json={"user_shares": current})
        assert kept.status_code == 200, kept.text
        added = client.patch(
            path,
            json={
                "user_shares": [
                    *current,
                    {"user_id": str(other.id), "permission": "VIEWER"},
                ]
            },
        )
    assert added.status_code == (200 if global_access else 403), added.text
    session.expire(skill, ["user_shares"])
    assert {share.user_id for share in skill.user_shares} == (
        {editor.id, other.id} if global_access else {editor.id}
    )
