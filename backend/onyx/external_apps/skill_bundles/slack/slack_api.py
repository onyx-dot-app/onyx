#!/usr/bin/env python3
"""Light Slack Web API wrapper for the Onyx Craft sandbox.

Auth is NOT handled here. Requests to https://slack.com/api/* are
authenticated by the Onyx egress proxy (it injects the Bearer token).

Common read endpoints are exposed as subcommands that auto-paginate
(cursor) and prune empty fields to keep responses small. `post` is the
only write. `call` is a raw escape hatch for any other Slack method.

    python slack_api.py channels [--limit N]
    python slack_api.py history <channel> [--limit N]
    python slack_api.py replies <channel> <ts> [--limit N]
    python slack_api.py users [--limit N]
    python slack_api.py user <user_id>
    python slack_api.py search <query> [--count N]
    python slack_api.py post <channel> <text>
    python slack_api.py call <method> [json_args]

Output is always JSON on stdout. Slack signals failure with
{"ok": false, "error": "..."} (still HTTP 200) — those are passed
through verbatim and exit non-zero.
"""

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.request
from typing import Any

_BASE = "https://slack.com/api/"
_METHOD_RE = re.compile(r"^[a-z][a-zA-Z0-9._]*$")
_PAGE_SIZE = 200
_DEFAULT_LIMIT = 200


def _make_opener() -> urllib.request.OpenerDirector:
    """DEMO egress hook: if ONYX_DEMO_EGRESS_PROXY is set, route this
    wrapper's requests through the demo interceptor and trust its CA.
    Unset → default behavior. Scoped to this process only; opencode
    ignores these (non-standard) vars, so its own egress is untouched.
    The production interceptor makes this unnecessary."""
    proxy = os.environ.get("ONYX_DEMO_EGRESS_PROXY")
    if not proxy:
        return urllib.request.build_opener()
    ca = os.environ.get("ONYX_DEMO_EGRESS_CA") or ""
    ca = os.path.expanduser(os.path.expandvars(ca))
    if ca and not os.path.isfile(ca):
        raise SystemExit(
            f"ONYX_DEMO_EGRESS_CA does not resolve to a file: {ca!r} "
            "(set it to an absolute, already-expanded path)"
        )
    ctx = ssl.create_default_context(cafile=ca or None)
    return urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy}),
        urllib.request.HTTPSHandler(context=ctx),
    )


_OPENER = _make_opener()


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays
    small. Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _call(method: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST to a Slack method; return the parsed JSON object. Raises on
    transport failure (handled by the caller)."""
    req = urllib.request.Request(
        _BASE + method,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with _OPENER.open(req, timeout=30) as resp:
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

    sp = sub.add_parser("call", help="raw Slack method")
    sp.add_argument("method")
    sp.add_argument("json_args", nargs="?")
    return p


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
    # call
    if not _METHOD_RE.match(a.method):
        return {"ok": False, "error": "invalid_method_name"}
    args: dict[str, Any] = {}
    if a.json_args:
        parsed = json.loads(a.json_args)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "json_args_not_object"}
        args = parsed
    return _call(a.method, args)


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
