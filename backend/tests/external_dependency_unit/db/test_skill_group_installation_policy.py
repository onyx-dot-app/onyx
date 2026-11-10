import json
from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import Engine, inspect, select, text
from sqlalchemy.orm import Session

from onyx.auth.users import current_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import SkillInstallationPolicy
from onyx.db.models import Skill, Skill__UserGroup
from onyx.db.skill import set_skill_installation_policy
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError, register_onyx_exception_handlers
from onyx.server.features.skill.api import user_router
from tests.external_dependency_unit.craft.db_helpers import (
    make_group,
    make_skill,
    make_user,
)


@pytest.mark.usefixtures("tenant_context")
@pytest.mark.parametrize("group_policy", [False, True], ids=["company", "group"])
@pytest.mark.parametrize(
    "route", ["share", "bulk", "editor", "batch", "import", "patch"]
)
def test_api_rejects_not_available(
    db_session: Session, route: str, group_policy: bool
) -> None:
    """Exercise JSON and multipart parsing through the real skill router."""
    try:
        admin = make_user(db_session, is_admin=True)
        skill = make_skill(db_session, author_user_id=admin.id)
        group = make_group(db_session)
        skill_ids_before = set(db_session.scalars(select(Skill.id)))
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
        app = FastAPI()
        app.include_router(user_router)
        register_onyx_exception_handlers(app)
        app.dependency_overrides[current_user] = lambda: admin
        app.dependency_overrides[get_session] = lambda: db_session
        with TestClient(app) as client:
            if route == "share":
                response = client.patch(
                    f"/skills/custom/{skill.id}/share", json=sharing
                )
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
            elif route == "import":
                response = client.post(
                    "/skills/github/import",
                    json={
                        "repository": "example/skills",
                        "revision": "a" * 40,
                        "paths": ["test-skill"],
                        "sharing": sharing,
                    },
                )
            elif route == "editor":
                response = client.post(
                    "/skills/custom/editor",
                    data={
                        "name": "test-skill",
                        "description": "Test skill",
                        "instructions_markdown": "Test instructions",
                        "sharing": json.dumps(sharing),
                    },
                )
            else:
                response = client.post(
                    "/skills/custom/batch",
                    files={"bundles": ("test.zip", b"not read", "application/zip")},
                    data={"sharing": json.dumps(sharing)},
                )
        if route in ("editor", "batch"):
            assert response.status_code == OnyxErrorCode.INVALID_INPUT.status_code
            assert response.json()["detail"] == "Invalid skill sharing settings."
        else:
            assert response.status_code == 422
            assert "installation_policy" in response.text
        db_session.refresh(skill)
        assert skill.installation_policy == SkillInstallationPolicy.AVAILABLE
        assert set(db_session.scalars(select(Skill.id))) == skill_ids_before
        assert (
            db_session.scalars(
                select(Skill__UserGroup).where(Skill__UserGroup.skill_id == skill.id)
            ).all()
            == []
        )
    finally:
        db_session.rollback()


@pytest.mark.usefixtures("tenant_context")
def test_database_setter_rejects_not_available_but_allows_duplicate_automatic_names(
    db_session: Session,
) -> None:
    try:
        automatic = make_skill(db_session, is_public=True)
        duplicate = make_skill(db_session, name=automatic.name, is_public=True)
        set_skill_installation_policy(
            automatic, SkillInstallationPolicy.DEFAULT, db_session
        )
        with pytest.raises(OnyxError, match="not supported yet") as rejected:
            set_skill_installation_policy(
                duplicate, SkillInstallationPolicy.NOT_AVAILABLE, db_session
            )
        assert rejected.value.error_code == OnyxErrorCode.INVALID_INPUT
        db_session.refresh(duplicate)
        assert duplicate.installation_policy == SkillInstallationPolicy.AVAILABLE
        set_skill_installation_policy(
            duplicate, SkillInstallationPolicy.REQUIRED, db_session
        )
        assert duplicate.installation_policy == SkillInstallationPolicy.REQUIRED
    finally:
        db_session.rollback()


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
