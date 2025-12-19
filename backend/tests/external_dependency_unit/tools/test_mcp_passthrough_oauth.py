"""
Test suite for MCP Pass-Through OAuth (PT_OAUTH) integration.

Tests the pass-through OAuth flow where Onyx forwards the user's login OAuth token
to an MCP server for authentication.

This test:
1. Creates a test user with an OAuthAccount (simulating Google OAuth login)
2. Creates an MCP server with PT_OAUTH auth type
3. Creates MCP tools for that server
4. Verifies the user's OAuth token is correctly passed to MCPTool

All external HTTP calls are mocked, but Postgres and Redis are running.
"""

from typing import Any
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.emitter import get_default_emitter
from onyx.context.search.enums import RecencyBiasSetting
from onyx.db.enums import MCPAuthenticationPerformer
from onyx.db.enums import MCPAuthenticationType
from onyx.db.enums import MCPTransport
from onyx.db.mcp import create_mcp_server__no_commit
from onyx.db.models import OAuthAccount
from onyx.db.models import Persona
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.llm.factory import get_default_llm
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.models import CustomToolCallSummary
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.tools.tool_implementations.mcp.mcp_tool import MCPTool
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_persona_with_mcp_tool(
    db_session: Session, user: User, tools: list[Tool]
) -> Persona:
    """Helper to create a test persona with MCP tools"""
    persona = Persona(
        name=f"Test MCP Persona {uuid4().hex[:8]}",
        description="Test persona with MCP tools",
        num_chunks=10.0,
        chunks_above=0,
        chunks_below=0,
        llm_relevance_filter=False,
        llm_filter_extraction=False,
        recency_bias=RecencyBiasSetting.NO_DECAY,
        system_prompt="You are a helpful assistant",
        task_prompt="Answer the user's question",
        tools=tools,
        document_sets=[],
        users=[user],
        groups=[],
        is_visible=True,
        is_public=True,
        display_priority=None,
        starter_messages=None,
        deleted=False,
    )
    db_session.add(persona)
    db_session.commit()
    db_session.refresh(persona)
    return persona


