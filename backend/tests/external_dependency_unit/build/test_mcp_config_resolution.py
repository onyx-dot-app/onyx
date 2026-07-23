"""External-dependency-unit tests for `resolve_craft_mcp_servers`.

Verifies the DB → opencode-config-input step: only craft-enabled servers the
user may access are emitted, tools split into enabled/disabled by the admin's
chat-side curation, and the opencode server key is stable + identifier-safe.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import (
    create_connection_config,
    create_mcp_server__no_commit,
    update_mcp_server__no_commit,
)
from onyx.db.models import MCPServer, Tool
from onyx.server.features.build.sandbox.util.mcp_config import (
    craft_mcp_fingerprint,
    resolve_craft_mcp_servers,
)
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def craft_server(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[MCPServer, MCPServer], None, None]:
    created: list[MCPServer] = []

    def _server(name: str, *, available_in_craft: bool) -> MCPServer:
        server = create_mcp_server__no_commit(
            owner_email="admin@example.com",
            name=name,
            description=None,
            server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
            auth_type=MCPAuthenticationType.API_TOKEN,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        update_mcp_server__no_commit(
            server_id=server.id,
            db_session=db_session,
            available_in_craft=available_in_craft,
        )
        created.append(server)
        return server

    craft = _server("Linear MCP", available_in_craft=True)
    db_session.add(Tool(name="list_issues", mcp_server_id=craft.id, enabled=True))
    db_session.add(Tool(name="create_issue", mcp_server_id=craft.id, enabled=True))
    db_session.add(Tool(name="delete_issue", mcp_server_id=craft.id, enabled=False))
    off = _server("Off Server", available_in_craft=False)
    db_session.commit()

    yield craft, off  # type: ignore[misc]
    db_session.rollback()
    for server in created:
        db_session.delete(server)
    db_session.commit()


def test_only_craft_enabled_servers_resolved_with_tool_curation(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
) -> None:
    craft, off = craft_server
    user = create_test_user(db_session, "mcp_config")
    by_url = {c.url: c for c in resolve_craft_mcp_servers(db_session, user)}

    assert off.server_url not in by_url
    config = by_url[craft.server_url]
    assert config.key == f"linear-mcp-{craft.id}"
    # Only disabled tools are tracked; enabled ones ride the wildcard allow.
    assert config.disabled_tools == ("delete_issue",)


def test_resolve_populates_server_id_and_user_auth(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
) -> None:
    """``server_id`` and ``authenticated`` feed the runtime hash: connecting
    credentials must flip ``authenticated`` and change the fingerprint so the
    user's session hot-reloads (tool discovery is credential-gated)."""
    craft, _ = craft_server
    user = create_test_user(db_session, "mcp_auth")

    before = {c.server_id: c for c in resolve_craft_mcp_servers(db_session, user)}
    assert craft.id in before
    assert before[craft.id].authenticated is False
    fp_before = craft_mcp_fingerprint(list(before.values()))

    create_connection_config(
        {"headers": {"Authorization": "Bearer x"}},
        db_session,
        mcp_server_id=craft.id,
        user_email=user.email,
    )
    db_session.commit()

    after = {c.server_id: c for c in resolve_craft_mcp_servers(db_session, user)}
    assert after[craft.id].authenticated is True
    assert craft_mcp_fingerprint(list(after.values())) != fp_before


def test_private_unshared_server_excluded_for_user(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
) -> None:
    """A craft-enabled but private, unshared server is not emitted into another
    user's sandbox config (the owner still sees it)."""
    craft, _ = craft_server
    craft.is_public = False
    db_session.commit()

    user = create_test_user(db_session, "mcp_config")
    assert craft.server_url not in {
        c.url for c in resolve_craft_mcp_servers(db_session, user)
    }

    owner = create_test_user(db_session, "mcp_owner")
    craft.owner = owner.email
    db_session.commit()
    assert craft.server_url in {
        c.url for c in resolve_craft_mcp_servers(db_session, owner)
    }
