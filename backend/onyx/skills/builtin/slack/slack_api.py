#!/usr/bin/env python3
"""Slack Web API wrapper for the Onyx Craft sandbox.

Common Slack operations exposed as subcommands. Output is JSON on stdout.
Slack signals failure with {"ok": false, "error": "..."} (still HTTP 200).
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://slack.com/api/"
_METHOD_RE = re.compile(r"^[a-z][a-zA-Z0-9._]*$")
_PAGE_SIZE = 200
_DEFAULT_LIMIT = 200
_HTTP_TIMEOUT_SECONDS = 180
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024  # Slack's own upload limit


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays
    small. Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _form_value(value: Any) -> str:
    """Coerce a param value for x-www-form-urlencoded Slack requests.
    Booleans become "true"/"false"; nested values are JSON-encoded
    (Slack reads complex args like blocks as JSON strings)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value)


def _call(method: str, body: dict[str, Any], as_json: bool = False) -> dict[str, Any]:
    """POST to a Slack method; return the parsed JSON. Raises on
    transport failure (handled by the caller).

    Args are form-encoded by default, not JSON: Slack's web/query methods
    (conversations.list, users.list, etc.) read params from the
    form-encoded body and silently ignore a JSON body. Set as_json=True
    for the few methods that require an application/json body."""
    if as_json:
        data = json.dumps(body).encode("utf-8")
        content_type = "application/json; charset=utf-8"
    else:
        data = urllib.parse.urlencode(
            {k: _form_value(v) for k, v in body.items() if v is not None}
        ).encode("utf-8")
        content_type = "application/x-www-form-urlencoded; charset=utf-8"
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        _BASE + method,
        data=data,
        method="POST",
        headers={"Content-Type": content_type},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _paginate(
    method: str, params: dict[str, Any], list_key: str, limit: int
) -> dict[str, Any]:
    """Cursor-paginate `method`, accumulating `list_key` up to `limit`.
    On a Slack error the raw error object is returned unchanged."""
    items: list[Any] = []
    cursor = ""
    truncated = False
    while True:
        body = dict(params, limit=min(_PAGE_SIZE, limit - len(items)))
        if cursor:
            body["cursor"] = cursor
        resp = _call(method, body)
        if not resp.get("ok"):
            return resp
        items.extend(resp.get(list_key, []))
        cursor = (resp.get("response_metadata") or {}).get("next_cursor") or ""
        if len(items) >= limit:
            truncated = bool(cursor)
            items = items[:limit]
            break
        if not cursor:
            break
    return {"ok": True, list_key: items, "count": len(items), "truncated": truncated}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="slack_api.py", description="Slack Web API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    with_limit(sub.add_parser("channels", help="list conversations"))

    sp = sub.add_parser("history", help="recent messages in a channel")
    sp.add_argument("channel")
    with_limit(sp)

    sp = sub.add_parser("replies", help="messages in a thread")
    sp.add_argument("channel")
    sp.add_argument("ts")
    with_limit(sp)

    with_limit(sub.add_parser("users", help="list workspace users"))

    sp = sub.add_parser("user", help="look up one user")
    sp.add_argument("user_id")

    sp = sub.add_parser("search", help="search messages")
    sp.add_argument("query")
    sp.add_argument("--count", type=int, default=20)

    sp = sub.add_parser("post", help="post a message (write)")
    sp.add_argument("channel")
    sp.add_argument("text")

    sp = sub.add_parser("upload", help="upload a file and share it (write)")
    sp.add_argument("channel")
    sp.add_argument("file_path")
    sp.add_argument("--title", help="file title shown in Slack")
    sp.add_argument("--comment", help="message text posted with the file")
    sp.add_argument("--thread-ts", dest="thread_ts", help="reply in this thread")

    sp = sub.add_parser("call", help="raw Slack method")
    sp.add_argument("method")
    sp.add_argument("json_args", nargs="?")
    sp.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="send args as a JSON body (for JSON-only methods)",
    )
    return p


def _raw_call(method: str, json_args: str | None, as_json: bool) -> dict[str, Any]:
    """`call` escape hatch: invoke an arbitrary Slack method with a
    JSON object of args."""
    if not _METHOD_RE.match(method):
        return {"ok": False, "error": "invalid_method_name"}
    args: dict[str, Any] = {}
    if json_args:
        parsed = json.loads(json_args)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "json_args_not_object"}
        args = parsed
    return _call(method, args, as_json=as_json)


def _upload_file(
    channel: str,
    file_path: str,
    title: str | None,
    comment: str | None,
    thread_ts: str | None,
) -> dict[str, Any]:
    """Share a local file using Slack's external upload flow:
    files.getUploadURLExternal -> POST bytes to the returned URL ->
    files.completeUploadExternal (which posts it to the channel/thread)."""
    if not os.path.isfile(file_path):
        return {"ok": False, "error": "file_not_found"}
    filename = os.path.basename(file_path)
    length = os.path.getsize(file_path)
    if length > _MAX_UPLOAD_BYTES:
        return {"ok": False, "error": "file_too_large"}
    reserved = _call(
        "files.getUploadURLExternal", {"filename": filename, "length": length}
    )
    if not reserved.get("ok"):
        return reserved
    upload_url = reserved.get("upload_url")
    file_id = reserved.get("file_id")
    if not upload_url or not file_id:
        return {"ok": False, "error": "missing_upload_url"}
    parsed_url = urllib.parse.urlparse(upload_url)
    if parsed_url.scheme != "https" or parsed_url.hostname != "files.slack.com":
        return {"ok": False, "error": "untrusted_upload_url"}
    with open(file_path, "rb") as fh:
        content = fh.read()
    put = urllib.request.Request(  # noqa: S310 — Slack-issued upload URL
        upload_url,
        data=content,
        method="POST",
        headers={"Content-Type": "application/octet-stream"},
    )
    with urllib.request.urlopen(put, timeout=_HTTP_TIMEOUT_SECONDS):  # noqa: S310
        pass
    file_entry: dict[str, Any] = {"id": file_id}
    if title:
        file_entry["title"] = title
    complete: dict[str, Any] = {"files": [file_entry], "channel_id": channel}
    if comment:
        complete["initial_comment"] = comment
    if thread_ts:
        complete["thread_ts"] = thread_ts
    return _call("files.completeUploadExternal", complete)


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "channels":
        return _paginate(
            "conversations.list",
            {"types": "public_channel,private_channel", "exclude_archived": True},
            "channels",
            a.limit,
        )

    if a.cmd == "history":
        return _paginate(
            "conversations.history", {"channel": a.channel}, "messages", a.limit
        )

    if a.cmd == "replies":
        return _paginate(
            "conversations.replies",
            {"channel": a.channel, "ts": a.ts},
            "messages",
            a.limit,
        )

    if a.cmd == "users":
        return _paginate("users.list", {}, "members", a.limit)

    if a.cmd == "user":
        return _call("users.info", {"user": a.user_id})

    if a.cmd == "search":
        return _call("search.messages", {"query": a.query, "count": a.count})

    if a.cmd == "post":
        return _call("chat.postMessage", {"channel": a.channel, "text": a.text})

    if a.cmd == "upload":
        return _upload_file(a.channel, a.file_path, a.title, a.comment, a.thread_ts)

    # `call` is the only remaining subcommand (subparser is required).
    return _raw_call(a.method, a.json_args, a.as_json)


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except json.JSONDecodeError as e:
        print(f"invalid json_args: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling Slack: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Slack: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
