"""Tests for migration 7b154e670bd8, which renames the stored manage:skills
permission to manage:plugins in group grants, user effective permissions and
personal access token scopes."""

import asyncio
from collections.abc import Generator
from types import SimpleNamespace
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from fastapi import Request
from sqlalchemy import Engine, create_engine, text

from onyx.auth.permissions import has_global_permission, require_permission
from onyx.configs.app_configs import (
    POSTGRES_DB,
    POSTGRES_HOST,
    POSTGRES_PASSWORD,
    POSTGRES_PORT,
    POSTGRES_USER,
)
from onyx.db.engine.sql_engine import SYNC_DB_API, build_connection_string
from onyx.db.enums import Permission
from onyx.db.models import User
from onyx.db.permissions import parse_permission_values
from onyx.utils.variable_functionality import global_version
from tests.integration.common_utils.reset import downgrade_postgres, upgrade_postgres

PREVIOUS_REVISION = "fdaeeca238a1"
RENAME_REVISION = "7b154e670bd8"
OLD_VALUE = "manage:skills"
NEW_VALUE = "manage:plugins"


def _engine() -> Engine:
    return create_engine(
        build_connection_string(
            db=POSTGRES_DB,
            user=POSTGRES_USER,
            password=POSTGRES_PASSWORD,
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            db_api=SYNC_DB_API,
        )
    )


def _migrate(direction: str, revision: str) -> None:
    if direction == "upgrade":
        upgrade_postgres(database=POSTGRES_DB, config_name="alembic", revision=revision)
    else:
        downgrade_postgres(
            database=POSTGRES_DB, config_name="alembic", revision=revision
        )


@pytest.fixture(scope="module")
def engine() -> Generator[Engine, None, None]:
    _migrate("upgrade", "head")
    _migrate("downgrade", PREVIOUS_REVISION)
    engine = _engine()
    try:
        yield engine
    finally:
        _migrate("upgrade", "head")
        engine.dispose()


class _Seeded:
    def __init__(self, user_id: UUID, groups: dict[str, int], pat_id: int) -> None:
        self.user_id = user_id
        self.groups = groups
        self.pat_id = pat_id


@pytest.fixture
def seeded(engine: Engine) -> Generator[_Seeded, None, None]:
    """Rows that hold the old value, written at the revision before the rename."""
    with engine.connect() as conn:
        revision = conn.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one()
    if revision != PREVIOUS_REVISION:
        _migrate("downgrade", PREVIOUS_REVISION)
    user_id = uuid4()
    suffix = user_id.hex[:8]
    groups: dict[str, int] = {}
    with engine.begin() as conn:
        for key in ("old_only", "both", "deleted_old"):
            groups[key] = conn.execute(
                text(
                    "INSERT INTO user_group (name, is_up_to_date, is_up_for_deletion) "
                    "VALUES (:name, true, false) RETURNING id"
                ),
                {"name": f"a2-{key}-{suffix}"},
            ).scalar_one()
        grants: list[dict[str, Any]] = [
            {"group_id": groups["old_only"], "permission": OLD_VALUE, "deleted": False},
            {"group_id": groups["both"], "permission": OLD_VALUE, "deleted": False},
            {"group_id": groups["both"], "permission": NEW_VALUE, "deleted": True},
            {
                "group_id": groups["deleted_old"],
                "permission": OLD_VALUE,
                "deleted": True,
            },
        ]
        for grant in grants:
            conn.execute(
                text(
                    "INSERT INTO permission_grant "
                    "(group_id, permission, grant_source, is_deleted) "
                    "VALUES (:group_id, :permission, 'SYSTEM', :deleted)"
                ),
                grant,
            )
        conn.execute(
            text(
                'INSERT INTO "user" (id, email, hashed_password, is_active, '
                "is_superuser, is_verified, effective_permissions) VALUES "
                "(:id, :email, '', true, false, true, CAST(:perms AS jsonb))"
            ),
            {
                "id": user_id,
                "email": f"a2-{suffix}@example.com",
                "perms": f'["basic", "{OLD_VALUE}", "{NEW_VALUE}"]',
            },
        )
        pat_id = conn.execute(
            text(
                "INSERT INTO personal_access_token "
                "(name, hashed_token, token_display, user_id, scopes) VALUES "
                "('a2', :hashed, 'onyx_pat_a2', :user_id, CAST(:scopes AS jsonb)) "
                "RETURNING id"
            ),
            {
                "hashed": f"a2-{suffix}",
                "user_id": user_id,
                "scopes": f'["read:chat", "{OLD_VALUE}"]',
            },
        ).scalar_one()
    yield _Seeded(user_id, groups, pat_id)
    with engine.begin() as conn:
        conn.execute(
            text("DELETE FROM personal_access_token WHERE id = :id"), {"id": pat_id}
        )
        conn.execute(text('DELETE FROM "user" WHERE id = :id'), {"id": user_id})
        conn.execute(
            text("DELETE FROM user_group WHERE id = ANY(:ids)"),
            {"ids": list(groups.values())},
        )


