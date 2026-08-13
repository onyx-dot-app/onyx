"""
Unit tests for the user registration workflow in UserManager.create().

Tests cover:
1. Disposable email validation (before tenant provisioning)
2. Multi-tenant vs single-tenant invite logic
3. Empty whitelist vs populated whitelist scenarios
4. Case-insensitive email matching for existing user checks
"""

from types import SimpleNamespace, TracebackType
from typing import cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.security import OAuth2PasswordRequestForm
from fastapi_users import exceptions

from onyx.auth.schemas import UserCreate, UserRole
from onyx.auth.users import UserManager
from onyx.db.enums import AccountType
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.utils import BasicAuthenticationError

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
    session.run_sync = AsyncMock(return_value=None)
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
    user_manager.validate_password = AsyncMock()
    user_manager._assign_default_pinned_assistants = AsyncMock()


class TestDisposableEmailValidation:
    """Test disposable email validation before tenant provisioning."""

    @pytest.mark.asyncio
    @patch("onyx.auth.users.is_disposable_email")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.get_user_count", new_callable=AsyncMock)
    async def test_blocks_disposable_email_before_tenant_provision(
        self,
        mock_get_user_count: MagicMock,  # noqa: ARG002
        mock_session_manager: MagicMock,  # noqa: ARG002
        mock_fetch_ee: MagicMock,
        mock_is_disposable: MagicMock,
        mock_user_create: UserCreate,
    ) -> None:
        """Disposable emails should be blocked before tenant provisioning."""
        # Setup
        mock_is_disposable.return_value = True
        user_manager = UserManager(MagicMock())

        # Execute & Assert
        with pytest.raises(OnyxError) as exc:
            await user_manager.create(mock_user_create)

        assert exc.value.status_code == 400
        assert "Disposable email" in exc.value.detail
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
        mock_verify_domain.assert_called_once_with(
            mock_user_create.email,
            valid_email_domains=(),
            is_registration=True,
        )


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
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_is_disposable: MagicMock,  # noqa: ARG002
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
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_is_disposable: MagicMock,  # noqa: ARG002
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
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_is_disposable: MagicMock,  # noqa: ARG002
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


class TestWhitelistBehavior:
    """Test invite whitelist scenarios."""

    @patch("onyx.auth.users.workspace_invite_only_enabled", return_value=False)
    @patch("onyx.auth.users.get_invited_users")
    def test_empty_whitelist_allows_all(
        self,
        mock_get_invited: MagicMock,
        _mock_invite_only: MagicMock,
    ) -> None:
        """Empty whitelist should allow all users."""
        from onyx.auth.users import verify_email_is_invited

        # Setup: Empty whitelist
        mock_get_invited.return_value = []

        # Execute - should not raise
        verify_email_is_invited("anyone@example.com")

    @patch("onyx.auth.users.workspace_invite_only_enabled", return_value=False)
    @patch("onyx.auth.users.get_invited_users")
    def test_invite_only_disabled_allows_non_invited_users(
        self,
        mock_get_invited: MagicMock,
        _mock_invite_only: MagicMock,
    ) -> None:
        from onyx.auth.users import verify_email_is_invited

        mock_get_invited.return_value = ["allowed@example.com"]

        verify_email_is_invited("notallowed@example.com")

    @patch("onyx.auth.users.workspace_invite_only_enabled", return_value=True)
    @patch("onyx.auth.users.get_invited_users")
    def test_whitelist_blocks_non_invited(
        self,
        mock_get_invited: MagicMock,
        _mock_invite_only: MagicMock,
    ) -> None:
        """Populated whitelist should block non-invited users."""
        from onyx.auth.users import verify_email_is_invited

        # Setup
        mock_get_invited.return_value = ["allowed@example.com"]

        # Execute & Assert
        with pytest.raises(OnyxError) as exc:
            verify_email_is_invited("notallowed@example.com")

        assert exc.value.status_code == 403

    @patch("onyx.auth.users.workspace_invite_only_enabled", return_value=True)
    @patch("onyx.auth.users.get_invited_users")
    def test_whitelist_allows_invited_case_insensitive(
        self,
        mock_get_invited: MagicMock,
        _mock_invite_only: MagicMock,
    ) -> None:
        """Whitelist should match emails case-insensitively."""
        from onyx.auth.users import verify_email_is_invited

        # Setup
        mock_get_invited.return_value = ["allowed@example.com"]

        # Execute - should not raise (case-insensitive match)
        verify_email_is_invited("ALLOWED@EXAMPLE.COM")
        verify_email_is_invited("Allowed@Example.Com")


