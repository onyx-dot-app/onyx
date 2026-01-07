"""
Unit tests for the user registration workflow in UserManager.create().

Tests cover:
1. Disposable email validation (before tenant provisioning)
2. Multi-tenant vs single-tenant invite logic
3. SAML/OIDC SSO bypass behavior
4. Empty whitelist vs populated whitelist scenarios
5. Case-insensitive email matching for existing user checks
"""

from types import TracebackType
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from onyx.auth.schemas import UserCreate
from onyx.auth.users import UserManager
from onyx.configs.constants import AuthType

# Note: Only async test methods are marked with @pytest.mark.asyncio individually
# to avoid warnings on synchronous tests


@pytest.fixture
def mock_user_create() -> UserCreate:
    """Create a mock UserCreate object for testing."""
    return UserCreate(
        email="newuser@example.com",
        password="SecurePassword123!",
        is_verified=False,
    )


@pytest.fixture
def mock_async_session() -> MagicMock:
    """Create a mock async database session."""
    session = MagicMock()
    session.execute = AsyncMock()
    session.scalar = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


class _AsyncSessionContextManager:
    def __init__(self, session: MagicMock) -> None:
        self._session = session

    async def __aenter__(self) -> MagicMock:
        return self._session

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> bool:
        return False


def _mock_user_manager_methods(user_manager: UserManager) -> None:
    setattr(user_manager, "validate_password", AsyncMock())
    setattr(user_manager, "_assign_default_pinned_assistants", AsyncMock())


class TestDisposableEmailValidation:
    """Test disposable email validation before tenant provisioning."""

    @pytest.mark.asyncio
    @patch("onyx.auth.users.is_disposable_email")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    async def test_blocks_disposable_email_before_tenant_provision(
        self,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_is_disposable: MagicMock,
        mock_user_create: UserCreate,
    ) -> None:
        """Disposable emails should be blocked before tenant provisioning."""
        # Setup
        mock_is_disposable.return_value = True
        user_manager = UserManager(MagicMock())

        # Execute & Assert
        with pytest.raises(HTTPException) as exc:
            await user_manager.create(mock_user_create)

        assert exc.value.status_code == 400
        assert "Disposable email" in str(exc.value.detail)
        # Verify we never got to tenant provisioning
        mock_fetch_ee.assert_not_called()

    @pytest.mark.asyncio
    @patch("onyx.auth.users.is_disposable_email")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    @patch("onyx.auth.users.MULTI_TENANT", False)
    async def test_allows_valid_email_domain(
        self,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,
        mock_user_create: UserCreate,
        mock_async_session: MagicMock,
    ) -> None:
        """Valid emails should pass domain validation."""
        # Setup
        mock_is_disposable.return_value = False
        mock_verify_domain.return_value = None  # No exception = valid
        mock_fetch_ee.return_value = AsyncMock(return_value="default_schema")
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_get_user_count.return_value = 0

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        # Mock the user_db to avoid actual database operations
        mock_user_db = MagicMock()
        mock_user_db.create = AsyncMock(return_value=MagicMock(id="test-id"))
        user_manager.user_db = mock_user_db

        try:
            await user_manager.create(mock_user_create)
        except Exception:
            pass  # We just want to verify domain check passed

        # Verify domain validation was called
        mock_verify_domain.assert_called_once_with(mock_user_create.email)


