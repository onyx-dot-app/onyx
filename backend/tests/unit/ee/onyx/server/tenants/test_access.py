"""Tests for data-plane token generation.

PyJWT (>=2.13) raises InvalidKeyError for an empty HMAC key, whereas earlier
versions silently signed with it. Callers only anticipate the ValueError that
signals a misconfigured secret, so an empty DATA_PLANE_SECRET must be treated
the same as unset.
"""

import jwt
import pytest

from ee.onyx.server.tenants import access


@pytest.mark.parametrize("secret", [None, ""])
def test_generate_data_plane_token_rejects_missing_secret(
    monkeypatch: pytest.MonkeyPatch, secret: str | None
) -> None:
    monkeypatch.setattr(access, "DATA_PLANE_SECRET", secret)
    with pytest.raises(ValueError, match="DATA_PLANE_SECRET is not set"):
        access.generate_data_plane_token()


def test_generate_data_plane_token_signs_with_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "x" * 32  # >= 32 bytes to satisfy PyJWT's HMAC length check
    monkeypatch.setattr(access, "DATA_PLANE_SECRET", secret)
    token = access.generate_data_plane_token()
    payload = jwt.decode(token, secret, algorithms=[access.JWT_ALGORITHM])
    assert payload["scope"] == "api_access"
