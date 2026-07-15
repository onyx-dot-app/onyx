#!/usr/bin/env python3
"""Confluence Cloud REST API wrapper for the Onyx Craft sandbox.

Common Confluence operations exposed as subcommands. The connected user's token
is injected by the egress gateway, so this script sends no credentials itself.

Every call other than site discovery is scoped to an Atlassian site by its
cloud id and rooted at the classic Confluence Cloud base
``/ex/confluence/{cloud_id}/wiki/rest/api``. The cloud id is resolved
automatically from ``/oauth/token/accessible-resources`` (first site, or the one
selected by ``--cloud-id`` / ``--site``) and cached for the process.

Output is JSON on stdout; Confluence signals failure with a non-2xx status and a
JSON body, surfaced here as ``{"ok": false, ...}``.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.atlassian.com"
_ACCESSIBLE_RESOURCES = "/oauth/token/accessible-resources"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 180
_HEADERS = {
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
    """Issue a request to the Atlassian API gateway; return the parsed JSON.
    Raises urllib errors on transport / non-2xx failure (handled by the caller).
    """
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
    with urllib.request.urlopen(
        req, timeout=_HTTP_TIMEOUT_SECONDS
    ) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _resolve_cloud_id(cloud_id: str | None, site: str | None) -> str:
    """Resolve the Atlassian cloud id to scope Confluence calls.

    Uses an explicit ``--cloud-id`` verbatim; otherwise reads the accessible
    sites and picks the one whose name/url matches ``--site`` (case-insensitive
    substring), falling back to the first site when neither override is given.
    """
    if cloud_id:
        return cloud_id
    resources = _request("GET", _ACCESSIBLE_RESOURCES)
    sites = resources if isinstance(resources, list) else []
    if not sites:
        raise _CloudIdError("no accessible Atlassian sites for this grant")
    if site:
        needle = site.lower()
        for s in sites:
            name = str(s.get("name", "")).lower()
            url = str(s.get("url", "")).lower()
            if needle in name or needle in url:
                return str(s["id"])
        raise _CloudIdError(f"no accessible site matched --site {site!r}")
    return str(sites[0]["id"])


class _CloudIdError(Exception):
    """No usable cloud id could be resolved (surfaced as a JSON error)."""


def _wiki(cloud_id: str, path: str) -> str:
    """Build a classic Confluence Cloud REST path under a site's cloud id."""
    return f"/ex/confluence/{cloud_id}/wiki/rest/api{path}"


