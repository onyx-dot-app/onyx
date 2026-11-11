"""Connection validation and publication leave no partial database changes."""

import asyncio
import time
from collections.abc import Generator
from unittest.mock import Mock

import pytest
from mcp.types import Tool as MCPTool
from psycopg2.errors import LockNotAvailable
from sqlalchemy import select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from onyx.db.action_policy import (
    get_or_create_gated_app_id,
    replace_workspace_action_policies,
)
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.enums import (
    ActionPolicy,
    GatedAppKind,
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
)
from onyx.db.mcp import get_mcp_server_by_id, upsert_user_connection_config
from onyx.db.models import MCPServer, Tool, User
from onyx.db.persona import (
    set_default_chat_tool__no_commit,
    update_default_assistant_configuration,
)
from onyx.error_handling.exceptions import OnyxError
from onyx.server.features.mcp import api
from onyx.server.features.mcp.credentials import extract_connection_data
from onyx.server.features.mcp.models import MCPConnectionData, MCPSetupRequest
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def setup_db(db_session: Session) -> Generator[Session, None, None]:
    """Exercise application commits inside an outer transaction that is discarded."""
    del db_session  # The shared fixture initializes the database engine.
    with SqlEngine.get_engine().connect() as connection:
        transaction = connection.begin()
        with Session(
            bind=connection, join_transaction_mode="create_savepoint"
        ) as session:
            try:
                yield session
            finally:
                session.close()
                transaction.rollback()


@pytest.fixture
def setup_admin(setup_db: Session, monkeypatch: pytest.MonkeyPatch) -> User:
    monkeypatch.setattr(api, "_hot_reload_craft_sessions", lambda *_: None)
    return create_test_user(setup_db, "staged_mcp", is_admin=True)


def request_for(user: User) -> MCPSetupRequest:
    return MCPSetupRequest(
        name=f"Setup {user.id}",
        server_url="https://old.example.com/mcp",
        auth_type=MCPAuthenticationType.API_TOKEN,
        auth_performer=MCPAuthenticationPerformer.ADMIN,
        api_token="working-secret",
        api_token_changed=True,
        is_public=True,
        enable_chat=False,
    )


def tools_named(name: str) -> list[MCPTool]:
    return [MCPTool(name=name, inputSchema={"type": "object"})]


