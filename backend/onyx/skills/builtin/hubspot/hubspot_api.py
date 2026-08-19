#!/usr/bin/env python3
"""HubSpot CRM (REST v3) wrapper for the Onyx Craft sandbox.

Common CRM operations exposed as subcommands. Authentication is handled by
the egress proxy, which injects the connected user's bearer token on the
wire — this script sends no credentials itself. User input is passed as
JSON request bodies / query params (never string-formatted into a URL path
beyond the object id), so there is no injection risk. Output is JSON on
stdout; HTTP failures are surfaced as ``{"ok": false, "status": ..., "error": ...}``.
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
_METHODS = ("GET", "POST", "PATCH", "PUT", "DELETE")

# CRM object types this helper supports (path segment under /crm/v3/objects).
_OBJECTS = ("contacts", "companies", "deals")

# Sensible default properties to fetch per object so output is useful without
# the caller having to enumerate every property name.
_DEFAULT_PROPERTIES: dict[str, list[str]] = {
    "contacts": ["firstname", "lastname", "email", "phone", "company", "jobtitle"],
    "companies": ["name", "domain", "industry", "city", "state", "country"],
    "deals": ["dealname", "amount", "dealstage", "pipeline", "closedate"],
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


def _request(method: str, path: str, body: dict[str, Any] | None = None) -> Any:
    """Make a request to the HubSpot API; return the parsed JSON. Raises on
    transport failure (handled by the caller)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(  # noqa: S310 — fixed https endpoint
        f"{_BASE}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _object_arg(value: str) -> str:
    if value not in _OBJECTS:
        raise argparse.ArgumentTypeError(f"object must be one of {', '.join(_OBJECTS)}")
    return value


def _props(a: argparse.Namespace, obj: str) -> list[str]:
    if getattr(a, "properties", None):
        return [p.strip() for p in a.properties.split(",") if p.strip()]
    return _DEFAULT_PROPERTIES.get(obj, [])


def _properties_from_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse repeated `--set key=value` flags into a HubSpot properties dict."""
    props: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        props[key.strip()] = value
    return props


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hubspot_api.py", description="HubSpot CRM.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="list objects of a type")
    sp.add_argument("object", type=_object_arg, help="contacts|companies|deals")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--properties", help="comma-separated property names")

    sp = sub.add_parser("get", help="fetch one object by id")
    sp.add_argument("object", type=_object_arg)
    sp.add_argument("id")
    sp.add_argument("--properties", help="comma-separated property names")

    sp = sub.add_parser("search", help="free-text search within an object type")
    sp.add_argument("object", type=_object_arg)
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--properties", help="comma-separated property names")

    sp = sub.add_parser("create", help="create an object (write)")
    sp.add_argument("object", type=_object_arg)
    sp.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="key=value",
        help="a property to set (repeatable), e.g. --set email=a@b.co",
    )

    sp = sub.add_parser("update", help="update an object (write)")
    sp.add_argument("object", type=_object_arg)
    sp.add_argument("id")
    sp.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="key=value",
        help="a property to set (repeatable)",
    )

    sp = sub.add_parser("owners", help="list CRM owners")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("call", help="raw request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="path starting with /, e.g. /crm/v3/objects/...")
    sp.add_argument("body", nargs="?", help="optional JSON request body")
    return p


def _paginate(path: str, key: str, properties: list[str], limit: int) -> dict[str, Any]:
    """Walk a HubSpot CRM list (`results` + `paging.next.after`) up to `limit`."""
    results: list[Any] = []
    after: str | None = None
    while True:
        params: dict[str, Any] = {"limit": min(_PAGE_SIZE, limit - len(results))}
        if properties:
            params["properties"] = ",".join(properties)
        if after:
            params["after"] = after
        query = urllib.parse.urlencode(params)
        page = _request("GET", f"{path}?{query}")
        results.extend(page.get("results") or [])
        after = ((page.get("paging") or {}).get("next") or {}).get("after")
        if len(results) >= limit:
            return {
                "ok": True,
                key: results[:limit],
                "count": limit,
                "truncated": bool(after),
            }
        if not after:
            break
    return {"ok": True, key: results, "count": len(results), "truncated": False}


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "list":
        return _paginate(
            f"/crm/v3/objects/{a.object}", a.object, _props(a, a.object), a.limit
        )

    if a.cmd == "get":
        params = {}
        props = _props(a, a.object)
        if props:
            params["properties"] = ",".join(props)
        query = f"?{urllib.parse.urlencode(params)}" if params else ""
        obj_id = urllib.parse.quote(a.id, safe="")
        result = _request("GET", f"/crm/v3/objects/{a.object}/{obj_id}{query}")
        return {"ok": True, a.object: result}

    if a.cmd == "search":
        # Search pages like the list endpoints, but the cursor goes in the POST
        # body rather than the query string.
        props = _props(a, a.object)
        results: list[Any] = []
        after: str | None = None
        total: Any = None
        if a.limit <= 0:
            return {"ok": False, "error": "limit must be a positive integer"}
        while len(results) < a.limit:
            body: dict[str, Any] = {
                "query": a.query,
                "limit": min(_PAGE_SIZE, a.limit - len(results)),
            }
            if props:
                body["properties"] = props
            if after:
                body["after"] = after
            page = _request("POST", f"/crm/v3/objects/{a.object}/search", body)
            results.extend(page.get("results") or [])
            total = page.get("total")
            after = ((page.get("paging") or {}).get("next") or {}).get("after")
            if not after:
                break
        return {
            "ok": True,
            a.object: results[: a.limit],
            "count": min(len(results), a.limit),
            "total": total,
            "truncated": bool(after),
        }

    if a.cmd in ("create", "update"):
        props = _properties_from_pairs(a.set)
        if not props:
            return {"ok": False, "error": "no_properties_given"}
        if a.cmd == "create":
            result = _request(
                "POST", f"/crm/v3/objects/{a.object}", {"properties": props}
            )
        else:
            obj_id = urllib.parse.quote(a.id, safe="")
            result = _request(
                "PATCH",
                f"/crm/v3/objects/{a.object}/{obj_id}",
                {"properties": props},
            )
        return {"ok": True, a.object: result}

    if a.cmd == "owners":
        return _paginate("/crm/v3/owners", "owners", [], a.limit)

    # `call` raw escape hatch
    body = None
    if a.body:
        parsed = json.loads(a.body)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "body must be a JSON object"}
        body = parsed
    result = _request(a.method, a.path, body)
    return {"ok": True, "data": result}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except (json.JSONDecodeError, ValueError) as e:
        print(f"invalid input: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            message = (
                parsed.get("message", detail) if isinstance(parsed, dict) else detail
            )
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
