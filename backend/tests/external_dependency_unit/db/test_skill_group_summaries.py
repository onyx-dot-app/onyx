"""Library group labels obey read authority without exposing editable share lists."""

from typing import Any

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import Permission, SkillInstallationPolicy, SkillSharePermission
from onyx.db.marketplace_access import materialize_marketplace_access__no_commit
from onyx.db.models import (
    Marketplace,
    Marketplace__UserGroup,
    Skill__User,
    Skill__UserGroup,
    User__UserGroup,
)
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_skill,
    make_user,
)
from tests.external_dependency_unit.db.test_marketplace_api import client_for
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


@pytest.mark.parametrize(
    "role,all_groups,own_group",
    [
        ("owner", True, False),
        ("editor", True, False),
        ("viewer", False, False),
        ("member", False, True),
        ("global", True, False),
        ("capped_global", False, True),
        ("scoped", False, True),
        ("capped_scoped", False, True),
    ],
)
def test_library_summaries_are_filtered_by_actor(
    session: Session, role: str, all_groups: bool, own_group: bool
) -> None:
    owner = make_user(session, standard_account=True)
    if "global" in role or "scoped" in role:
        actor, managed_id = manager(session, global_access="global" in role)
    else:
        actor = owner if role == "owner" else make_user(session, standard_account=True)
        managed_id = make_group(session, name="Visible group").id
    other = make_group(session, name="Other group")
    skill = make_skill(session, author_user_id=owner.id, is_public=True)
    for group_id, policy in (
        (managed_id, None),
        (other.id, SkillInstallationPolicy.NOT_AVAILABLE),
    ):
        session.add(
            Skill__UserGroup(
                skill_id=skill.id,
                user_group_id=group_id,
                permission=SkillSharePermission.VIEWER,
                installation_policy=policy,
            )
        )
    if role == "member":
        session.add(User__UserGroup(user_id=actor.id, user_group_id=managed_id))
    if role == "editor":
        session.add(
            Skill__User(
                skill_id=skill.id,
                user_id=actor.id,
                permission=SkillSharePermission.EDITOR,
            )
        )
    session.commit()
    scopes = [Permission.BASIC_ACCESS] if role.startswith("capped_") else None
    with client_for(actor, session, scopes) as client:
        listing = client.get("/skills")
        assert listing.status_code == 200, listing.text
        row = next(
            item for item in listing.json()["customs"] if item["id"] == str(skill.id)
        )
        expected = (
            {managed_id, other.id}
            if all_groups
            else {managed_id}
            if own_group
            else set()
        )
        summaries = row["group_summaries"]
        assert {item["group_id"] for item in summaries} == expected
        assert all(item["source"] == "direct" for item in summaries)
        assert row["group_shares"] == []
        assert row["user_shares"] == []
        detail = client.get(f"/skills/{skill.id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["group_summaries"] == summaries
        if all_groups:
            by_id = {item["group_id"]: item for item in summaries}
            assert by_id[managed_id]["installation_policy"] is None
            assert by_id[other.id]["installation_policy"] == "NOT_AVAILABLE"
            assert by_id[other.id]["group_name"] == other.name


def test_marketplace_summaries_follow_saved_access_provenance(
    session: Session, marketplace: Marketplace
) -> None:
    actor, group_id = manager(session, global_access=True)
    session.add(
        Marketplace__UserGroup(
            marketplace_id=marketplace.id,
            user_group_id=group_id,
            permission=SkillSharePermission.VIEWER,
            installation_policy=SkillInstallationPolicy.REQUIRED,
        )
    )
    apply(session, marketplace, catalog("following", "overridden"))
    materialize_marketplace_access__no_commit(marketplace.id, session)
    imported = {item.name: item for item in skills(session, marketplace)}
    imported["overridden"].follows_marketplace_access = False
    imported["overridden"].group_shares[
        0
    ].installation_policy = SkillInstallationPolicy.AVAILABLE
    session.commit()
    with client_for(actor, session) as client:
        result = client.get("/skills")
        assert result.status_code == 200, result.text
        rows = {item["name"]: item for item in result.json()["customs"]}
        following = rows["following"]["group_summaries"]
        overridden = rows["overridden"]["group_summaries"]
        assert len(following) == len(overridden) == 1
        assert following[0]["source"] == "marketplace"
        assert following[0]["installation_policy"] == "REQUIRED"
        assert overridden[0]["source"] == "direct"
        assert overridden[0]["installation_policy"] == "AVAILABLE"


def test_share_detail_roundtrips_group_overrides(session: Session) -> None:
    actor, group_id = manager(session, global_access=True)
    skill = make_skill(session, author_user_id=actor.id)
    session.add(
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group_id,
            permission=SkillSharePermission.VIEWER,
            installation_policy=SkillInstallationPolicy.NOT_AVAILABLE,
        )
    )
    session.commit()
    path = f"/skills/custom/{skill.id}/share"

    def shared_policy(response_json: dict[str, Any]) -> str | None:
        (share,) = response_json["group_shares"]
        assert share["group_id"] == group_id
        return share["installation_policy"]

    with client_for(actor, session) as client:
        detail = client.get(path)
        assert detail.status_code == 200, detail.text
        assert shared_policy(detail.json()) == "NOT_AVAILABLE"

        # Omitted keeps the override, even when the permission changes.
        kept = client.patch(
            path,
            json={"group_shares": [{"group_id": group_id, "permission": "EDITOR"}]},
        )
        assert kept.status_code == 200, kept.text
        assert shared_policy(kept.json()) == "NOT_AVAILABLE"
        assert kept.json()["group_shares"][0]["permission"] == "EDITOR"

        cleared = client.patch(
            path,
            json={
                "group_shares": [
                    {
                        "group_id": group_id,
                        "permission": "EDITOR",
                        "installation_policy": None,
                    }
                ]
            },
        )
        assert cleared.status_code == 200, cleared.text
        assert shared_policy(cleared.json()) is None

        restored = client.patch(
            path,
            json={
                "group_shares": [
                    {
                        "group_id": group_id,
                        "permission": "EDITOR",
                        "installation_policy": "REQUIRED",
                    }
                ]
            },
        )
        assert restored.status_code == 200, restored.text
        assert shared_policy(client.get(path).json()) == "REQUIRED"
