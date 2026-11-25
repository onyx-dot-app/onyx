"""The sign-in link email: both bodies carry the link and its lifetime."""

from unittest.mock import MagicMock, patch

from onyx.auth import email_utils
from onyx.auth.email_utils import build_magic_link_email, send_magic_link_email

LINK = "https://playground.example.com/auth/magic-link?token=abc123"


def test_both_bodies_carry_the_link_the_lifetime_and_the_name() -> None:
    text, html = build_magic_link_email("Acme", LINK, 15)

    for body in (text, html):
        assert LINK in body
        assert "15 minutes" in body
        assert "Acme" in body
        assert "once" in body
    assert f'<a class="cta-button" href="{LINK}">Sign in</a>' in html


def test_send_builds_the_subject_and_lifetime_from_the_settings() -> None:
    logo = MagicMock()
    logo.data = b"png"
    with (
        patch.object(email_utils, "_load_application_name", return_value="Acme"),
        patch.object(email_utils, "MAGIC_LINK_TTL_SECONDS", 600),
        patch.object(email_utils.OnyxRuntime, "get_emailable_logo", return_value=logo),
        patch.object(email_utils, "send_email") as send_email,
    ):
        send_magic_link_email("someone@example.com", LINK)

    send_email.assert_called_once()
    recipient, subject, html, text, _mail_from = send_email.call_args.args
    assert recipient == "someone@example.com"
    assert subject == "Sign in to Acme"
    assert LINK in html and LINK in text
    assert "10 minutes" in text
    assert send_email.call_args.kwargs["inline_png"] == ("logo.png", b"png")
