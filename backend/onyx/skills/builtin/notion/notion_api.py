#!/usr/bin/env python3
"""Notion REST API wrapper for the Onyx Craft sandbox.

Common Notion operations exposed as subcommands. The connected user's token is
injected by the egress gateway, so this script sends no credentials itself.
Output is JSON on stdout; Notion signals failure with a non-2xx status and a
``{"code": ..., "message": ...}`` body, surfaced here as ``{"ok": false, ...}``.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from typing import Any

_BASE = "https://api.notion.com"
_NOTION_VERSION = "2025-09-03"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 180
_HEADERS = {
    "Notion-Version": _NOTION_VERSION,
    "Accept": "application/json",
}


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays small.
    Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _request(
    method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Issue a request to the Notion REST API; return the parsed JSON. Raises
    urllib errors on transport / non-2xx failure (handled by the caller)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = dict(_HEADERS)
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        _BASE + path,
        data=data,
        method=method,
        headers=headers,
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _one(path: str, key: str) -> dict[str, Any]:
    return {"ok": True, key: _request("GET", path)}


def _paginate_get(path: str, list_key: str, limit: int) -> dict[str, Any]:
    """Page through a GET list endpoint (Notion cursor pagination via the
    `start_cursor` query param and `has_more` / `next_cursor` in the body)."""
    results: list[Any] = []
    cursor: str | None = None
    while len(results) < limit:
        page_size = min(_PAGE_SIZE, limit - len(results))
        sep = "&" if "?" in path else "?"
        url = f"{path}{sep}page_size={page_size}"
        if cursor:
            url += f"&start_cursor={cursor}"
        parsed = _request("GET", url)
        results.extend(parsed.get("results") or [])
        if not parsed.get("has_more"):
            return {
                "ok": True,
                list_key: results[:limit],
                "count": len(results[:limit]),
                "truncated": False,
            }
        cursor = parsed.get("next_cursor")
    return {"ok": True, list_key: results[:limit], "count": limit, "truncated": True}


def _paginate_post(
    path: str, body: dict[str, Any], list_key: str, limit: int
) -> dict[str, Any]:
    """Page through a POST list endpoint (search / database query), where the
    cursor and page size ride in the JSON body."""
    results: list[Any] = []
    cursor: str | None = None
    while len(results) < limit:
        payload = dict(body, page_size=min(_PAGE_SIZE, limit - len(results)))
        if cursor:
            payload["start_cursor"] = cursor
        parsed = _request("POST", path, payload)
        results.extend(parsed.get("results") or [])
        if not parsed.get("has_more"):
            return {
                "ok": True,
                list_key: results[:limit],
                "count": len(results[:limit]),
                "truncated": False,
            }
        cursor = parsed.get("next_cursor")
    return {"ok": True, list_key: results[:limit], "count": limit, "truncated": True}


def _rich_text(text: str) -> list[dict[str, Any]]:
    """A minimal rich_text array carrying a single plain-text run."""
    return [{"type": "text", "text": {"content": text}}]


def _paragraph_block(text: str) -> dict[str, Any]:
    return {
        "object": "block",
        "type": "paragraph",
        "paragraph": {"rich_text": _rich_text(text)},
    }


def _bad_request(message: str) -> dict[str, Any]:
    """A client-side validation failure, in the same JSON shape as API errors."""
    return {"ok": False, "status": None, "error": message}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="notion_api.py", description="Notion REST API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sub.add_parser("me", help="the connected integration/bot user")

    with_limit(sub.add_parser("users", help="list the workspace's users"))

    sp = sub.add_parser("search", help="search pages and data sources")
    sp.add_argument("query", nargs="?", default="", help="search text (optional)")
    sp.add_argument(
        "--filter",
        choices=["page", "data_source"],
        help="restrict results to pages or data sources",
    )
    with_limit(sp)

    sp = sub.add_parser("page", help="fetch a page's properties")
    sp.add_argument("page_id")

    sp = sub.add_parser("blocks", help="list a page/block's child blocks")
    sp.add_argument("block_id")
    with_limit(sp)

    sp = sub.add_parser("database", help="list a database's data sources")
    sp.add_argument("database_id")

    sp = sub.add_parser("data-source", help="fetch a data source's schema")
    sp.add_argument("data_source_id")

    sp = sub.add_parser("query", help="query a data source's rows")
    sp.add_argument("data_source_id")
    with_limit(sp)

    sp = sub.add_parser("create-page", help="create a page (write)")
    group = sp.add_mutually_exclusive_group(required=True)
    group.add_argument("--parent-page", help="parent page id")
    group.add_argument("--parent-data-source", help="parent data source id")
    sp.add_argument("--title", required=True, help="page title")
    sp.add_argument("--text", help="optional first paragraph of body text")

    sp = sub.add_parser("append", help="append blocks to a page/block (write)")
    sp.add_argument("block_id", help="parent page or block id")
    sp.add_argument("--text", required=True, help="paragraph text to append")

    sp = sub.add_parser("comment", help="add a comment to a page (write)")
    sp.add_argument("page_id")
    sp.add_argument("body")

    sp = sub.add_parser(
        "update-page", help="update a page's title/icon, or archive/restore it (write)"
    )
    sp.add_argument("page_id")
    sp.add_argument("--title", help="new page title")
    sp.add_argument("--icon", help="new page icon as a single emoji")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument("--archive", action="store_true", help="move the page to trash")
    grp.add_argument(
        "--restore", action="store_true", help="restore the page from trash"
    )

    sp = sub.add_parser(
        "update-block",
        help="update a paragraph block's text, or archive/restore it (write)",
    )
    sp.add_argument("block_id")
    sp.add_argument("--text", help="new paragraph text (block must be a paragraph)")
    grp = sp.add_mutually_exclusive_group()
    grp.add_argument(
        "--archive", action="store_true", help="archive (soft-delete) the block"
    )
    grp.add_argument("--restore", action="store_true", help="restore the block")

    sp = sub.add_parser("delete-block", help="delete a block (move to trash) (write)")
    sp.add_argument("block_id")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "me":
        return _one("/v1/users/me", "user")

    if a.cmd == "users":
        return _paginate_get("/v1/users", "users", a.limit)

    if a.cmd == "search":
        body: dict[str, Any] = {}
        if a.query:
            body["query"] = a.query
        if a.filter:
            body["filter"] = {"property": "object", "value": a.filter}
        return _paginate_post("/v1/search", body, "results", a.limit)

    if a.cmd == "page":
        return _one(f"/v1/pages/{a.page_id}", "page")

    if a.cmd == "blocks":
        return _paginate_get(f"/v1/blocks/{a.block_id}/children", "blocks", a.limit)

    if a.cmd == "database":
        return _one(f"/v1/databases/{a.database_id}", "database")

    if a.cmd == "data-source":
        return _one(f"/v1/data_sources/{a.data_source_id}", "data_source")

    if a.cmd == "query":
        return _paginate_post(
            f"/v1/data_sources/{a.data_source_id}/query", {}, "results", a.limit
        )

    if a.cmd == "create-page":
        if a.parent_data_source:
            parent = {"data_source_id": a.parent_data_source}
        else:
            parent = {"page_id": a.parent_page}
        # A row's title lives under its title property; the well-known "title"
        # key works for the default schema of both page and data-source parents.
        properties = {"title": {"title": _rich_text(a.title)}}
        payload: dict[str, Any] = {"parent": parent, "properties": properties}
        if a.text:
            payload["children"] = [_paragraph_block(a.text)]
        return {"ok": True, "page": _request("POST", "/v1/pages", payload)}

    if a.cmd == "append":
        payload = {"children": [_paragraph_block(a.text)]}
        return {
            "ok": True,
            "result": _request("PATCH", f"/v1/blocks/{a.block_id}/children", payload),
        }

    if a.cmd == "comment":
        payload = {
            "parent": {"page_id": a.page_id},
            "rich_text": _rich_text(a.body),
        }
        return {"ok": True, "comment": _request("POST", "/v1/comments", payload)}

    if a.cmd == "update-page":
        payload = {}
        if a.title:
            payload["properties"] = {"title": {"title": _rich_text(a.title)}}
        if a.icon:
            payload["icon"] = {"type": "emoji", "emoji": a.icon}
        if a.archive:
            payload["archived"] = True
        elif a.restore:
            payload["archived"] = False
        if not payload:
            return _bad_request(
                "update-page needs at least one of --title/--icon/--archive/--restore"
            )
        return {
            "ok": True,
            "page": _request("PATCH", f"/v1/pages/{a.page_id}", payload),
        }

    if a.cmd == "update-block":
        payload = {}
        if a.text is not None:
            payload["paragraph"] = {"rich_text": _rich_text(a.text)}
        if a.archive:
            payload["archived"] = True
        elif a.restore:
            payload["archived"] = False
        if not payload:
            return _bad_request("update-block needs --text and/or --archive/--restore")
        return {
            "ok": True,
            "block": _request("PATCH", f"/v1/blocks/{a.block_id}", payload),
        }

    if a.cmd == "delete-block":
        return {"ok": True, "block": _request("DELETE", f"/v1/blocks/{a.block_id}")}

    raise AssertionError(f"unhandled command: {a.cmd!r}")


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("message", detail)
        except ValueError:
            message = detail
        print(json.dumps({"ok": False, "status": e.code, "error": message}))
        return 1
    except urllib.error.URLError as e:
        # DNS / connection / timeout failures carry no HTTP status, but still
        # emit the documented JSON-on-stdout contract so agents parse one shape.
        print(
            json.dumps(
                {
                    "ok": False,
                    "status": None,
                    "error": f"network error calling Notion: {e.reason}",
                }
            )
        )
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