def test_discovery_failure_does_not_create_server(
    setup_db: Session, setup_admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = request_for(setup_admin)
    monkeypatch.setattr(
        api, "discover_mcp_tools", Mock(side_effect=RuntimeError("Discovery failed"))
    )
    with pytest.raises(RuntimeError, match="Discovery failed"):
        asyncio.run(api.setup_mcp_server(request, setup_db, setup_admin))
    assert (
        setup_db.scalar(select(MCPServer).where(MCPServer.name == request.name)) is None
    )


def test_publish_failure_does_not_commit_new_server_or_tools(
    setup_db: Session, setup_admin: User, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = request_for(setup_admin)
    monkeypatch.setattr(
        api,
        "_db_mcp_server_to_api_mcp_server",
        Mock(side_effect=RuntimeError("Response failed")),
    )
    with pytest.raises(RuntimeError, match="Response failed"):
        api._publish_mcp_setup(
            request, tools_named("new_tool"), None, setup_admin, setup_db
        )
    assert (
        setup_db.scalar(select(MCPServer).where(MCPServer.name == request.name)) is None
    )


@pytest.mark.parametrize("failure_stage", ["discovery", "publish"])
def test_failed_edit_preserves_url_credentials_and_tools(
    setup_db: Session,
    setup_admin: User,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    request = request_for(setup_admin)
    saved = api._publish_mcp_setup(
        request, tools_named("old_tool"), None, setup_admin, setup_db
    )
    previous = get_mcp_server_by_id(saved.id, setup_db)
    fingerprint = api._mcp_setup_configuration_fingerprint(
        previous, setup_admin, setup_db
    )
    credentials = extract_connection_data(previous.admin_connection_config)
    edit = request.model_copy(
        update={
            "existing_server_id": saved.id,
            "name": "Changed draft",
            "server_url": "https://new.example.com/mcp",
            "api_token": "replacement-secret",
        }
    )
    if failure_stage == "discovery":
        monkeypatch.setattr(
            api,
            "discover_mcp_tools",
            Mock(side_effect=RuntimeError("Discovery failed")),
        )
        with pytest.raises(RuntimeError, match="Discovery failed"):
            asyncio.run(api.setup_mcp_server(edit, setup_db, setup_admin))
    else:
        monkeypatch.setattr(
            api,
            "_db_mcp_server_to_api_mcp_server",
            Mock(side_effect=RuntimeError("Response failed")),
        )
        with pytest.raises(RuntimeError, match="Response failed"):
            api._publish_mcp_setup(
                edit, tools_named("new_tool"), None, setup_admin, setup_db, fingerprint
            )
    setup_db.expire_all()
    unchanged = get_mcp_server_by_id(saved.id, setup_db)
    assert unchanged.name == request.name
    assert unchanged.server_url == request.server_url
    assert extract_connection_data(unchanged.admin_connection_config) == credentials
    assert list(
        setup_db.scalars(select(Tool.name).where(Tool.mcp_server_id == saved.id))
    ) == ["old_tool"]


def test_successful_edit_updates_connection_and_tools_together(
    setup_db: Session, setup_admin: User
) -> None:
    request = request_for(setup_admin)
    saved = api._publish_mcp_setup(
        request, tools_named("old_tool"), None, setup_admin, setup_db
    )
    previous = get_mcp_server_by_id(saved.id, setup_db)
    fingerprint = api._mcp_setup_configuration_fingerprint(
        previous, setup_admin, setup_db
    )
    edit = request.model_copy(
        update={
            "existing_server_id": saved.id,
            "server_url": "https://new.example.com/mcp",
            "api_token": "replacement-secret",
        }
    )
    api._publish_mcp_setup(
        edit, tools_named("new_tool"), None, setup_admin, setup_db, fingerprint
    )
    setup_db.expire_all()
    updated = get_mcp_server_by_id(saved.id, setup_db)
    assert updated.server_url == edit.server_url
    assert extract_connection_data(updated.admin_connection_config)["headers"] == {
        "Authorization": "Bearer replacement-secret"
    }
    assert list(
        setup_db.scalars(select(Tool.name).where(Tool.mcp_server_id == saved.id))
    ) == ["new_tool"]


def test_stale_edit_cannot_overwrite_a_newer_saved_configuration(
    setup_db: Session, setup_admin: User
) -> None:
    request = request_for(setup_admin)
    saved = api._publish_mcp_setup(
        request, tools_named("old_tool"), None, setup_admin, setup_db
    )
    server = get_mcp_server_by_id(saved.id, setup_db)
    fingerprint = api._mcp_setup_configuration_fingerprint(
        server, setup_admin, setup_db
    )
    server.description = "Saved while authentication was pending"
    setup_db.commit()
    edit = request.model_copy(
        update={"existing_server_id": saved.id, "api_token": "stale-secret"}
    )
    with pytest.raises(OnyxError, match="configuration changed"):
        api._publish_mcp_setup(
            edit, tools_named("new_tool"), None, setup_admin, setup_db, fingerprint
        )
    setup_db.expire_all()
    preserved = get_mcp_server_by_id(saved.id, setup_db)
    assert preserved.description == "Saved while authentication was pending"
    assert extract_connection_data(preserved.admin_connection_config)["headers"] == {
        "Authorization": "Bearer working-secret"
    }


@pytest.mark.parametrize(
    "setting", ["action_policy", "policy_management", "default_chat"]
)
def test_pending_edit_preserves_newer_policy_and_chat_settings(
    setup_db: Session, setup_admin: User, setting: str
) -> None:
    request = request_for(setup_admin)
    saved = api._publish_mcp_setup(
        request, tools_named("old_tool"), None, setup_admin, setup_db
    )
    server = get_mcp_server_by_id(saved.id, setup_db)
    fingerprint = api._mcp_setup_configuration_fingerprint(
        server, setup_admin, setup_db
    )
    if setting == "default_chat":
        tool = setup_db.scalar(select(Tool).where(Tool.mcp_server_id == saved.id))
        assert tool is not None
        set_default_chat_tool__no_commit(setup_db, tool, True)
    else:
        gated_app_id = get_or_create_gated_app_id(
            setup_db, GatedAppKind.MCP_SERVER, saved.id
        )
        replace_workspace_action_policies(
            setup_db,
            gated_app_id,
            {"old_tool": ActionPolicy.DENY} if setting == "action_policy" else None,
            users_can_manage=False if setting == "policy_management" else None,
        )
    setup_db.commit()
    edit = request.model_copy(update={"existing_server_id": saved.id})
    with pytest.raises(OnyxError, match="configuration changed"):
        api._publish_mcp_setup(
            edit, tools_named("new_tool"), None, setup_admin, setup_db, fingerprint
        )


def test_edit_retains_registered_oauth_client_metadata(
    setup_db: Session, setup_admin: User
) -> None:
    request = MCPSetupRequest(
        name="Registered OAuth",
        oauth_setup_mode="automatic",
        server_url="https://old.example.com/mcp",
        auth_type=MCPAuthenticationType.OAUTH,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        oauth_client_id="client",
        oauth_client_secret="secret",
        is_public=True,
    )
    registration = {
        "redirect_uris": ["https://onyx.example.com/mcp/oauth/callback"],
        "client_id": "client",
        "client_secret": "secret",
        "token_endpoint_auth_method": "client_secret_basic",
        "client_id_issued_at": 1234567890,
    }
    saved = api._publish_mcp_setup(
        request,
        tools_named("old_tool"),
        {
            "headers": {},
            "client_info": registration,
            "tokens": {
                "access_token": "access",
                "token_type": "Bearer",
                "refresh_token": "original",
            },
            "token_expires_at": time.time() + 3600,
        },
        setup_admin,
        setup_db,
    )
    edit = request.model_copy(
        update={
            "existing_server_id": saved.id,
            "oauth_client_secret": "••••••••••••",
            "oauth_setup_mode": None,
        }
    )
    normalized, fingerprint, client_information = api._prepare_mcp_setup(
        edit, setup_admin, setup_db
    )
    assert normalized.oauth_client_secret == "secret"
    assert client_information is not None
    assert client_information.token_endpoint_auth_method == "client_secret_basic"
    assert client_information.client_id_issued_at == 1234567890
    assert normalized.oauth_setup_mode == "automatic"
    rotated: MCPConnectionData = {
        "headers": {"Authorization": "Bearer rotated"},
        "client_info": registration,
        "tokens": {
            "access_token": "rotated",
            "token_type": "Bearer",
            "refresh_token": "fresh",
        },
        "token_expires_at": time.time() + 7200,
    }
    upsert_user_connection_config(saved.id, setup_admin.email, rotated, setup_db)
    setup_db.commit()
    assert (
        api._mcp_setup_configuration_fingerprint(
            get_mcp_server_by_id(saved.id, setup_db), setup_admin, setup_db
        )
        == fingerprint
    )
    normalized.transport = api.MCPTransport.SSE
    result = api._publish_mcp_setup(
        normalized,
        tools_named("new_tool"),
        None,
        setup_admin,
        setup_db,
        fingerprint,
        reuse_existing_grant=True,
    )
    assert result.transport == api.MCPTransport.SSE
    current = extract_connection_data(
        api.get_user_connection_config(saved.id, setup_admin.email, setup_db)
    )
    assert current["tokens"]["refresh_token"] == "fresh"
    current.pop("token_expires_at")
    upsert_user_connection_config(saved.id, setup_admin.email, current, setup_db)
    setup_db.commit()
    omitted_transport = edit.model_copy(update={"transport": None})
    prepared, _, _ = api._prepare_mcp_setup(omitted_transport, setup_admin, setup_db)
    assert prepared.transport == api.MCPTransport.SSE
    assert api._reusable_mcp_setup_grant(prepared, setup_admin, setup_db) is not None
    different_endpoint = edit.model_copy(
        update={
            "server_url": "https://new.example.com/mcp",
            "oauth_client_id": None,
            "oauth_client_secret": None,
        }
    )
    _, _, different_registration = api._prepare_mcp_setup(
        different_endpoint, setup_admin, setup_db
    )
    assert different_registration is None


def test_pending_publication_blocks_concurrent_default_chat_save(
    setup_db: Session,
    setup_admin: User,
) -> None:
    request = request_for(setup_admin)
    saved = api._publish_mcp_setup(
        request, tools_named("old_tool"), None, setup_admin, setup_db
    )
    edit = request.model_copy(update={"existing_server_id": saved.id})
    prepared, fingerprint, _ = api._prepare_mcp_setup(edit, setup_admin, setup_db)
    api._assert_mcp_setup_current(
        prepared, setup_admin, setup_db, fingerprint, for_update=True
    )
    with Session(SqlEngine.get_engine()) as concurrent:
        concurrent.execute(text("SET LOCAL lock_timeout = '100ms'"))
        with pytest.raises(OperationalError) as error:
            update_default_assistant_configuration(concurrent, tool_ids=[])
        assert isinstance(error.value.orig, LockNotAvailable)
        concurrent.rollback()
