"""
Test suite for OAuth integration in tool_constructor.

Tests the priority logic for OAuth tokens when constructing custom tools:
1. Priority 1: OAuth config (per-tool OAuth)
2. Priority 2: Passthrough auth (user's login OAuth token)

All external HTTP calls are mocked, but Postgres and Redis are running.
"""

from typing import Any
from unittest.mock import Mock
from unittest.mock import patch
from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.chat.models import AnswerStyleConfig
from onyx.chat.models import CitationConfig
from onyx.chat.models import DocumentPruningConfig
from onyx.chat.models import PromptConfig
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.enums import RecencyBiasSetting
from onyx.context.search.models import RetrievalDetails
from onyx.db.models import OAuthAccount
from onyx.db.models import OAuthConfig
from onyx.db.models import Persona
from onyx.db.models import Tool
from onyx.db.models import User
from onyx.db.oauth_config import create_oauth_config
from onyx.db.oauth_config import upsert_user_oauth_token
from onyx.llm.factory import get_default_llms
from onyx.llm.interfaces import LLM
from onyx.tools.tool_constructor import construct_tools
from onyx.tools.tool_constructor import SearchToolConfig
from onyx.tools.tool_implementations.custom.custom_tool import CustomTool
from tests.external_dependency_unit.answer.conftest import ensure_default_llm_provider
from tests.external_dependency_unit.conftest import create_test_user


# Simple OpenAPI schema for testing
SIMPLE_OPENAPI_SCHEMA: dict[str, Any] = {
    "openapi": "3.0.0",
    "info": {"title": "Test API", "version": "1.0.0"},
    "servers": [{"url": "https://api.example.com"}],
    "paths": {
        "/test": {
            "get": {
                "operationId": "test_operation",
                "summary": "Test operation",
                "description": "A test operation",
                "responses": {"200": {"description": "Success"}},
            }
        }
    },
}


