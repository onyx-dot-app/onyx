"""Tests for admin-defined custom headers on MCP servers.

Covers the credential-resolution chokepoint (`ResolvedMCPCredentials`), the
upsert masked-value/changed-flag handling, request validation, and the chat
runtime path (`MCPTool.run`). Postgres is running; outbound MCP calls are
mocked.
"""

import queue
from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from onyx.chat.emitter import Emitter
from onyx.db.enums import (
    MCPAuthenticationPerformer,
    MCPAuthenticationType,
    MCPTransport,
)
from onyx.db.mcp import (
    ResolvedMCPCredentials,
    can_resolve_mcp_credentials,
    create_mcp_server__no_commit,
    extract_custom_headers,
    resolve_mcp_credentials,
)
from onyx.db.models import MCPServer, OAuthAccount, User
from onyx.server.features.mcp.api import _upsert_mcp_server
from onyx.server.features.mcp.models import MCPToolCreateRequest
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from onyx.utils.sensitive import SensitiveValue
from tests.external_dependency_unit.conftest import create_test_user

_GATEWAY_KEY_HEADER = "x-litellm-api-key"
_GATEWAY_KEY_VALUE = "Bearer gateway_admission_key_123"
_ATTRIBUTION_HEADER = "x-litellm-end-user-id"


def _create_pt_oauth_user(db_session: Session, prefix: str) -> tuple[User, str]:
    """User with a login OAuth token, as PT_OAUTH requires."""
    user = create_test_user(db_session, prefix)
    token = f"login_token_{uuid4().hex[:8]}"
    db_session.add(
        OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id=f"acct_{uuid4().hex[:8]}",
            account_email=user.email,
            access_token=token,
            refresh_token="",
        )
    )
    db_session.commit()
    db_session.refresh(user)
    return user, token


def _create_server_with_custom_headers(
    db_session: Session,
    owner_email: str,
    auth_type: MCPAuthenticationType,
    custom_headers: dict[str, str] | None,
) -> MCPServer:
    server = create_mcp_server__no_commit(
        owner_email=owner_email,
        name=f"Custom Header Server {uuid4().hex[:8]}",
        description=None,
        server_url="http://gateway.example.com/mcp",
        auth_type=auth_type,
        transport=MCPTransport.STREAMABLE_HTTP,
        auth_performer=MCPAuthenticationPerformer.PER_USER,
        db_session=db_session,
        custom_headers=custom_headers,
    )
    db_session.commit()
    db_session.refresh(server)
    return server


class TestResolvedCredentials:
    def test_custom_headers_merged_below_auth_headers(
        self, db_session: Session
    ) -> None:
        """PT_OAUTH: custom headers ride along, {user_email} is substituted,
        and the login token owns Authorization."""
        user, token = _create_pt_oauth_user(db_session, "gateway_user")
        server = _create_server_with_custom_headers(
            db_session,
            user.email,
            MCPAuthenticationType.PT_OAUTH,
            {
                _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE,
                _ATTRIBUTION_HEADER: "{user_email}",
            },
        )

        creds = resolve_mcp_credentials(server, user, db_session)
        headers = creds.build_headers()

        assert headers[_GATEWAY_KEY_HEADER] == _GATEWAY_KEY_VALUE
        assert headers[_ATTRIBUTION_HEADER] == user.email
        assert headers["Authorization"] == f"Bearer {token}"
        # Auth headers exclude the custom headers — they signal "connected".
        assert _GATEWAY_KEY_HEADER not in creds.build_auth_headers()

    def test_stored_reserved_headers_stripped_at_read(self) -> None:
        """A directly-written DB row can't smuggle Authorization or Host
        through custom headers — build_headers strips them defensively."""
        creds = ResolvedMCPCredentials(
            connection_config=None,
            user_oauth_token="real_user_token",
            custom_headers={
                "authorization": "Bearer attacker_token",
                "Host": "internal.example.com",
                _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE,
            },
            user_email="someone@example.com",
        )
        headers = creds.build_headers()
        assert headers["Authorization"] == "Bearer real_user_token"
        assert "authorization" not in headers
        assert "Host" not in headers
        assert headers[_GATEWAY_KEY_HEADER] == _GATEWAY_KEY_VALUE

    def test_custom_headers_do_not_fake_connected_state(
        self, db_session: Session
    ) -> None:
        """A per-user OAUTH server with custom headers but no stored user
        credentials must still resolve as not-connected."""
        user = create_test_user(db_session, "unconnected_user")
        server = _create_server_with_custom_headers(
            db_session,
            user.email,
            MCPAuthenticationType.OAUTH,
            {_GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE},
        )
        assert not can_resolve_mcp_credentials(server, user, db_session)

    def test_none_auth_still_sends_custom_headers(self, db_session: Session) -> None:
        user = create_test_user(db_session, "none_auth_user")
        server = _create_server_with_custom_headers(
            db_session,
            user.email,
            MCPAuthenticationType.NONE,
            {_GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE},
        )
        creds = resolve_mcp_credentials(server, user, db_session)
        assert creds.build_headers() == {_GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE}
        assert creds.build_auth_headers() == {}