class TestSeatLimitEnforcement:
    """Seat limits block new user creation on self-hosted deployments."""

    def test_adding_user_fails_when_seats_full(self) -> None:
        from onyx.auth.users import enforce_seat_limit

        seat_result = MagicMock(available=False, error_message="Seat limit reached")
        with patch(
            "onyx.auth.users.fetch_ee_implementation_or_noop",
            return_value=lambda *_a, **_kw: seat_result,
        ):
            with pytest.raises(OnyxError) as exc:
                enforce_seat_limit(MagicMock())

            assert exc.value.status_code == 402

    def test_seat_limit_only_enforced_for_self_hosted(self) -> None:
        from onyx.auth.users import enforce_seat_limit

        # In MULTI_TENANT mode the local seat check is bypassed in favor of
        # the cloud auto-bill helper. Patch fetch_ee_implementation_or_noop
        # to the no-op default so the test does not depend on whether the
        # real EE billing module has been imported by an earlier test.
        with (
            patch("onyx.auth.users.MULTI_TENANT", True),
            patch(
                "onyx.auth.users.fetch_ee_implementation_or_noop",
                return_value=lambda **_kw: None,
            ),
        ):
            enforce_seat_limit(MagicMock())  # should not raise

    def test_cloud_locked_variant_forwards_session_to_billing(self) -> None:
        from onyx.auth.users import enforce_seat_limit_locked

        captured: dict = {}

        def fake_cloud_enforce(**kwargs: object) -> None:
            captured.update(kwargs)

        def fake_acquire_lock(*_a: object, **_kw: object) -> None:
            pass

        def fake_fetch(_module: str, name: str, _default: object) -> object:
            if name == "acquire_seat_lock":
                return fake_acquire_lock
            if name == "enforce_cloud_seat_limit":
                return fake_cloud_enforce
            return _default

        db_session = MagicMock()
        with (
            patch("onyx.auth.users.MULTI_TENANT", True),
            patch(
                "onyx.auth.users.get_current_tenant_id",
                return_value="tenant_xyz",
            ),
            patch(
                "onyx.auth.users.fetch_ee_implementation_or_noop",
                side_effect=fake_fetch,
            ),
        ):
            enforce_seat_limit_locked(db_session, seats_needed=2)

        assert captured["db_session"] is db_session
        assert captured["tenant_id"] == "tenant_xyz"
        assert captured["seats_needed"] == 2


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
        mock_is_disposable: MagicMock,  # noqa: ARG002
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
        mock_verify_domain.assert_called_once_with(
            user_create.email,
            valid_email_domains=(),
            is_registration=True,
        )

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
        mock_verify_domain.assert_called_once_with(
            mock_user_create.email,
            valid_email_domains=(),
            is_registration=True,
        )
        mock_verify_invited.assert_called_once()  # Existing tenant = invite needed


