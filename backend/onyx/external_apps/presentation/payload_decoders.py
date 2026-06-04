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


class GmailRawMimeDecoder:
    """Decode a base64url RFC-822 message at ``raw_path`` into reviewable fields.

    ``messages.send`` holds it top-level (``{"raw": …}``); draft create/update
    nest it (``{"message": {"raw": …}}``). Surfaces all recipients and attachment
    metadata (never contents), replacing the blob in place. Falls back to the raw
    payload if the field is absent or unparseable.
    """

    def __init__(self, raw_path: tuple[str, ...]) -> None:
        self._raw_path = raw_path

    def decode(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw = _dig(payload, self._raw_path)
        if not isinstance(raw, str):
            return payload
        try:
            message = message_from_bytes(_b64url_decode(raw), policy=policy.default)
        except (binascii.Error, ValueError):
            return payload
        return _replace_raw(payload, self._raw_path, _summarize_message(message))


def _dig(payload: dict[str, Any], path: tuple[str, ...]) -> Any:
    """The value at ``path`` within nested dicts, or ``None`` if absent."""
    current: Any = payload
    for key in path:
        if not isinstance(current, dict):
            return None
        current = current.get(key)
    return current


def _replace_raw(
    payload: dict[str, Any], path: tuple[str, ...], summary: dict[str, Any]
) -> dict[str, Any]:
    """``payload`` with the ``raw`` key at ``path`` swapped for ``summary``; all
    other keys kept."""
    head, *tail = path
    if not tail:
        return {**{k: v for k, v in payload.items() if k != head}, **summary}
    nested = payload.get(head)
    if not isinstance(nested, dict):
        return payload
    return {**payload, head: _replace_raw(nested, tuple(tail), summary)}


def _b64url_decode(data: str) -> bytes:
    """base64url-decode, restoring the padding Gmail's encoder strips."""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _summarize_message(message: EmailMessage) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for field, header in (("to", "To"), ("cc", "Cc"), ("bcc", "Bcc")):
        recipients = _addresses(message.get_all(header))
        if recipients:
            summary[field] = recipients
    subject = message["Subject"]
    if subject:
        summary["subject"] = str(subject)
    body = _plain_body(message)
    if body:
        summary["body"] = body
    attachments = _attachments(message)
    if attachments:
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
