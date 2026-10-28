"""Legacy PATs retain a fixed permission cap without changing their raw scopes."""

from pathlib import Path
from uuid import uuid4

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import bindparam, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.schema import CreateSchema


def test_pat_permission_caps_upgrade_downgrade_upgrade(
    isolated_engine: Engine,
) -> None:
    basic_cap = {
        "add:agents",
        "basic",
        "create:user_api_keys",
        "generate:image",
        "read:chat",
        "read:search",
        "write:chat",
    }
    admin_cap = {
        "add:agents",
        "admin",
        "basic",
        "create:user_api_keys",
        "generate:image",
        "manage:actions",
        "manage:agents",
        "manage:bots",
        "manage:connectors",
        "manage:document_sets",
        "manage:llms",
        "manage:service_account_api_keys",
        "manage:skills",
        "manage:user_groups",
        "read:admin",
        "read:agent_analytics",
        "read:agents",
        "read:chat",
        "read:connectors",
        "read:document_sets",
        "read:query_history",
        "read:search",
        "read:user_groups",
        "read:users",
        "write:chat",
    }
    raw_scopes: dict[str, list[str] | None] = {
        "unrestricted_basic": None,
        "unrestricted_basic_json_null": None,
        "basic_bundle": ["basic"],
        "unrestricted_admin": None,
        "unrestricted_admin_json_null": None,
        "admin_bundle_basic_owner": ["admin"],
        "chat_write": ["write:chat"],
        "gateway": ["use:llm_gateway"],
        "unknown": ["future:permission"],
        "empty": [],
        "revoked": None,
        "expired": None,
        "craft": ["craft_sandbox"],
        "basic_with_gateway": ["basic", "use:llm_gateway"],
        "manage_agents": ["manage:agents"],
        "basic_limited_owner": ["basic"],
        "user_craft_bundle": ["craft_sandbox"],
        "unrestricted_empty_owner": None,
        "unrestricted_json_null_owner": None,
        "unrestricted_sql_null_owner": None,
        "known_and_unknown": ["future:permission", "write:chat"],
        "craft_unknown": ["future:permission"],
        "unrestricted_manager": None,
        "narrow_manager": ["read:search"],
    }
    expected_caps = {
        "unrestricted_basic": basic_cap,
        "unrestricted_basic_json_null": basic_cap,
        "basic_bundle": basic_cap - {"add:agents", "create:user_api_keys"},
        "unrestricted_admin": admin_cap,
        "unrestricted_admin_json_null": admin_cap,
        "admin_bundle_basic_owner": basic_cap,
        "chat_write": {"read:chat", "write:chat"},
        "gateway": {"use:llm_gateway"},
        "unknown": set(),
        "empty": set(),
        "revoked": basic_cap,
        "expired": basic_cap,
        "craft": {
            "craft_sandbox",
            "generate:image",
            "read:search",
            "use:llm_gateway",
        },
        "basic_with_gateway": (basic_cap - {"add:agents", "create:user_api_keys"})
        | {"use:llm_gateway"},
        "manage_agents": {
            "add:agents",
            "manage:agents",
            "read:agent_analytics",
            "read:agents",
            "read:document_sets",
        },
        "basic_limited_owner": {"read:chat"},
        "user_craft_bundle": {"generate:image", "read:search"},
        "unrestricted_empty_owner": {"add:agents"},
        "unrestricted_json_null_owner": {"add:agents"},
        "unrestricted_sql_null_owner": {"add:agents"},
        "known_and_unknown": {"read:chat", "write:chat"},
        "craft_unknown": set(),
        "unrestricted_manager": basic_cap
        | {
            "manage:actions",
            "manage:agents",
            "manage:connectors",
            "manage:document_sets",
            "manage:skills",
            "manage:user_groups",
            "read:agent_analytics",
            "read:agents",
            "read:connectors",
            "read:document_sets",
            "read:user_groups",
            "read:users",
        },
        "narrow_manager": {"read:search"},
    }
    schema = f"pat_cap_migration_{uuid4().hex}"
    with isolated_engine.connect() as connection, connection.begin():
        connection.execute(CreateSchema(schema))
        connection.execute(
            text("SELECT set_config('search_path', :schema, true)"),
            {"schema": schema},
        )
        connection.execute(
            text("""
                CREATE TABLE "user" (
                    id integer PRIMARY KEY,
                    effective_permissions jsonb,
                    is_group_manager boolean NOT NULL DEFAULT false
                );
                CREATE TABLE personal_access_token (
                    id integer PRIMARY KEY,
                    name text NOT NULL UNIQUE,
                    user_id integer NOT NULL REFERENCES "user" (id),
                    scopes jsonb,
                    pat_type text NOT NULL DEFAULT 'USER',
                    is_revoked boolean NOT NULL DEFAULT false,
                    expires_at timestamptz
                );
                INSERT INTO "user" (id, effective_permissions) VALUES
                    (1, '["basic", "create:user_api_keys"]'),
                    (2, '["admin"]'),
                    (3, '["basic", "manage:agents"]'),
                    (4, '["read:chat"]'),
                    (5, '[]'),
                    (6, 'null'),
                    (7, NULL);
                INSERT INTO "user" VALUES
                    (8, '["basic", "create:user_api_keys"]', true);
            """)
        )
        insert = text("""
            INSERT INTO personal_access_token (id, name, user_id, scopes, pat_type)
            VALUES (:id, :name, :user_id, :scopes, :pat_type)
        """).bindparams(bindparam("scopes", type_=JSONB(none_as_null=True)))
        owner_ids = {
            "unrestricted_admin": 2,
            "unrestricted_admin_json_null": 2,
            "manage_agents": 3,
            "basic_limited_owner": 4,
            "unrestricted_empty_owner": 5,
            "unrestricted_json_null_owner": 6,
            "unrestricted_sql_null_owner": 7,
            "user_craft_bundle": 2,
            "unrestricted_manager": 8,
            "narrow_manager": 8,
        }
        connection.execute(
            insert,
            [
                {
                    "id": token_id,
                    "name": name,
                    "user_id": owner_ids.get(name, 1),
                    "scopes": scopes,
                    "pat_type": "CRAFT" if name.startswith("craft") else "USER",
                }
                for token_id, (name, scopes) in enumerate(raw_scopes.items(), start=1)
            ],
        )
        connection.execute(
            text("""
                UPDATE personal_access_token SET is_revoked = true
                WHERE name = 'revoked';
                UPDATE personal_access_token SET expires_at = '2020-01-01T00:00:00Z'
                WHERE name = 'expired';
                UPDATE personal_access_token SET scopes = 'null'::jsonb
                WHERE name IN (
                    'unrestricted_basic_json_null',
                    'unrestricted_admin_json_null',
                    'unrestricted_json_null_owner'
                );
            """)
        )
        original_rows = connection.execute(
            text("SELECT * FROM personal_access_token ORDER BY id")
        ).all()
        original_scope_storage = connection.execute(
            text("SELECT name, scopes::text FROM personal_access_token ORDER BY id")
        ).all()
        scripts = ScriptDirectory(str(Path(__file__).resolve().parents[3] / "alembic"))
        revision = scripts.get_revision("e826382a22c8")
        assert revision is not None
        with Operations.context(MigrationContext.configure(connection)):
            for _ in range(2):
                revision.module.upgrade()
                columns = {
                    column["name"]: column
                    for column in inspect(connection).get_columns(
                        "personal_access_token", schema=schema
                    )
                }
                assert "permission_cap" in columns
                assert isinstance(columns["permission_cap"]["type"], JSONB)
                assert not columns["permission_cap"]["nullable"]
                assert columns["permission_cap"]["default"] is None
                rows = connection.execute(
                    text(
                        "SELECT name, scopes, permission_cap FROM personal_access_token"
                    )
                ).all()
                assert {row.name: row.scopes for row in rows} == raw_scopes
                assert (
                    connection.execute(
                        text(
                            "SELECT name, scopes::text FROM personal_access_token ORDER BY id"
                        )
                    ).all()
                    == original_scope_storage
                )
                assert {
                    row.name: set(row.permission_cap) for row in rows
                } == expected_caps
                assert all(
                    row.permission_cap == sorted(row.permission_cap) for row in rows
                )
                with pytest.raises(IntegrityError), connection.begin_nested():
                    connection.execute(
                        text("""
                            INSERT INTO personal_access_token (id, name, user_id)
                            VALUES (100, 'missing-cap', 1)
                        """)
                    )
                revision.module.downgrade()
                assert "permission_cap" not in {
                    column["name"]
                    for column in inspect(connection).get_columns(
                        "personal_access_token", schema=schema
                    )
                }
                assert (
                    connection.execute(
                        text("SELECT * FROM personal_access_token ORDER BY id")
                    ).all()
                    == original_rows
                )
        connection.rollback()
