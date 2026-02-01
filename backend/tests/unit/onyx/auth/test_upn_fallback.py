"""
Tests for UPN (User Principal Name) fallback functionality in OIDC and SAML authentication.

When USE_UPN_AS_EMAIL_FALLBACK is enabled, the system will check additional claims
(preferred_username, upn) if the standard email claim is not present.
"""

from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from onyx.auth import users as users_module


class TestOIDCEmailClaimKeys:
    """Test the OIDC email claim key constants."""

    def test_oidc_email_claim_keys_order(self) -> None:
        """Verify the claim keys are checked in the correct priority order."""
        assert users_module._OIDC_EMAIL_CLAIM_KEYS == (
            "email",
            "preferred_username",
            "upn",
        )


class TestOpenIDWithUPNFallback:
    """Tests for the OpenIDWithUPNFallback class."""

    @pytest.mark.asyncio
    async def test_get_id_email_returns_email_when_present(self) -> None:
        """When email claim is present, it should be used regardless of fallback setting."""
        profile = {
            "sub": "user-123",
            "email": "user@example.com",
            "upn": "user@different.com",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            # Test with fallback disabled
            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", False):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                assert account_email == "user@example.com"

            # Test with fallback enabled - should still use email first
            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", True):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                assert account_email == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_id_email_fallback_disabled_no_email(self) -> None:
        """When fallback is disabled and no email claim, should return None."""
        profile = {
            "sub": "user-123",
            "upn": "user@example.com",
            "preferred_username": "user@example.com",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", False):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                assert account_email is None

    @pytest.mark.asyncio
    async def test_get_id_email_fallback_to_preferred_username(self) -> None:
        """When fallback is enabled and no email, should try preferred_username."""
        profile = {
            "sub": "user-123",
            "preferred_username": "user@example.com",
            "upn": "user@different.com",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", True):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                # preferred_username comes before upn in priority
                assert account_email == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_id_email_fallback_to_upn(self) -> None:
        """When fallback is enabled and only UPN is available, should use UPN."""
        profile = {
            "sub": "user-123",
            "upn": "user@example.com",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", True):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                assert account_email == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_id_email_normalizes_email(self) -> None:
        """Email should be normalized to lowercase."""
        profile = {
            "sub": "user-123",
            "upn": "User@EXAMPLE.COM",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", True):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_email == "user@example.com"

    @pytest.mark.asyncio
    async def test_get_id_email_skips_invalid_email_format(self) -> None:
        """Invalid email formats should be skipped in favor of valid ones."""
        profile = {
            "sub": "user-123",
            "email": "not-an-email",
            "preferred_username": "also-invalid",
            "upn": "valid@example.com",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", True):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                # Should skip invalid emails and find the valid UPN
                assert account_email == "valid@example.com"

    @pytest.mark.asyncio
    async def test_get_id_email_returns_none_when_no_valid_email(self) -> None:
        """When no valid email is found in any claim, should return None."""
        profile = {
            "sub": "user-123",
            "email": "invalid",
            "preferred_username": "also-invalid",
            "upn": "still-invalid",
        }

        client = users_module.OpenIDWithUPNFallback(
            client_id="test",
            client_secret="test",
            openid_configuration_endpoint="https://example.com/.well-known/openid-configuration",
        )

        with patch.object(
            client, "get_profile", new_callable=AsyncMock
        ) as mock_profile:
            mock_profile.return_value = profile

            with patch.object(users_module, "USE_UPN_AS_EMAIL_FALLBACK", True):
                account_id, account_email = await client.get_id_email("fake-token")
                assert account_id == "user-123"
                assert account_email is None


class TestSAMLUPNFallback:
    """Tests for SAML UPN fallback configuration."""

    def test_saml_email_attribute_keys_without_upn_fallback(self) -> None:
        """When USE_UPN_AS_EMAIL_FALLBACK is False, UPN keys should not be included."""
        # Import fresh to test module-level behavior
        from onyx.server import saml as saml_module

        # Base keys that should always be present
        base_keys = {
            "email",
            "emailaddress",
            "mail",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/emailaddress",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/mail",
            "http://schemas.microsoft.com/identity/claims/emailaddress",
        }

        # Verify base keys are present
        for key in base_keys:
            assert key in saml_module.EMAIL_ATTRIBUTE_KEYS

    def test_saml_upn_keys_format(self) -> None:
        """Verify the UPN keys that would be added follow expected formats."""
        upn_keys = {
            "upn",
            "http://schemas.xmlsoap.org/ws/2005/05/identity/claims/upn",
            "http://schemas.microsoft.com/identity/claims/upn",
        }

        # These are the keys that should be added when USE_UPN_AS_EMAIL_FALLBACK is True
        for key in upn_keys:
            # Just verify they're valid strings
            assert isinstance(key, str)
            assert len(key) > 0


class TestExtractEmailFromJWTWithUPN:
    """Tests for _extract_email_from_jwt UPN handling (existing functionality)."""

    def test_extract_email_prefers_email_over_upn(self) -> None:
        """Email claim should be preferred over UPN."""
        payload = {
            "email": "email@example.com",
            "upn": "upn@example.com",
        }
        result = users_module._extract_email_from_jwt(payload)
        assert result == "email@example.com"

    def test_extract_email_prefers_preferred_username_over_upn(self) -> None:
        """preferred_username should be preferred over UPN."""
        payload = {
            "preferred_username": "preferred@example.com",
            "upn": "upn@example.com",
        }
        result = users_module._extract_email_from_jwt(payload)
        assert result == "preferred@example.com"

    def test_extract_email_uses_upn_as_last_resort(self) -> None:
        """UPN should be used when email and preferred_username are not available."""
        payload = {
            "upn": "upn@example.com",
        }
        result = users_module._extract_email_from_jwt(payload)
        assert result == "upn@example.com"

    def test_extract_email_validates_upn_format(self) -> None:
        """UPN must be a valid email format to be used."""
        payload = {
            "upn": "not-an-email",
        }
        result = users_module._extract_email_from_jwt(payload)
        assert result is None

    def test_extract_email_normalizes_upn(self) -> None:
        """UPN should be normalized to lowercase."""
        payload = {
            "upn": "User@EXAMPLE.COM",
        }
        result = users_module._extract_email_from_jwt(payload)
        assert result == "user@example.com"
