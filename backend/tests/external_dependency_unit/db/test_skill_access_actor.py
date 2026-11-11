"""Access writes use current database authority, not the earlier auth snapshot."""

from collections.abc import Container
from typing import Literal
from unittest.mock import patch
from uuid import UUID, uuid4

import pytest
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from onyx.auth.permissions import has_global_permission
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.enums import Permission
from onyx.db.models import Skill, User, User__UserGroup, UserGroup, UserSkillPreference
from onyx.db.permissions import recompute_user_permissions__no_commit
from onyx.file_store.file_store import FileStore
from onyx.server.features.skill import api
from onyx.skills.ingest import IngestedBundle
from tests.external_dependency_unit.craft.db_helpers import (
    make_external_app,
    make_skill,
    make_user,
)
from tests.external_dependency_unit.db.test_skill_access_locks import (
    try_lock_group_membership,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import client_for
from tests.external_dependency_unit.db.test_skill_version_writes import (
    bundle,
    stored_bundles,
)

pytestmark = pytest.mark.usefixtures(
    "tenant_context", "enable_ee", "initialize_file_store"
)

Revocation = Literal["manager", "basic", "inactive"]
Operation = Literal[
    "share", "share_noop", "bulk", "toggle", "delete", "bulk_delete", "transfer"
]


def admin_with_basic(session: Session) -> User:
    actor = make_user(session, is_admin=True)
    basic_group_id = session.scalar(
        select(UserGroup.id).where(UserGroup.name == "Basic")
    )
    assert basic_group_id is not None
    session.add(User__UserGroup(user_id=actor.id, user_group_id=basic_group_id))
    session.flush()
    recompute_user_permissions__no_commit(actor.id, session)
    return actor


def revoke(user_id: UUID, revocation: Revocation) -> None:
    with get_session_with_current_tenant() as writer:
        try_lock_group_membership(writer)
        if revocation == "inactive":
            actor = writer.get(User, user_id)
            assert actor is not None
            actor.is_active = False
        else:
            statement = delete(User__UserGroup).where(
                User__UserGroup.user_id == user_id
            )
            if revocation == "manager":
                statement = statement.where(
                    User__UserGroup.user_group_id.in_(
                        select(UserGroup.id).where(UserGroup.name == "Admin")
                    )
                )
            writer.execute(statement)
            recompute_user_permissions__no_commit(user_id, writer)
        writer.commit()


@pytest.mark.parametrize(
    "operation",
    ["share", "share_noop", "bulk", "toggle", "delete", "bulk_delete", "transfer"],
)
@pytest.mark.parametrize("revocation", ["manager", "basic", "inactive"])
def test_access_uses_current_actor(
    db_session: Session,
    operation: Operation,
    revocation: Revocation,
) -> None:
    actor = admin_with_basic(db_session)
    target = make_user(db_session, standard_account=True)
    skill = make_skill(db_session, author_user_id=actor.id)
    skill_id, actor_id, target_id = skill.id, actor.id, target.id
    db_session.commit()
    with get_session_with_current_tenant() as auth_session:
        auth_user = auth_session.get(User, actor_id)
        assert auth_user is not None and auth_user is not actor
        revoke(actor_id, revocation)
        assert has_global_permission(auth_user, Permission.MANAGE_SKILLS)
        with client_for(auth_user, db_session) as client:
            if operation in ("share", "share_noop"):
                result = client.patch(
                    f"/skills/custom/{skill_id}/share",
                    json={"public_permission": "VIEWER"}
                    if operation == "share"
                    else {},
                )
            elif operation in ("bulk", "bulk_delete"):
                data: dict[str, object] = {
                    "action": "delete",
                    "skill_ids": [str(skill_id)],
                }
                if operation == "bulk":
                    data.update(action="share", sharing={"public_permission": "VIEWER"})
                result = client.post("/skills/bulk", json=data)
            elif operation == "delete":
                result = client.delete(f"/skills/custom/{skill_id}")
            elif operation == "transfer":
                result = client.post(
                    f"/skills/custom/{skill_id}/transfer-ownership",
                    json={"new_owner_user_id": str(target_id)},
                )
            else:
                result = client.put(
                    f"/skills/{skill_id}/enabled", json={"enabled": True}
                )
        allowed = revocation == "manager" and operation not in ("share", "bulk")
        if allowed:
            assert result.is_success, result.text
        elif operation == "bulk" and revocation == "manager":
            assert result.status_code == 200, result.text
            assert result.json()["succeeded"] == []
            assert len(result.json()["failed"]) == 1
        else:
            assert result.status_code == 403, result.text
        db_session.expire_all()
        retained = db_session.scalar(select(Skill).where(Skill.id == skill_id))
        if allowed and operation in ("delete", "bulk_delete"):
            assert retained is None
        else:
            assert retained is not None and retained.public_permission is None
            assert retained.author_user_id == (
                target_id if allowed and operation == "transfer" else actor_id
            )
        preference = db_session.get(UserSkillPreference, (actor_id, skill_id))
        assert bool(preference and preference.enabled) == (
            operation == "toggle" and allowed
        )


@pytest.mark.parametrize(
    ("operation", "revocation"),
    [
        ("create", "basic"),
        ("batch", "basic"),
        ("editor", "inactive"),
        ("editor_app", "manager"),
    ],
)
def test_creation_rechecks_authority_after_storage(
    db_session: Session,
    operation: Literal["create", "batch", "editor", "editor_app"],
    revocation: Revocation,
) -> None:
    actor = admin_with_basic(db_session)
    existing = make_skill(db_session, author_user_id=actor.id)
    app = make_external_app(db_session, skill=existing, auth_template={})
    actor_id, app_id = actor.id, app.id
    db_session.commit()
    before = stored_bundles(db_session)
    name = f"revoked-{uuid4().hex}"
    original_ingest = api.ingest_skill_bundle
    staged: list[str] = []

    def ingest(
        content: bytes,
        filename: str | None,
        file_store: FileStore,
        *,
        expected_name: str | None = None,
        stored: bool = False,
        uncapped_paths: Container[str] | None = None,
    ) -> IngestedBundle:
        result = original_ingest(
            content,
            filename,
            file_store,
            expected_name=expected_name,
            stored=stored,
            uncapped_paths=uncapped_paths,
        )
        staged.append(result.bundle_file_id)
        revoke(actor_id, revocation)
        return result

    with get_session_with_current_tenant() as auth_session:
        auth_user = auth_session.get(User, actor_id)
        assert auth_user is not None and auth_user is not actor
        with (
            client_for(auth_user, db_session) as client,
            patch.object(api, "ingest_skill_bundle", side_effect=ingest),
        ):
            if operation in ("create", "batch"):
                field = "bundles" if operation == "batch" else "bundle"
                suffix = "/batch" if operation == "batch" else ""
                result = client.post(
                    f"/skills/custom{suffix}",
                    data={"auto_enable": "false"},
                    files={field: ("bundle.zip", bundle(name), "application/zip")},
                )
            else:
                data = {
                    "name": name,
                    "description": "Test",
                    "instructions_markdown": "Test",
                    "auto_enable": "false",
                }
                if operation == "editor_app":
                    data["external_app_id"] = str(app_id)
                result = client.post("/skills/custom/editor", data=data)
        assert has_global_permission(auth_user, Permission.MANAGE_SKILLS)
        assert result.status_code == 403, result.text
    assert len(staged) == 1
    assert stored_bundles(db_session) == before
    assert db_session.scalar(select(Skill.id).where(Skill.name == name)) is None
