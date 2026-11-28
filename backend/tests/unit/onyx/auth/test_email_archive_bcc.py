from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from onyx.auth import email_utils


def test_archive_bcc_added_to_sendgrid_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_utils,
        "EMAIL_ARCHIVE_BCC_ADDRESSES",
        ("archive@example.com", "to@example.com", "ARCHIVE@example.com"),
        raising=True,
    )
    post = MagicMock(return_value=SimpleNamespace(status_code=202))
    sendgrid_client = SimpleNamespace(
        client=SimpleNamespace(mail=SimpleNamespace(send=SimpleNamespace(post=post)))
    )

    with patch.object(
        email_utils.sendgrid, "SendGridAPIClient", return_value=sendgrid_client
    ):
        email_utils.send_email_with_sendgrid(
            user_email="to@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_body="x",
            mail_from="from@example.com",
        )

    post.assert_called_once()
    request_body = post.call_args.kwargs["request_body"]
    assert request_body["personalizations"][0]["bcc"] == [
        {"email": "archive@example.com"}
    ]


def test_an_email_kept_out_of_the_archive_has_no_bcc(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_utils,
        "EMAIL_ARCHIVE_BCC_ADDRESSES",
        ("archive@example.com",),
        raising=True,
    )
    post = MagicMock(return_value=SimpleNamespace(status_code=202))
    sendgrid_client = SimpleNamespace(
        client=SimpleNamespace(mail=SimpleNamespace(send=SimpleNamespace(post=post)))
    )

    with patch.object(
        email_utils.sendgrid, "SendGridAPIClient", return_value=sendgrid_client
    ):
        email_utils.send_email_with_sendgrid(
            user_email="to@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_body="x",
            mail_from="from@example.com",
            archive=False,
        )

    request_body = post.call_args.kwargs["request_body"]
    assert "bcc" not in request_body["personalizations"][0]


def test_smtp_sends_only_to_the_recipient_when_kept_out_of_the_archive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        email_utils,
        "EMAIL_ARCHIVE_BCC_ADDRESSES",
        ("archive@example.com",),
        raising=True,
    )
    smtp = MagicMock()
    with patch.object(email_utils.smtplib, "SMTP") as smtp_cls:
        smtp_cls.return_value.__enter__.return_value = smtp
        email_utils.send_email_with_smtplib(
            user_email="to@example.com",
            subject="s",
            html_body="<p>x</p>",
            text_body="x",
            mail_from="from@example.com",
            archive=False,
        )

    assert smtp.send_message.call_args.kwargs["to_addrs"] == ["to@example.com"]
