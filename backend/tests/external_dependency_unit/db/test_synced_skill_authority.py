"""Synced sharing and retired deletion use the same rules in single and bulk writes."""

from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import Permission, SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Marketplace, Skill, Skill__User, Skill__UserGroup
from onyx.server.features.skill import api
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.skill_api_client import client_for
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


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize(
    "role", ["owner", "editor", "scoped", "global", "limited_global"]
)
def test_retired_deletion_requires_owner_or_global(
    session: Session, marketplace: Marketplace, bulk: bool, personal: bool, role: str
) -> None:
    owner = make_user(session, standard_account=True)
    if personal:
        marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("retired"))
    skill = skills(session, marketplace)[0]
    group_id = None
    if role in {"scoped", "global", "limited_global"}:
        actor, group_id = manager(session, global_access=role != "scoped")
    else:
        actor = owner if role == "owner" else make_user(session, standard_account=True)
    if role == "scoped":
        session.add(
            Skill__UserGroup(
                skill_id=skill.id,
                user_group_id=group_id,
                permission=SkillSharePermission.EDITOR,
            )
        )
    elif actor.id != skill.author_user_id:
        session.add(
            Skill__User(
                skill_id=skill.id,
                user_id=actor.id,
                permission=SkillSharePermission.EDITOR,
            )
        )
    skill.retired_at = datetime.now(timezone.utc)
    skill.installation_policy = SkillInstallationPolicy.REQUIRED
    identifier = skill.id
    session.commit()
    allowed = role == "global" or (personal and role == "owner")
    with (
        client_for(
            actor,
            session,
            [Permission.BASIC_ACCESS] if role == "limited_global" else None,
        ) as client,
        patch.object(api, "push_skills_for_users") as push,
        patch.object(api, "delete_unreferenced_skill_bundles") as cleanup,
    ):
        if bulk:
            response = client.post(
                "/skills/bulk",
                json={"action": "delete", "skill_ids": [str(identifier)]},
            )
            assert response.status_code == 200, response.text
            assert response.json()["succeeded"] == (
                [str(identifier)] if allowed else []
            )
            if not allowed:
                assert "owner or global" in response.json()["failed"][0]["detail"]
        else:
            response = client.delete(f"/skills/custom/{identifier}")
            assert response.status_code == (200 if allowed else 403), response.text
            if not allowed:
                push.assert_not_called()
                cleanup.assert_not_called()
    assert (session.get(Skill, identifier) is None) == allowed


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("role", ["owner", "editor", "scoped", "global"])
def test_only_owner_changes_personal_synced_grants(
    session: Session, marketplace: Marketplace, bulk: bool, role: str
) -> None:
    owner = make_user(session, standard_account=True)
    recipient = make_user(session, standard_account=True)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("personal"))
    skill = skills(session, marketplace)[0]
    if role in {"scoped", "global"}:
        actor, group_id = manager(session, global_access=role == "global")
        session.add(
            Skill__UserGroup(
                skill_id=skill.id,
                user_group_id=group_id,
                permission=SkillSharePermission.EDITOR,
            )
        )
    else:
        actor = owner if role == "owner" else make_user(session, standard_account=True)
        if role == "editor":
            session.add(
                Skill__User(
                    skill_id=skill.id,
                    user_id=actor.id,
                    permission=SkillSharePermission.EDITOR,
                )
            )
    session.commit()
    change = {"user_shares": [{"user_id": str(recipient.id), "permission": "VIEWER"}]}
    with (
        client_for(actor, session) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        if bulk:
            response = client.post(
                "/skills/bulk",
                json={
                    "action": "share",
                    "skill_ids": [str(skill.id)],
                    "sharing": change,
                },
            )
            assert response.status_code == 200, response.text
            assert response.json()["succeeded"] == (
                [str(skill.id)] if role == "owner" else []
            )
            if role != "owner":
                assert "Only the owner" in response.json()["failed"][0]["detail"]
        else:
            response = client.patch(f"/skills/custom/{skill.id}/share", json=change)
            assert response.status_code == (200 if role == "owner" else 403), (
                response.text
            )
    session.refresh(skill)
    assert (recipient.id in {share.user_id for share in skill.user_shares}) == (
        role == "owner"
    )


@pytest.mark.parametrize("change", ["group", "public"])
def test_global_manager_cannot_change_personal_synced_audience(
    session: Session, marketplace: Marketplace, change: str
) -> None:
    owner = make_user(session, standard_account=True)
    admin, group = manager(session, global_access=True)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("personal"))
    skill = skills(session, marketplace)[0]
    session.commit()
    payload = (
        {"public_permission": "VIEWER"}
        if change == "public"
        else {"group_shares": [{"group_id": group, "permission": "VIEWER"}]}
    )
    with client_for(admin, session) as client:
        response = client.patch(f"/skills/custom/{skill.id}/share", json=payload)
    assert response.status_code == 403, response.text
    assert "Only the owner" in response.json()["detail"]
    session.refresh(skill)
    assert skill.public_permission is None and not skill.group_shares