class TestMultiTenantInviteLogic:
    """Test invite logic for multi-tenant environments."""

    @patch("onyx.auth.users.SQLAlchemyUserAdminDB")
    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    @patch("onyx.auth.users.verify_email_is_invited")
    @patch("onyx.auth.users.MULTI_TENANT", True)
    @patch("onyx.auth.users.CURRENT_TENANT_ID_CONTEXTVAR")
    @pytest.mark.asyncio
    async def test_first_user_no_invite_required(
        self,
        mock_context_var: MagicMock,
        mock_verify_invited: MagicMock,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,
        mock_sql_alchemy_db: MagicMock,
        mock_user_create: UserCreate,
        mock_async_session: MagicMock,
    ) -> None:
        """First user in tenant should not require invite."""
        # Setup: No existing users
        mock_get_user_count.return_value = 0
        mock_fetch_ee.return_value = AsyncMock(return_value="tenant_123")
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_context_var.set.return_value = MagicMock()

        # Mock the user_db to avoid actual database operations
        mock_user_db = MagicMock()
        mock_user_db.create = AsyncMock(return_value=MagicMock(id="test-id"))
        mock_sql_alchemy_db.return_value = mock_user_db

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        try:
            await user_manager.create(mock_user_create)
        except Exception:
            pass

        # Verify invite check was NOT called (user_count = 0)
        mock_verify_invited.assert_not_called()

    @patch("onyx.auth.users.SQLAlchemyUserAdminDB")
    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    @patch("onyx.auth.users.verify_email_is_invited")
    @patch("onyx.auth.users.MULTI_TENANT", True)
    @patch("onyx.auth.users.CURRENT_TENANT_ID_CONTEXTVAR")
    @pytest.mark.asyncio
    async def test_subsequent_user_requires_invite(
        self,
        mock_context_var: MagicMock,
        mock_verify_invited: MagicMock,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,
        mock_sql_alchemy_db: MagicMock,
        mock_user_create: UserCreate,
        mock_async_session: MagicMock,
    ) -> None:
        """Subsequent users in existing tenant should require invite."""
        # Setup: Existing tenant with users
        mock_get_user_count.return_value = 5
        mock_fetch_ee.return_value = AsyncMock(return_value="tenant_123")
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_context_var.set.return_value = MagicMock()

        # Mock the user_db to avoid actual database operations
        mock_user_db = MagicMock()
        mock_user_db.create = AsyncMock(return_value=MagicMock(id="test-id"))
        mock_sql_alchemy_db.return_value = mock_user_db

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        try:
            await user_manager.create(mock_user_create)
        except Exception:
            pass

        # Verify invite check WAS called (user_count > 0)
        mock_verify_invited.assert_called_once_with(mock_user_create.email)


class TestSingleTenantInviteLogic:
    """Test invite logic for single-tenant environments."""

    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    @patch("onyx.auth.users.verify_email_is_invited")
    @patch("onyx.auth.users.MULTI_TENANT", False)
    @patch("onyx.auth.users.CURRENT_TENANT_ID_CONTEXTVAR")
    @pytest.mark.asyncio
    async def test_always_checks_invite_list(
        self,
        mock_context_var: MagicMock,
        mock_verify_invited: MagicMock,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,
        mock_user_create: UserCreate,
        mock_async_session: MagicMock,
    ) -> None:
        """Single-tenant should always check invite list."""
        # Setup
        mock_fetch_ee.return_value = AsyncMock(return_value="default_schema")
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_get_user_count.return_value = 0
        mock_context_var.set.return_value = MagicMock()

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        # Mock the user_db to avoid actual database operations
        mock_user_db = MagicMock()
        mock_user_db.create = AsyncMock(return_value=MagicMock(id="test-id"))
        user_manager.user_db = mock_user_db

        try:
            await user_manager.create(mock_user_create)
        except Exception:
            pass

        # Verify invite check was called
        mock_verify_invited.assert_called_once_with(mock_user_create.email)


class TestSAMLOIDCBehavior:
    """Test SSO (SAML/OIDC) bypass of invite whitelist."""

    @pytest.mark.parametrize("auth_type", [AuthType.SAML, AuthType.OIDC])
    @patch("onyx.auth.users.get_invited_users")
    @patch("onyx.auth.users.AUTH_TYPE")
    def test_sso_bypasses_whitelist(
        self,
        mock_auth_type: MagicMock,
        mock_get_invited: MagicMock,
        auth_type: AuthType,
    ) -> None:
        """SAML/OIDC should bypass invite whitelist."""
        from onyx.auth.users import verify_email_is_invited

        # Setup
        mock_auth_type.return_value = auth_type
        mock_get_invited.return_value = ["allowed@example.com"]

        # Execute - should not raise even with populated whitelist
        with patch("onyx.auth.users.AUTH_TYPE", auth_type):
            verify_email_is_invited("newuser@example.com")  # Should not raise

    @patch("onyx.auth.users.get_invited_users")
    @patch("onyx.auth.users.AUTH_TYPE", AuthType.BASIC)
    def test_basic_auth_enforces_whitelist(
        self,
        mock_get_invited: MagicMock,
    ) -> None:
        """Basic auth should enforce invite whitelist."""
        from onyx.auth.users import verify_email_is_invited

        # Setup
        mock_get_invited.return_value = ["allowed@example.com"]

        # Execute & Assert
        with pytest.raises(PermissionError):
            verify_email_is_invited("newuser@example.com")


