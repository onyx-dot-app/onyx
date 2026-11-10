"""Exercise token-capped reads and content writes against PostgreSQL and FileStore."""

from unittest.mock import patch

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from onyx.db.enums import Permission, SkillInstallationPolicy, SkillSharePermission
from onyx.db.models import Skill, Skill__User, Skill__UserGroup, User
from onyx.file_store.file_store import FileStore
from onyx.server.features.skill import api
from onyx.skills.ingest import IngestedBundle
from tests.external_dependency_unit.craft.db_helpers import make_user
from tests.external_dependency_unit.db.skill_api_client import client_for
from tests.external_dependency_unit.db.test_skill_access_mutations import manager
from tests.external_dependency_unit.db.test_skill_version_writes import bundle, upload
from tests.external_dependency_unit.db.test_skill_version_writes import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import tenant as tenant
from tests.external_dependency_unit.db.test_skill_version_writes import user as user

pytestmark = pytest.mark.usefixtures("enable_ee")


@pytest.fixture
def skill(session: Session, user: User) -> Skill:
    response = api.create_custom_skill(
        upload(bundle("token-content")),
        False,
        user,
        session,
        http_request=Request({"type": "http"}),
    )
    row = session.get(Skill, response.id)
    assert row is not None
    return row


def request(client: TestClient, skill: Skill, operation: str) -> httpx.Response:
    base = f"/skills/custom/{skill.id}"
    if operation == "bundle":
        return client.put(
            base + "/bundle",
            files={"bundle": ("skill.zip", bundle(skill.name, "Changed"))},
        )
    if operation == "upload":
        return client.post(base + "/files", files={"upload": ("notes.md", b"Notes")})
    if operation == "restore":
        return client.post(base + f"/versions/{skill.current_version_id}/restore")
    if operation == "patch":
        return client.patch(base, json={"description": "Changed"})
    if operation == "remove":
        return client.delete(base + "/files", params={"path": "notes.md"})
    if operation == "delete":
        return client.delete(base)
    if operation == "enable":
        return client.put(f"/skills/{skill.id}/enabled", json={"enabled": True})
    paths = {
        "detail": f"/skills/{skill.id}",
        "preview": f"/skills/{skill.id}/preview",
        "edit": base + "/edit",
        "history": base + "/versions",
        "version": base + f"/versions/{skill.current_version_id}",
    }
    return client.get(paths[operation])


@pytest.mark.parametrize(
    "operation",
    [
        "detail",
        "preview",
        "edit",
        "history",
        "version",
        "bundle",
        "upload",
        "restore",
        "patch",
        "remove",
        "delete",
        "enable",
    ],
)
def test_basic_token_cannot_use_global_management_on_private_skill(
    session: Session, skill: Skill, operation: str
) -> None:
    actor, _ = manager(session, global_access=True)
    session.commit()
    with client_for(actor, session, [Permission.BASIC_ACCESS]) as client:
        response = request(client, skill, operation)
        assert response.status_code == 404, response.text
        listing = client.get("/skills")
        assert listing.status_code == 200, listing.text
        assert str(skill.id) not in {row["id"] for row in listing.json()["customs"]}
    # The same user with management scope can still inspect the private bundle.
    with client_for(
        actor, session, [Permission.BASIC_ACCESS, Permission.MANAGE_SKILLS]
    ) as client:
        response = request(client, skill, "edit")
        assert response.status_code == 200, response.text
        assert response.json()["user_permission"] == "EDITOR"


@pytest.mark.parametrize(
    "operation", ["bundle", "upload", "restore", "patch", "remove"]
)
def test_basic_token_preserves_explicit_editor_content_rights(
    session: Session, skill: Skill, user: User, operation: str
) -> None:
    actor, _ = manager(session, global_access=True)
    session.add(
        Skill__User(
            skill_id=skill.id, user_id=actor.id, permission=SkillSharePermission.EDITOR
        )
    )
    session.commit()
    with (
        patch.object(api, "push_skill_to_affected_sandboxes"),
        client_for(user, session) as owner,
    ):
        assert request(owner, skill, "upload").status_code == 200
    session.refresh(skill)
    with (
        client_for(actor, session, [Permission.BASIC_ACCESS]) as client,
        patch.object(api, "push_skill_to_affected_sandboxes"),
        patch.object(api, "push_skills_for_users"),
    ):
        response = request(client, skill, operation)
        assert response.status_code == 200, response.text
        read = request(client, skill, "edit")
        assert read.status_code == 200, read.text
        assert read.json()["user_permission"] == "EDITOR"
        if operation == "patch":
            assert read.json()["description"] == "Changed"
        if operation == "bundle":
            assert read.json()["instructions_markdown"] == "Changed"
        if operation == "remove":
            assert "notes.md" not in {entry["path"] for entry in read.json()["files"]}


