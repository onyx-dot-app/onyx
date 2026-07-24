"""External-dependency-unit tests for `resolve_craft_mcp_servers`.

Verifies the DB → opencode-config-input step: only craft-enabled servers the
user may access *and the proxy can authenticate them against* are emitted, tools
split into enabled/disabled by the admin's chat-side curation, and the opencode
server key is stable + identifier-safe.
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
        # NONE auth keeps these fixtures about access + tool curation: they need
        # no stored credentials to pass the emission filter.
        server = create_mcp_server__no_commit(
            owner_email="admin@example.com",
            name=name,
            description=None,
            server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
            auth_type=MCPAuthenticationType.NONE,
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


def test_per_user_server_emitted_only_once_credentials_connected(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
) -> None:
    """A PER_USER server the proxy can't authenticate is not emitted at all —
    its tool discovery would be blocked at injection. Connecting credentials adds
    it to the set, which changes the fingerprint so the session hot-reloads."""
    craft, _ = craft_server
    craft.auth_type = MCPAuthenticationType.API_TOKEN
    craft.auth_performer = MCPAuthenticationPerformer.PER_USER
    db_session.commit()
    user = create_test_user(db_session, "mcp_auth")

    before = resolve_craft_mcp_servers(db_session, user)
    assert craft.id not in {c.server_id for c in before}
    fp_before = craft_mcp_fingerprint(before)

    config = create_connection_config(
        {"headers": {"Authorization": "Bearer x"}},
        db_session,
        mcp_server_id=craft.id,
        user_email=user.email,
    )
    db_session.commit()

    after = resolve_craft_mcp_servers(db_session, user)
    assert craft.id in {c.server_id for c in after}
    assert craft_mcp_fingerprint(after) != fp_before

    # Disconnecting drops it back out, restoring the original fingerprint.
    db_session.delete(config)
    db_session.commit()
    assert (
        craft_mcp_fingerprint(resolve_craft_mcp_servers(db_session, user)) == fp_before
    )


def test_admin_managed_server_emitted_without_per_user_credentials(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
) -> None:
    """An ADMIN-performer server authenticates every user off the admin's stored
    credential (`user_email=""`), so it must be emitted for a user who has no
    per-user row of their own."""
    craft, _ = craft_server
    craft.auth_type = MCPAuthenticationType.API_TOKEN
    craft.auth_performer = MCPAuthenticationPerformer.ADMIN
    craft.admin_connection_config = create_connection_config(
        {"headers": {"Authorization": "Bearer admin-token"}},
        db_session,
        mcp_server_id=craft.id,
        user_email="",
    )
    db_session.commit()

    user = create_test_user(db_session, "mcp_admin_managed")
    assert craft.id in {
        c.server_id for c in resolve_craft_mcp_servers(db_session, user)
    }


def test_no_auth_server_emitted_with_no_credentials_stored(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
) -> None:
    """`auth_type=NONE` needs no credentials, so it is emitted as-is."""
    craft, _ = craft_server
    assert craft.auth_type == MCPAuthenticationType.NONE
    user = create_test_user(db_session, "mcp_no_auth")
    assert craft.id in {
        c.server_id for c in resolve_craft_mcp_servers(db_session, user)
    }


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
