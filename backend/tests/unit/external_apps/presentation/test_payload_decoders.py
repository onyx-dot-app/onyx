from __future__ import annotations

import base64
from email.message import EmailMessage
from typing import Any

from onyx.db.enums import ExternalAppType
from onyx.db.models import ExternalApp
from onyx.external_apps.presentation.decode import decode_action_payload
from onyx.external_apps.presentation.payload_decoders import GmailRawMimeDecoder
from onyx.external_apps.providers.gmail import GmailAction
from onyx.external_apps.providers.gmail import GmailProvider

# The `messages.send` decoder; draft create/update use the nested `message.raw`.
_SEND_DECODER = GmailRawMimeDecoder(("raw",))


def _b64(message: EmailMessage) -> str:
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def _raw(message: EmailMessage) -> dict[str, Any]:
    """The Gmail send body for ``message`` — base64url of the MIME bytes."""
    return {"raw": _b64(message)}


def _message(
    *,
    to: str = "alice@example.com",
    subject: str = "Hello",
    body: str = "Hi there",
    cc: str | None = None,
    bcc: str | None = None,
) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to
    message["Subject"] = subject
    if cc:
        message["Cc"] = cc
    if bcc:
        message["Bcc"] = bcc
    message.set_content(body)
    return message


def test_decodes_recipients_subject_and_body() -> None:
    payload = _raw(
        _message(
            to="alice@example.com, Bob <bob@example.com>",
            cc="carol@example.com",
            bcc="dave@example.com",
            subject="Q2 numbers",
            body="Here are the numbers.",
        )
    )

    decoded = _SEND_DECODER.decode(payload)

    assert decoded["to"] == ["alice@example.com", "Bob <bob@example.com>"]
    assert decoded["cc"] == ["carol@example.com"]
    assert decoded["bcc"] == ["dave@example.com"]  # Bcc surfaced, not hidden
    assert decoded["subject"] == "Q2 numbers"
    assert decoded["body"] == "Here are the numbers."
    assert "raw" not in decoded


def test_html_only_body_is_extracted() -> None:
    message = EmailMessage()
    message["To"] = "alice@example.com"
    message["Subject"] = "HTML"
    message.set_content("<p>Hello</p>", subtype="html")

    decoded = _SEND_DECODER.decode(_raw(message))

    assert "Hello" in decoded["body"]


def test_attachment_surfaced_as_metadata_only() -> None:
    message = _message(body="see attached")
    message.add_attachment(
        b"%PDF-1.4 fake",
        maintype="application",
        subtype="pdf",
        filename="report.pdf",
    )

    decoded = _SEND_DECODER.decode(_raw(message))

    assert decoded["attachments"] == [
        {
            "filename": "report.pdf",
            "type": "application/pdf",
            "size": len(b"%PDF-1.4 fake"),
        }
    ]
    # Metadata only — the bytes themselves are never carried.
    assert "%PDF" not in str(decoded)


def test_sibling_keys_preserved() -> None:
    payload = _raw(_message())
    payload["threadId"] = "abc123"

    decoded = _SEND_DECODER.decode(payload)

    assert decoded["threadId"] == "abc123"


def test_missing_raw_returns_payload_unchanged() -> None:
    payload = {"not_raw": "x"}
    assert _SEND_DECODER.decode(payload) == payload


def test_malformed_base64_fails_open_to_raw() -> None:
    payload = {"raw": "!!!! not base64 !!!!"}
    # No exception, original payload returned so the reviewer still sees a body.
    assert _SEND_DECODER.decode(payload) == payload


def test_decodes_nested_draft_message() -> None:
    # Draft create/update nest the MIME under `message`.
    payload = {"message": _raw(_message(to="alice@example.com", subject="Draft"))}

    decoded = GmailRawMimeDecoder(("message", "raw")).decode(payload)

    assert decoded["message"]["to"] == ["alice@example.com"]
    assert decoded["message"]["subject"] == "Draft"
    assert "raw" not in decoded["message"]


def test_nested_decoder_fails_open_when_message_absent() -> None:
    payload = {"id": "draft-123"}  # e.g. a body without the nested message
    assert GmailRawMimeDecoder(("message", "raw")).decode(payload) == payload


def test_provider_factory_resolves_encoded_body_actions() -> None:
    provider = GmailProvider()
    assert isinstance(
        provider.payload_decoder(GmailAction.MESSAGES_SEND), GmailRawMimeDecoder
    )
    assert isinstance(
        provider.payload_decoder(GmailAction.DRAFTS_CREATE), GmailRawMimeDecoder
    )
    assert isinstance(
        provider.payload_decoder(GmailAction.DRAFTS_UPDATE), GmailRawMimeDecoder
    )
    assert provider.payload_decoder(GmailAction.MESSAGES_READ) is None
    assert provider.payload_decoder("nonexistent.action") is None


def _gmail_app() -> ExternalApp:
    # Transient model is enough — get_provider_for_app reads only app_type.
    return ExternalApp(app_type=ExternalAppType.GMAIL)


def test_orchestrator_decodes_gmail_send() -> None:
    payload = _raw(_message(to="alice@example.com", subject="Hi", body="Body"))

    decoded = decode_action_payload(_gmail_app(), GmailAction.MESSAGES_SEND, payload)

    assert decoded["to"] == ["alice@example.com"]
    assert decoded["subject"] == "Hi"
    assert "raw" not in decoded


def test_orchestrator_decodes_draft_create() -> None:
    payload = {"message": _raw(_message(to="alice@example.com", subject="Draft"))}

    decoded = decode_action_payload(_gmail_app(), GmailAction.DRAFTS_CREATE, payload)

    assert decoded["message"]["to"] == ["alice@example.com"]
    assert "raw" not in decoded["message"]


def test_orchestrator_passthrough_for_undecoded_action() -> None:
    payload = {"addLabelIds": ["INBOX"]}
    result = decode_action_payload(_gmail_app(), GmailAction.MESSAGES_MODIFY, payload)
    assert result == payload


def test_orchestrator_passthrough_for_unregistered_app() -> None:
    payload = {"raw": "anything"}
    result = decode_action_payload(
        ExternalApp(app_type=ExternalAppType.CUSTOM), "custom.action", payload
    )
    assert result == payload