class TestOAuthDottedGmail:
    """OAuth account creation must not apply the dotted-Gmail signup block.

    Regression guard for the redirect loop where a dotted-Gmail Google account
    could never be created (verify_email_domain(is_registration=True) rejected
    it on every first login), so the user never became "existing".
    """

    @pytest.mark.asyncio
    @patch("onyx.auth.users.MULTI_TENANT", False)
    @patch("onyx.auth.users.verify_email_in_whitelist")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.remove_user_from_invited_users")
    async def test_oauth_create_does_not_block_dotted_gmail(
        self,
        mock_remove_invited: MagicMock,  # noqa: ARG002
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,
        mock_verify_whitelist: MagicMock,  # noqa: ARG002
        mock_async_session: MagicMock,
    ) -> None:
        dotted_email = "first.last@gmail.com"

        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        provision_tenant = AsyncMock(return_value="test_tenant")
        mock_fetch_ee.side_effect = lambda _module, attribute, _default: (
            provision_tenant if attribute == "get_or_provision_tenant" else MagicMock()
        )
        mock_verify_domain.return_value = None

        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)
        user_manager.on_after_register = AsyncMock()
        user_manager.get_by_oauth_account = AsyncMock(
            side_effect=exceptions.UserNotExists()
        )

        created_user = MagicMock(id="test-id", email=dotted_email)
        created_user.oidc_expiry = None

        mock_user_db = MagicMock()
        mock_user_db.get_by_email = AsyncMock(side_effect=exceptions.UserNotExists())
        mock_user_db.create = AsyncMock(return_value=created_user)
        mock_user_db.add_oauth_account = AsyncMock(return_value=MagicMock())
        mock_user_db.session = MagicMock()
        mock_user_db.session.run_sync = AsyncMock()
        user_manager.user_db = mock_user_db

        await user_manager.oauth_callback(
            oauth_name="google",
            access_token="token",
            account_id="acct-123",
            account_email=dotted_email,
        )

        # The user was actually created (creation branch reached, not blocked).
        mock_user_db.create.assert_awaited_once()
        # No verify_email_domain call on the OAuth path used the signup block.
        assert mock_verify_domain.call_args_list
        for call in mock_verify_domain.call_args_list:
            assert call.kwargs.get("is_registration") is not True