@pytest.mark.parametrize("scoped", [False, True])
def test_basic_token_read_permission_matches_explicit_viewer_grant(
    session: Session, skill: Skill, scoped: bool
) -> None:
    actor, group = manager(session, global_access=not scoped)
    session.add(
        Skill__UserGroup(
            skill_id=skill.id,
            user_group_id=group,
            permission=SkillSharePermission.VIEWER,
        )
    )
    session.commit()
    with client_for(actor, session, [Permission.BASIC_ACCESS]) as client:
        detail = request(client, skill, "detail")
        assert detail.status_code == 200, detail.text
        assert detail.json()["user_permission"] == "VIEWER"
        listing = client.get("/skills")
        assert listing.status_code == 200, listing.text
        listed = next(
            row for row in listing.json()["customs"] if row["id"] == str(skill.id)
        )
        assert listed["user_permission"] == "VIEWER"
        assert request(client, skill, "edit").status_code == 404


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("limited", [False, True])
def test_required_delete_needs_management_scope_even_for_an_editor(
    session: Session, skill: Skill, bulk: bool, limited: bool
) -> None:
    actor, _ = manager(session, global_access=True)
    session.add(
        Skill__User(
            skill_id=skill.id, user_id=actor.id, permission=SkillSharePermission.EDITOR
        )
    )
    skill.installation_policy = SkillInstallationPolicy.REQUIRED
    session.commit()
    skill_id = skill.id
    with (
        client_for(
            actor, session, [Permission.BASIC_ACCESS] if limited else None
        ) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        response = (
            client.post(
                "/skills/bulk", json={"action": "delete", "skill_ids": [str(skill_id)]}
            )
            if bulk
            else request(client, skill, "delete")
        )
        if bulk:
            assert response.status_code == 200, response.text
            assert response.json()["succeeded"] == ([] if limited else [str(skill_id)])
        else:
            assert response.status_code == (403 if limited else 200), response.text
    assert (session.get(Skill, skill_id) is not None) == limited


@pytest.mark.parametrize("limited", [False, True])
def test_claiming_vacant_ownership_requires_management_scope(
    session: Session, skill: Skill, limited: bool
) -> None:
    actor, _ = manager(session, global_access=True)
    recipient = make_user(session, standard_account=True)
    skill.author_user_id = None
    skill.public_permission = SkillSharePermission.VIEWER
    session.add(
        Skill__User(
            skill_id=skill.id, user_id=actor.id, permission=SkillSharePermission.EDITOR
        )
    )
    session.commit()
    with (
        client_for(
            actor, session, [Permission.BASIC_ACCESS] if limited else None
        ) as client,
        patch.object(api, "push_skills_for_users"),
    ):
        response = client.post(
            f"/skills/custom/{skill.id}/transfer-ownership",
            json={"new_owner_user_id": str(recipient.id)},
        )
        assert response.status_code == (403 if limited else 200), response.text
    session.refresh(skill)
    assert skill.author_user_id == (None if limited else recipient.id)


def test_storage_recheck_does_not_fall_back_to_management(
    session: Session, skill: Skill
) -> None:
    actor, _ = manager(session, global_access=True)
    grant = Skill__User(
        skill_id=skill.id, user_id=actor.id, permission=SkillSharePermission.EDITOR
    )
    session.add(grant)
    session.commit()
    original_version = skill.current_version_id
    ingest = api.ingest_skill_bundle

    def revoke_after_storage(
        bundle_bytes: bytes,
        filename: str | None,
        file_store: FileStore,
        *,
        expected_name: str | None = None,
        reject_plugins: bool = True,
        stored: bool = False,
    ) -> IngestedBundle:
        ingested = ingest(
            bundle_bytes,
            filename,
            file_store,
            expected_name=expected_name,
            reject_plugins=reject_plugins,
            stored=stored,
        )
        session.delete(grant)
        session.commit()
        return ingested

    with (
        client_for(actor, session, [Permission.BASIC_ACCESS]) as client,
        patch.object(api, "ingest_skill_bundle", revoke_after_storage),
        patch.object(api, "push_skill_to_affected_sandboxes") as push,
    ):
        response = request(client, skill, "bundle")
        assert response.status_code == 404, response.text
        push.assert_not_called()
    session.refresh(skill)
    assert skill.current_version_id == original_version