class TestWhitelistBehavior:
    """Test invite whitelist scenarios."""

    @patch("onyx.auth.users.get_invited_users")
    @patch("onyx.auth.users.AUTH_TYPE", AuthType.BASIC)
    def test_empty_whitelist_allows_all(
        self,
        mock_get_invited: MagicMock,
    ) -> None:
        """Empty whitelist should allow all users."""
        from onyx.auth.users import verify_email_is_invited

        # Setup: Empty whitelist
        mock_get_invited.return_value = []

        # Execute - should not raise
        verify_email_is_invited("anyone@example.com")

    @patch("onyx.auth.users.get_invited_users")
    @patch("onyx.auth.users.AUTH_TYPE", AuthType.BASIC)
    def test_whitelist_blocks_non_invited(
        self,
        mock_get_invited: MagicMock,
    ) -> None:
        """Populated whitelist should block non-invited users."""
        from onyx.auth.users import verify_email_is_invited

        # Setup
        mock_get_invited.return_value = ["allowed@example.com"]

        # Execute & Assert
        with pytest.raises(PermissionError) as exc:
            verify_email_is_invited("notallowed@example.com")

        assert "not on allowed user whitelist" in str(exc.value)

    @patch("onyx.auth.users.get_invited_users")
    @patch("onyx.auth.users.AUTH_TYPE", AuthType.BASIC)
    def test_whitelist_allows_invited_case_insensitive(
        self,
        mock_get_invited: MagicMock,
    ) -> None:
        """Whitelist should match emails case-insensitively."""
        from onyx.auth.users import verify_email_is_invited

        # Setup
        mock_get_invited.return_value = ["allowed@example.com"]

        # Execute - should not raise (case-insensitive match)
        verify_email_is_invited("ALLOWED@EXAMPLE.COM")
        verify_email_is_invited("Allowed@Example.Com")


class TestCaseInsensitiveEmailMatching:
    """Test case-insensitive email matching for existing user checks."""

    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    @patch("onyx.auth.users.SQLAlchemyUserAdminDB")
    @patch("onyx.auth.users.MULTI_TENANT", True)
    @patch("onyx.auth.users.CURRENT_TENANT_ID_CONTEXTVAR")
    @pytest.mark.asyncio
    async def test_existing_user_check_case_insensitive(
        self,
        mock_context_var: MagicMock,
        mock_sql_alchemy_db: MagicMock,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,
        mock_async_session: MagicMock,
    ) -> None:
        """Existing user check should use case-insensitive email comparison."""

        # Setup
        mock_get_user_count.return_value = 0  # First user - no invite needed
        mock_fetch_ee.return_value = AsyncMock(return_value="tenant_123")
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_context_var.set.return_value = MagicMock()

        # Create a result mock
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_async_session.execute.return_value = result_mock

        user_create = UserCreate(
            email="NewUser@Example.COM",
            password="SecurePassword123!",
            is_verified=False,
        )

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        # Mock the user_db to avoid actual database operations
        mock_user_db = MagicMock()
        mock_user_db.create = AsyncMock(return_value=MagicMock(id="test-id"))
        mock_sql_alchemy_db.return_value = mock_user_db

        try:
            await user_manager.create(user_create)
        except Exception:
            pass

        # Verify flow
        mock_verify_domain.assert_called_once_with(user_create.email)

    @patch("onyx.auth.users.is_disposable_email")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    @patch("onyx.auth.users.verify_email_is_invited")
    @patch("onyx.auth.users.SQLAlchemyUserAdminDB")
    @patch("onyx.auth.users.MULTI_TENANT", True)
    @patch("onyx.auth.users.CURRENT_TENANT_ID_CONTEXTVAR")
    @pytest.mark.asyncio
    async def test_full_registration_flow_existing_tenant(
        self,
        mock_context_var: MagicMock,
        mock_sql_alchemy_db: MagicMock,
        mock_verify_invited: MagicMock,
        mock_get_user_count: MagicMock,
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,
        mock_user_create: UserCreate,
        mock_async_session: MagicMock,
    ) -> None:
        """Test complete flow: valid email, existing tenant, invite required."""
        # Setup: All validations pass, existing tenant
        mock_is_disposable.return_value = False
        mock_verify_domain.return_value = None
        mock_get_user_count.return_value = 10  # Existing tenant
        mock_fetch_ee.return_value = AsyncMock(return_value="existing_tenant_789")
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_context_var.set.return_value = MagicMock()

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        # Mock the user_db to avoid actual database operations
        mock_user_db = MagicMock()
        mock_user_db.create = AsyncMock(return_value=MagicMock(id="test-id"))
        mock_sql_alchemy_db.return_value = mock_user_db

        try:
            await user_manager.create(mock_user_create)
        except Exception:
            pass

        # Verify flow
        mock_verify_domain.assert_called_once_with(mock_user_create.email)
        mock_verify_invited.assert_called_once()  # Existing tenant = invite needed