class TestOAuthNoAutoLinkExemptions:
    """With auto-link off, a web-login row refuses a same-email login once it is
    spoken for: a linked IdP (a second provider must not attach), a rename (a moved
    address stops proving whose row it is), or deactivation. A row with none of
    those is claimed. Placeholders skip the checks and are promoted instead."""

    @staticmethod
    def _unclaimed(**attrs: object) -> MagicMock:
        """A row provisioned ahead of its owner: no IdP, original address, active.

        Every attribute the guard reads is set explicitly. A bare MagicMock
        attribute is truthy, which would silently invert the assertions here.
        """
        return MagicMock(
            **{  # ty: ignore[invalid-argument-type]
                "id": "user-id",
                "email": "provisioned@corp.com",
                "oauth_accounts": [],
                "prior_emails": [],
                "is_active": True,
                "account_type": AccountType.STANDARD,
                # Read by the offboarding tail of oauth_callback, not the guard.
                "oidc_expiry": None,
                **attrs,
            }
        )

    @staticmethod
    def _manager_with_existing(existing_user: MagicMock) -> UserManager:
        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)
        user_manager.on_after_register = AsyncMock()
        user_manager.get_by_oauth_account = AsyncMock(
            side_effect=exceptions.UserNotExists()
        )
        mock_user_db = MagicMock()
        mock_user_db.get_by_email = AsyncMock(return_value=existing_user)
        mock_user_db.get = AsyncMock(return_value=existing_user)
        mock_user_db.add_oauth_account = AsyncMock(return_value=existing_user)
        mock_user_db.update = AsyncMock(return_value=existing_user)
        mock_user_db.session = MagicMock()
        user_manager.user_db = mock_user_db
        return user_manager

    @pytest.mark.asyncio
    # A placeholder is deactivated until its owner shows up, so the deactivated
    # case is the one that matters: it must promote, not be turned away.
    @pytest.mark.parametrize("is_active", [True, False], ids=["active", "deactivated"])
    @patch("onyx.auth.users.MULTI_TENANT", False)
    @patch("onyx.auth.users.verify_email_in_whitelist")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.remove_user_from_invited_users")
    @patch("onyx.auth.users.assign_user_to_default_groups__no_commit")
    @patch("onyx.auth.users._upgrade_will_add_seat", return_value=False)
    @patch("onyx.auth.users.get_session_with_current_tenant")
    async def test_placeholder_promoted_without_auto_link(
        self,
        mock_sync_session_factory: MagicMock,
        mock_will_add_seat: MagicMock,  # noqa: ARG002
        mock_assign_groups: MagicMock,
        mock_remove_invited: MagicMock,  # noqa: ARG002
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_verify_whitelist: MagicMock,  # noqa: ARG002
        is_active: bool,
        mock_async_session: MagicMock,
    ) -> None:
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        provision_tenant = AsyncMock(return_value="test_tenant")
        mock_fetch_ee.side_effect = lambda _module, attribute, _default: (
            provision_tenant if attribute == "get_or_provision_tenant" else MagicMock()
        )

        placeholder = self._unclaimed(
            id="placeholder-id",
            email="synced@corp.com",
            account_type=AccountType.EXT_PERM_USER,
            is_active=is_active,
        )
        user_manager = self._manager_with_existing(placeholder)

        sync_user = MagicMock(is_active=is_active)
        mock_sync_db = MagicMock()
        mock_sync_db.query.return_value.filter.return_value.first.return_value = (
            sync_user
        )
        mock_sync_session_factory.return_value.__enter__ = MagicMock(
            return_value=mock_sync_db
        )
        mock_sync_session_factory.return_value.__exit__ = MagicMock(return_value=False)

        result = await user_manager.oauth_callback(
            oauth_name="okta",
            access_token="token",
            account_id="acct-1",
            account_email="synced@corp.com",
            associate_by_email=False,
            is_verified_by_default=True,
        )

        # The oauth account attaches instead of UserAlreadyExists, and the
        # existing non-web-login upgrade block promotes the placeholder.
        cast(AsyncMock, user_manager.user_db.add_oauth_account).assert_awaited_once()
        assert sync_user.role == UserRole.BASIC
        assert sync_user.account_type == AccountType.STANDARD
        assert sync_user.is_verified is True
        # Promotion reactivates, so the web-login deactivation check must not
        # short-circuit a placeholder before it reaches the upgrade.
        assert sync_user.is_active is True
        mock_assign_groups.assert_called_once()
        mock_sync_db.commit.assert_called_once()
        assert result is placeholder

    @pytest.mark.asyncio
    @patch("onyx.auth.users.MULTI_TENANT", False)
    @patch("onyx.auth.users.verify_email_in_whitelist")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.remove_user_from_invited_users")
    async def test_unclaimed_row_is_claimed_by_first_login(
        self,
        mock_remove_invited: MagicMock,  # noqa: ARG002
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_verify_whitelist: MagicMock,  # noqa: ARG002
        mock_async_session: MagicMock,
    ) -> None:
        """The provisioned-ahead-of-its-owner case: SCIM, invite, any out-of-band
        create. Nothing about the row is spoken for, so the login claims it."""
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_fetch_ee.return_value = AsyncMock(return_value="test_tenant")

        provisioned = self._unclaimed()
        user_manager = self._manager_with_existing(provisioned)

        result = await user_manager.oauth_callback(
            oauth_name="okta",
            access_token="token",
            account_id="acct-3",
            account_email="provisioned@corp.com",
            associate_by_email=False,
        )

        cast(AsyncMock, user_manager.user_db.add_oauth_account).assert_awaited_once()
        assert result is provisioned

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "overrides",
        [
            # A second provider must not attach to a row an IdP already owns.
            pytest.param({"oauth_accounts": [MagicMock()]}, id="already-linked"),
            # A rename moved this row onto the address, so the address no longer
            # proves whose row it is.
            pytest.param({"prior_emails": ["old@corp.com"]}, id="renamed"),
        ],
    )
    @patch("onyx.auth.users.MULTI_TENANT", False)
    @patch("onyx.auth.users.verify_email_in_whitelist")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.remove_user_from_invited_users")
    async def test_spoken_for_row_is_rejected(
        self,
        mock_remove_invited: MagicMock,  # noqa: ARG002
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_verify_whitelist: MagicMock,  # noqa: ARG002
        overrides: dict[str, object],
        mock_async_session: MagicMock,
    ) -> None:
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_fetch_ee.return_value = AsyncMock(return_value="test_tenant")

        user_manager = self._manager_with_existing(self._unclaimed(**overrides))

        with pytest.raises(exceptions.UserAlreadyExists):
            await user_manager.oauth_callback(
                oauth_name="entra",
                access_token="token",
                account_id="acct-4",
                account_email="provisioned@corp.com",
                associate_by_email=False,
            )

        cast(AsyncMock, user_manager.user_db.add_oauth_account).assert_not_awaited()

    @pytest.mark.asyncio
    @patch("onyx.auth.users.MULTI_TENANT", False)
    @patch("onyx.auth.users.verify_email_in_whitelist")
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_async_session_context_manager")
    @patch("onyx.auth.users.remove_user_from_invited_users")
    async def test_deactivated_row_is_not_linked(
        self,
        mock_remove_invited: MagicMock,  # noqa: ARG002
        mock_session_manager: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_verify_domain: MagicMock,  # noqa: ARG002
        mock_verify_whitelist: MagicMock,  # noqa: ARG002
        mock_async_session: MagicMock,
    ) -> None:
        """Linking commits, so a deprovisioned row must come back unclaimed. The
        caller's is_active gate is what turns this into a rejected login."""
        mock_session_manager.return_value = _AsyncSessionContextManager(
            mock_async_session
        )
        mock_fetch_ee.return_value = AsyncMock(return_value="test_tenant")

        deactivated = self._unclaimed(is_active=False)
        user_manager = self._manager_with_existing(deactivated)

        result = await user_manager.oauth_callback(
            oauth_name="okta",
            access_token="token",
            account_id="acct-5",
            account_email="provisioned@corp.com",
            associate_by_email=False,
        )

        cast(AsyncMock, user_manager.user_db.add_oauth_account).assert_not_awaited()
        assert result is deactivated
        assert result.is_active is False


