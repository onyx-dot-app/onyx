from unittest.mock import MagicMock

import pytest

import onyx.auth.users as users
from onyx.auth.users import verify_auth_setting
from onyx.configs.constants import AuthType


def test_verify_auth_setting_raises_for_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Cloud auth type is not valid for self-hosted deployments."""
    monkeypatch.setenv("AUTH_TYPE", "cloud")

    with pytest.raises(ValueError, match="'cloud' is not a valid auth type"):
        verify_auth_setting()


def test_verify_auth_setting_warns_for_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Disabled auth type logs a deprecation warning."""
    monkeypatch.setenv("AUTH_TYPE", "disabled")

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "AUTH_TYPE", AuthType.BASIC)

    verify_auth_setting()

    mock_logger.warning.assert_called_once()
    assert "no longer supported" in mock_logger.warning.call_args[0][0]


@pytest.mark.parametrize(
    "auth_type",
    [AuthType.BASIC, AuthType.GOOGLE_OAUTH, AuthType.OIDC, AuthType.SAML],
)
def test_verify_auth_setting_valid_auth_types(
    monkeypatch: pytest.MonkeyPatch,
    auth_type: AuthType,
) -> None:
    """Valid auth types work without errors or warnings."""
    monkeypatch.setenv("AUTH_TYPE", auth_type.value)

    mock_logger = MagicMock()
    monkeypatch.setattr(users, "logger", mock_logger)
    monkeypatch.setattr(users, "AUTH_TYPE", auth_type)

    verify_auth_setting()

    mock_logger.warning.assert_not_called()
    mock_logger.notice.assert_called_once_with("Using Auth Type: %s", auth_type.value)
