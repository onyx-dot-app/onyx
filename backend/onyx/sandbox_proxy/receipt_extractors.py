"""Per-provider receipt refinement.

Pure functions from a gated request and its response to the details a receipt
card deserves: a human destination, a deep link, a provider-level verdict,
and the operation key that coalesces multi-request flows into one receipt.
Best-effort: a body that cannot be parsed refines nothing, and the
response-side caller additionally guards against extractor bugs.

Deep links are constructed from shape-checked provider ids, not payload URLs,
except Linear, which only returns a canonical URL and is accepted after a
scheme, host, and full-path shape check.
"""

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qs

from onyx.db.enums import ReceiptStatus

# Coalescing keys are session-scoped by the DAL's unique index, so no tenant
# or session qualifier. The action-type prefix keeps provider ids from
# colliding across providers.
SLACK_UPLOAD_KEY_PREFIX = "slack.files.write:"

_LINEAR_URL_SHAPE = re.compile(
    r"^https://linear\.app/[A-Za-z0-9\-_]+/(issue|project)(/[A-Za-z0-9\-_]+)+/?$"
)
_MAX_LINK_LEN = 512

# Provider ids interpolated into links. Anything else refines nothing.
_SAFE_ID_SHAPE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")
# Slack conversation ids (C../G../D..), which are not channel names.
_SLACK_CONVERSATION_ID_SHAPE = re.compile(r"^[CGD][A-Z0-9]{7,}$")

_GDRIVE_LINKS_BY_MIME = {
    "application/vnd.google-apps.document": "https://docs.google.com/document/d/{id}",
    "application/vnd.google-apps.spreadsheet": "https://docs.google.com/spreadsheets/d/{id}",
    "application/vnd.google-apps.presentation": "https://docs.google.com/presentation/d/{id}",
}
_GDRIVE_GENERIC_LINK = "https://drive.google.com/file/d/{id}"


@dataclass(frozen=True)
class RequestFacts:
    """Refinements known before the request executes."""

    destination: str | None = None
    operation_key: str | None = None


@dataclass(frozen=True)
class ResponseFacts:
    """Refinements the origin's response reveals."""

    link: str | None = None
    # Provider-level failure inside a transport-level success, e.g. Slack's
    # 200 with ok=false. None keeps the transport verdict.
    status_override: ReceiptStatus | None = None
    # Learned late: the Slack upload's file id only exists after step one.
    operation_key: str | None = None


