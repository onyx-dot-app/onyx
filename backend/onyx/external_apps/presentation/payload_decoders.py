from __future__ import annotations

import base64
import binascii
from email import message_from_bytes
from email import policy
from email.message import EmailMessage
from email.utils import formataddr
from email.utils import getaddresses
from typing import Any
from typing import Protocol


class PayloadDecoder(Protocol):
    """A single (provider, action) body-decoding strategy."""

    def decode(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Human-readable view of ``payload``. MUST fail open — return ``payload``
        unchanged rather than raise — so an unparseable body still surfaces."""
        ...


class GmailRawMimeDecoder(PayloadDecoder):
    """Decode the base64url RFC-822 message in a Gmail body into reviewable fields.

    ``messages.send`` carries it directly (``{"raw": …}``); draft create/update
    wrap it under ``message`` (``{"message": {"raw": …}}``). ``wrapper_key`` names
    that wrapper, or ``None`` when ``raw`` is top-level.

    The opaque blob is replaced in place with To/Cc/Bcc/Subject/Body and
    attachment metadata (never attachment contents); all other keys are kept.
    Falls back to the raw payload if ``raw`` is missing or won't parse.
    """

    def __init__(self, wrapper_key: str | None = None) -> None:
        self._wrapper_key = wrapper_key

    def decode(self, payload: dict[str, Any]) -> dict[str, Any]:
        container = self._container(payload)
        if container is None or not isinstance(container.get("raw"), str):
            return payload
        message = _parse_mime(container["raw"])
        if message is None:
            return payload

        decoded = {key: value for key, value in container.items() if key != "raw"}
        decoded.update(_summarize_message(message))
        if self._wrapper_key is None:
            return decoded
        return {**payload, self._wrapper_key: decoded}

    def _container(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """The dict that directly holds ``raw`` — ``payload`` itself, or its
        ``wrapper_key`` sub-dict — or ``None`` when that isn't a dict."""
        if self._wrapper_key is None:
            return payload
        nested = payload.get(self._wrapper_key)
        return nested if isinstance(nested, dict) else None


def _parse_mime(raw_b64: str) -> EmailMessage | None:
    """Parse a base64url-encoded RFC-822 message, or ``None`` if it won't decode."""
    try:
        return message_from_bytes(_b64url_decode(raw_b64), policy=policy.default)
    except (binascii.Error, ValueError):
        return None


def _b64url_decode(data: str) -> bytes:
    """base64url-decode, restoring the padding Gmail's encoder strips."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


# Recipient headers surfaced on the card; the lower-cased name is the payload
# key ("To" -> "to").
_RECIPIENT_HEADERS = ("To", "Cc", "Bcc")


def _summarize_message(message: EmailMessage) -> dict[str, Any]:
    """The reviewable fields of a parsed message; absent fields are omitted."""
    summary: dict[str, Any] = {}
    for header in _RECIPIENT_HEADERS:
        if recipients := _addresses(message.get_all(header)):
            summary[header.lower()] = recipients
    if subject := message["Subject"]:
        summary["subject"] = str(subject)
    if body := _plain_body(message):
        summary["body"] = body
    if attachments := _attachments(message):
        summary["attachments"] = attachments
    return summary


def _addresses(values: list[Any] | None) -> list[str]:
    """Flatten one or more address headers to ``Name <addr>`` / ``addr`` strings."""
    if not values:
        return []
    return [
        formataddr((name, addr)) if name else addr
        for name, addr in getaddresses([str(value) for value in values])
        if addr
    ]


def _plain_body(message: EmailMessage) -> str:
    """The message's text body, preferring plaintext over HTML."""
    body_part = message.get_body(preferencelist=("plain", "html"))
    if body_part is None:
        return ""
    try:
        content = body_part.get_content()
    except (LookupError, ValueError):
        return ""
    return content.strip() if isinstance(content, str) else ""


def _attachments(message: EmailMessage) -> list[dict[str, Any]]:
    """Attachment metadata only — filename, type, and byte size; never content."""
    attachments: list[dict[str, Any]] = []
    for part in message.iter_attachments():
        content = part.get_payload(decode=True)
        attachments.append(
            {
                "filename": part.get_filename() or "(unnamed)",
                "type": part.get_content_type(),
                "size": len(content) if isinstance(content, bytes) else 0,
            }
        )
    return attachments