class TestRequestValidation:
    def _base_request(self, custom_headers: dict[str, str]) -> dict[str, Any]:
        return {
            "name": "Validation Server",
            "server_url": "http://gateway.example.com/mcp",
            "auth_type": MCPAuthenticationType.PT_OAUTH,
            "auth_performer": MCPAuthenticationPerformer.PER_USER,
            "custom_headers": custom_headers,
        }

    def test_authorization_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Authorization"):
            MCPToolCreateRequest(**self._base_request({"Authorization": "Bearer nope"}))

    def test_host_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Host"):
            MCPToolCreateRequest(**self._base_request({"Host": "evil.example.com"}))

    def test_invalid_field_name_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Invalid custom header name"):
            MCPToolCreateRequest(**self._base_request({"bad header": "value"}))

    def test_case_insensitive_duplicate_rejected(self) -> None:
        with pytest.raises(ValidationError, match="Duplicate custom header"):
            MCPToolCreateRequest(
                **self._base_request({"X-Api-Key": "a", "x-api-key": "b"})
            )

    def test_valid_headers_accepted(self) -> None:
        request = MCPToolCreateRequest(
            **self._base_request({_GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE})
        )
        assert request.custom_headers == {_GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE}


class TestUpsert:
    def test_create_persists_encrypted_and_masked_replay_is_ignored(
        self, db_session: Session
    ) -> None:
        admin = create_test_user(db_session, "upsert_admin")
        create_request = MCPToolCreateRequest(
            name=f"Upsert Server {uuid4().hex[:8]}",
            server_url="http://gateway.example.com/mcp",
            auth_type=MCPAuthenticationType.PT_OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            custom_headers={
                _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE,
                _ATTRIBUTION_HEADER: "{user_email}",
            },
        )
        server = _upsert_mcp_server(create_request, db_session, admin)
        assert isinstance(server.custom_headers, SensitiveValue)
        assert extract_custom_headers(server) == {
            _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE,
            _ATTRIBUTION_HEADER: "{user_email}",
        }

        # Edit replaying masked values (changed=False) keeps stored values;
        # a changed key takes the new value; a dropped key is removed.
        update_request = MCPToolCreateRequest(
            name=server.name,
            server_url=server.server_url,
            auth_type=MCPAuthenticationType.PT_OAUTH,
            auth_performer=MCPAuthenticationPerformer.PER_USER,
            transport=MCPTransport.STREAMABLE_HTTP,
            existing_server_id=server.id,
            custom_headers={
                _GATEWAY_KEY_HEADER: "••••••••••••",  # masked replay
                "x-new-header": "fresh_value",
            },
            custom_headers_changed={
                _GATEWAY_KEY_HEADER: False,
                "x-new-header": True,
            },
        )
        server = _upsert_mcp_server(update_request, db_session, admin)
        assert extract_custom_headers(server) == {
            _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE,
            "x-new-header": "fresh_value",
        }

    def test_omitted_field_leaves_headers_untouched_and_empty_clears(
        self, db_session: Session
    ) -> None:
        admin = create_test_user(db_session, "upsert_admin2")
        base: dict[str, Any] = {
            "name": f"Upsert Server {uuid4().hex[:8]}",
            "server_url": "http://gateway.example.com/mcp",
            "auth_type": MCPAuthenticationType.PT_OAUTH,
            "auth_performer": MCPAuthenticationPerformer.PER_USER,
            "transport": MCPTransport.STREAMABLE_HTTP,
        }
        server = _upsert_mcp_server(
            MCPToolCreateRequest(
                **base, custom_headers={_GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE}
            ),
            db_session,
            admin,
        )

        server = _upsert_mcp_server(
            MCPToolCreateRequest(**base, existing_server_id=server.id),
            db_session,
            admin,
        )
        assert extract_custom_headers(server) == {
            _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE
        }

        server = _upsert_mcp_server(
            MCPToolCreateRequest(
                **base, existing_server_id=server.id, custom_headers={}
            ),
            db_session,
            admin,
        )
        assert extract_custom_headers(server) == {}


class TestMCPToolRun:
    def test_run_sends_custom_headers_alongside_user_authorization(
        self, db_session: Session
    ) -> None:
        """The customer scenario: per-user OAuth through a gateway. The tool
        call must carry the gateway admission key, the substituted attribution
        header, and the user's own Authorization."""
        user, token = _create_pt_oauth_user(db_session, "run_user")
        server = _create_server_with_custom_headers(
            db_session,
            user.email,
            MCPAuthenticationType.PT_OAUTH,
            {
                _GATEWAY_KEY_HEADER: _GATEWAY_KEY_VALUE,
                _ATTRIBUTION_HEADER: "{user_email}",
            },
        )
        creds = resolve_mcp_credentials(server, user, db_session)
        mcp_tool = MCPTool(
            tool_id=1,
            emitter=Emitter(merged_queue=queue.Queue()),
            mcp_server=server,
            tool_name="gateway_tool",
            tool_description="tool behind a gateway",
            tool_definition={"type": "object", "properties": {}},
            connection_config=creds.connection_config,
            user_email=user.email,
            user_id=str(user.id),
            user_oauth_token=creds.user_oauth_token,
        )

        captured_headers: dict[str, str] = {}

        def mock_call_mcp_tool(
            server_url: str,  # noqa: ARG001
            tool_name: str,  # noqa: ARG001
            arguments: dict[str, Any],  # noqa: ARG001
            connection_headers: dict[str, str],
            transport: MCPTransport,  # noqa: ARG001
            auth: Any = None,  # noqa: ARG001
        ) -> dict[str, Any]:
            captured_headers.update(connection_headers)
            return {"result": "ok"}

        with patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            side_effect=mock_call_mcp_tool,
        ):
            mcp_tool.run(placement=Placement(turn_index=0, tab_index=0))

        assert captured_headers[_GATEWAY_KEY_HEADER] == _GATEWAY_KEY_VALUE
        assert captured_headers[_ATTRIBUTION_HEADER] == user.email
        assert captured_headers["Authorization"] == f"Bearer {token}"
