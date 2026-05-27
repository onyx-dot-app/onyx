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
from email.message import EmailMessage
from typing import Any

_BASE = "https://gmail.googleapis.com/gmail/v1/users/me/"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 25
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
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310
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
    sp.add_argument("to")
    sp.add_argument("subject")
    sp.add_argument("body")
    sp.add_argument("--cc", help="comma-separated emails")
    sp.add_argument("--bcc", help="comma-separated emails")

    sub.add_parser("labels", help="list labels")

    sp = sub.add_parser("modify", help="add/remove labels on a message (write)")
    sp.add_argument("message_id")
    sp.add_argument("--add", help="comma-separated label ids")
    sp.add_argument("--remove", help="comma-separated label ids")

    sp = sub.add_parser("trash", help="move a message to trash (write)")
    sp.add_argument("message_id")

    sub.add_parser("profile", help="the connected user's Gmail profile")

    sp = sub.add_parser("call", help="raw Gmail request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="appended to users/me/")
    sp.add_argument("json_body", nargs="?")
    return p


def _cmd_messages(a: argparse.Namespace) -> dict[str, Any]:
    listed = _list_ids(
        "messages",
        {"q": a.q, "labelIds": a.label},
        "messages",
        a.limit,
    )
    summaries: list[dict[str, Any]] = []
    for ref in listed["items"]:
        msg = _req(
            "GET",
            f"messages/{_seg(ref['id'])}",
            params={"format": "metadata", "metadataHeaders": list(_METADATA_HEADERS)},
        )
        summaries.append(
            {
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "labelIds": msg.get("labelIds"),
                "snippet": msg.get("snippet"),
                "headers": _headers_to_dict(msg.get("payload", {}).get("headers", [])),
            }
        )
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
        payload = msg.get("payload", {})
        return {
            "ok": True,
            "message": {
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "labelIds": msg.get("labelIds"),
                "snippet": msg.get("snippet"),
                "headers": _headers_to_dict(payload.get("headers", [])),
                "body": _extract_plain_body(payload),
            },
        }

    if a.cmd == "send":
        em = EmailMessage()
        em["To"] = a.to
        em["Subject"] = a.subject
        if a.cc:
            em["Cc"] = a.cc
        if a.bcc:
            em["Bcc"] = a.bcc
        em.set_content(a.body)
        raw = base64.urlsafe_b64encode(em.as_bytes()).decode("ascii")
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