def _create_test_persona(db_session: Session, user: User, tools: list[Tool]) -> Persona:
    """Helper to create a test persona with the given tools"""
    # Create persona with prompts directly on it
    persona = Persona(
        name=f"Test Persona {uuid4().hex[:8]}",
        description="Test persona",
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


def _create_test_oauth_config(
    db_session: Session, name: str | None = None
) -> OAuthConfig:
    """Helper to create a test OAuth config"""
    return create_oauth_config(
        name=name or f"Test OAuth Config {uuid4().hex[:8]}",
        authorization_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        scopes=["repo", "user"],
        additional_params=None,
        db_session=db_session,
    )


def _get_test_llms() -> tuple[LLM, LLM]:
    """Helper to get test LLMs"""
    llm, fast_llm = get_default_llms()
    return llm, fast_llm


def _get_authorization_header(headers: dict[str, str]) -> str | None:
    """
    Helper to extract authorization header from headers dict.
    Checks both 'authorization' and 'Authorization' keys.

    Returns:
        The authorization header value, or None if not present.
    """
    return headers.get("authorization") or headers.get("Authorization")


def _assert_has_authorization_header(headers: dict[str, str]) -> None:
    """Assert that headers contain an authorization header (any case)."""
    assert (
        "authorization" in headers or "Authorization" in headers
    ), "Expected authorization header to be present"


def _assert_no_authorization_header(headers: dict[str, str]) -> None:
    """Assert that headers do NOT contain an authorization header."""
    assert (
        "authorization" not in headers and "Authorization" not in headers
    ), "Expected no authorization header"


class TestOAuthToolIntegrationPriority:
    """Tests for OAuth token priority logic in tool_constructor"""

    @pytest.fixture(autouse=True)
    def setup_llm_provider(self, db_session: Session) -> None:
        """Ensure default LLM provider is set up for each test."""
        ensure_default_llm_provider(db_session)

    def test_oauth_config_priority_over_passthrough(self, db_session: Session) -> None:
        """
        Test that oauth_config_id takes priority over passthrough_auth.
        When both are set, the tool should use the OAuth config token.
        """
        # Create user with login OAuth token
        user = create_test_user(db_session, "oauth_user")
        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="github",
            account_id="github_user_123",
            account_email=user.email,
            access_token="user_login_token_12345",
            refresh_token="",
        )
        db_session.add(oauth_account)
        db_session.commit()
        # Refresh user to load oauth_accounts relationship
        db_session.refresh(user)

        # Create OAuth config with a valid token
        oauth_config = _create_test_oauth_config(db_session)
        token_data = {
            "access_token": "oauth_config_token_67890",
            "token_type": "Bearer",
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Create tool with BOTH oauth_config_id and passthrough_auth set
        tool = Tool(
            name="test_tool",
            description="Test tool",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=oauth_config.id,  # Priority 1
            passthrough_auth=True,  # Priority 2 - should be ignored
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona and chat session
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Construct tools
        prompt_config = PromptConfig(
            system_prompt="Test",
            task_prompt="Test",
            datetime_aware=False,
        )
        search_tool_config = SearchToolConfig(
            answer_style_config=AnswerStyleConfig(
                citation_config=CitationConfig(all_docs_useful=False)
            ),
            document_pruning_config=DocumentPruningConfig(),
            retrieval_options=RetrievalDetails(),
        )

        tool_dict = construct_tools(
            persona=persona,
            prompt_config=prompt_config,
            db_session=db_session,
            user=user,
            llm=llm,
            fast_llm=fast_llm,
            run_search_setting=OptionalSearchSetting.ALWAYS,
            search_tool_config=search_tool_config,
        )

        # Verify tool was constructed
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify the OAuth config token is used (Priority 1), NOT passthrough token
        _assert_has_authorization_header(custom_tool.headers)
        auth_header = _get_authorization_header(custom_tool.headers)
        assert auth_header == "Bearer oauth_config_token_67890"

    def test_passthrough_auth_when_no_oauth_config(self, db_session: Session) -> None:
        """
        Test that passthrough_auth works when oauth_config_id is not set.
        """
        # Create user with login OAuth token
        user = create_test_user(db_session, "oauth_user")
        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="google",
            account_id="google_user_456",
            account_email=user.email,
            access_token="user_passthrough_token_99999",
            refresh_token="",
        )
        db_session.add(oauth_account)
        db_session.commit()
        # Refresh user to load oauth_accounts relationship
        db_session.refresh(user)

        # Create tool with only passthrough_auth set (no oauth_config_id)
        tool = Tool(
            name="test_tool_passthrough",
            description="Test tool with passthrough",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=None,  # No OAuth config
            passthrough_auth=True,  # Should use user's login token
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Construct tools
        prompt_config = PromptConfig(
            system_prompt="Test",
            task_prompt="Test",
            datetime_aware=False,
        )

        tool_dict = construct_tools(
            persona=persona,
            prompt_config=prompt_config,
            db_session=db_session,
            user=user,
            llm=llm,
            fast_llm=fast_llm,
            run_search_setting=OptionalSearchSetting.ALWAYS,
        )

        # Verify tool was constructed
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify the passthrough token is used
        _assert_has_authorization_header(custom_tool.headers)
        auth_header = _get_authorization_header(custom_tool.headers)
        assert auth_header == "Bearer user_passthrough_token_99999"

    def test_oauth_config_without_valid_token_logs_warning(
        self, db_session: Session, caplog: pytest.LogCaptureFixture
    ) -> None:
        """
        Test that when oauth_config_id is set but no valid token exists,
        a warning is logged and the tool has no auth header.
        """
        # Create user (no OAuth account)
        user = create_test_user(db_session, "oauth_user")

        # Create OAuth config but DO NOT create a token for the user
        oauth_config = _create_test_oauth_config(db_session)

        # Create tool with oauth_config_id but user has no token
        tool = Tool(
            name="test_tool_no_token",
            description="Test tool without token",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=oauth_config.id,
            passthrough_auth=False,
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Construct tools
        prompt_config = PromptConfig(
            system_prompt="Test",
            task_prompt="Test",
            datetime_aware=False,
        )

        with caplog.at_level("WARNING"):
            tool_dict = construct_tools(
                persona=persona,
                prompt_config=prompt_config,
                db_session=db_session,
                user=user,
                llm=llm,
                fast_llm=fast_llm,
                run_search_setting=OptionalSearchSetting.ALWAYS,
            )

        # Verify warning was logged
        assert any(
            "No valid OAuth token found for tool" in record.message
            for record in caplog.records
        )
        assert any(str(oauth_config.id) in record.message for record in caplog.records)

        # Verify tool was constructed but has no authorization header
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify NO authorization header is present
        _assert_no_authorization_header(custom_tool.headers)

    def test_no_auth_when_both_disabled(self, db_session: Session) -> None:
        """
        Test that when neither oauth_config_id nor passthrough_auth is set,
        the tool has no authorization header.
        """
        # Create user with OAuth account (but tool won't use it)
        user = create_test_user(db_session, "oauth_user")
        oauth_account = OAuthAccount(
            user_id=user.id,
            oauth_name="github",
            account_id="github_user_789",
            account_email=user.email,
            access_token="unused_token",
            refresh_token="",
        )
        db_session.add(oauth_account)
        db_session.commit()

        # Create tool with neither oauth_config_id nor passthrough_auth
        tool = Tool(
            name="test_tool_no_auth",
            description="Test tool without auth",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=None,
            passthrough_auth=False,
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Construct tools
        prompt_config = PromptConfig(
            system_prompt="Test",
            task_prompt="Test",
            datetime_aware=False,
        )

        tool_dict = construct_tools(
            persona=persona,
            prompt_config=prompt_config,
            db_session=db_session,
            user=user,
            llm=llm,
            fast_llm=fast_llm,
            run_search_setting=OptionalSearchSetting.ALWAYS,
        )

        # Verify tool was constructed
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify NO authorization header
        _assert_no_authorization_header(custom_tool.headers)

    def test_oauth_config_with_expired_token_refreshes(
        self, db_session: Session
    ) -> None:
        """
        Test that expired OAuth config tokens are automatically refreshed.
        """
        import time

        # Create user
        user = create_test_user(db_session, "oauth_user")

        # Create OAuth config with expired token
        oauth_config = _create_test_oauth_config(db_session)
        expired_token_data = {
            "access_token": "expired_token",
            "refresh_token": "refresh_token_12345",
            "expires_at": int(time.time()) - 100,  # Expired 100 seconds ago
        }
        upsert_user_oauth_token(
            oauth_config.id, user.id, expired_token_data, db_session
        )

        # Create tool with oauth_config_id
        tool = Tool(
            name="test_tool_refresh",
            description="Test tool with token refresh",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=oauth_config.id,
            passthrough_auth=False,
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Mock the token refresh response
        mock_response = Mock()
        mock_response.json.return_value = {
            "access_token": "refreshed_token_67890",
            "refresh_token": "refresh_token_12345",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_response.raise_for_status = Mock()

        with patch("onyx.auth.oauth_token_manager.requests.post") as mock_post:
            mock_post.return_value = mock_response

            # Construct tools
            prompt_config = PromptConfig(
                system_prompt="Test",
                task_prompt="Test",
                datetime_aware=False,
            )

            tool_dict = construct_tools(
                persona=persona,
                prompt_config=prompt_config,
                db_session=db_session,
                user=user,
                llm=llm,
                fast_llm=fast_llm,
                run_search_setting=OptionalSearchSetting.ALWAYS,
            )

            # Verify token refresh was called
            mock_post.assert_called_once()
            call_args = mock_post.call_args
            assert call_args[0][0] == oauth_config.token_url
            assert call_args[1]["data"]["grant_type"] == "refresh_token"
            assert call_args[1]["data"]["refresh_token"] == "refresh_token_12345"

        # Verify tool was constructed with refreshed token
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify the refreshed token is used
        _assert_has_authorization_header(custom_tool.headers)
        auth_header = _get_authorization_header(custom_tool.headers)
        assert auth_header == "Bearer refreshed_token_67890"

    def test_custom_headers_combined_with_oauth_token(
        self, db_session: Session
    ) -> None:
        """
        Test that custom headers are properly combined with OAuth token.
        The OAuth Authorization header should be added to existing custom headers.
        """
        # Create user
        user = create_test_user(db_session, "oauth_user")

        # Create OAuth config with token
        oauth_config = _create_test_oauth_config(db_session)
        token_data = {
            "access_token": "oauth_token_abc123",
            "token_type": "Bearer",
        }
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Create tool with oauth_config_id AND custom headers
        tool = Tool(
            name="test_tool_combined",
            description="Test tool with custom headers and OAuth",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=oauth_config.id,
            custom_headers=[
                {"key": "X-Custom-Header", "value": "custom-value"},
                {"key": "X-API-Key", "value": "api-key-123"},
            ],
            passthrough_auth=False,
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Construct tools
        prompt_config = PromptConfig(
            system_prompt="Test",
            task_prompt="Test",
            datetime_aware=False,
        )

        tool_dict = construct_tools(
            persona=persona,
            prompt_config=prompt_config,
            db_session=db_session,
            user=user,
            llm=llm,
            fast_llm=fast_llm,
            run_search_setting=OptionalSearchSetting.ALWAYS,
        )

        # Verify tool was constructed
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify both OAuth token AND custom headers are present
        _assert_has_authorization_header(custom_tool.headers)
        auth_header = _get_authorization_header(custom_tool.headers)
        assert auth_header == "Bearer oauth_token_abc123"

        # Headers are capitalized by the tool
        assert "X-Custom-Header" in custom_tool.headers
        assert custom_tool.headers["X-Custom-Header"] == "custom-value"
        assert "X-API-Key" in custom_tool.headers
        assert custom_tool.headers["X-API-Key"] == "api-key-123"

    def test_passthrough_auth_without_user_oauth_account(
        self, db_session: Session
    ) -> None:
        """
        Test that passthrough_auth handles gracefully when user has no OAuth account.
        """
        # Create user WITHOUT OAuth account
        user = create_test_user(db_session, "no_oauth_user")

        # Create tool with passthrough_auth
        tool = Tool(
            name="test_tool_no_account",
            description="Test tool passthrough without account",
            openapi_schema=SIMPLE_OPENAPI_SCHEMA,
            oauth_config_id=None,
            passthrough_auth=True,
            user_id=user.id,
        )
        db_session.add(tool)
        db_session.commit()
        db_session.refresh(tool)

        # Create persona
        persona = _create_test_persona(db_session, user, [tool])
        llm, fast_llm = _get_test_llms()

        # Construct tools
        prompt_config = PromptConfig(
            system_prompt="Test",
            task_prompt="Test",
            datetime_aware=False,
        )

        tool_dict = construct_tools(
            persona=persona,
            prompt_config=prompt_config,
            db_session=db_session,
            user=user,
            llm=llm,
            fast_llm=fast_llm,
            run_search_setting=OptionalSearchSetting.ALWAYS,
        )

        # Verify tool was constructed
        assert tool.id in tool_dict
        custom_tools = tool_dict[tool.id]
        assert len(custom_tools) == 1
        custom_tool = custom_tools[0]
        assert isinstance(custom_tool, CustomTool)

        # Verify NO authorization header (user has no OAuth account)
        _assert_no_authorization_header(custom_tool.headers)
