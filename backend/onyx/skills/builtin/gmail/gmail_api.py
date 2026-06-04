#!/usr/bin/env python3
"""Gmail wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. Output is JSON on stdout. The
Authorization header is injected by the Onyx egress gateway from the connected
user's credentials, so no token handling happens here.
"""

import argparse
import base64
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from email.message import EmailMessage
from typing import Any

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me/"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 25
_HTTP_TIMEOUT_SECONDS = 180
# Each listed message needs its own metadata GET (Gmail's list returns only
# id/threadId), so fan them out concurrently rather than N sequential calls.
_MAX_FETCH_WORKERS = 8
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
# Headers worth surfacing from a metadata-format message fetch.
_METADATA_HEADERS = ("From", "To", "Cc", "Subject", "Date")


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays
    small. Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _seg(value: str) -> str:
    """URL-encode a single path segment (ids may contain @ or /)."""
    return urllib.parse.quote(value, safe="")


def _req(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Gmail endpoint; return parsed JSON ({} on empty/204).
    Raises on transport failure (handled by the caller)."""
    url = _BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _list_ids(
    path: str, params: dict[str, Any], key: str, limit: int
) -> dict[str, Any]:
    """Walk a list endpoint (`<key>` + `nextPageToken`) up to `limit`,
    collecting the lightweight id records Gmail returns."""
    items: list[Any] = []
    token: str | None = None
    while True:
        q = dict(params, maxResults=min(_PAGE_SIZE, limit - len(items)))
        if token:
            q["pageToken"] = token
        resp = _req("GET", path, params=q)
        items.extend(resp.get(key) or [])
        token = resp.get("nextPageToken")
        if len(items) >= limit:
            return {"items": items[:limit], "truncated": bool(token)}
        if not token:
            break
    return {"items": items, "truncated": False}


def _headers_to_dict(headers: list[dict[str, str]]) -> dict[str, str]:
    wanted = {h.lower() for h in _METADATA_HEADERS}
    return {
        h["name"]: h["value"] for h in headers if h.get("name", "").lower() in wanted
    }


def _decode_b64url(data: str) -> str:
    pad = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + pad).decode("utf-8", errors="replace")


def _extract_plain_body(payload: dict[str, Any]) -> str:
    """Pull the first text/plain part out of a message payload."""
    if payload.get("mimeType") == "text/plain":
        body_data = payload.get("body", {}).get("data")
        if body_data:
            return _decode_b64url(body_data)
    for part in payload.get("parts") or []:
        found = _extract_plain_body(part)
        if found:
            return found
    return ""


def _build_raw(
    to: str, subject: str, body: str, cc: str | None, bcc: str | None
) -> str:
    """Build a base64url-encoded RFC 2822 message for send / draft writes."""
    em = EmailMessage()
    em["To"] = to
    em["Subject"] = subject
    if cc:
        em["Cc"] = cc
    if bcc:
        em["Bcc"] = bcc
    em.set_content(body)
    return base64.urlsafe_b64encode(em.as_bytes()).decode("ascii")


def _add_compose_args(sp: argparse.ArgumentParser) -> None:
    """The to/subject/body/cc/bcc args shared by `send` and the draft writes."""
    sp.add_argument("to")
    sp.add_argument("subject")
    sp.add_argument("body")
    sp.add_argument("--cc", help="comma-separated emails")
    sp.add_argument("--bcc", help="comma-separated emails")


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gmail_api.py", description="Gmail.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("messages", help="list / search message headers")
    sp.add_argument("--q", help="Gmail search query")
    sp.add_argument("--label", help="filter to a label id")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("message", help="one message with decoded body")
    sp.add_argument("message_id")

    sp = sub.add_parser("send", help="send an email (write)")
    _add_compose_args(sp)

    sub.add_parser("labels", help="list labels")

    sp = sub.add_parser("modify", help="add/remove labels on a message (write)")
    sp.add_argument("message_id")
    sp.add_argument("--add", help="comma-separated label ids")
    sp.add_argument("--remove", help="comma-separated label ids")

    sp = sub.add_parser("trash", help="move a message to trash (write)")
    sp.add_argument("message_id")

    sub.add_parser("profile", help="the connected user's Gmail profile")

    sp = sub.add_parser("thread", help="one conversation thread with decoded bodies")
    sp.add_argument("thread_id")

    sp = sub.add_parser("attachment", help="download a message attachment")
    sp.add_argument("message_id")
    sp.add_argument("attachment_id")
    sp.add_argument("--out", help="write the decoded bytes to this file path")

    sp = sub.add_parser("drafts", help="list drafts")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("draft", help="one draft with decoded body")
    sp.add_argument("draft_id")

    sp = sub.add_parser("draft-create", help="save a new draft (write, not sent)")
    _add_compose_args(sp)

    sp = sub.add_parser("draft-update", help="replace a draft (write, not sent)")
    sp.add_argument("draft_id")
    _add_compose_args(sp)

    sp = sub.add_parser("draft-delete", help="delete a draft (write)")
    sp.add_argument("draft_id")

    sp = sub.add_parser("draft-send", help="send an existing draft (write)")
    sp.add_argument("draft_id")

    sp = sub.add_parser("call", help="raw Gmail request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="appended to users/me/")
    sp.add_argument("json_body", nargs="?")
    return p


def _message_summary(ref: dict[str, Any]) -> dict[str, Any]:
    """Fetch one message's metadata and reduce it to the summary fields."""
    msg = _req(
        "GET",
        f"messages/{_seg(ref['id'])}",
        params={"format": "metadata", "metadataHeaders": list(_METADATA_HEADERS)},
    )
    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds"),
        "snippet": msg.get("snippet"),
        "headers": _headers_to_dict(msg.get("payload", {}).get("headers", [])),
    }