def parse_json_object(raw: bytes | str | None) -> dict[str, Any] | None:
    if raw is None:
        return None
    try:
        parsed = json.loads(raw)
    except (ValueError, UnicodeDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _parse_request_body(raw: bytes | None) -> dict[str, Any] | None:
    """Request payloads arrive as JSON or form-encoded (slack_sdk's default);
    a form field holding serialized JSON is decoded in place."""
    parsed = parse_json_object(raw)
    if parsed is not None or raw is None:
        return parsed
    try:
        fields = parse_qs(raw.decode(), strict_parsing=True)
    except (ValueError, UnicodeDecodeError):
        return None
    body: dict[str, Any] = {}
    for key, values in fields.items():
        value = values[0]
        if value[:1] in ("{", "["):
            try:
                body[key] = json.loads(value)
                continue
            except ValueError:
                pass
        body[key] = value
    return body


def _safe_id(value: Any) -> str | None:
    if isinstance(value, str) and _SAFE_ID_SHAPE.match(value):
        return value
    return None


def _slack_destination(channel: str) -> str:
    if channel.startswith("#") or _SLACK_CONVERSATION_ID_SHAPE.match(channel):
        return channel
    return f"#{channel}"


def request_facts(action_type: str, request_body: bytes | None) -> RequestFacts:
    """What the request alone reveals: a destination and, for flows whose
    later steps carry the correlating id, the coalescing key."""
    body = _parse_request_body(request_body)
    if action_type == "slack.messages.write":
        channel = (body or {}).get("channel")
        if isinstance(channel, str) and channel:
            return RequestFacts(destination=_slack_destination(channel))
    if action_type == "slack.files.write":
        # completeUploadExternal names the files being shared. The earlier
        # steps of the flow key in through the response or the token map.
        files = (body or {}).get("files")
        if isinstance(files, list) and files:
            first = files[0]
            file_id = first.get("id") if isinstance(first, dict) else None
            if _safe_id(file_id) is not None:
                return RequestFacts(operation_key=f"{SLACK_UPLOAD_KEY_PREFIX}{file_id}")
    return RequestFacts()


def response_facts(action_type: str, response_body: bytes | None) -> ResponseFacts:
    """What the origin's response reveals, keyed by the recorded action."""
    body = parse_json_object(response_body)
    if body is None:
        return ResponseFacts()
    if action_type.startswith("slack."):
        return _slack_facts(action_type, body)
    if action_type.startswith("gdrive."):
        return _gdrive_facts(body)
    if action_type.startswith("gmail."):
        return _gmail_facts(action_type, body)
    if action_type.startswith("linear."):
        return _linear_facts(body)
    return ResponseFacts()


def slack_upload_key(body: dict[str, Any]) -> str | None:
    """The coalescing key step one of the upload flow reveals."""
    file_id = _safe_id(body.get("file_id"))
    if file_id is not None:
        return f"{SLACK_UPLOAD_KEY_PREFIX}{file_id}"
    return None


def upload_url_token(url_or_path: str) -> str | None:
    """The trailing path segment of a pre-signed upload URL, shared by the
    writer (step one's upload_url) and the reader (step two's request path)
    so the two derivations can never disagree."""
    path = url_or_path.split("?", 1)[0].rstrip("/")
    if "/" not in path:
        return None
    return path.rsplit("/", 1)[-1] or None


def slack_upload_url_token(body: dict[str, Any]) -> str | None:
    """The upload URL token correlating step two of the upload flow back to
    the file id step one returned."""
    upload_url = body.get("upload_url")
    if isinstance(upload_url, str):
        return upload_url_token(upload_url)
    return None


def _slack_facts(action_type: str, body: dict[str, Any]) -> ResponseFacts:
    # The Slack Web API reports failures as 200 with ok=false.
    if body.get("ok") is False:
        return ResponseFacts(status_override=ReceiptStatus.FAILED)
    link = None
    operation_key = None
    if action_type == "slack.messages.write":
        channel, ts = _safe_id(body.get("channel")), _safe_id(body.get("ts"))
        if channel is not None and ts is not None:
            link = f"https://slack.com/archives/{channel}/p{ts.replace('.', '')}"
    if action_type == "slack.files.write":
        operation_key = slack_upload_key(body)
    return ResponseFacts(link=link, operation_key=operation_key)


# The dedicated editor APIs name their id after the product and return no
# mimeType, so the key alone picks the link.
_GDRIVE_LINKS_BY_ID_KEY = {
    "documentId": "https://docs.google.com/document/d/{id}",
    "spreadsheetId": "https://docs.google.com/spreadsheets/d/{id}",
    "presentationId": "https://docs.google.com/presentation/d/{id}",
}


def _gdrive_facts(body: dict[str, Any]) -> ResponseFacts:
    for key, template in _GDRIVE_LINKS_BY_ID_KEY.items():
        editor_id = _safe_id(body.get(key))
        if editor_id is not None:
            return ResponseFacts(link=template.format(id=editor_id))
    file_id = _safe_id(body.get("id"))
    if file_id is None:
        return ResponseFacts()
    mime = body.get("mimeType")
    template = _GDRIVE_LINKS_BY_MIME.get(str(mime), _GDRIVE_GENERIC_LINK)
    return ResponseFacts(link=template.format(id=file_id))


def _gmail_facts(action_type: str, body: dict[str, Any]) -> ResponseFacts:
    # Drafts nest the message, sends carry it at the top level.
    nested = body.get("message")
    message = nested if isinstance(nested, dict) else body
    message_id = _safe_id(message.get("id"))
    if message_id is None:
        return ResponseFacts()
    # An unsent draft is not in #all, so its link opens the drafts view.
    # drafts.send returns the sent Message, which lives in #all like any send.
    is_draft = action_type in ("gmail.drafts.create", "gmail.drafts.update")
    view = "drafts" if is_draft else "all"
    return ResponseFacts(link=f"https://mail.google.com/mail/u/0/#{view}/{message_id}")


def _linear_facts(body: dict[str, Any]) -> ResponseFacts:
    # GraphQL failures are 200s with an errors array.
    if body.get("errors"):
        return ResponseFacts(status_override=ReceiptStatus.FAILED)
    url = _first_string_named(body.get("data"), "url")
    if url is not None and len(url) <= _MAX_LINK_LEN and _LINEAR_URL_SHAPE.match(url):
        return ResponseFacts(link=url)
    return ResponseFacts()


def _first_string_named(node: Any, key: str, depth: int = 0) -> str | None:
    """First string value under ``key`` in a small nested payload. Bounded so
    a pathological response cannot recurse away."""
    if depth > 4:
        return None
    if isinstance(node, list):
        children: list[Any] = node[:20]
    elif isinstance(node, dict):
        value = node.get(key)
        if isinstance(value, str):
            return value
        children = list(node.values())
    else:
        return None
    for child in children:
        if isinstance(child, (dict, list)):
            found = _first_string_named(child, key, depth + 1)
            if found is not None:
                return found
    return None
