"""Unit tests for the Turnstile verification + signed-cookie helpers."""

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.auth import turnstile as turnstile_module

# ---------- turnstile_enforcement_enabled ----------


def test_enforcement_disabled_when_secret_key_empty() -> None:
    with patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", ""):
        assert turnstile_module.turnstile_enforcement_enabled() is False


def test_enforcement_enabled_when_secret_key_set() -> None:
    with patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", "some-nonempty-secret"):
        assert turnstile_module.turnstile_enforcement_enabled() is True


# ---------- verify_turnstile_token ----------


@pytest.mark.asyncio
async def test_verify_turnstile_token_noop_when_secret_unset() -> None:
    """With no secret configured the helper short-circuits to success."""
    with patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", ""):
        ok, err = await turnstile_module.verify_turnstile_token("any-token")
        assert ok is True
        assert err is None


@pytest.mark.asyncio
async def test_verify_turnstile_token_success() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"success": True})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", "real-secret"),
        patch.object(turnstile_module.httpx, "AsyncClient", return_value=mock_client),
    ):
        ok, err = await turnstile_module.verify_turnstile_token("good-token", "1.2.3.4")

    assert ok is True
    assert err is None
    mock_client.post.assert_called_once()
    call_kwargs = mock_client.post.call_args
    assert call_kwargs.kwargs["data"]["secret"] == "real-secret"
    assert call_kwargs.kwargs["data"]["response"] == "good-token"
    assert call_kwargs.kwargs["data"]["remoteip"] == "1.2.3.4"


@pytest.mark.asyncio
async def test_verify_turnstile_token_failure_returns_error_codes() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(
        return_value={
            "success": False,
            "error-codes": ["invalid-input-response", "bad-request"],
        }
    )

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", "real-secret"),
        patch.object(turnstile_module.httpx, "AsyncClient", return_value=mock_client),
    ):
        ok, err = await turnstile_module.verify_turnstile_token("bad-token")

    assert ok is False
    assert err is not None
    assert "invalid-input-response" in err
    assert "bad-request" in err


@pytest.mark.asyncio
async def test_verify_turnstile_token_failure_with_no_error_codes() -> None:
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value={"success": False})

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", "real-secret"),
        patch.object(turnstile_module.httpx, "AsyncClient", return_value=mock_client),
    ):
        ok, err = await turnstile_module.verify_turnstile_token("bad-token")

    assert ok is False
    assert err == "verification-failed"


@pytest.mark.asyncio
async def test_verify_turnstile_token_network_error_returns_unreachable() -> None:
    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch.object(turnstile_module, "TURNSTILE_SECRET_KEY", "real-secret"),
        patch.object(turnstile_module.httpx, "AsyncClient", return_value=mock_client),
    ):
        ok, err = await turnstile_module.verify_turnstile_token("token")

    assert ok is False
    assert err == "siteverify-unreachable"


# ---------- cookie issue / validate roundtrip ----------


def test_issued_cookie_validates() -> None:
    """A freshly issued cookie passes validation."""
    cookie = turnstile_module.issue_turnstile_cookie_value()
    assert turnstile_module.validate_turnstile_cookie_value(cookie) is True


def test_validate_rejects_none() -> None:
    assert turnstile_module.validate_turnstile_cookie_value(None) is False


def test_validate_rejects_empty_string() -> None:
    assert turnstile_module.validate_turnstile_cookie_value("") is False


def test_validate_rejects_malformed_no_separator() -> None:
    assert turnstile_module.validate_turnstile_cookie_value("nodot") is False


def test_validate_rejects_non_numeric_expiry() -> None:
    assert (
        turnstile_module.validate_turnstile_cookie_value("notanumber.deadbeef") is False
    )


def test_validate_rejects_tampered_signature() -> None:
    """Swapping the signature while keeping the expiry is rejected."""
    cookie = turnstile_module.issue_turnstile_cookie_value()
    expiry, _sig = cookie.split(".", 1)
    tampered = f"{expiry}.deadbeefdeadbeefdeadbeefdeadbeef"
    assert turnstile_module.validate_turnstile_cookie_value(tampered) is False


def test_validate_rejects_expired_timestamp() -> None:
    """An expiry in the past is rejected even with a valid signature."""
    # Issue a cookie "in the past" by passing a tiny `now` value.
    cookie = turnstile_module.issue_turnstile_cookie_value(now=0)
    assert turnstile_module.validate_turnstile_cookie_value(cookie) is False


def test_validate_rejects_modified_expiry() -> None:
    """Bumping the expiry forward invalidates the signature."""
    cookie = turnstile_module.issue_turnstile_cookie_value()
    _expiry, sig = cookie.split(".", 1)
    bumped = f"99999999999.{sig}"
    assert turnstile_module.validate_turnstile_cookie_value(bumped) is False