def test_policy_change_accepts_unchanged_personal_shares(
    session: Session, marketplace: Marketplace
) -> None:
    owner = make_user(session, standard_account=True)
    admin, group = manager(session, global_access=True)
    recipient = make_user(session, standard_account=True)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("personal"))
    skill = skills(session, marketplace)[0]
    session.add(
        Skill__User(
            skill_id=skill.id,
            user_id=recipient.id,
            permission=SkillSharePermission.VIEWER,
        )
    )
    session.add(
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group,
            permission=SkillSharePermission.VIEWER,
        )
    )
    session.commit()
    with (
        client_for(admin, session) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        response = client.patch(
            f"/skills/custom/{skill.id}/share",
            json={
                "installation_policy": SkillInstallationPolicy.REQUIRED.value,
                "user_shares": [{"user_id": str(recipient.id), "permission": "VIEWER"}],
                "group_shares": [{"group_id": group, "permission": "VIEWER"}],
                "public_permission": None,
            },
        )
    assert response.status_code == 200, response.text
    session.refresh(skill)
    assert skill.installation_policy == SkillInstallationPolicy.REQUIRED
    assert skill.user_shares[0].user_id == recipient.id
    assert skill.group_shares[0].user_group_id == group


@pytest.mark.parametrize("limited", [False, True])
def test_reset_requires_manage_skills_token_scope(
    session: Session, marketplace: Marketplace, limited: bool
) -> None:
    admin, _ = manager(session, global_access=True)
    apply(session, marketplace, catalog("company"))
    skill = skills(session, marketplace)[0]
    skill.follows_marketplace_access = False
    session.commit()
    scopes = (
        [Permission.BASIC_ACCESS]
        if limited
        else [Permission.BASIC_ACCESS, Permission.MANAGE_SKILLS]
    )
    with (
        client_for(admin, session, scopes) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        response = client.post(f"/skills/custom/{skill.id}/reset-marketplace-access")
    assert response.status_code == (403 if limited else 200), response.text
    session.refresh(skill)
    assert skill.follows_marketplace_access != limited


@pytest.mark.parametrize("bulk", [False, True])
def test_personal_owner_controls_audience_but_not_installation(
    session: Session, marketplace: Marketplace, bulk: bool
) -> None:
    owner = make_user(session, standard_account=True)
    _, group = manager(session, global_access=False)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("personal"))
    skill = skills(session, marketplace)[0]
    session.commit()
    change = {
        "public_permission": "VIEWER",
        "group_shares": [
            {"group_id": group, "permission": "VIEWER", "installation_policy": None}
        ],
    }
    with (
        client_for(owner, session) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        response = (
            client.post(
                "/skills/bulk",
                json={
                    "action": "share",
                    "skill_ids": [str(skill.id)],
                    "sharing": change,
                },
            )
            if bulk
            else client.patch(f"/skills/custom/{skill.id}/share", json=change)
        )
        assert response.status_code == 200, response.text
        if bulk:
            assert response.json()["succeeded"] == [str(skill.id)]
        session.refresh(skill)
        assert skill.public_permission == SkillSharePermission.VIEWER
        assert skill.group_shares[0].user_group_id == group
        for request in (
            {"installation_policy": "REQUIRED"},
            {
                "group_shares": [
                    {
                        "group_id": group,
                        "permission": "VIEWER",
                        "installation_policy": "REQUIRED",
                    }
                ]
            },
        ):
            denied = client.patch(f"/skills/custom/{skill.id}/share", json=request)
            assert denied.status_code == 403, denied.text
        response = client.patch(
            f"/skills/custom/{skill.id}", json={"public_permission": None}
        )
        assert response.status_code == 200, response.text
        session.refresh(skill)
        assert skill.public_permission is None


@pytest.mark.parametrize("scopes", [None, [Permission.BASIC_ACCESS]])
def test_scoped_owner_keeps_personal_audience_authority(
    session: Session, marketplace: Marketplace, scopes: list[Permission] | None
) -> None:
    owner, own_group = manager(session, global_access=False)
    _, outside_group = manager(session, global_access=False)
    marketplace.owner_user_id = owner.id
    apply(session, marketplace, catalog("personal"))
    skill = skills(session, marketplace)[0]
    session.commit()
    with (
        client_for(owner, session, scopes) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        published = client.patch(
            f"/skills/custom/{skill.id}/share", json={"public_permission": "VIEWER"}
        )
        assert published.status_code == 200, published.text
        for group in (own_group, outside_group):
            response = client.patch(
                f"/skills/custom/{skill.id}/share",
                json={"group_shares": [{"group_id": group, "permission": "VIEWER"}]},
            )
            assert response.status_code == 200, response.text
        refused = client.patch(
            f"/skills/custom/{skill.id}/share",
            json={
                "group_shares": [
                    {
                        "group_id": outside_group,
                        "permission": "VIEWER",
                        "installation_policy": "REQUIRED",
                    }
                ]
            },
        )
        assert refused.status_code == 403, refused.text
