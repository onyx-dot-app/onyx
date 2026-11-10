"""Retired history stays readable only to the owner or a scoped-token global manager."""

from datetime import datetime, timezone

import pytest
from fastapi import Request
from sqlalchemy.orm import Session

from onyx.db.enums import Permission, SkillSharePermission
from onyx.db.models import Marketplace, Skill, Skill__User, User
from onyx.server.features.skill import api
from onyx.skills.marketplace.models import GitHubMarketplaceConfig, MarketplaceProvider
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.skill_api_client import client_for
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_version_writes import bundle, upload
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user


@pytest.mark.parametrize("personal", [False, True])
@pytest.mark.parametrize(
    "role", ["owner", "editor", "viewer", "global", "limited_global"]
)
def test_retired_history_authority_and_restore_refusal(
    session: Session, user: User, personal: bool, role: str
) -> None:
    created = api.create_custom_skill(
        upload(bundle("retired-history")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    skill = session.get(Skill, created.id)
    assert skill is not None and skill.current_version_id is not None
    source = Marketplace(
        name="History source",
        provider=MarketplaceProvider.GITHUB,
        provider_config=GitHubMarketplaceConfig(owner="acme", repo="tools", ref="main"),
        owner_user_id=user.id if personal else None,
    )
    session.add(source)
    session.flush()
    skill.marketplace_id = source.id
    skill.marketplace_entry_key = "history/retired-history"
    skill.author_user_id = user.id if personal else None
    skill.retired_at = datetime.now(timezone.utc)
    if role in {"global", "limited_global"}:
        actor, _ = manager(session, global_access=True)
    else:
        actor = user if role == "owner" else make_user(session, standard_account=True)
    if role in {"editor", "viewer", "limited_global"}:
        session.add(
            Skill__User(
                skill_id=skill.id,
                user_id=actor.id,
                permission=SkillSharePermission.VIEWER
                if role == "viewer"
                else SkillSharePermission.EDITOR,
            )
        )
    version_id = skill.current_version_id
    session.commit()
    allowed = role == "global" or (personal and role == "owner")
    with client_for(
        actor, session, [Permission.BASIC_ACCESS] if role == "limited_global" else None
    ) as client:
        path = f"/skills/custom/{skill.id}/versions"
        history = client.get(path)
        preview = client.get(f"{path}/{version_id}")
        assert history.status_code == (200 if allowed else 404), history.text
        assert preview.status_code == (200 if allowed else 404), preview.text
        if allowed:
            assert history.json()[0]["id"] == str(version_id)
            assert preview.json()["instructions_markdown"] == "First instructions"
        assert client.post(f"{path}/{version_id}/restore").status_code != 200
        library = client.get("/skills")
        assert library.status_code == 200
        assert str(skill.id) not in [row["id"] for row in library.json()["customs"]]
