"""
Test suite for OAuth Config CRUD operations.

Tests the basic CRUD operations for OAuth configurations and user tokens,
including creation, retrieval, updates, deletion, and token management.
"""

from uuid import uuid4

import pytest
from sqlalchemy.orm import Session

from onyx.db.models import OAuthConfig
from onyx.db.models import Tool
from onyx.db.oauth_config import create_oauth_config
from onyx.db.oauth_config import delete_oauth_config
from onyx.db.oauth_config import delete_user_oauth_token
from onyx.db.oauth_config import get_oauth_config
from onyx.db.oauth_config import get_oauth_configs
from onyx.db.oauth_config import get_tools_by_oauth_config
from onyx.db.oauth_config import get_user_oauth_token
from onyx.db.oauth_config import update_oauth_config
from onyx.db.oauth_config import upsert_user_oauth_token
from tests.external_dependency_unit.conftest import create_test_user


def _create_test_oauth_config(
    db_session: Session,
    name: str | None = None,
) -> OAuthConfig:
    """Helper to create a test OAuth config with unique name"""
    unique_name = name or f"Test OAuth Config {uuid4().hex[:8]}"
    return create_oauth_config(
        name=unique_name,
        authorization_url="https://github.com/login/oauth/authorize",
        token_url="https://github.com/login/oauth/access_token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        scopes=["repo", "user"],
        additional_params={"test_param": "test_value"},
        db_session=db_session,
    )


def _create_test_tool_with_oauth(
    db_session: Session, oauth_config: OAuthConfig
) -> Tool:
    """Helper to create a test tool with OAuth config"""
    user = create_test_user(db_session, "tool_owner")
    tool = Tool(
        name="Test Tool",
        description="Test tool with OAuth",
        openapi_schema={"openapi": "3.0.0"},
        user_id=user.id,
        oauth_config_id=oauth_config.id,
    )
    db_session.add(tool)
    db_session.commit()
    db_session.refresh(tool)
    return tool