class TestPasswordAuthKillSwitch:
    """Password auth off refuses the public register route (``safe=True``) and
    password login, single-tenant only. SAML/JWT provisioning uses the default
    ``safe=False`` and OAuth bypasses create(), so SSO users are still created
    through their provider, and SSO login never reaches authenticate().
    """

    @pytest.mark.asyncio
    @patch("onyx.auth.users.get_security_settings")
    async def test_signup_disabled_blocks_public_registration(
        self,
        mock_get_settings: MagicMock,
        mock_user_create: UserCreate,
    ) -> None:
        mock_get_settings.return_value = SimpleNamespace(
            password_auth_enabled=False, valid_email_domains=()
        )
        user_manager = UserManager(MagicMock())

        with pytest.raises(OnyxError) as exc:
            await user_manager.create(mock_user_create, safe=True)

        assert exc.value.error_code is OnyxErrorCode.REGISTRATION_DISABLED
        assert exc.value.status_code == 403

    @pytest.mark.asyncio
    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.get_security_settings")
    async def test_signup_disabled_allows_sso_provisioning(
        self,
        mock_get_settings: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,  # noqa: ARG002
        mock_user_create: UserCreate,
    ) -> None:
        """SSO-driven create() (safe=False) must NOT be blocked when signup is
        off, otherwise SAML/JWT can never onboard a new user."""
        mock_get_settings.return_value = SimpleNamespace(
            password_auth_enabled=False, valid_email_domains=()
        )
        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        try:
            await user_manager.create(mock_user_create, safe=False)
        except OnyxError as e:
            assert e.error_code is not OnyxErrorCode.REGISTRATION_DISABLED
        except Exception:
            pass

        # The guard let it through into domain validation instead of blocking.
        mock_verify_domain.assert_called_once_with(
            mock_user_create.email,
            valid_email_domains=(),
            is_registration=True,
        )

    @pytest.mark.asyncio
    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.get_security_settings")
    async def test_signup_enabled_passes_the_guard(
        self,
        mock_get_settings: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,  # noqa: ARG002
        mock_user_create: UserCreate,
    ) -> None:
        """With signup on, the public route proceeds past the guard."""
        mock_get_settings.return_value = SimpleNamespace(
            password_auth_enabled=True, valid_email_domains=()
        )
        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        try:
            await user_manager.create(mock_user_create, safe=True)
        except Exception:
            pass

        mock_verify_domain.assert_called_once_with(
            mock_user_create.email,
            valid_email_domains=(),
            is_registration=True,
        )

    @pytest.mark.asyncio
    @patch("onyx.auth.users.MULTI_TENANT", True)
    @patch("onyx.auth.users.is_disposable_email", return_value=False)
    @patch("onyx.auth.users.verify_email_domain")
    @patch("onyx.auth.users.get_security_settings")
    async def test_multi_tenant_never_blocks_signup(
        self,
        mock_get_settings: MagicMock,
        mock_verify_domain: MagicMock,
        mock_is_disposable: MagicMock,  # noqa: ARG002
        mock_user_create: UserCreate,
    ) -> None:
        """Multi-tenant reads ambient settings here, so the gate must not fire
        even when the value says signup is off."""
        mock_get_settings.return_value = SimpleNamespace(
            password_auth_enabled=False, valid_email_domains=()
        )
        user_manager = UserManager(MagicMock())
        _mock_user_manager_methods(user_manager)

        try:
            await user_manager.create(mock_user_create, safe=True)
        except OnyxError as e:
            assert e.error_code is not OnyxErrorCode.REGISTRATION_DISABLED
        except Exception:
            pass

        mock_verify_domain.assert_called_once_with(
            mock_user_create.email,
            valid_email_domains=(),
            is_registration=True,
        )

    @pytest.mark.asyncio
    @patch("onyx.auth.users.emit_audit_event")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_security_settings")
    async def test_login_disabled_raises_before_tenant_lookup(
        self,
        mock_get_settings: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_emit_audit: MagicMock,  # noqa: ARG002
    ) -> None:
        mock_get_settings.return_value = SimpleNamespace(password_auth_enabled=False)
        user_manager = UserManager(MagicMock())
        credentials = OAuth2PasswordRequestForm(
            username="user@example.com", password="pw"
        )

        with pytest.raises(BasicAuthenticationError) as exc:
            await user_manager.authenticate(credentials)

        assert exc.value.status_code == 403
        assert exc.value.detail == "PASSWORD_LOGIN_DISABLED"
        mock_fetch_ee.assert_not_called()

    @pytest.mark.asyncio
    @patch("onyx.auth.users.MULTI_TENANT", True)
    @patch("onyx.auth.users.emit_audit_event")
    @patch("onyx.auth.users.fetch_ee_implementation_or_noop")
    @patch("onyx.auth.users.get_security_settings")
    async def test_multi_tenant_never_blocks_login(
        self,
        mock_get_settings: MagicMock,
        mock_fetch_ee: MagicMock,
        mock_emit_audit: MagicMock,  # noqa: ARG002
    ) -> None:
        """Multi-tenant reads ambient settings here, so the gate must not fire
        and authentication proceeds to the tenant lookup."""
        mock_get_settings.return_value = SimpleNamespace(password_auth_enabled=False)
        user_manager = UserManager(MagicMock())
        credentials = OAuth2PasswordRequestForm(
            username="user@example.com", password="pw"
        )

        try:
            await user_manager.authenticate(credentials)
        except BasicAuthenticationError as e:
            assert e.detail != "PASSWORD_LOGIN_DISABLED"
        except Exception:
            pass

        mock_fetch_ee.assert_called()
        assert mock_fetch_ee.call_args_list[0].args[:2] == (
            "onyx.db.user_tenant_mapping",
            "get_tenant_id_for_email",
        )
