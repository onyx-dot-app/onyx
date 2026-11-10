import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, text
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SkillInstallationPolicy
from onyx.db.models import UserSkillPreference
from onyx.db.skill import set_skill_installation_policy
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.features.skill.api import user_router
from tests.external_dependency_unit.craft.db_helpers import (
    add_user_to_group,
    make_group,
    make_skill,
    make_user,
)
from tests.external_dependency_unit.db.test_skill_access_mutations import (
    session as session,
)
from tests.external_dependency_unit.db.test_skill_version_writes import bundle


@pytest.mark.usefixtures("tenant_context", "enable_ee")
@pytest.mark.parametrize("group_policy", [False, True], ids=["company", "group"])
@pytest.mark.parametrize("route", ["share", "bulk", "editor", "batch", "patch"])
def test_api_accepts_not_available_through_sharing(
    session: Session, route: str, group_policy: bool
) -> None:
    admin = make_user(session, is_admin=True)
    skill = make_skill(session, author_user_id=admin.id)
    group = make_group(session)
    add_user_to_group(session, admin, group)
    sharing: dict[str, object] = (
        {
            "group_shares": [
                {
                    "group_id": group.id,
                    "permission": "VIEWER",
                    "installation_policy": "NOT_AVAILABLE",
                }
            ]
        }
        if group_policy
        else {"installation_policy": "NOT_AVAILABLE"}
    )
    name = f"g3-api-{uuid4().hex}"
    app = FastAPI()
    app.include_router(user_router)
    register_onyx_exception_handlers(app)
    app.dependency_overrides[current_user] = lambda: admin
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as client:
        if route == "share":
            response = client.patch(f"/skills/custom/{skill.id}/share", json=sharing)
        elif route == "patch":
            response = client.patch(f"/skills/custom/{skill.id}", json=sharing)
        elif route == "bulk":
            response = client.post(
                "/skills/bulk",
                json={
                    "skill_ids": [str(skill.id)],
                    "action": "share",
                    "sharing": sharing,
                },
            )
        elif route == "editor":
            response = client.post(
                "/skills/custom/editor",
                data={
                    "name": name,
                    "description": "Test skill",
                    "instructions_markdown": "Test instructions",
                    "sharing": json.dumps(sharing),
                },
            )
        else:
            response = client.post(
                "/skills/custom/batch",
                files={"bundles": ("test.zip", bundle(name), "application/zip")},
                data={"sharing": json.dumps(sharing)},
            )
        if route == "patch":
            # Content patching still refuses sharing fields; use the sharing route.
            assert response.status_code == 422
            return
        assert response.status_code == 200, response.text
        if route == "batch":
            imported = response.json()["imported"]
            assert len(imported) == 1 and response.json()["not_imported"] == []
            assert (
                imported[0]["disabled_reason"] == "This skill is Not available for you."
            )
            skill_id = UUID(imported[0]["skill"]["id"])
        elif route == "editor":
            assert response.json()["effective_installation_policy"] == "NOT_AVAILABLE"
            assert response.json()["enabled"] is False
            skill_id = UUID(response.json()["id"])
        else:
            skill_id = skill.id
        if route == "bulk":
            assert response.json()["succeeded"] == [str(skill.id)]
            assert not response.json()["failed"]
        detail = client.get(f"/skills/{skill_id}")
        assert detail.status_code == 200, detail.text
        assert detail.json()["effective_installation_policy"] == "NOT_AVAILABLE"
        assert detail.json()["installation_policy"] == (
            "AVAILABLE" if group_policy else "NOT_AVAILABLE"
        )
        assert (
            detail.json()["enabled"] is False and detail.json()["can_toggle"] is False
        )
        assert session.get(UserSkillPreference, (admin.id, skill_id)) is None


@pytest.mark.usefixtures("tenant_context")
def test_database_setter_accepts_not_available_and_historical_duplicates(
    db_session: Session,
) -> None:
    automatic = make_skill(db_session, is_public=True)
    duplicate = make_skill(db_session, name=automatic.name, is_public=True)
    for policy in SkillInstallationPolicy:
        set_skill_installation_policy(automatic, policy, db_session)
        set_skill_installation_policy(duplicate, policy, db_session)
        assert automatic.installation_policy == duplicate.installation_policy == policy


def test_group_policy_migration_preserves_shares(isolated_engine: Engine) -> None:
    scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
    migration = scripts.get_revision("13a2d6969b0b")
    assert migration is not None
    schema = f"test_group_policy_{uuid4().hex}"
    with isolated_engine.connect() as connection, connection.begin():
        connection.execute(text(f"CREATE SCHEMA {schema}"))
        connection.execute(
            text(
                f"CREATE TABLE {schema}.skill__user_group "
                "(LIKE skill__user_group INCLUDING ALL)"
            )
        )
        connection.execute(text(f"SET LOCAL search_path TO {schema}"))
        with Operations.context(MigrationContext.configure(connection)):
            migration.module.downgrade()
            connection.execute(
                text(
                    "INSERT INTO skill__user_group (skill_id, user_group_id, permission) "
                    "VALUES (:skill_id, 1, 'EDITOR')"
                ),
                {"skill_id": uuid4()},
            )
            migration.module.upgrade()
            row = connection.execute(
                text("SELECT permission, installation_policy FROM skill__user_group")
            ).one()
            assert row == ("EDITOR", None)
            for policy in SkillInstallationPolicy:
                connection.execute(
                    text("UPDATE skill__user_group SET installation_policy = :policy"),
                    {"policy": policy.value},
                )
                assert (
                    connection.scalar(
                        text("SELECT installation_policy FROM skill__user_group")
                    )
                    == policy.value
                )
            migration.module.downgrade()
            assert "installation_policy" not in {
                column["name"]
                for column in inspect(connection).get_columns("skill__user_group")
            }
            assert (
                connection.scalar(text("SELECT permission FROM skill__user_group"))
                == "EDITOR"
            )
            migration.module.upgrade()
            assert (
                connection.scalar(
                    text("SELECT installation_policy FROM skill__user_group")
                )
                is None
            )
        connection.rollback()