def _message_detail(msg: dict[str, Any]) -> dict[str, Any]:
    """Reduce a `format=full` message to id/headers/decoded body."""
    payload = msg.get("payload", {})
    return {
        "id": msg.get("id"),
        "threadId": msg.get("threadId"),
        "labelIds": msg.get("labelIds"),
        "snippet": msg.get("snippet"),
        "headers": _headers_to_dict(payload.get("headers", [])),
        "body": _extract_plain_body(payload),
    }


def _draft_summary(draft: dict[str, Any]) -> dict[str, Any]:
    """Fetch the underlying message metadata for one listed draft."""
    msg_ref = draft.get("message") or {}
    if not msg_ref.get("id"):
        return {"draftId": draft.get("id")}
    return {"draftId": draft.get("id"), **_message_summary(msg_ref)}


def _cmd_messages(a: argparse.Namespace) -> dict[str, Any]:
    listed = _list_ids(
        "messages",
        {"q": a.q, "labelIds": a.label},
        "messages",
        a.limit,
    )
    refs = listed["items"]
    # Fan the per-message metadata GETs out concurrently: a page of N is then
    # ~one round-trip of latency instead of N sequential ones. `map` preserves
    # input order and re-raises the first failure (same fail-fast as a loop).
    with ThreadPoolExecutor(
        max_workers=min(_MAX_FETCH_WORKERS, len(refs) or 1)
    ) as pool:
        summaries = list(pool.map(_message_summary, refs))
    return {
        "ok": True,
        "items": summaries,
        "count": len(summaries),
        "truncated": listed["truncated"],
    }


