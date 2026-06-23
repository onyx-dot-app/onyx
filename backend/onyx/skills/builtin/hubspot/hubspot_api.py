#!/usr/bin/env python3
"""HubSpot CRM (REST v3) wrapper for the Onyx Craft sandbox.

Common CRM operations on contacts, companies, and deals exposed as
subcommands. The egress proxy injects the user's HubSpot OAuth token on
the wire, so this script sends NO credentials. Output is JSON on stdout.

Stdlib only — do not import onyx internals.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.hubapi.com"
_DEFAULT_LIMIT = 100
_PAGE_SIZE = 100
_HTTP_TIMEOUT_SECONDS = 180

# The three CRM object types this helper knows about.
_OBJECTS = ("contacts", "companies", "deals")


def _request(
    method: str, path: str, params: dict[str, Any] | None = None, body: Any = None
) -> dict[str, Any]:
    """Send a request to the HubSpot REST API; return the parsed JSON.

    Raises urllib errors on transport / HTTP failure (handled by ``main``)."""
    url = _BASE + path
    if params:
        # Drop None values, then encode (lists become repeated keys).
        clean = {k: v for k, v in params.items() if v is not None}
        url = url + "?" + urllib.parse.urlencode(clean, doseq=True)
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(  # noqa: S310 — fixed https endpoint
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _properties_arg(value: str | None) -> list[str] | None:
    """Comma-separated property list → list of property names."""
    if not value:
        return None
    return [p.strip() for p in value.split(",") if p.strip()]


def _list(obj: str, limit: int, properties: list[str] | None) -> dict[str, Any]:
    """List CRM objects of ``obj``, auto-paginating up to ``limit``."""
    results: list[Any] = []
    after: str | None = None
    while True:
        params: dict[str, Any] = {"limit": min(_PAGE_SIZE, limit - len(results))}
        if after:
            params["after"] = after
        if properties:
            params["properties"] = properties
        resp = _request("GET", f"/crm/v3/objects/{obj}", params=params)
        results.extend(resp.get("results") or [])
        paging = (resp.get("paging") or {}).get("next") or {}
        after = paging.get("after")
        if len(results) >= limit:
            return {
                "ok": True,
                obj: results[:limit],
                "count": limit,
                "truncated": bool(after),
            }
        if not after:
            break
    return {"ok": True, obj: results, "count": len(results), "truncated": False}


def _get(obj: str, object_id: str, properties: list[str] | None) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if properties:
        params["properties"] = properties
    resp = _request("GET", f"/crm/v3/objects/{obj}/{object_id}", params=params or None)
    return {"ok": True, obj[:-1]: resp}


def _search(
    obj: str, query: str | None, limit: int, properties: list[str] | None
) -> dict[str, Any]:
    """POST to the search endpoint (a read). ``query`` is HubSpot's free-text
    search term applied across default searchable properties."""
    body: dict[str, Any] = {"limit": min(_PAGE_SIZE, limit)}
    if query:
        body["query"] = query
    if properties:
        body["properties"] = properties
    resp = _request("POST", f"/crm/v3/objects/{obj}/search", body=body)
    results = (resp.get("results") or [])[:limit]
    return {
        "ok": True,
        obj: results,
        "count": len(results),
        "total": resp.get("total"),
    }


def _create(obj: str, properties: dict[str, Any]) -> dict[str, Any]:
    resp = _request("POST", f"/crm/v3/objects/{obj}", body={"properties": properties})
    return {"ok": True, obj[:-1]: resp}


def _update(obj: str, object_id: str, properties: dict[str, Any]) -> dict[str, Any]:
    resp = _request(
        "PATCH",
        f"/crm/v3/objects/{obj}/{object_id}",
        body={"properties": properties},
    )
    return {"ok": True, obj[:-1]: resp}


def _parse_properties(value: str | None) -> dict[str, Any]:
    """Parse a JSON object of CRM properties from ``--properties``."""
    if not value:
        return {}
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("properties must be a JSON object")
    return parsed


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hubspot_api.py", description="HubSpot CRM REST v3 wrapper."
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_obj(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("object", choices=_OBJECTS, help="CRM object type")

    sp = sub.add_parser("list", help="list objects (read)")
    add_obj(sp)
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--properties", help="comma-separated property names to return")

    sp = sub.add_parser("get", help="fetch one object by id (read)")
    add_obj(sp)
    sp.add_argument("id")
    sp.add_argument("--properties", help="comma-separated property names to return")

    sp = sub.add_parser("search", help="search objects (read)")
    add_obj(sp)
    sp.add_argument("--query", help="free-text search term")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--properties", help="comma-separated property names to return")

    sp = sub.add_parser("create", help="create an object (write)")
    add_obj(sp)
    sp.add_argument("--properties", required=True, help="JSON object of properties")

    sp = sub.add_parser("update", help="update an object by id (write)")
    add_obj(sp)
    sp.add_argument("id")
    sp.add_argument("--properties", required=True, help="JSON object of properties")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "list":
        return _list(a.object, a.limit, _properties_arg(a.properties))
    if a.cmd == "get":
        return _get(a.object, a.id, _properties_arg(a.properties))
    if a.cmd == "search":
        return _search(a.object, a.query, a.limit, _properties_arg(a.properties))
    if a.cmd == "create":
        return _create(a.object, _parse_properties(a.properties))
    if a.cmd == "update":
        return _update(a.object, a.id, _parse_properties(a.properties))
    return {"ok": False, "error": f"unknown command {a.cmd!r}"}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except ValueError as e:
        print(f"invalid input: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"invalid JSON: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling HubSpot: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling HubSpot: {e.reason}", file=sys.stderr)
        return 1
    print(json.dumps(result))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
