"""Creation cannot turn a Basic-scoped manager token into a management token."""

import json
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from onyx.db.enums import ExternalAppType, GrantSource, Permission
from onyx.db.external_app import create_external_app
from onyx.db.models import FileRecord, PermissionGrant, Skill, User
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.server.features.skill import api
from onyx.skills.models import GitHubRepository, GitHubSkillBundle
from tests.external_dependency_unit.db.skill_api_client import client_for
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_version_writes import bundle
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user

pytestmark = pytest.mark.usefixtures("enable_ee")


def create(
    client: TestClient, route: str, sharing: dict[str, object]
) -> httpx.Response:
    if route == "editor":
        return client.post(
            "/skills/custom/editor",
            data={
                "name": "creation-token",
                "description": "Test",
                "instructions_markdown": "Test instructions",
                "auto_enable": "false",
                "sharing": json.dumps(sharing),
            },
        )
    if route == "batch":
        return client.post(
            "/skills/custom/batch",
            data={"auto_enable": "false", "sharing": json.dumps(sharing)},
            files={"bundles": ("skill.zip", bundle("creation-token"))},
        )
    return client.post(
        "/skills/github/import",
        json={
            "repository": "owner/repo",
            "revision": "a" * 40,
            "paths": ["skills/creation-token"],
            "sharing": sharing,
        },
    )


@pytest.mark.parametrize("route", ["editor", "batch", "github"])
@pytest.mark.parametrize("change", ["public", "policy", "group_policy", "none"])
@pytest.mark.parametrize("limited", [False, True])
def test_creation_scopes_sharing_and_rolls_back_rejected_bundles(
    session: Session, user: User, route: str, change: str, limited: bool
) -> None:
    actor, group = manager(session, global_access=True)
    assert actor.id != user.id
    session.commit()
    sharing: dict[str, object] = (
        {"public_permission": "VIEWER"}
        if change == "public"
        else {"installation_policy": "REQUIRED"}
        if change == "policy"
        else {
            "group_shares": [
                {
                    "group_id": group,
                    "permission": "VIEWER",
                    "installation_policy": "REQUIRED",
                }
            ]
        }
        if change == "group_policy"
        else {}
    )
    before_files = set(session.scalars(select(FileRecord.file_id)))
    allowed = not limited or change == "none"
    with (
        client_for(
            actor,
            session,
            [Permission.BASIC_ACCESS]
            if limited
            else [Permission.BASIC_ACCESS, Permission.MANAGE_SKILLS],
        ) as client,
        patch.object(api, "push_skill_to_affected_sandboxes"),
        patch.object(api, "push_skills_for_users"),
        patch.object(api, "github_authorization_header", return_value=None),
        patch.object(
            api,
            "fetch_github_skill_bundles",
            return_value=(
                GitHubRepository(owner="owner", repo="repo", revision="a" * 40),
                [
                    GitHubSkillBundle(
                        path="skills/creation-token",
                        name="creation-token",
                        description="Test",
                        bundle_bytes=bundle("creation-token"),
                    )
                ],
            ),
        ),
    ):
        response = create(client, route, sharing)
        if route == "editor":
            assert response.status_code == (200 if allowed else 403), response.text
            if allowed:
                assert response.json()["user_permission"] == "OWNER"
        else:
            assert response.status_code == 200, response.text
            assert len(response.json()["imported"]) == int(allowed)
            if not allowed:
                assert len(response.json()["not_imported"]) == 1
                assert response.json()["not_imported"][0]["reason"]
                if change == "group_policy":
                    assert "scope" in response.json()["not_imported"][0]["reason"]
    rows = list(session.scalars(select(Skill).where(Skill.name == "creation-token")))
    assert len(rows) == int(allowed)
    if allowed:
        assert rows[0].author_user_id == actor.id
        if change == "public":
            assert rows[0].public_permission is not None
        if change == "policy":
            assert rows[0].installation_policy.value == "REQUIRED"
        if change == "group_policy":
            assert rows[0].group_shares[0].installation_policy is not None
    else:
        assert set(session.scalars(select(FileRecord.file_id))) == before_files


@pytest.mark.parametrize(
    "scopes",
    [
        [Permission.BASIC_ACCESS],
        [Permission.BASIC_ACCESS, Permission.MANAGE_SKILLS],
        [Permission.BASIC_ACCESS, Permission.FULL_ADMIN_PANEL_ACCESS],
    ],
)
@pytest.mark.usefixtures("tenant_context", "initialize_file_store")
def test_app_skill_creation_requires_full_admin_token_scope(
    db_session: Session, scopes: list[Permission]
) -> None:
    session = db_session
    actor, group = manager(session, global_access=True)
    session.add(
        PermissionGrant(
            group_id=group,
            permission=Permission.FULL_ADMIN_PANEL_ACCESS,
            grant_source=GrantSource.USER,
        )
    )
    session.flush()
    recompute_user_permissions__no_commit(actor.id, session)
    session.refresh(actor)
    app = create_external_app(
        db_session=session,
        name="Token app",
        app_type=ExternalAppType.CUSTOM,
        upstream_url_patterns=[],
        auth_template={},
        organization_credentials={},
    )
    session.commit()
    before = session.scalar(select(func.count()).select_from(FileRecord))
    allowed = Permission.FULL_ADMIN_PANEL_ACCESS in scopes
    with client_for(actor, session, scopes) as client:
        response = client.post(
            "/skills/custom/editor",
            data={
                "name": "app-token",
                "description": "Test",
                "instructions_markdown": "Test",
                "external_app_id": str(app.id),
            },
        )
    assert response.status_code == (200 if allowed else 403), response.text
    assert session.scalar(
        select(func.count()).select_from(Skill).where(Skill.name == "app-token")
    ) == int(allowed)
    if not allowed:
        assert session.scalar(select(func.count()).select_from(FileRecord)) == before
