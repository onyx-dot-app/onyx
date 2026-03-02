from unittest.mock import patch

import pytest

from onyx.auth.users import verify_auth_setting


def test_verify_auth_setting_raises_for_cloud() -> None:
    """Cloud auth type is not valid for self-hosted deployments."""
    with patch.dict("os.environ", {"AUTH_TYPE": "cloud"}):
        with pytest.raises(ValueError, match="'cloud' is not a valid auth type"):
            verify_auth_setting()


def test_verify_auth_setting_warns_for_disabled() -> None:
    """Disabled auth type logs a deprecation warning."""
    with patch.dict("os.environ", {"AUTH_TYPE": "disabled"}):
        with patch("onyx.auth.users.logger") as mock_logger:
            with patch("onyx.auth.users.AUTH_TYPE") as mock_auth_type:
                mock_auth_type.value = "basic"
                verify_auth_setting()
                mock_logger.warning.assert_called_once()
                assert "no longer supported" in mock_logger.warning.call_args[0][0]


def test_verify_auth_setting_basic() -> None:
    """Basic auth type works without errors or warnings."""
    with patch.dict("os.environ", {"AUTH_TYPE": "basic"}):
        with patch("onyx.auth.users.logger") as mock_logger:
            with patch("onyx.auth.users.AUTH_TYPE") as mock_auth_type:
                mock_auth_type.value = "basic"
                verify_auth_setting()
                mock_logger.warning.assert_not_called()
                mock_logger.notice.assert_called_once_with("Using Auth Type: basic")