class TestOAuthConfigCRUD:
    """Tests for OAuth configuration CRUD operations"""

    def test_create_oauth_config(self, db_session: Session) -> None:
        """Test creating a new OAuth configuration"""
        oauth_config = _create_test_oauth_config(db_session)

        assert oauth_config.id is not None
        assert oauth_config.name.startswith("Test OAuth Config")
        assert (
            oauth_config.authorization_url == "https://github.com/login/oauth/authorize"
        )
        assert oauth_config.token_url == "https://github.com/login/oauth/access_token"
        assert oauth_config.scopes == ["repo", "user"]
        assert oauth_config.additional_params == {"test_param": "test_value"}
        assert oauth_config.created_at is not None
        assert oauth_config.updated_at is not None

        # Verify encrypted fields are stored (we can't decrypt in tests, but we can check they exist)
        assert oauth_config.client_id is not None
        assert oauth_config.client_secret is not None

    def test_get_oauth_config(self, db_session: Session) -> None:
        """Test retrieving an OAuth config by ID"""
        created_config = _create_test_oauth_config(db_session)

        retrieved_config = get_oauth_config(created_config.id, db_session)

        assert retrieved_config is not None
        assert retrieved_config.id == created_config.id
        assert retrieved_config.name == created_config.name

    def test_get_oauth_config_not_found(self, db_session: Session) -> None:
        """Test retrieving a non-existent OAuth config returns None"""
        config = get_oauth_config(99999, db_session)
        assert config is None

    def test_get_oauth_configs(self, db_session: Session) -> None:
        """Test retrieving all OAuth configurations"""
        # Create multiple configs with unique names
        config1 = _create_test_oauth_config(db_session)
        config2 = _create_test_oauth_config(db_session)

        configs = get_oauth_configs(db_session)

        assert len(configs) >= 2
        config_ids = [c.id for c in configs]
        assert config1.id in config_ids
        assert config2.id in config_ids

    def test_update_oauth_config(self, db_session: Session) -> None:
        """Test updating an OAuth configuration"""
        oauth_config = _create_test_oauth_config(db_session)
        original_name = oauth_config.name

        # Update the config with unique name
        new_name = f"Updated GitHub OAuth {uuid4().hex[:8]}"
        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            name=new_name,
            scopes=["repo", "user", "admin"],
        )

        assert updated_config.id == oauth_config.id
        assert updated_config.name == new_name
        assert updated_config.name != original_name
        assert updated_config.scopes == ["repo", "user", "admin"]

    def test_update_oauth_config_preserves_secrets(self, db_session: Session) -> None:
        """Test that updating config without providing secrets preserves existing values"""
        oauth_config = _create_test_oauth_config(db_session)
        original_client_id = oauth_config.client_id
        original_client_secret = oauth_config.client_secret

        # Update config without providing client_id or client_secret
        new_name = f"Updated Name {uuid4().hex[:8]}"
        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            name=new_name,
            client_id=None,
            client_secret=None,
        )

        # Secrets should be preserved
        assert updated_config.client_id == original_client_id
        assert updated_config.client_secret == original_client_secret
        # But name should be updated
        assert updated_config.name == new_name

    def test_update_oauth_config_not_found(self, db_session: Session) -> None:
        """Test updating a non-existent OAuth config raises error"""
        with pytest.raises(
            ValueError, match="OAuth config with id 99999 does not exist"
        ):
            update_oauth_config(99999, db_session, name="New Name")

    def test_update_oauth_config_clear_client_id(self, db_session: Session) -> None:
        """Test clearing client_id while preserving client_secret"""
        oauth_config = _create_test_oauth_config(db_session)
        original_client_secret = oauth_config.client_secret

        # Clear client_id
        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            clear_client_id=True,
        )

        # client_id should be cleared (empty string)
        assert updated_config.client_id == ""
        # client_secret should be preserved
        assert updated_config.client_secret == original_client_secret

    def test_update_oauth_config_clear_client_secret(self, db_session: Session) -> None:
        """Test clearing client_secret while preserving client_id"""
        oauth_config = _create_test_oauth_config(db_session)
        original_client_id = oauth_config.client_id

        # Clear client_secret
        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            clear_client_secret=True,
        )

        # client_secret should be cleared (empty string)
        assert updated_config.client_secret == ""
        # client_id should be preserved
        assert updated_config.client_id == original_client_id

    def test_update_oauth_config_clear_both_secrets(self, db_session: Session) -> None:
        """Test clearing both client_id and client_secret"""
        oauth_config = _create_test_oauth_config(db_session)

        # Clear both secrets
        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            clear_client_id=True,
            clear_client_secret=True,
        )

        # Both should be cleared (empty strings)
        assert updated_config.client_id == ""
        assert updated_config.client_secret == ""

    def test_update_oauth_config_authorization_url(self, db_session: Session) -> None:
        """Test updating authorization_url"""
        oauth_config = _create_test_oauth_config(db_session)
        new_auth_url = "https://example.com/oauth/authorize"

        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            authorization_url=new_auth_url,
        )

        assert updated_config.authorization_url == new_auth_url

    def test_update_oauth_config_token_url(self, db_session: Session) -> None:
        """Test updating token_url"""
        oauth_config = _create_test_oauth_config(db_session)
        new_token_url = "https://example.com/oauth/token"

        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            token_url=new_token_url,
        )

        assert updated_config.token_url == new_token_url

    def test_update_oauth_config_additional_params(self, db_session: Session) -> None:
        """Test updating additional_params"""
        oauth_config = _create_test_oauth_config(db_session)
        new_params = {"access_type": "offline", "prompt": "consent"}

        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            additional_params=new_params,
        )

        assert updated_config.additional_params == new_params

    def test_update_oauth_config_multiple_fields(self, db_session: Session) -> None:
        """Test updating multiple fields at once"""
        oauth_config = _create_test_oauth_config(db_session)
        new_name = f"Updated Config {uuid4().hex[:8]}"
        new_auth_url = "https://example.com/oauth/authorize"
        new_token_url = "https://example.com/oauth/token"
        new_scopes = ["read", "write", "admin"]
        new_params = {"access_type": "offline"}
        new_client_id = "new_client_id"

        updated_config = update_oauth_config(
            oauth_config.id,
            db_session,
            name=new_name,
            authorization_url=new_auth_url,
            token_url=new_token_url,
            scopes=new_scopes,
            additional_params=new_params,
            client_id=new_client_id,
        )

        assert updated_config.name == new_name
        assert updated_config.authorization_url == new_auth_url
        assert updated_config.token_url == new_token_url
        assert updated_config.scopes == new_scopes
        assert updated_config.additional_params == new_params
        assert updated_config.client_id == new_client_id

    def test_delete_oauth_config(self, db_session: Session) -> None:
        """Test deleting an OAuth configuration"""
        oauth_config = _create_test_oauth_config(db_session)
        config_id = oauth_config.id

        # Delete the config
        delete_oauth_config(config_id, db_session)

        # Verify it's deleted
        deleted_config = get_oauth_config(config_id, db_session)
        assert deleted_config is None

    def test_delete_oauth_config_not_found(self, db_session: Session) -> None:
        """Test deleting a non-existent OAuth config raises error"""
        with pytest.raises(
            ValueError, match="OAuth config with id 99999 does not exist"
        ):
            delete_oauth_config(99999, db_session)

    def test_delete_oauth_config_sets_tool_reference_to_null(
        self, db_session: Session
    ) -> None:
        """Test that deleting OAuth config sets tool's oauth_config_id to NULL"""
        oauth_config = _create_test_oauth_config(db_session)
        tool = _create_test_tool_with_oauth(db_session, oauth_config)

        assert tool.oauth_config_id == oauth_config.id

        # Delete the OAuth config
        delete_oauth_config(oauth_config.id, db_session)

        # Refresh tool from database
        db_session.refresh(tool)

        # Tool should still exist but oauth_config_id should be NULL
        assert tool.oauth_config_id is None


