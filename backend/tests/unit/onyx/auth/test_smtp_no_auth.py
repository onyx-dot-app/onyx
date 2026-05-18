"""Tests for SMTP without authentication (issue #10682).

Verifies that:
- Email is considered configured when only SMTP_SERVER is set
- starttls() is skipped when SMTP_STARTTLS=false
- login() is skipped when SMTP_USER/SMTP_PASS are empty
- Existing behavior is preserved when credentials are provided
"""

from email.mime.text import MIMEText
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest


@pytest.fixture
def mock_smtp():
    with patch("onyx.auth.email_utils.smtplib.SMTP") as mock:
        instance = MagicMock()
        mock.return_value.__enter__ = MagicMock(return_value=instance)
        mock.return_value.__exit__ = MagicMock(return_value=False)
        yield instance


class TestEmailConfigured:
    """Test that EMAIL_CONFIGURED works with server-only config."""

    @patch.dict(
        "os.environ",
        {"SMTP_SERVER": "mail.example.com", "SMTP_USER": "", "SMTP_PASS": ""},
        clear=False,
    )
    def test_email_configured_with_server_only(self) -> None:
        """EMAIL_CONFIGURED should be True when only SMTP_SERVER is set."""
        # Re-import to pick up patched env
        import importlib

        import onyx.configs.app_configs as app_configs

        importlib.reload(app_configs)

        assert app_configs.EMAIL_CONFIGURED is True

    @patch.dict(
        "os.environ",
        {"SMTP_SERVER": "", "SMTP_USER": "", "SMTP_PASS": ""},
        clear=False,
    )
    def test_email_not_configured_without_server(self) -> None:
        """EMAIL_CONFIGURED should be False when SMTP_SERVER is empty."""
        import importlib

        import onyx.configs.app_configs as app_configs

        importlib.reload(app_configs)

        assert app_configs.EMAIL_CONFIGURED is False


class TestSmtpNoAuth:
    """Test SMTP sending without authentication."""

    @patch("onyx.auth.email_utils.SMTP_STARTTLS", True)
    @patch("onyx.auth.email_utils.SMTP_USER", "")
    @patch("onyx.auth.email_utils.SMTP_PASS", "")
    @patch("onyx.auth.email_utils.SMTP_SERVER", "localhost")
    @patch("onyx.auth.email_utils.SMTP_PORT", 1025)
    @patch("onyx.auth.email_utils.EMAIL_FROM", "test@example.com")
    def test_no_login_when_credentials_empty(self, mock_smtp: MagicMock) -> None:
        """login() should not be called when SMTP_USER and SMTP_PASS are empty."""
        from onyx.auth.email_utils import send_email_with_smtplib

        send_email_with_smtplib(
            user_email="recipient@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            text_body="Hello",
        )

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_not_called()
        mock_smtp.send_message.assert_called_once()

    @patch("onyx.auth.email_utils.SMTP_STARTTLS", False)
    @patch("onyx.auth.email_utils.SMTP_USER", "")
    @patch("onyx.auth.email_utils.SMTP_PASS", "")
    @patch("onyx.auth.email_utils.SMTP_SERVER", "localhost")
    @patch("onyx.auth.email_utils.SMTP_PORT", 1025)
    @patch("onyx.auth.email_utils.EMAIL_FROM", "test@example.com")
    def test_no_starttls_when_disabled(self, mock_smtp: MagicMock) -> None:
        """starttls() should not be called when SMTP_STARTTLS is False."""
        from onyx.auth.email_utils import send_email_with_smtplib

        send_email_with_smtplib(
            user_email="recipient@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            text_body="Hello",
        )

        mock_smtp.starttls.assert_not_called()
        mock_smtp.login.assert_not_called()
        mock_smtp.send_message.assert_called_once()

    @patch("onyx.auth.email_utils.SMTP_STARTTLS", True)
    @patch("onyx.auth.email_utils.SMTP_USER", "user@example.com")
    @patch("onyx.auth.email_utils.SMTP_PASS", "secret")
    @patch("onyx.auth.email_utils.SMTP_SERVER", "smtp.example.com")
    @patch("onyx.auth.email_utils.SMTP_PORT", 587)
    @patch("onyx.auth.email_utils.EMAIL_FROM", "noreply@example.com")
    def test_login_called_when_credentials_provided(
        self, mock_smtp: MagicMock
    ) -> None:
        """login() should still be called when credentials are provided."""
        from onyx.auth.email_utils import send_email_with_smtplib

        send_email_with_smtplib(
            user_email="recipient@example.com",
            subject="Test",
            html_body="<p>Hello</p>",
            text_body="Hello",
        )

        mock_smtp.starttls.assert_called_once()
        mock_smtp.login.assert_called_once_with("user@example.com", "secret")
        mock_smtp.send_message.assert_called_once()
