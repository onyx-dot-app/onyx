from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from ee.onyx.server.scim.auth import _hash_scim_token
from ee.onyx.server.scim.auth import generate_scim_token
from ee.onyx.server.scim.auth import SCIM_TOKEN_PREFIX
from ee.onyx.server.scim.auth import verify_scim_token


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
        with pytest.raises(HTTPException) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401
        assert "Missing" in str(exc_info.value.detail)

    def test_wrong_prefix_raises_401(self) -> None:
        request = self._make_request("Bearer on_some_api_key")
        dal = self._make_dal()
        with pytest.raises(HTTPException) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401

    def test_token_not_in_db_raises_401(self) -> None:
        raw, _, _ = generate_scim_token()
        request = self._make_request(f"Bearer {raw}")
        dal = self._make_dal(token=None)
        with pytest.raises(HTTPException) as exc_info:
            verify_scim_token(request, dal)
        assert exc_info.value.status_code == 401
        assert "Invalid" in str(exc_info.value.detail)

    def test_inactive_token_raises_401(self) -> None:
        raw, _, _ = generate_scim_token()
        request = self._make_request(f"Bearer {raw}")
        mock_token = MagicMock()
        mock_token.is_active = False
        dal = self._make_dal(token=mock_token)
        with pytest.raises(HTTPException) as exc_info:
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