def _query(path: str, params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    if not clean:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{urllib.parse.urlencode(clean)}"


def _one(path: str, key: str) -> dict[str, Any]:
    return {"ok": True, key: _request("GET", path)}


def _paginate(
    path: str, list_key: str, limit: int, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Page through a Confluence list endpoint (offset/limit pagination via
    ``start`` and ``limit`` query params; ``results`` in the body)."""
    results: list[Any] = []
    start = 0
    base_params = dict(params or {})
    while len(results) < limit:
        page_limit = min(_PAGE_SIZE, limit - len(results))
        url = _query(path, dict(base_params, start=start, limit=page_limit))
        parsed = _request("GET", url)
        batch = parsed.get("results") or []
        results.extend(batch)
        if len(batch) < page_limit:
            return {
                "ok": True,
                list_key: results[:limit],
                "count": len(results[:limit]),
                "truncated": False,
            }
        start += page_limit
    return {"ok": True, list_key: results[:limit], "count": limit, "truncated": True}


def _bad_request(message: str) -> dict[str, Any]:
    """A client-side validation failure, in the same JSON shape as API errors."""
    return {"ok": False, "status": None, "error": message}


def _storage_body(html: str) -> dict[str, Any]:
    """A Confluence storage-format body wrapper for a page/blog/comment."""
    return {"storage": {"value": html, "representation": "storage"}}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="confluence_api.py", description="Confluence Cloud REST API."
    )
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    p.add_argument("--cloud-id", help="Atlassian cloud id to target (skips lookup)")
    p.add_argument("--site", help="pick a site by name/url substring (else the first)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sub.add_parser("sites", help="list accessible Atlassian sites + cloud ids")

    sub.add_parser("me", help="the connected user's Confluence profile")

    sp = sub.add_parser("spaces", help="list spaces")
    with_limit(sp)

    sp = sub.add_parser("search", help="search content with CQL")
    sp.add_argument("cql", help="a CQL query, e.g. 'type=page and text ~ \"roadmap\"'")
    with_limit(sp)

    sp = sub.add_parser("page", help="fetch a piece of content by id")
    sp.add_argument("content_id")

    sp = sub.add_parser("children", help="list a content's children")
    sp.add_argument("content_id")
    sp.add_argument("--type", default="page", help="child type (default: page)")
    with_limit(sp)

    sp = sub.add_parser("create-page", help="create a page (write)")
    sp.add_argument("--space", required=True, help="space key")
    sp.add_argument("--title", required=True, help="page title")
    sp.add_argument("--body", required=True, help="body as storage-format HTML")
    sp.add_argument("--parent", help="parent content id (creates a child page)")

    sp = sub.add_parser("update-page", help="update a page (write)")
    sp.add_argument("content_id")
    sp.add_argument("--title", required=True, help="new title")
    sp.add_argument("--body", required=True, help="new body as storage-format HTML")
    sp.add_argument(
        "--version",
        type=int,
        required=True,
        help="new version number (current version + 1)",
    )

    sp = sub.add_parser("comment", help="add a comment to content (write)")
    sp.add_argument("content_id", help="the content the comment is attached to")
    sp.add_argument("body", help="comment text as storage-format HTML")

    sp = sub.add_parser("delete-page", help="delete (trash) content (write)")
    sp.add_argument("content_id")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    # `sites` is the one command that needs no cloud id — resolve lazily for the
    # rest so a bad/unauthorized grant surfaces one clean error.
    if a.cmd == "sites":
        return {"ok": True, "sites": _request("GET", _ACCESSIBLE_RESOURCES)}

    cloud_id = _resolve_cloud_id(a.cloud_id, a.site)

    if a.cmd == "me":
        return _one(_wiki(cloud_id, "/user/current"), "user")

    if a.cmd == "spaces":
        return _paginate(_wiki(cloud_id, "/space"), "spaces", a.limit)

    if a.cmd == "search":
        return _paginate(
            _wiki(cloud_id, "/search"), "results", a.limit, params={"cql": a.cql}
        )

    if a.cmd == "page":
        path = _query(
            _wiki(cloud_id, f"/content/{a.content_id}"),
            {"expand": "body.storage,version,space"},
        )
        return {"ok": True, "content": _request("GET", path)}

    if a.cmd == "children":
        return _paginate(
            _wiki(cloud_id, f"/content/{a.content_id}/child/{a.type}"),
            "children",
            a.limit,
        )

    if a.cmd == "create-page":
        payload: dict[str, Any] = {
            "type": "page",
            "title": a.title,
            "space": {"key": a.space},
            "body": _storage_body(a.body),
        }
        if a.parent:
            payload["ancestors"] = [{"id": a.parent}]
        return {
            "ok": True,
            "content": _request("POST", _wiki(cloud_id, "/content"), payload),
        }

    if a.cmd == "update-page":
        payload = {
            "type": "page",
            "title": a.title,
            "body": _storage_body(a.body),
            "version": {"number": a.version},
        }
        return {
            "ok": True,
            "content": _request(
                "PUT", _wiki(cloud_id, f"/content/{a.content_id}"), payload
            ),
        }

    if a.cmd == "comment":
        payload = {
            "type": "comment",
            "container": {"id": a.content_id, "type": "page"},
            "body": _storage_body(a.body),
        }
        return {
            "ok": True,
            "comment": _request("POST", _wiki(cloud_id, "/content"), payload),
        }

    if a.cmd == "delete-page":
        _request("DELETE", _wiki(cloud_id, f"/content/{a.content_id}"))
        return {"ok": True, "deleted": a.content_id}

    raise AssertionError(f"unhandled command: {a.cmd!r}")


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except _CloudIdError as e:
        print(json.dumps({"ok": False, "status": None, "error": str(e)}))
        return 1
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = parsed.get("message") or parsed.get("error") or detail
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
                    "error": f"network error calling Confluence: {e.reason}",
                }
            )
        )
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
