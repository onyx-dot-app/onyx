"""Regression coverage for #10682: SMTP without auth / without STARTTLS.

`send_email_with_smtplib` must not call `starttls()` when STARTTLS is disabled
and must not call `login()` when credentials are not configured — internal
IP-whitelisted relays don't support either.
"""

from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from onyx.auth import email_utils


def _smtp_with_mock_session() -> tuple[MagicMock, MagicMock]:
    """Build a context-manager mock for smtplib.SMTP whose __enter__ returns a
    fresh MagicMock session — that session is what receives starttls / login /
    send_message calls inside the `with` block."""
    session = MagicMock(name="smtp_session")
    smtp_cls = MagicMock(name="smtp_cls")
    smtp_cls.return_value.__enter__.return_value = session
    return smtp_cls, session


def _call_send(monkeypatch: pytest.MonkeyPatch, **overrides: object) -> MagicMock:
    """Patch the module-level SMTP config knobs, mock smtplib.SMTP, invoke
    send_email_with_smtplib, and return the session mock so the test can
    assert which methods fired."""
    defaults: dict[str, object] = {
        "SMTP_SERVER": "smtp.example.com",
        "SMTP_PORT": 587,
        "SMTP_USER": "u",
        "SMTP_PASS": "p",
        "SMTP_STARTTLS": True,
        "EMAIL_ARCHIVE_BCC_ADDRESSES": (),
    }
    defaults.update(overrides)
    for name, value in defaults.items():
        monkeypatch.setattr(email_utils, name, value, raising=True)

    smtp_cls, session = _smtp_with_mock_session()
    with patch.object(email_utils.smtplib, "SMTP", smtp_cls):
        email_utils.send_email_with_smtplib(
            user_email="to@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_body="x",
            mail_from="from@example.com",
        )
    return session


def test_default_config_calls_starttls_and_login(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _call_send(monkeypatch)
    session.starttls.assert_called_once()
    session.login.assert_called_once_with("u", "p")
    session.send_message.assert_called_once()


def test_starttls_disabled_skips_starttls(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _call_send(monkeypatch, SMTP_STARTTLS=False)
    session.starttls.assert_not_called()
    session.login.assert_called_once_with("u", "p")
    session.send_message.assert_called_once()


def test_empty_credentials_skip_login(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _call_send(monkeypatch, SMTP_USER="", SMTP_PASS="")
    session.starttls.assert_called_once()
    session.login.assert_not_called()
    session.send_message.assert_called_once()


def test_unauthenticated_relay_skips_both(monkeypatch: pytest.MonkeyPatch) -> None:
    session = _call_send(monkeypatch, SMTP_USER="", SMTP_PASS="", SMTP_STARTTLS=False)
    session.starttls.assert_not_called()
    session.login.assert_not_called()
    session.send_message.assert_called_once()


def test_archive_bcc_added_to_smtp_recipients_without_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session = _call_send(
        monkeypatch,
        EMAIL_ARCHIVE_BCC_ADDRESSES=(
            "archive@example.com",
            "to@example.com",
            "ARCHIVE@example.com",
        ),
    )

    session.send_message.assert_called_once()
    message = session.send_message.call_args.args[0]
    assert message["Cc"] is None
    assert message["Bcc"] is None
    assert session.send_message.call_args.kwargs["to_addrs"] == [
        "to@example.com",
        "archive@example.com",
    ]
