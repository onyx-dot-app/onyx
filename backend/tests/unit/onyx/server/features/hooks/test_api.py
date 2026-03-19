"""Unit tests for onyx.server.features.hooks.api helpers.

Covers:
- _validate_endpoint: httpx exception → HookValidateStatus mapping
  ConnectTimeout     → cannot_connect  (TCP handshake never completed)
  ConnectError       → cannot_connect  (DNS / TLS failure)
  ReadTimeout et al. → timeout         (TCP connected, server slow)
  Any other exc      → cannot_connect
- _raise_for_validation_failure: HookValidateStatus → OnyxError mapping
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import httpx
import pytest

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.hooks.models import HookValidateResponse
from onyx.hooks.models import HookValidateStatus
from onyx.server.features.hooks.api import _raise_for_validation_failure
from onyx.server.features.hooks.api import _validate_endpoint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_URL = "https://example.com/hook"
_API_KEY = "secret"
_TIMEOUT = 5.0


def _mock_response(status_code: int) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    return response


# ---------------------------------------------------------------------------
# _validate_endpoint
# ---------------------------------------------------------------------------


class TestValidateEndpoint:
    def _call(self, *, api_key: str | None = _API_KEY) -> HookValidateResponse:
        return _validate_endpoint(
            endpoint_url=_URL,
            api_key=api_key,
            timeout_seconds=_TIMEOUT,
        )

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_2xx_returns_passed(self, mock_client_cls: MagicMock) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = (
            _mock_response(200)
        )
        assert self._call().status == HookValidateStatus.passed

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_5xx_returns_passed(self, mock_client_cls: MagicMock) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = (
            _mock_response(500)
        )
        assert self._call().status == HookValidateStatus.passed

    @patch("onyx.server.features.hooks.api.httpx.Client")
    @pytest.mark.parametrize("status_code", [401, 403])
    def test_401_403_returns_auth_failed(
        self, mock_client_cls: MagicMock, status_code: int
    ) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = (
            _mock_response(status_code)
        )
        result = self._call()
        assert result.status == HookValidateStatus.auth_failed
        assert str(status_code) in (result.error_message or "")

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_4xx_non_auth_returns_passed(self, mock_client_cls: MagicMock) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.return_value = (
            _mock_response(422)
        )
        assert self._call().status == HookValidateStatus.passed

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_connect_timeout_returns_cannot_connect(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = (
            httpx.ConnectTimeout("timed out")
        )
        assert self._call().status == HookValidateStatus.cannot_connect

    @patch("onyx.server.features.hooks.api.httpx.Client")
    @pytest.mark.parametrize(
        "exc",
        [
            httpx.ReadTimeout("read timeout"),
            httpx.WriteTimeout("write timeout"),
            httpx.PoolTimeout("pool timeout"),
        ],
    )
    def test_read_write_pool_timeout_returns_timeout(
        self, mock_client_cls: MagicMock, exc: httpx.TimeoutException
    ) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = exc
        assert self._call().status == HookValidateStatus.timeout

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_connect_error_returns_cannot_connect(
        self, mock_client_cls: MagicMock
    ) -> None:
        # Covers DNS failures, TLS errors, and other connection-level errors.
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = (
            httpx.ConnectError("name resolution failed")
        )
        assert self._call().status == HookValidateStatus.cannot_connect

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_arbitrary_exception_returns_cannot_connect(
        self, mock_client_cls: MagicMock
    ) -> None:
        mock_client_cls.return_value.__enter__.return_value.post.side_effect = (
            ConnectionRefusedError("refused")
        )
        assert self._call().status == HookValidateStatus.cannot_connect

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_api_key_sent_as_bearer(self, mock_client_cls: MagicMock) -> None:
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = _mock_response(200)
        self._call(api_key="mykey")
        _, kwargs = mock_post.call_args
        assert kwargs["headers"]["Authorization"] == "Bearer mykey"

    @patch("onyx.server.features.hooks.api.httpx.Client")
    def test_no_api_key_omits_auth_header(self, mock_client_cls: MagicMock) -> None:
        mock_post = mock_client_cls.return_value.__enter__.return_value.post
        mock_post.return_value = _mock_response(200)
        self._call(api_key=None)
        _, kwargs = mock_post.call_args
        assert "Authorization" not in kwargs["headers"]


# ---------------------------------------------------------------------------
# _raise_for_validation_failure
# ---------------------------------------------------------------------------


class TestRaiseForValidationFailure:
    @pytest.mark.parametrize(
        "status, expected_code",
        [
            (HookValidateStatus.auth_failed, OnyxErrorCode.CREDENTIAL_INVALID),
            (HookValidateStatus.timeout, OnyxErrorCode.GATEWAY_TIMEOUT),
            (HookValidateStatus.cannot_connect, OnyxErrorCode.BAD_GATEWAY),
        ],
    )
    def test_raises_correct_error_code(
        self, status: HookValidateStatus, expected_code: OnyxErrorCode
    ) -> None:
        validation = HookValidateResponse(status=status, error_message="some error")
        with pytest.raises(OnyxError) as exc_info:
            _raise_for_validation_failure(validation)
        assert exc_info.value.error_code == expected_code

    def test_auth_failed_passes_error_message_directly(self) -> None:
        validation = HookValidateResponse(
            status=HookValidateStatus.auth_failed, error_message="bad credentials"
        )
        with pytest.raises(OnyxError) as exc_info:
            _raise_for_validation_failure(validation)
        assert exc_info.value.detail == "bad credentials"

    @pytest.mark.parametrize(
        "status", [HookValidateStatus.timeout, HookValidateStatus.cannot_connect]
    )
    def test_timeout_and_cannot_connect_wrap_error_message(
        self, status: HookValidateStatus
    ) -> None:
        validation = HookValidateResponse(status=status, error_message="raw error")
        with pytest.raises(OnyxError) as exc_info:
            _raise_for_validation_failure(validation)
        assert exc_info.value.detail == "Endpoint validation failed: raw error"


# ---------------------------------------------------------------------------
# HookValidateStatus enum string values (API contract)
# ---------------------------------------------------------------------------


class TestHookValidateStatusValues:
    @pytest.mark.parametrize(
        "status, expected",
        [
            (HookValidateStatus.passed, "passed"),
            (HookValidateStatus.auth_failed, "auth_failed"),
            (HookValidateStatus.timeout, "timeout"),
            (HookValidateStatus.cannot_connect, "cannot_connect"),
        ],
    )
    def test_string_values(self, status: HookValidateStatus, expected: str) -> None:
        assert status == expected