class TestOAuthUserTokenCRUD:
    """Tests for OAuth user token CRUD operations"""

    def test_upsert_user_oauth_token_create(self, db_session: Session) -> None:
        """Test creating a new user OAuth token"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        token_data = {
            "access_token": "test_access_token",
            "refresh_token": "test_refresh_token",
            "token_type": "Bearer",
            "expires_at": 1234567890,
        }

        user_token = upsert_user_oauth_token(
            oauth_config.id, user.id, token_data, db_session
        )

        assert user_token.id is not None
        assert user_token.oauth_config_id == oauth_config.id
        assert user_token.user_id == user.id
        assert user_token.token_data == token_data
        assert user_token.created_at is not None
        assert user_token.updated_at is not None

    def test_upsert_user_oauth_token_update(self, db_session: Session) -> None:
        """Test updating an existing user OAuth token"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create initial token
        initial_token_data = {
            "access_token": "initial_token",
            "expires_at": 1234567890,
        }
        initial_token = upsert_user_oauth_token(
            oauth_config.id, user.id, initial_token_data, db_session
        )
        initial_token_id = initial_token.id

        # Update with new token data
        updated_token_data = {
            "access_token": "updated_token",
            "expires_at": 9876543210,
        }
        updated_token = upsert_user_oauth_token(
            oauth_config.id, user.id, updated_token_data, db_session
        )

        # Should be the same token record (updated, not inserted)
        assert updated_token.id == initial_token_id
        assert updated_token.token_data == updated_token_data
        assert updated_token.token_data != initial_token_data

    def test_get_user_oauth_token(self, db_session: Session) -> None:
        """Test retrieving a user's OAuth token"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        token_data = {"access_token": "test_token"}
        created_token = upsert_user_oauth_token(
            oauth_config.id, user.id, token_data, db_session
        )

        retrieved_token = get_user_oauth_token(oauth_config.id, user.id, db_session)

        assert retrieved_token is not None
        assert retrieved_token.id == created_token.id
        assert retrieved_token.token_data == token_data

    def test_get_user_oauth_token_not_found(self, db_session: Session) -> None:
        """Test retrieving a non-existent user token returns None"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        token = get_user_oauth_token(oauth_config.id, user.id, db_session)
        assert token is None

    def test_delete_user_oauth_token(self, db_session: Session) -> None:
        """Test deleting a user's OAuth token"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        token_data = {"access_token": "test_token"}
        upsert_user_oauth_token(oauth_config.id, user.id, token_data, db_session)

        # Delete the token
        delete_user_oauth_token(oauth_config.id, user.id, db_session)

        # Verify it's deleted
        deleted_token = get_user_oauth_token(oauth_config.id, user.id, db_session)
        assert deleted_token is None

    def test_delete_user_oauth_token_not_found(self, db_session: Session) -> None:
        """Test deleting a non-existent user token raises error"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        with pytest.raises(
            ValueError,
            match=f"OAuth token for user {user.id} and config {oauth_config.id} does not exist",
        ):
            delete_user_oauth_token(oauth_config.id, user.id, db_session)

    def test_unique_constraint_on_user_config(self, db_session: Session) -> None:
        """Test that unique constraint prevents duplicate tokens per user per config"""
        oauth_config = _create_test_oauth_config(db_session)
        user = create_test_user(db_session, "oauth_user")

        # Create first token
        token_data1 = {"access_token": "token1"}
        upsert_user_oauth_token(oauth_config.id, user.id, token_data1, db_session)

        # Try to manually insert a duplicate (should fail at DB level)
        # But upsert should work fine (updates instead of inserting)
        token_data2 = {"access_token": "token2"}
        updated_token = upsert_user_oauth_token(
            oauth_config.id, user.id, token_data2, db_session
        )

        # Should only be one token
        retrieved_token = get_user_oauth_token(oauth_config.id, user.id, db_session)
        assert retrieved_token is not None
        assert retrieved_token.id == updated_token.id
        assert retrieved_token.token_data == token_data2

    def test_cascade_delete_user_tokens_on_config_deletion(
        self, db_session: Session
    ) -> None:
        """Test that deleting OAuth config cascades to user tokens"""
        oauth_config = _create_test_oauth_config(db_session)
        user1 = create_test_user(db_session, "user1")
        user2 = create_test_user(db_session, "user2")

        # Create tokens for both users
        upsert_user_oauth_token(
            oauth_config.id, user1.id, {"access_token": "token1"}, db_session
        )
        upsert_user_oauth_token(
            oauth_config.id, user2.id, {"access_token": "token2"}, db_session
        )

        # Delete the OAuth config
        delete_oauth_config(oauth_config.id, db_session)

        # User tokens should be deleted
        token1 = get_user_oauth_token(oauth_config.id, user1.id, db_session)
        token2 = get_user_oauth_token(oauth_config.id, user2.id, db_session)
        assert token1 is None
        assert token2 is None


