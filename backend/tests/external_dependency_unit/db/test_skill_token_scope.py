"""Token caps apply again at the sharing boundary, including after actor reload."""

from unittest.mock import patch

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import Permission, SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Marketplace, Skill__User, Skill__UserGroup
from onyx.server.features.skill import api
from tests.external_dependency_unit.craft.db_helpers import make_skill, make_user
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
@pytest.mark.parametrize("source", ["uploaded", "personal", "company"])
@pytest.mark.parametrize("change", ["policy", "group_policy", "public"])
@pytest.mark.parametrize("limited", [True, False])
def test_global_authority_is_capped_for_share_mutations(
    session: Session,
    marketplace: Marketplace,
    bulk: bool,
    source: str,
    change: str,
    limited: bool,
) -> None:
    actor, group = manager(session, global_access=True)
    owner = make_user(session, standard_account=True)
    if source == "uploaded":
        skill = make_skill(session, author_user_id=owner.id)
    else:
        if source == "personal":
            marketplace.owner_user_id = owner.id
        apply(session, marketplace, catalog("token-target"))
        skill = skills(session, marketplace)[0]
    # Direct EDIT isolates permission escalation from the separate management-only fetch gate.
    session.add(
        Skill__User(
            skill_id=skill.id, user_id=actor.id, permission=SkillSharePermission.EDITOR
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
    payload = (
        {"installation_policy": "REQUIRED"}
        if change == "policy"
        else {"public_permission": "VIEWER"}
        if change == "public"
        else {
            "group_shares": [
                {
                    "group_id": group,
                    "permission": "VIEWER",
                    "installation_policy": "REQUIRED",
                }
            ]
        }
    )
    allowed = not limited and not (source == "personal" and change == "public")
    with (
        client_for(
            actor,
            session,
            [Permission.BASIC_ACCESS]
            if limited
            else [Permission.BASIC_ACCESS, Permission.MANAGE_SKILLS],
        ) as client,
        patch.object(api, "push_skills_for_users") as push,
    ):
        response = (
            client.post(
                "/skills/bulk",
                json={
                    "action": "share",
                    "skill_ids": [str(skill.id)],
                    "sharing": payload,
                },
            )
            if bulk
            else client.patch(f"/skills/custom/{skill.id}/share", json=payload)
        )
        if bulk:
            assert response.status_code == 200, response.text
            assert response.json()["succeeded"] == ([str(skill.id)] if allowed else [])
        else:
            assert response.status_code == (200 if allowed else 403), response.text
        if not allowed:
            if bulk:
                push.assert_called_once_with(set(), session)
            else:
                push.assert_not_called()
    session.refresh(skill)
    assert skill.follows_marketplace_access == (source != "company" or not allowed)
    assert skill.installation_policy == (
        SkillInstallationPolicy.REQUIRED
        if allowed and change == "policy"
        else SkillInstallationPolicy.AVAILABLE
    )
    assert skill.public_permission == (
        SkillSharePermission.VIEWER if allowed and change == "public" else None
    )
    assert skill.group_shares[0].installation_policy == (
        SkillInstallationPolicy.REQUIRED
        if allowed and change == "group_policy"
        else None
    )


@pytest.mark.parametrize("grant", ["none", "direct", "scoped"])
def test_limited_token_cannot_use_management_to_read_or_patch(
    session: Session, grant: str
) -> None:
    actor, group = manager(session, global_access=grant != "scoped")
    owner = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=owner.id)
    if grant == "direct":
        session.add(
            Skill__User(
                skill_id=skill.id,
                user_id=actor.id,
                permission=SkillSharePermission.EDITOR,
            )
        )
    elif grant == "scoped":
        session.add(
            Skill__UserGroup(
                skill_id=skill.id,
                user_group_id=group,
                permission=SkillSharePermission.VIEWER,
            )
        )
    session.commit()
    with client_for(actor, session, [Permission.BASIC_ACCESS]) as client:
        read = client.get(f"/skills/custom/{skill.id}/share")
        assert read.status_code == (200 if grant == "direct" else 404), read.text
        changed = client.patch(
            f"/skills/custom/{skill.id}", json={"public_permission": "VIEWER"}
        )
        assert changed.status_code == (403 if grant == "direct" else 404), changed.text
    session.refresh(skill)
    assert skill.public_permission is None


@pytest.mark.parametrize("bulk", [False, True])
def test_basic_token_keeps_explicit_editor_sharing_rights(
    session: Session, bulk: bool
) -> None:
    actor, _ = manager(session, global_access=True)
    owner = make_user(session, standard_account=True)
    recipient = make_user(session, standard_account=True)
    skill = make_skill(session, author_user_id=owner.id)
    session.add(
        Skill__User(
            skill_id=skill.id, user_id=actor.id, permission=SkillSharePermission.EDITOR
        )
    )
    session.commit()
    payload = {
        "user_shares": [
            {"user_id": str(actor.id), "permission": "EDITOR"},
            {"user_id": str(recipient.id), "permission": "VIEWER"},
        ]
    }
    with (
        client_for(actor, session, [Permission.BASIC_ACCESS]) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        response = (
            client.post(
                "/skills/bulk",
                json={
                    "action": "share",
                    "skill_ids": [str(skill.id)],
                    "sharing": payload,
                },
            )
            if bulk
            else client.patch(f"/skills/custom/{skill.id}/share", json=payload)
        )
        assert response.status_code == 200, response.text
        if bulk:
            assert response.json()["succeeded"] == [str(skill.id)]
    session.refresh(skill)
    assert recipient.id in {share.user_id for share in skill.user_shares}
