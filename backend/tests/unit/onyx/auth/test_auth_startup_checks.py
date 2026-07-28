"""Startup-time auth checks: the mode notice and the USER_AUTH_SECRET gate."""

from unittest.mock import MagicMock

import pytest

import onyx.auth.users as users
from onyx.auth.users import log_auth_mode, verify_user_auth_secret


@pytest.mark.parametrize(
    ("multi_tenant", "expected_mode"), [(False, "basic"), (True, "cloud")]
)
def test_log_auth_mode_reports_deployment_mode(
    monkeypatch: pytest.MonkeyPatch,
    multi_tenant: bool,
    expected_mode: str,
) -> None:
    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "MULTI_TENANT", multi_tenant)

    log_auth_mode()

    mock_logger.notice.assert_called_once_with("Using Auth Type: %s", expected_mode)


@pytest.mark.parametrize("auth_type", ["disabled", "google_oauth", "oidc", "saml"])
def test_log_auth_mode_never_warns_about_retired_auth_type(
    monkeypatch: pytest.MonkeyPatch,
    auth_type: str,
) -> None:
    monkeypatch.setenv("AUTH_TYPE", auth_type)

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "MULTI_TENANT", False)

    log_auth_mode()

    mock_logger.warning.assert_not_called()


def test_verify_user_auth_secret_rejects_empty_secret_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty USER_AUTH_SECRET must abort startup outside dev/test modes."""
    monkeypatch.setattr(users, "USER_AUTH_SECRET", "")
    monkeypatch.setattr(users, "DEV_MODE", False)
    monkeypatch.setattr(users, "INTEGRATION_TESTS_MODE", False)

    with pytest.raises(ValueError, match="USER_AUTH_SECRET"):
        verify_user_auth_secret()


@pytest.mark.parametrize("flag", ["DEV_MODE", "INTEGRATION_TESTS_MODE"])
def test_verify_user_auth_secret_warns_in_dev_modes(
    monkeypatch: pytest.MonkeyPatch,
    flag: str,
) -> None:
    """DEV_MODE / INTEGRATION_TESTS_MODE downgrade the empty-secret failure to a warning."""
    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "USER_AUTH_SECRET", "")
    monkeypatch.setattr(users, "DEV_MODE", flag == "DEV_MODE")
    monkeypatch.setattr(
        users, "INTEGRATION_TESTS_MODE", flag == "INTEGRATION_TESTS_MODE"
    )

    verify_user_auth_secret()

    mock_logger.warning.assert_called_once()


def test_verify_user_auth_secret_accepts_configured_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured secret passes even when no dev/test mode is set."""
    monkeypatch.setattr(users, "USER_AUTH_SECRET", "a-real-secret")
    monkeypatch.setattr(users, "DEV_MODE", False)
    monkeypatch.setattr(users, "INTEGRATION_TESTS_MODE", False)

    verify_user_auth_secret()
