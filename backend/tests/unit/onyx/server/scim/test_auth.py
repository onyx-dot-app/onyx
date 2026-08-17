from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.scim.auth import (
    SCIM_TOKEN_PREFIX,
    ScimAuthError,
    _hash_scim_token,
    generate_scim_token,
    verify_scim_token,
)
from onyx.auth.utils import extract_tenant_from_auth_header


class TestGenerateScimToken:
    def test_returns_three_strings(self) -> None:
        raw, hashed, display = generate_scim_token()
        assert isinstance(raw, str)
        assert isinstance(hashed, str)
        assert isinstance(display, str)

    def test_raw_token_has_prefix(self) -> None:
        raw, _, _ = generate_scim_token()
        assert raw.startswith(SCIM_TOKEN_PREFIX)

    def test_hash_is_sha256_hex(self) -> None:
        raw, hashed, _ = generate_scim_token()
        assert len(hashed) == 64
        assert hashed == _hash_scim_token(raw)

    def test_display_shows_last_four_chars(self) -> None:
        raw, _, display = generate_scim_token()
        assert display.endswith(raw[-4:])
        assert "****" in display

    def test_tokens_are_unique(self) -> None:
        tokens = {generate_scim_token()[0] for _ in range(10)}
        assert len(tokens) == 10


class TestScimTokenTenantResolution:
    """An IdP sends nothing but the bearer token, so the token itself has to
    carry the tenant. Without it every SCIM call on cloud resolved to the
    default schema and the tier gate rejected it as non-Enterprise.
    """

    TENANT = "tenant_abc123"

    def _request(self, auth_header: str) -> MagicMock:
        request = MagicMock()
        request.headers = {"Authorization": auth_header}
        return request

    @patch("ee.onyx.server.scim.auth.MULTI_TENANT", True)
    def test_multi_tenant_token_embeds_tenant(self) -> None:
        raw, _, _ = generate_scim_token(self.TENANT)
        assert raw.startswith(f"{SCIM_TOKEN_PREFIX}{self.TENANT}.")

    @patch("ee.onyx.server.scim.auth.MULTI_TENANT", True)
    def test_tenant_round_trips_through_auth_header(self) -> None:
        raw, _, _ = generate_scim_token(self.TENANT)
        assert (
            extract_tenant_from_auth_header(self._request(f"Bearer {raw}"))
            == self.TENANT
        )

    @patch("ee.onyx.server.scim.auth.MULTI_TENANT", True)
    def test_hash_covers_the_whole_token(self) -> None:
        raw, hashed, _ = generate_scim_token(self.TENANT)
        assert hashed == _hash_scim_token(raw)

    @patch("ee.onyx.server.scim.auth.MULTI_TENANT", True)
    def test_verify_accepts_tenant_bearing_token(self) -> None:
        raw, _, _ = generate_scim_token(self.TENANT)
        token = MagicMock()
        token.is_active = True
        dal = MagicMock()
        dal.get_token_by_hash.return_value = token
        assert verify_scim_token(self._request(f"Bearer {raw}"), dal) is token

    @patch("ee.onyx.server.scim.auth.MULTI_TENANT", False)
    def test_self_hosted_token_keeps_the_untenanted_format(self) -> None:
        raw, _, _ = generate_scim_token(self.TENANT)
        assert "." not in raw
        assert extract_tenant_from_auth_header(self._request(f"Bearer {raw}")) is None


class TestHashScimToken:
    def test_deterministic(self) -> None:
        assert _hash_scim_token("test") == _hash_scim_token("test")

    def test_different_inputs_different_hashes(self) -> None:
        assert _hash_scim_token("a") != _hash_scim_token("b")


class TestVerifyScimToken:
    def _make_request(self, auth_header: str | None = None) -> MagicMock:
        request = MagicMock()
        headers: dict[str, str] = {}
        if auth_header is not None:
            headers["Authorization"] = auth_header
        request.headers = headers
        return request

    def _make_dal(self, token: MagicMock | None = None) -> MagicMock:
        dal = MagicMock()
        dal.get_token_by_hash.return_value = token
        return dal

    def test_missing_header_raises_401(self) -> None:
        request = self._make_request(None)
        dal = self._make_dal()
        with pytest.raises(ScimAuthError) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401
        assert "Missing" in str(exc_info.value.detail)

    def test_wrong_prefix_raises_401(self) -> None:
        request = self._make_request("Bearer on_some_api_key")
        dal = self._make_dal()
        with pytest.raises(ScimAuthError) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401

    def test_token_not_in_db_raises_401(self) -> None:
        raw, _, _ = generate_scim_token()
        request = self._make_request(f"Bearer {raw}")
        dal = self._make_dal(token=None)
        with pytest.raises(ScimAuthError) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401
        assert "Invalid" in str(exc_info.value.detail)

    def test_inactive_token_raises_401(self) -> None:
        raw, _, _ = generate_scim_token()
        request = self._make_request(f"Bearer {raw}")
        mock_token = MagicMock()
        mock_token.is_active = False
        dal = self._make_dal(token=mock_token)
        with pytest.raises(ScimAuthError) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401
        assert "revoked" in str(exc_info.value.detail)

    def test_valid_token_returns_token(self) -> None:
        raw, _, _ = generate_scim_token()
        request = self._make_request(f"Bearer {raw}")
        mock_token = MagicMock()
        mock_token.is_active = True
        dal = self._make_dal(token=mock_token)
        result = verify_scim_token(request, dal)
        assert result is mock_token
        dal.get_token_by_hash.assert_called_once()
