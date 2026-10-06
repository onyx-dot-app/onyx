import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI
from redis.asyncio import Redis
from sqlalchemy import Engine, Table, text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.orm import Session

from ee.onyx.server.middleware import tenant_tracking
from onyx.auth.session_tokens import build_session_token_value
from onyx.auth.users import auth_backend, get_redis_strategy
from onyx.configs import app_configs
from onyx.configs.constants import FASTAPI_USERS_AUTH_COOKIE_NAME
from onyx.db import oauth_provider as oauth_provider_db
from onyx.db.engine import async_sql_engine, sql_engine
from onyx.db.enums import AccountType, Permission
from onyx.db.models import Base, PublicBase, User, UserTenantMapping
from onyx.error_handling.exceptions import register_onyx_exception_handlers
from onyx.server.oauth_provider.api import router
from onyx.utils.logger import setup_logger
from shared_configs.contextvars import CURRENT_TENANT_ID_CONTEXTVAR

pytestmark = pytest.mark.asyncio(loop_scope="module")


async def test_cloud_token_tenant_wins_over_cookie_without_membership_bypass(
    migration_database: Engine, redis_client: Redis, monkeypatch: pytest.MonkeyPatch
) -> None:
    catalog_engine = migration_database
    PublicBase.metadata.create_all(catalog_engine)
    tenant_ids = ["tenant_oauth_a", "tenant_oauth_b"]
    with catalog_engine.begin() as connection:
        for tenant_id in tenant_ids:
            connection.execute(text(f'CREATE SCHEMA "{tenant_id}"'))
    tables = {
        Base.metadata.tables[name]
        for name in (
            "user",
            "oauth_account",
            "user__pinned_persona",
            "key_value_store",
            "oauth_provider_grant",
            "oauth_provider_token",
            "api_key",
            "personal_access_token",
        )
    }
    pending = list(tables)
    while pending:
        table = pending.pop()
        for foreign_key in table.foreign_keys:
            dependency = foreign_key.column.table
            assert isinstance(dependency, Table)
            if dependency not in tables:
                tables.add(dependency)
                pending.append(dependency)
    for tenant_id in tenant_ids:
        Base.metadata.create_all(
            catalog_engine.execution_options(schema_translate_map={None: tenant_id}),
            tables=list(tables),
        )
    async_engine = create_async_engine(
        catalog_engine.url.set(drivername="postgresql+asyncpg")
    )
    routed_tenants: list[str] = []

    def sync_engine_for_tenant(tenant_id: str) -> Engine:
        routed_tenants.append(tenant_id)
        return catalog_engine

    async def async_engine_for_tenant(tenant_id: str) -> AsyncEngine:
        routed_tenants.append(tenant_id)
        return async_engine

    monkeypatch.setattr(sql_engine, "get_engine_for_tenant", sync_engine_for_tenant)
    monkeypatch.setattr(sql_engine, "get_catalog_engine", lambda: catalog_engine)
    monkeypatch.setattr(
        async_sql_engine, "get_async_engine_for_tenant", async_engine_for_tenant
    )
    monkeypatch.setattr(mcp_oauth, "MULTI_TENANT", True)
    monkeypatch.setattr(tenant_tracking, "MULTI_TENANT", True)
    monkeypatch.setattr(app_configs, "OAUTH_PROVIDER_ENABLED", True)
    monkeypatch.setattr(app_configs, "WEB_DOMAIN", "http://localhost:3000")
    monkeypatch.setattr(app_configs, "MCP_SERVER_OAUTH_RESOURCE_URL", None)
    users: list[User] = []
    access_tokens: list[str] = []
    context = CURRENT_TENANT_ID_CONTEXTVAR.set("public")
    session_token = secrets.token_urlsafe(32)
    strategy = get_redis_strategy()
    try:
        for index, tenant_id in enumerate(tenant_ids):
            CURRENT_TENANT_ID_CONTEXTVAR.set(tenant_id)
            with sql_engine.get_session_with_current_tenant() as session:
                user = User(
                    id=uuid4(),
                    email=f"oauth-owner-{index}@example.com",
                    hashed_password="unused",
                    is_active=True,
                    is_verified=True,
                    is_superuser=False,
                    account_type=AccountType.STANDARD,
                    effective_permissions=[
                        Permission.READ_SEARCH.value,
                        Permission.CREATE_USER_API_KEYS.value,
                    ],
                )
                session.add(user)
                session.commit()
                pair = oauth_provider_db.create_mcp_oauth_grant__no_commit(
                    session,
                    user_id=user.id,
                    client_id="tenant-test-client",
                    client_name="Tenant test",
                    resource="http://localhost:3000/mcp/",
                    issue_refresh=True,
                )
                session.commit()
                assert pair is not None
                users.append(user)
                access_tokens.append(pair.access_token)
            with Session(catalog_engine) as catalog:
                catalog.add(
                    UserTenantMapping(
                        email=user.email, tenant_id=tenant_id, active=True
                    )
                )
                catalog.commit()
        CURRENT_TENANT_ID_CONTEXTVAR.set("public")
        now = datetime.now(timezone.utc)
        await redis_client.set(
            f"{strategy.key_prefix}{session_token}",
            build_session_token_value(
                user_id=str(users[1].id),
                tenant_id=tenant_ids[1],
                issued_at=now,
                expires_at=now + timedelta(minutes=5),
            ),
            ex=300,
        )
        app = FastAPI()
        register_onyx_exception_handlers(app)
        app.include_router(router)
        app.dependency_overrides[auth_backend.get_strategy] = get_redis_strategy
        tenant_tracking.add_api_server_tenant_id_middleware(app, setup_logger())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app),
            base_url="http://localhost:3000",
            cookies={FASTAPI_USERS_AUTH_COOKIE_NAME: session_token},
        ) as client:
            response = await client.get(
                "/oauth-provider/introspect",
                headers={"Authorization": f"Bearer {access_tokens[0]}"},
            )
            assert response.status_code == 200, response.text
            assert response.json()["subject"] == str(users[0].id)
            tampered = access_tokens[0].replace(tenant_ids[0], tenant_ids[1])
            assert (
                await client.get(
                    "/oauth-provider/introspect",
                    headers={"Authorization": f"Bearer {tampered}"},
                )
            ).status_code == 401
            unknown = access_tokens[0].replace(tenant_ids[0], "tenant_does_not_exist")
            assert (
                await client.get(
                    "/oauth-provider/introspect",
                    headers={"Authorization": f"Bearer {unknown}"},
                )
            ).status_code == 401
            assert "tenant_does_not_exist" not in routed_tenants
            with Session(catalog_engine) as catalog:
                owner = catalog.get(UserTenantMapping, (users[0].email, tenant_ids[0]))
                assert owner is not None
                owner.active = False
                catalog.add(
                    UserTenantMapping(
                        email="other-member@example.com",
                        tenant_id=tenant_ids[0],
                        active=True,
                    )
                )
                catalog.commit()
            retired = await client.get(
                "/oauth-provider/introspect",
                headers={"Authorization": f"Bearer {access_tokens[0]}"},
            )
            assert retired.status_code == 401, retired.text
    finally:
        await redis_client.delete(f"{strategy.key_prefix}{session_token}")
        await async_engine.dispose()
        CURRENT_TENANT_ID_CONTEXTVAR.reset(context)
