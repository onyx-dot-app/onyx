"""External-dependency-unit tests for ``resolve_craft_mcp_servers``.

Verifies the DB → opencode-config-input step: only craft-enabled servers the
user may access *and the proxy can authenticate them against* are emitted, tools
split into enabled/disabled by the admin's chat-side curation, and the opencode
server key is stable + identifier-safe.
"""

from __future__ import annotations

from collections.abc import Generator
from uuid import uuid4

import pytest
from sqlalchemy import event
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
from onyx.server.features.mcp.api import get_craft_mcp_servers_for_user
from onyx.server.features.mcp.models import MCPConnectionData
from tests.external_dependency_unit.conftest import create_test_user


@pytest.fixture
def craft_server(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> Generator[tuple[MCPServer, MCPServer], None, None]:
    created: list[MCPServer] = []

    def _server(name: str, *, available_in_craft: bool) -> MCPServer:
        # NONE auth keeps these fixtures about access + tool curation, not
        # credentials.
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

    yield craft, off
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
    """An unauthenticated PER_USER server is not emitted at all; connecting
    credentials adds it, changing the fingerprint so the session hot-reloads."""
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

    # Disconnecting drops it back out.
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
    credential (`user_email=""`), so a user with no per-user row still gets it."""
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


_ADMIN_HEADERS: MCPConnectionData = {"headers": {"Authorization": "Bearer admin-token"}}
# What an admin-performed OAuth setup actually stores: the registered client, no
# tokens. Tokens from the exchange land in the *user's* config, which the ADMIN
# performer branch never reads — so the client alone authenticates nobody.
_ADMIN_OAUTH_CLIENT: MCPConnectionData = {
    "headers": {},
    "client_info": {"client_id": "abc123"},
}

# label, auth type, performer, admin config contents, per-user credential, connected
_LISTING_CASES: list[
    tuple[
        str,
        MCPAuthenticationType,
        MCPAuthenticationPerformer,
        MCPConnectionData | None,
        bool,
        bool,
    ]
] = [
    (
        "no auth",
        MCPAuthenticationType.NONE,
        MCPAuthenticationPerformer.ADMIN,
        None,
        False,
        True,
    ),
    (
        "admin api token",
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationPerformer.ADMIN,
        _ADMIN_HEADERS,
        False,
        True,
    ),
    (
        "admin api token, nothing configured",
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationPerformer.ADMIN,
        None,
        False,
        False,
    ),
    (
        "admin oauth, client registered but no token exchanged",
        MCPAuthenticationType.OAUTH,
        MCPAuthenticationPerformer.ADMIN,
        _ADMIN_OAUTH_CLIENT,
        False,
        False,
    ),
    (
        "per-user api token, connected",
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationPerformer.PER_USER,
        None,
        True,
        True,
    ),
    (
        "per-user api token, disconnected",
        MCPAuthenticationType.API_TOKEN,
        MCPAuthenticationPerformer.PER_USER,
        None,
        False,
        False,
    ),
    # No login OAuth token to pass through, so the proxy cannot authenticate this
    # user even though there is nothing for them to connect.
    (
        "pass-through oauth, password-login user",
        MCPAuthenticationType.PT_OAUTH,
        MCPAuthenticationPerformer.ADMIN,
        None,
        False,
        False,
    ),
]


@pytest.mark.parametrize(
    "label,auth_type,performer,admin_config_data,with_user_config,expected_connected",
    _LISTING_CASES,
    ids=[case[0] for case in _LISTING_CASES],
)
def test_craft_listing_agrees_with_session_emission(
    db_session: Session,
    craft_server: tuple[MCPServer, MCPServer],
    label: str,
    auth_type: MCPAuthenticationType,
    performer: MCPAuthenticationPerformer,
    admin_config_data: MCPConnectionData | None,
    with_user_config: bool,
    expected_connected: bool,
) -> None:
    """The Apps page reads `craft_connected`; the sandbox config reads
    `resolve_craft_mcp_servers`. A disagreement means a green "Connected" check on
    a server the session never gets, so pin the two together across the auth
    matrix rather than trusting them to stay in sync by hand.

    Asserting each consumer against `user_can_authenticate` directly cannot
    serve this purpose: both derive from it, so per-consumer assertions would
    pass even if the two consumers drifted apart.
    """
    craft, _ = craft_server
    user = create_test_user(db_session, "mcp_listing")
    craft.auth_type = auth_type
    craft.auth_performer = performer
    if admin_config_data is not None:
        craft.admin_connection_config = create_connection_config(
            admin_config_data,
            db_session,
            mcp_server_id=craft.id,
            user_email="",
        )
    if with_user_config:
        create_connection_config(
            {"headers": {"Authorization": "Bearer user-token"}},
            db_session,
            mcp_server_id=craft.id,
            user_email=user.email,
        )
    db_session.commit()

    emitted = craft.id in {
        c.server_id for c in resolve_craft_mcp_servers(db_session, user)
    }
    listed = {
        server.id: server.craft_connected
        for server in get_craft_mcp_servers_for_user(
            db=db_session, user=user
        ).mcp_servers
    }

    assert craft.id in listed, f"{label}: server missing from the craft listing"
    assert emitted is expected_connected, f"{label}: emission"
    assert listed[craft.id] is expected_connected, f"{label}: listing"


def test_query_count_flat_in_number_of_servers(
    db_session: Session,
    tenant_context: None,  # noqa: ARG001
) -> None:
    """Resolution runs per user in the admin restamp fan-out, which for a public
    server covers every user with a running sandbox — so credential state must be
    batch-loaded rather than queried per server."""
    user = create_test_user(db_session, "mcp_queries")
    created: list[MCPServer] = []

    def _add_per_user_server(*, connected: bool) -> None:
        server = create_mcp_server__no_commit(
            owner_email="admin@example.com",
            name=f"perf-{uuid4().hex[:8]}",
            description=None,
            server_url=f"https://api-{uuid4().hex[:8]}.example.com/mcp",
            auth_type=MCPAuthenticationType.API_TOKEN,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            db_session=db_session,
        )
        update_mcp_server__no_commit(
            server_id=server.id, db_session=db_session, available_in_craft=True
        )
        if connected:
            create_connection_config(
                {"headers": {"Authorization": "Bearer x"}},
                db_session,
                mcp_server_id=server.id,
                user_email=user.email,
            )
        created.append(server)

    def _executed_statements() -> list[str]:
        statements: list[str] = []

        def _record(
            _conn: object, _cursor: object, statement: str, *_rest: object
        ) -> None:
            statements.append(statement)

        db_session.expire_all()
        event.listen(db_session.bind, "before_cursor_execute", _record)
        try:
            resolve_craft_mcp_servers(db_session, user)
        finally:
            event.remove(db_session.bind, "before_cursor_execute", _record)
        return statements

    try:
        for _ in range(2):
            _add_per_user_server(connected=True)
            _add_per_user_server(connected=False)
        db_session.commit()
        baseline = _executed_statements()

        for _ in range(6):
            _add_per_user_server(connected=True)
            _add_per_user_server(connected=False)
        db_session.commit()
        grown = _executed_statements()
        assert len(grown) == len(baseline), (
            f"4 servers -> {len(baseline)} queries, 16 -> {len(grown)}: "
            f"{grown[len(baseline) :]}"
        )
    finally:
        db_session.rollback()
        for server in created:
            db_session.delete(server)
        db_session.commit()


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