def _grants(engine: Engine, group_id: int) -> list[tuple[str, bool]]:
    with engine.connect() as conn:
        return [
            (row.permission, row.is_deleted)
            for row in conn.execute(
                text(
                    "SELECT permission, is_deleted FROM permission_grant "
                    "WHERE group_id = :id ORDER BY permission"
                ),
                {"id": group_id},
            )
        ]


def _user_permissions(engine: Engine, user_id: UUID) -> list[str]:
    with engine.connect() as conn:
        return conn.execute(
            text('SELECT effective_permissions FROM "user" WHERE id = :id'),
            {"id": user_id},
        ).scalar_one()


def _pat_scopes(engine: Engine, pat_id: int) -> list[str]:
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT scopes FROM personal_access_token WHERE id = :id"),
            {"id": pat_id},
        ).scalar_one()


def test_upgrade_renames_and_keeps_access(engine: Engine, seeded: _Seeded) -> None:
    _migrate("upgrade", RENAME_REVISION)

    assert _grants(engine, seeded.groups["old_only"]) == [(NEW_VALUE, False)]
    # The active old grant wins over the deleted new one.
    assert _grants(engine, seeded.groups["both"]) == [(NEW_VALUE, False)]
    assert _grants(engine, seeded.groups["deleted_old"]) == [(NEW_VALUE, True)]

    stored_permissions = _user_permissions(engine, seeded.user_id)
    assert stored_permissions == ["basic", NEW_VALUE]
    scopes = _pat_scopes(engine, seeded.pat_id)
    assert scopes == ["read:chat", NEW_VALUE]

    global_version.set_ee()
    try:
        user = User(effective_permissions=stored_permissions, is_group_manager=False)
        assert has_global_permission(user, Permission.MANAGE_PLUGINS)
        request = cast(
            Request,
            SimpleNamespace(
                state=SimpleNamespace(token_scopes=parse_permission_values(scopes))
            ),
        )
        dep = require_permission(Permission.MANAGE_PLUGINS)
        assert asyncio.run(dep(request=request, user=user)) is user
    finally:
        global_version.unset_ee()


def test_downgrade_restores_old_value(engine: Engine, seeded: _Seeded) -> None:
    _migrate("upgrade", RENAME_REVISION)
    _migrate("downgrade", PREVIOUS_REVISION)

    assert _grants(engine, seeded.groups["old_only"]) == [(OLD_VALUE, False)]
    assert _grants(engine, seeded.groups["both"]) == [(OLD_VALUE, False)]
    assert _grants(engine, seeded.groups["deleted_old"]) == [(OLD_VALUE, True)]
    assert _user_permissions(engine, seeded.user_id) == ["basic", OLD_VALUE]
    assert _pat_scopes(engine, seeded.pat_id) == ["read:chat", OLD_VALUE]
