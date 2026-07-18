from unittest.mock import MagicMock

import pytest

import onyx.auth.users as users
from onyx.auth.users import verify_auth_setting
from onyx.auth.users import verify_user_auth_secret


@pytest.mark.parametrize("stale_value", ["", "basic", "cloud"])
def test_verify_auth_setting_silent_for_inert_values(
    monkeypatch: pytest.MonkeyPatch,
    stale_value: str,
) -> None:
    """Inert values (unset, basic, cloud) log only the mode notice, no warning."""
    if stale_value:
        monkeypatch.setenv("AUTH_TYPE", stale_value)
    else:
        monkeypatch.delenv("AUTH_TYPE", raising=False)

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "MULTI_TENANT", False)

    verify_auth_setting()

    mock_logger.warning.assert_not_called()
    mock_logger.notice.assert_called_once_with("Using Auth Type: %s", "basic")


def test_verify_auth_setting_reports_cloud_when_multi_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AUTH_TYPE", raising=False)

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "MULTI_TENANT", True)

    verify_auth_setting()

    mock_logger.warning.assert_not_called()
    mock_logger.notice.assert_called_once_with("Using Auth Type: %s", "cloud")


def test_verify_auth_setting_warns_for_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled auth type logs a deprecation warning."""
    monkeypatch.setenv("AUTH_TYPE", "disabled")

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "MULTI_TENANT", False)

    verify_auth_setting()

    mock_logger.warning.assert_called_once()
    assert "no longer supported" in mock_logger.warning.call_args[0][0]


@pytest.mark.parametrize("legacy_value", ["google_oauth", "oidc", "saml"])
def test_verify_auth_setting_warns_for_legacy_sso_modes(
    monkeypatch: pytest.MonkeyPatch,
    legacy_value: str,
) -> None:
    """Legacy single-provider modes warn that the config migrated to a
    provider row and the deployment runs as basic."""
    monkeypatch.setenv("AUTH_TYPE", legacy_value)

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "MULTI_TENANT", False)

    verify_auth_setting()

    mock_logger.warning.assert_called_once()
    assert "SSO provider row" in mock_logger.warning.call_args[0][0]


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