class TestOAuthHelperOperations:
    """Tests for OAuth helper operations"""

    def test_get_tools_by_oauth_config(self, db_session: Session) -> None:
        """Test retrieving tools that use a specific OAuth config"""
        oauth_config = _create_test_oauth_config(db_session)

        # Create multiple tools using this config
        tool1 = _create_test_tool_with_oauth(db_session, oauth_config)
        tool2 = _create_test_tool_with_oauth(db_session, oauth_config)

        # Create another tool without OAuth
        user = create_test_user(db_session, "other_user")
        tool3 = Tool(
            name="Tool without OAuth",
            description="No OAuth config",
            openapi_schema={"openapi": "3.0.0"},
            user_id=user.id,
        )
        db_session.add(tool3)
        db_session.commit()

        # Get tools by OAuth config
        tools = get_tools_by_oauth_config(oauth_config.id, db_session)

        assert len(tools) == 2
        tool_ids = [t.id for t in tools]
        assert tool1.id in tool_ids
        assert tool2.id in tool_ids
        assert tool3.id not in tool_ids

    def test_get_tools_by_oauth_config_empty(self, db_session: Session) -> None:
        """Test retrieving tools for config with no associated tools"""
        oauth_config = _create_test_oauth_config(db_session)

        tools = get_tools_by_oauth_config(oauth_config.id, db_session)

        assert len(tools) == 0
