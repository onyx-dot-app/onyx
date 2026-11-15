import secrets
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from ee.onyx.server.scim.auth import generate_scim_token
from onyx.auth.api_key import generate_api_key, get_hashed_api_key_from_request
from onyx.auth.constants import (
    API_KEY_LENGTH,
    API_KEY_PREFIX,
    DEPRECATED_API_KEY_PREFIX,
    MAX_BEARER_TOKEN_LENGTH,
    PAT_PREFIX,
    SCIM_TOKEN_PREFIX,
)
from onyx.auth.pat import generate_pat
from onyx.auth.utils import (
    extract_tenant_from_auth_header,
    get_hashed_bearer_token_from_request,
)

ALL_PREFIXES = [
    API_KEY_PREFIX,
    DEPRECATED_API_KEY_PREFIX,
    PAT_PREFIX,
    SCIM_TOKEN_PREFIX,
]
# Postgres caps schema names at 63 bytes; a space URL-encodes to 3 chars.
WORST_CASE_TENANT = " " * 63


def _request(auth_header: str) -> MagicMock:
    request = MagicMock()
    request.headers = {"Authorization": auth_header}
    return request


_TOKEN_BUILDERS: dict[str, Callable[[], str]] = {
    "api_key": lambda: generate_api_key(),
    "api_key_tenant": lambda: generate_api_key(WORST_CASE_TENANT),
    "dn_key": lambda: DEPRECATED_API_KEY_PREFIX + secrets.token_urlsafe(API_KEY_LENGTH),
    "dn_key_tenant": lambda: (
        f"{DEPRECATED_API_KEY_PREFIX}tenant_abc.{secrets.token_urlsafe(API_KEY_LENGTH)}"
    ),
    "pat": lambda: generate_pat(),
    "pat_tenant": lambda: generate_pat(WORST_CASE_TENANT),
    "scim": lambda: generate_scim_token()[0],
    "scim_tenant": lambda: generate_scim_token(WORST_CASE_TENANT)[0],
}


@pytest.mark.parametrize("kind", list(_TOKEN_BUILDERS))
def test_real_tokens_are_hashed(kind: str) -> None:
    with (
        patch("onyx.auth.api_key.MULTI_TENANT", True),
        patch("onyx.auth.pat.MULTI_TENANT", True),
        patch("ee.onyx.server.scim.auth.MULTI_TENANT", True),
    ):
        token = _TOKEN_BUILDERS[kind]()
    assert len(token) <= MAX_BEARER_TOKEN_LENGTH
    hash_fn = MagicMock(return_value="hashed")

    result = get_hashed_bearer_token_from_request(
        _request(f"Bearer {token}"), ALL_PREFIXES, hash_fn
    )

    assert result == "hashed"
    hash_fn.assert_called_once_with(token)


@pytest.mark.parametrize("bearer", [True, False])
def test_over_length_dn_token_is_not_hashed(bearer: bool) -> None:
    token = DEPRECATED_API_KEY_PREFIX + "a" * 4000
    header = f"Bearer {token}" if bearer else token
    hash_fn = MagicMock(return_value="hashed")

    result = get_hashed_bearer_token_from_request(
        _request(header), ALL_PREFIXES, hash_fn, allow_non_bearer=True
    )

    assert result is None
    hash_fn.assert_not_called()


def test_over_length_dn_token_skips_sha256_crypt() -> None:
    token = DEPRECATED_API_KEY_PREFIX + "a" * 4000
    with patch("onyx.auth.api_key._deprecated_hash_api_key") as deprecated_hash:
        assert get_hashed_api_key_from_request(_request(f"Bearer {token}")) is None
    deprecated_hash.assert_not_called()


def test_token_at_cap_is_hashed() -> None:
    token = API_KEY_PREFIX + "a" * (MAX_BEARER_TOKEN_LENGTH - len(API_KEY_PREFIX))
    hash_fn = MagicMock(return_value="hashed")

    result = get_hashed_bearer_token_from_request(
        _request(f"Bearer {token}"), ALL_PREFIXES, hash_fn
    )

    assert result == "hashed"


def test_tenant_extraction_rejects_over_length_token() -> None:
    token = f"{DEPRECATED_API_KEY_PREFIX}tenant_abc.{'a' * 4000}"
    assert extract_tenant_from_auth_header(_request(f"Bearer {token}")) is None


def test_tenant_extraction_handles_worst_case_tenant() -> None:
    with patch("onyx.auth.pat.MULTI_TENANT", True):
        token = generate_pat(WORST_CASE_TENANT)
    assert extract_tenant_from_auth_header(_request(f"Bearer {token}")) == (
        WORST_CASE_TENANT
    )
