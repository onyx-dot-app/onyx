#!/usr/bin/env python3
"""HubSpot CRM API wrapper for the Onyx Craft sandbox.

Common HubSpot CRM operations (contacts / companies / deals) exposed as
subcommands. The connected user's OAuth token is injected by the egress gateway,
so this script sends no credentials itself. Output is JSON on stdout; HubSpot
signals failure with a non-2xx status and a ``{"status": ..., "message": ...}``
body, surfaced here as ``{"ok": false, ...}``.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.hubapi.com"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 180
_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")
# CRM object type -> path segment. Drives the per-object subcommands.
_OBJECTS = {
    "contacts": "contacts",
    "companies": "companies",
    "deals": "deals",
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


def _seg(value: str) -> str:
    """URL-encode a single path segment."""
    return urllib.parse.quote(value, safe="")


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> Any:
    """Issue a request to the HubSpot CRM API; return parsed JSON ({} on empty).
    Raises urllib errors on transport / non-2xx failure (handled by caller)."""
    url = _BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _paginate(
    path: str, properties: list[str] | None, limit: int
) -> dict[str, Any]:
    """Page through a HubSpot CRM list endpoint up to `limit`. HubSpot returns
    `{"results": [...], "paging": {"next": {"after": "<cursor>"}}}`."""
    results: list[Any] = []
    after: str | None = None
    while len(results) < limit:
        params: dict[str, Any] = {"limit": min(_PAGE_SIZE, limit - len(results))}
        if properties:
            params["properties"] = ",".join(properties)
        if after:
            params["after"] = after
        resp = _request("GET", path, params=params)
        results.extend(resp.get("results") or [])
        after = (resp.get("paging") or {}).get("next", {}).get("after")
        if not after:
            break
    return {
        "ok": True,
        "results": results[:limit],
        "count": min(len(results), limit),
        "truncated": bool(after) or len(results) > limit,
    }


def _properties_param(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _properties_body(value: str) -> dict[str, Any]:
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("--properties must be a JSON object")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hubspot_api.py", description="HubSpot CRM API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    # Per-object list / get / create / update subcommands. Singular form reads
    # one record; plural lists.
    for obj, singular in (
        ("contacts", "contact"),
        ("companies", "company"),
        ("deals", "deal"),
    ):
        sp = sub.add_parser(obj, help=f"list {obj}")
        sp.add_argument("--properties", help="comma-separated property names")
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

        sp = sub.add_parser(singular, help=f"read one {singular} by id")
        sp.add_argument("object_id")
        sp.add_argument("--properties", help="comma-separated property names")

        sp = sub.add_parser(f"{singular}-create", help=f"create a {singular} (write)")
        sp.add_argument(
            "--properties", required=True, help="JSON object of property values"
        )

        sp = sub.add_parser(f"{singular}-update", help=f"update a {singular} (write)")
        sp.add_argument("object_id")
        sp.add_argument(
            "--properties", required=True, help="JSON object of property values"
        )

    sp = sub.add_parser("call", help="raw HubSpot request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="full API path, e.g. /crm/v3/objects/contacts")
    sp.add_argument("json_body", nargs="?")
    return p


# Maps a subcommand prefix to its CRM object path segment.
_SINGULAR_TO_OBJECT = {
    "contact": "contacts",
    "company": "companies",
    "deal": "deals",
}


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd in _OBJECTS:
        path = f"/crm/v3/objects/{_OBJECTS[a.cmd]}"
        return _paginate(path, _properties_param(a.properties), a.limit)

    if a.cmd in _SINGULAR_TO_OBJECT:
        obj = _SINGULAR_TO_OBJECT[a.cmd]
        params = {}
        props = _properties_param(a.properties)
        if props:
            params["properties"] = ",".join(props)
        record = _request(
            "GET", f"/crm/v3/objects/{obj}/{_seg(a.object_id)}", params=params or None
        )
        return {"ok": True, a.cmd: record}

    for singular, obj in _SINGULAR_TO_OBJECT.items():
        if a.cmd == f"{singular}-create":
            body = {"properties": _properties_body(a.properties)}
            record = _request("POST", f"/crm/v3/objects/{obj}", body=body)
            return {"ok": True, singular: record}
        if a.cmd == f"{singular}-update":
            body = {"properties": _properties_body(a.properties)}
            record = _request(
                "PATCH", f"/crm/v3/objects/{obj}/{_seg(a.object_id)}", body=body
            )
            return {"ok": True, singular: record}

    # `call` raw escape hatch
    body = None
    if a.json_body:
        body = json.loads(a.json_body)
        if not isinstance(body, dict):
            return {"ok": False, "error": "json_body_not_object"}
    resp = _request(a.method, "/" + a.path.lstrip("/"), body=body)
    return {"ok": True, "data": resp}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except (ValueError, json.JSONDecodeError) as e:
        print(f"invalid argument: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("message", detail)
        except ValueError:
            message = detail
        print(json.dumps({"ok": False, "status": e.code, "error": message}))
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling HubSpot: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
