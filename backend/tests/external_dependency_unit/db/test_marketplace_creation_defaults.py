"""Company defaults and the first sync request publish as one transaction."""

from unittest.mock import Mock, patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Marketplace, Skill
from onyx.server.features.skill import marketplace_api as api
from onyx.server.settings.models import Tier
from onyx.skills.sync import sync_marketplace
from shared_configs.contextvars import get_current_tenant_id
from tests.external_dependency_unit.db.test_marketplace_api import SOURCE, client_for
from tests.external_dependency_unit.db.test_marketplace_api import github as github
from tests.external_dependency_unit.db.test_marketplace_management import connect
from tests.external_dependency_unit.db.test_marketplace_sync import (
    GitHub,
    catalog_bytes,
)
from tests.external_dependency_unit.db.test_marketplace_sync_tasks import (
    broker as broker,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import manager

pytestmark = pytest.mark.usefixtures(
    "tenant_context", "enable_ee", "broker", "initialize_file_store"
)


def test_dispatch_and_first_sync_observe_initial_group_defaults(
    db_session: Session, github: GitHub, broker: Mock
) -> None:
    actor, group = manager(db_session, global_access=True)
    connect(db_session, actor)
    db_session.commit()
    name = f"atomic-{uuid4().hex[:8]}"
    github.archive = catalog_bytes(name)
    sent: list[UUID] = []

    def tier_before_locks() -> Tier:
        assert not db_session.in_transaction()
        return Tier.BUSINESS

    def committed_send(_task: str, **_options: object) -> None:
        assert not db_session.in_transaction()
        with get_session_with_current_tenant() as observer:
            row = observer.scalar(select(Marketplace).where(Marketplace.name == name))
            assert row is not None and row.owner_user_id is None and row.sync_requested
            assert row.public_permission is None
            assert row.installation_policy == SkillInstallationPolicy.DEFAULT
            assert [
                (g.user_group_id, g.permission, g.installation_policy)
                for g in row.group_shares
            ] == [
                (group, SkillSharePermission.VIEWER, SkillInstallationPolicy.REQUIRED)
            ]
            sent.append(row.id)

    broker.side_effect = committed_send
    with (
        client_for(actor, db_session) as client,
        patch.object(api, "get_current_tier", tier_before_locks),
    ):
        response = client.post(
            "/marketplaces",
            json=SOURCE
            | {
                "personal": False,
                "name": name,
                "access": {
                    "public_permission": None,
                    "installation_policy": "DEFAULT",
                    "group_shares": [
                        {
                            "group_id": group,
                            "permission": "VIEWER",
                            "installation_policy": "REQUIRED",
                        }
                    ],
                },
            },
        )
    assert response.status_code == 200, response.text
    identifier = UUID(response.json()["id"])
    assert sent == [identifier]
    assert response.json()["group_shares"][0]["user_group_id"] == group
    with patch("onyx.skills.sync.push_skills_for_users"):
        result = sync_marketplace(
            identifier, get_current_tenant_id(), request_work=False
        )
    assert result is not None and result.status == "applied"
    with get_session_with_current_tenant() as observer:
        skill = observer.scalar(select(Skill).where(Skill.marketplace_id == identifier))
        assert skill is not None and skill.author_user_id is None
        assert skill.public_permission is None and skill.follows_marketplace_access
        assert skill.installation_policy == SkillInstallationPolicy.DEFAULT
        assert [
            (g.user_group_id, g.permission, g.installation_policy)
            for g in skill.group_shares
        ] == [(group, SkillSharePermission.VIEWER, SkillInstallationPolicy.REQUIRED)]


@pytest.mark.parametrize(
    "invalid", ["missing_group", "community_groups", "personal", "user_grant"]
)
def test_invalid_creation_defaults_leave_no_source_or_sync_request(
    db_session: Session, github: GitHub, broker: Mock, invalid: str
) -> None:
    actor, group = manager(db_session, global_access=True)
    connect(db_session, actor)
    db_session.commit()
    name = f"invalid-{uuid4().hex[:8]}"
    access: dict[str, object] = {
        "group_shares": [
            {
                "group_id": 2147483647 if invalid == "missing_group" else group,
                "permission": "VIEWER",
            }
        ]
    }
    if invalid == "user_grant":
        access = {"user_shares": [{"user_id": str(actor.id), "permission": "VIEWER"}]}
    with (
        client_for(actor, db_session) as client,
        patch.object(
            api,
            "get_current_tier",
            return_value=Tier.COMMUNITY
            if invalid == "community_groups"
            else Tier.BUSINESS,
        ),
    ):
        response = client.post(
            "/marketplaces",
            json=SOURCE
            | {"name": name, "personal": invalid == "personal", "access": access},
        )
    assert response.status_code == (
        422 if invalid in {"personal", "user_grant"} else 400
    ), response.text
    assert (
        db_session.scalar(select(Marketplace.id).where(Marketplace.name == name))
        is None
    )
    db_session.commit()
    with get_session_with_current_tenant() as observer:
        assert (
            observer.scalar(select(Marketplace.id).where(Marketplace.name == name))
            is None
        )
    broker.assert_not_called()
    assert bool(github.urls) == (invalid not in {"personal", "user_grant"})
