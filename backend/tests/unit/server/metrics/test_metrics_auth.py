"""Unit tests for the /metrics bearer-token auth dependency.

Auth is required by default; ``DISABLE_METRICS_AUTH`` is the explicit opt-out.
"""

from unittest.mock import MagicMock

import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.server.metrics import metrics_auth
from onyx.server.metrics.metrics_auth import verify_metrics_token


@pytest.fixture(autouse=True)
def _baseline_config(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default to 'auth required, nothing configured' so each test is isolated
    from the ambient environment and overrides only what it exercises."""
    monkeypatch.setattr(metrics_auth, "METRICS_AUTH_TOKEN", "")
    monkeypatch.setattr(metrics_auth, "DISABLE_METRICS_AUTH", False)


def _request_with_auth(auth_header: str | None) -> MagicMock:
    """Build a fake Request whose headers return the given Authorization value."""
    headers: dict[str, str] = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header
    request = MagicMock()
    request.headers.get.side_effect = lambda key, default="": headers.get(key, default)
    return request


def test_locked_when_unconfigured() -> None:
    """No token and not explicitly disabled => fail secure (lock the endpoint)."""
    with pytest.raises(OnyxError) as exc_info:
        verify_metrics_token(_request_with_auth(None))
    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHENTICATED
    # RFC 6750: advertise the bearer scheme on 401.
    assert exc_info.value.headers == {"WWW-Authenticate": "Bearer"}

    # Even a bearer header can't satisfy a locked endpoint with no configured token.
    with pytest.raises(OnyxError):
        verify_metrics_token(_request_with_auth("Bearer anything"))


def test_no_op_when_auth_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """DISABLE_METRICS_AUTH opts out entirely, regardless of token/header."""
    monkeypatch.setattr(metrics_auth, "DISABLE_METRICS_AUTH", True)

    verify_metrics_token(_request_with_auth(None))
    verify_metrics_token(_request_with_auth("Bearer whatever"))


def test_valid_token_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_auth, "METRICS_AUTH_TOKEN", "s3cret")

    verify_metrics_token(_request_with_auth("Bearer s3cret"))


def test_missing_header_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_auth, "METRICS_AUTH_TOKEN", "s3cret")

    with pytest.raises(OnyxError) as exc_info:
        verify_metrics_token(_request_with_auth(None))
    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHENTICATED


def test_non_bearer_header_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_auth, "METRICS_AUTH_TOKEN", "s3cret")

    with pytest.raises(OnyxError) as exc_info:
        verify_metrics_token(_request_with_auth("s3cret"))
    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHENTICATED


def test_wrong_token_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(metrics_auth, "METRICS_AUTH_TOKEN", "s3cret")

    with pytest.raises(OnyxError) as exc_info:
        verify_metrics_token(_request_with_auth("Bearer wrong"))
    assert exc_info.value.error_code == OnyxErrorCode.UNAUTHENTICATED