def _comma_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "messages":
        return _cmd_messages(a)

    if a.cmd == "message":
        msg = _req(
            "GET",
            f"messages/{_seg(a.message_id)}",
            params={"format": "full"},
        )
        return {"ok": True, "message": _message_detail(msg)}

    if a.cmd == "send":
        raw = _build_raw(a.to, a.subject, a.body, a.cc, a.bcc)
        sent = _req("POST", "messages/send", body={"raw": raw})
        return {"ok": True, "sent": sent}

    if a.cmd == "labels":
        resp = _req("GET", "labels")
        return {"ok": True, "labels": resp.get("labels") or []}

    if a.cmd == "modify":
        body: dict[str, Any] = {}
        if add := _comma_list(a.add):
            body["addLabelIds"] = add
        if remove := _comma_list(a.remove):
            body["removeLabelIds"] = remove
        if not body:
            return {"ok": False, "error": "nothing_to_modify"}
        msg = _req("POST", f"messages/{_seg(a.message_id)}/modify", body=body)
        return {"ok": True, "id": msg.get("id"), "labelIds": msg.get("labelIds")}

    if a.cmd == "trash":
        msg = _req("POST", f"messages/{_seg(a.message_id)}/trash")
        return {"ok": True, "id": msg.get("id"), "labelIds": msg.get("labelIds")}

    if a.cmd == "profile":
        return {"ok": True, "profile": _req("GET", "profile")}

    if a.cmd == "thread":
        thread = _req("GET", f"threads/{_seg(a.thread_id)}", params={"format": "full"})
        return {
            "ok": True,
            "thread": {
                "id": thread.get("id"),
                "messages": [_message_detail(m) for m in thread.get("messages") or []],
            },
        }

    if a.cmd == "attachment":
        att = _req(
            "GET",
            f"messages/{_seg(a.message_id)}/attachments/{_seg(a.attachment_id)}",
        )
        size = att.get("size")
        data = att.get("data")
        if not a.out:
            # Binary bytes don't belong on stdout; require --out to materialise
            # them and otherwise just report what's available.
            return {"ok": True, "size": size, "saved": False, "out": None}
        if not data:
            # No bytes to write — don't leave a zero-byte file looking like success.
            return {"ok": False, "error": "no_attachment_data", "size": size}
        pad = "=" * (-len(data) % 4)
        raw_bytes = base64.urlsafe_b64decode(data + pad)
        with open(a.out, "wb") as fh:
            fh.write(raw_bytes)
        return {"ok": True, "size": size, "saved": True, "out": a.out}

    if a.cmd == "drafts":
        listed = _list_ids("drafts", {}, "drafts", a.limit)
        refs = listed["items"]
        with ThreadPoolExecutor(
            max_workers=min(_MAX_FETCH_WORKERS, len(refs) or 1)
        ) as pool:
            summaries = list(pool.map(_draft_summary, refs))
        return {
            "ok": True,
            "items": summaries,
            "count": len(summaries),
            "truncated": listed["truncated"],
        }

    if a.cmd == "draft":
        draft = _req("GET", f"drafts/{_seg(a.draft_id)}", params={"format": "full"})
        return {
            "ok": True,
            "draft": {
                "id": draft.get("id"),
                "message": _message_detail(draft.get("message", {})),
            },
        }

    if a.cmd == "draft-create":
        raw = _build_raw(a.to, a.subject, a.body, a.cc, a.bcc)
        draft = _req("POST", "drafts", body={"message": {"raw": raw}})
        return {"ok": True, "draft": draft}

    if a.cmd == "draft-update":
        raw = _build_raw(a.to, a.subject, a.body, a.cc, a.bcc)
        draft = _req(
            "PUT", f"drafts/{_seg(a.draft_id)}", body={"message": {"raw": raw}}
        )
        return {"ok": True, "draft": draft}

    if a.cmd == "draft-delete":
        _req("DELETE", f"drafts/{_seg(a.draft_id)}")
        return {"ok": True, "deleted": a.draft_id}

    if a.cmd == "draft-send":
        sent = _req("POST", "drafts/send", body={"id": a.draft_id})
        return {"ok": True, "sent": sent}

    # `call` raw escape hatch
    body = None
    if a.json_body:
        body = json.loads(a.json_body)
        if not isinstance(body, dict):
            return {"ok": False, "error": "json_body_not_object"}
    resp = _req(a.method, a.path.lstrip("/"), body=body)
    return {"ok": True, "data": resp}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except json.JSONDecodeError as e:
        print(f"invalid json_body: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling Gmail: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Gmail: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