class TestMCPPassThroughOAuth:
    """Tests for MCP Pass-Through OAuth (PT_OAUTH) flow"""

    @pytest.fixture(autouse=True)
    def setup_llm_provider(self, db_session: Session) -> None:
        """Ensure default LLM provider is set up for each test."""
        ensure_default_llm_provider(db_session)

    def test_pt_oauth_passes_user_login_token(self, db_session: Session) -> None:
        """
        Test that PT_OAUTH correctly passes the user's login OAuth token to MCPTool.

        This simulates a user who logged into Onyx with Google OAuth and is using
        an MCP server that requires their Google token for authentication.
        """
        # Create user with login OAuth token (simulating Google OAuth login)
        user = create_test_user(db_session, "pt_oauth_user")
        user_oauth_token = "google_oauth_token_abc123"

        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id="google_user_12345",
            account_email=user.email,
            access_token=user_oauth_token,
            refresh_token="google_refresh_token",
        )
        db_session.add(oauth_account)
        db_session.commit()
        # Refresh user to load oauth_accounts relationship
        db_session.refresh(user)

        # Create MCP server with PT_OAUTH auth type
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=f"PT_OAUTH Test Server {uuid4().hex[:8]}",
            description="MCP server for pass-through OAuth testing",
            server_url="http://test-mcp-server.example.com/mcp",
            auth_type=MCPAuthenticationType.PT_OAUTH,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,  # Not used for PT_OAUTH
            db_session=db_session,
        )
        db_session.commit()

        # Create MCP tool associated with this server
        mcp_tool_db = Tool(
            name="test_mcp_tool",
            display_name="Test MCP Tool",
            description="Test MCP tool for PT_OAUTH",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={
                "type": "object",
                "properties": {
                    "message": {"type": "string", "description": "Test message"}
                },
            },
            user_id=user.id,
        )
        db_session.add(mcp_tool_db)
        db_session.commit()
        db_session.refresh(mcp_tool_db)

        # Create persona with the MCP tool
        persona = _create_test_persona_with_mcp_tool(db_session, user, [mcp_tool_db])
        llm = get_default_llm()

        # Construct tools
        search_tool_config = SearchToolConfig()

        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=llm,
            search_tool_config=search_tool_config,
        )

        # Verify MCP tool was constructed
        assert mcp_tool_db.id in tool_dict
        constructed_tools = tool_dict[mcp_tool_db.id]
        assert len(constructed_tools) == 1
        mcp_tool = constructed_tools[0]
        assert isinstance(mcp_tool, MCPTool)

        # Verify the user's OAuth token was passed to the MCPTool
        assert mcp_tool._user_oauth_token == user_oauth_token

    def test_pt_oauth_without_user_oauth_account(self, db_session: Session) -> None:
        """
        Test PT_OAUTH behavior when user doesn't have an OAuth account.

        The user logged in with basic auth (no OAuth token), so the MCP tool
        should have no OAuth token to pass through.
        """
        # Create user WITHOUT OAuth account (basic auth login)
        user = create_test_user(db_session, "basic_auth_user")
        # No OAuthAccount created

        # Create MCP server with PT_OAUTH auth type
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=f"PT_OAUTH No Token Server {uuid4().hex[:8]}",
            description="MCP server for testing missing OAuth token",
            server_url="http://test-mcp-server.example.com/mcp",
            auth_type=MCPAuthenticationType.PT_OAUTH,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        db_session.commit()

        # Create MCP tool
        mcp_tool_db = Tool(
            name="test_mcp_tool_no_token",
            display_name="Test MCP Tool No Token",
            description="Test MCP tool without OAuth token",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            user_id=user.id,
        )
        db_session.add(mcp_tool_db)
        db_session.commit()
        db_session.refresh(mcp_tool_db)

        # Create persona
        persona = _create_test_persona_with_mcp_tool(db_session, user, [mcp_tool_db])
        llm = get_default_llm()

        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(),
        )

        # Verify MCP tool was constructed
        assert mcp_tool_db.id in tool_dict
        constructed_tools = tool_dict[mcp_tool_db.id]
        assert len(constructed_tools) == 1
        mcp_tool = constructed_tools[0]
        assert isinstance(mcp_tool, MCPTool)

        # Verify NO OAuth token was passed (user has no OAuth account)
        assert mcp_tool._user_oauth_token is None

    def test_pt_oauth_vs_api_token_auth(self, db_session: Session) -> None:
        """
        Test that PT_OAUTH and API_TOKEN auth types behave differently.

        PT_OAUTH should use the user's login token, while API_TOKEN should
        NOT use the user's login token (it uses the connection config instead).
        """
        # Create user with OAuth account
        user = create_test_user(db_session, "auth_type_test_user")
        user_oauth_token = "user_login_token_xyz789"

        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id="google_user_xyz",
            account_email=user.email,
            access_token=user_oauth_token,
            refresh_token="",
        )
        db_session.add(oauth_account)
        db_session.commit()
        db_session.refresh(user)

        # Create MCP server with API_TOKEN auth type (not PT_OAUTH)
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=f"API Token Server {uuid4().hex[:8]}",
            description="MCP server with API token auth",
            server_url="http://api-token-server.example.com/mcp",
            auth_type=MCPAuthenticationType.API_TOKEN,  # Not PT_OAUTH
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        db_session.commit()

        # Create MCP tool
        mcp_tool_db = Tool(
            name="api_token_tool",
            display_name="API Token Tool",
            description="Tool with API token auth",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={
                "type": "object",
                "properties": {"data": {"type": "string"}},
            },
            user_id=user.id,
        )
        db_session.add(mcp_tool_db)
        db_session.commit()
        db_session.refresh(mcp_tool_db)

        # Create persona
        persona = _create_test_persona_with_mcp_tool(db_session, user, [mcp_tool_db])
        llm = get_default_llm()

        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(),
        )
        # Verify MCP tool was constructed
        assert mcp_tool_db.id in tool_dict
        constructed_tools = tool_dict[mcp_tool_db.id]
        assert len(constructed_tools) == 1
        mcp_tool = constructed_tools[0]
        assert isinstance(mcp_tool, MCPTool)

        # Verify the user's OAuth token was NOT passed (API_TOKEN auth type)
        # API_TOKEN auth should use connection config, not user's login token
        assert mcp_tool._user_oauth_token is None

    def test_mcp_tool_run_sets_authorization_header_for_pt_oauth(
        self, db_session: Session
    ) -> None:
        """
        Test that MCPTool.run() correctly sets the Authorization header
        when PT_OAUTH is configured.
        """
        # Create user with OAuth token
        user = create_test_user(db_session, "pt_oauth_header_user")
        user_oauth_token = "bearer_token_for_mcp_server"

        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id="google_header_user",
            account_email=user.email,
            access_token=user_oauth_token,
            refresh_token="",
        )
        db_session.add(oauth_account)
        db_session.commit()
        db_session.refresh(user)

        # Create MCP server with PT_OAUTH
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=f"Header Test Server {uuid4().hex[:8]}",
            description="Server for testing Authorization header",
            server_url="http://header-test-server.example.com/mcp",
            auth_type=MCPAuthenticationType.PT_OAUTH,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        db_session.commit()

        # Create MCP tool
        mcp_tool_db = Tool(
            name="header_test_tool",
            display_name="Header Test Tool",
            description="Tool to test Authorization header",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={
                "type": "object",
                "properties": {"input": {"type": "string"}},
            },
            user_id=user.id,
        )
        db_session.add(mcp_tool_db)
        db_session.commit()
        db_session.refresh(mcp_tool_db)

        # Create persona
        persona = _create_test_persona_with_mcp_tool(db_session, user, [mcp_tool_db])
        llm = get_default_llm()

        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(),
        )

        # Get the constructed MCPTool
        mcp_tool = tool_dict[mcp_tool_db.id][0]
        assert isinstance(mcp_tool, MCPTool)

        # Mock the call_mcp_tool function to capture the headers
        captured_headers: dict[str, str] = {}

        mocked_response = {"result": "mocked_response"}

        def mock_call_mcp_tool(
            server_url: str,
            tool_name: str,
            kwargs: dict[str, Any],
            connection_headers: dict[str, str],
            transport: MCPTransport,
        ) -> dict[str, Any]:
            captured_headers.update(connection_headers)
            return mocked_response

        with patch(
            "onyx.tools.tool_implementations.mcp.mcp_tool.call_mcp_tool",
            side_effect=mock_call_mcp_tool,
        ):
            # Run the tool
            response = mcp_tool.run(
                placement=Placement(turn_index=0, tab_index=0),
                override_kwargs=None,
                input="test",
            )
            print(response.rich_response)
            assert isinstance(response.rich_response, CustomToolCallSummary)
            print(response.rich_response.tool_result)
            assert response.rich_response.tool_result["tool_result"] == mocked_response

        # Verify Authorization header was set with the user's OAuth token
        assert "Authorization" in captured_headers
        assert captured_headers["Authorization"] == f"Bearer {user_oauth_token}"

    def test_pt_oauth_works_with_oidc_provider(self, db_session: Session) -> None:
        """
        Test that PT_OAUTH works correctly when user logged in via OIDC (not Google).

        This is important because OIDC providers (Okta, Auth0, Keycloak, etc.)
        use oauth_name='openid' while Google uses oauth_name='google'.
        The PT_OAUTH code should work with any OAuth provider.
        """
        # Create user with OIDC OAuth token (simulating Okta/Auth0/Keycloak login)
        user = create_test_user(db_session, "oidc_user")
        # Use a random test token (not a real JWT to avoid pre-commit false positives)
        oidc_access_token = "oidc_test_token_abc123_not_a_real_jwt_xyz789"

        # OIDC providers use oauth_name='openid' by default
        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="openid",  # This is the key difference from Google OAuth
            account_id="oidc_user_sub_12345",
            account_email=user.email,
            access_token=oidc_access_token,
            refresh_token="oidc_refresh_token",
        )
        db_session.add(oauth_account)
        db_session.commit()
        db_session.refresh(user)

        # Create MCP server with PT_OAUTH auth type
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=f"PT_OAUTH OIDC Server {uuid4().hex[:8]}",
            description="MCP server for OIDC pass-through OAuth testing",
            server_url="http://oidc-mcp-server.example.com/mcp",
            auth_type=MCPAuthenticationType.PT_OAUTH,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        db_session.commit()

        # Create MCP tool
        mcp_tool_db = Tool(
            name="oidc_mcp_tool",
            display_name="OIDC MCP Tool",
            description="Test MCP tool for OIDC PT_OAUTH",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
            },
            user_id=user.id,
        )
        db_session.add(mcp_tool_db)
        db_session.commit()
        db_session.refresh(mcp_tool_db)

        # Create persona
        persona = _create_test_persona_with_mcp_tool(db_session, user, [mcp_tool_db])
        llm = get_default_llm()

        # Construct tools
        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(),
        )
        # Verify MCP tool was constructed
        assert mcp_tool_db.id in tool_dict
        constructed_tools = tool_dict[mcp_tool_db.id]
        assert len(constructed_tools) == 1
        mcp_tool = constructed_tools[0]
        assert isinstance(mcp_tool, MCPTool)

        # Verify the OIDC token was passed to the MCPTool
        # (code should work identically for Google OAuth and OIDC)
        assert mcp_tool._user_oauth_token == oidc_access_token

    def test_pt_oauth_uses_first_oauth_account(self, db_session: Session) -> None:
        """
        Test that PT_OAUTH uses the first OAuth account when user has multiple.

        Users might have OAuth accounts from multiple providers (unlikely but possible).
        The code should consistently use the first one.
        """
        user = create_test_user(db_session, "multi_oauth_user")
        first_token = "first_oauth_token_123"
        second_token = "second_oauth_token_456"

        # Add first OAuth account (Google)
        oauth_account_1 = OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id="google_user_123",
            account_email=user.email,
            access_token=first_token,
            refresh_token="",
        )
        db_session.add(oauth_account_1)
        db_session.commit()

        # Add second OAuth account (OIDC)
        oauth_account_2 = OAuthAccount(
            user_id=user.id,
            oauth_name="openid",
            account_id="oidc_user_456",
            account_email=user.email,
            access_token=second_token,
            refresh_token="",
        )
        db_session.add(oauth_account_2)
        db_session.commit()
        db_session.refresh(user)

        # Create MCP server and tool
        mcp_server = create_mcp_server__no_commit(
            owner_email=user.email,
            name=f"Multi OAuth Server {uuid4().hex[:8]}",
            description="MCP server for multi-OAuth testing",
            server_url="http://multi-oauth-server.example.com/mcp",
            auth_type=MCPAuthenticationType.PT_OAUTH,
            transport=MCPTransport.STREAMABLE_HTTP,
            auth_performer=MCPAuthenticationPerformer.ADMIN,
            db_session=db_session,
        )
        db_session.commit()

        mcp_tool_db = Tool(
            name="multi_oauth_tool",
            display_name="Multi OAuth Tool",
            description="Test tool",
            mcp_server_id=mcp_server.id,
            mcp_input_schema={"type": "object", "properties": {}},
            user_id=user.id,
        )
        db_session.add(mcp_tool_db)
        db_session.commit()
        db_session.refresh(mcp_tool_db)

        persona = _create_test_persona_with_mcp_tool(db_session, user, [mcp_tool_db])
        llm = get_default_llm()

        tool_dict = construct_tools(
            persona=persona,
            db_session=db_session,
            emitter=get_default_emitter(),
            user=user,
            llm=llm,
            search_tool_config=SearchToolConfig(),
        )

        mcp_tool = tool_dict[mcp_tool_db.id][0]
        assert isinstance(mcp_tool, MCPTool)

        # Should use the first OAuth account's token
        assert mcp_tool._user_oauth_token == first_token
