#!/usr/bin/env python3
"""HubSpot CRM wrapper for the Onyx Craft sandbox.

Common CRM operations (contacts, companies, deals) exposed as subcommands.
Output is JSON on stdout. The Authorization header is injected by the Onyx
egress gateway from the connected user's credentials, so no token handling
happens here.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.hubapi.com"
_DEFAULT_LIMIT = 25
_HTTP_TIMEOUT_SECONDS = 180
_METHODS = ("GET", "POST", "PATCH", "DELETE")
# The CRM object types this helper exposes first-class subcommands for.
_OBJECTS = ("contacts", "companies", "deals")


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
    """URL-encode a single path segment (ids may contain reserved chars)."""
    return urllib.parse.quote(value, safe="")


def _req(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a HubSpot endpoint; return parsed JSON ({} on empty/204).
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
    with urllib.request.urlopen(  # noqa: S310
        req, timeout=_HTTP_TIMEOUT_SECONDS
    ) as resp:
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _properties_arg(value: str | None) -> list[str] | None:
    if not value:
        return None
    return [v.strip() for v in value.split(",") if v.strip()]


def _kv_to_props(pairs: list[str]) -> dict[str, str]:
    """Turn ``name=value`` CLI args into a HubSpot ``properties`` dict."""
    props: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"property must be name=value, got {pair!r}")
        key, val = pair.split("=", 1)
        props[key.strip()] = val
    return props


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hubspot_api.py", description="HubSpot CRM.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="object", required=True)

    # One identical set of verbs per CRM object (contacts / companies / deals).
    for obj in _OBJECTS:
        op = sub.add_parser(obj, help=f"{obj} read/search/create/update")
        verbs = op.add_subparsers(dest="verb", required=True)

        lp = verbs.add_parser("list", help=f"list {obj}")
        lp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
        lp.add_argument("--after", help="pagination cursor")
        lp.add_argument("--properties", help="comma-separated properties to return")

        gp = verbs.add_parser("get", help=f"get one {obj[:-1]} by id")
        gp.add_argument("id")
        gp.add_argument("--properties", help="comma-separated properties to return")

        spp = verbs.add_parser("search", help=f"search {obj} by a property filter")
        spp.add_argument("property", help="property name to filter on")
        spp.add_argument("value", help="value to match")
        spp.add_argument(
            "--operator",
            default="EQ",
            help="filter operator (EQ, CONTAINS_TOKEN, GT, LT, ...)",
        )
        spp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
        spp.add_argument("--properties", help="comma-separated properties to return")

        cp = verbs.add_parser("create", help=f"create a {obj[:-1]} (write)")
        cp.add_argument("props", nargs="+", help="name=value property pairs")

        up = verbs.add_parser("update", help=f"update a {obj[:-1]} (write)")
        up.add_argument("id")
        up.add_argument("props", nargs="+", help="name=value property pairs")

    # Raw escape hatch for any other CRM endpoint.
    cp = sub.add_parser("call", help="raw HubSpot request")
    cp.add_argument("method", choices=_METHODS)
    cp.add_argument("path", help="path under https://api.hubapi.com")
    cp.add_argument("json_body", nargs="?")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.object == "call":
        body = None
        if a.json_body:
            body = json.loads(a.json_body)
            if not isinstance(body, dict):
                return {"ok": False, "error": "json_body_not_object"}
        path = a.path if a.path.startswith("/") else "/" + a.path
        resp = _req(a.method, path, body=body)
        return {"ok": True, "data": resp}

    base = f"/crm/v3/objects/{a.object}"

    if a.verb == "list":
        params: dict[str, Any] = {"limit": a.limit, "after": a.after}
        if props := _properties_arg(a.properties):
            params["properties"] = props
        resp = _req("GET", base, params=params)
        return {
            "ok": True,
            "items": resp.get("results") or [],
            "count": len(resp.get("results") or []),
            "paging": resp.get("paging"),
        }

    if a.verb == "get":
        params = {}
        if props := _properties_arg(a.properties):
            params["properties"] = props
        resp = _req("GET", f"{base}/{_seg(a.id)}", params=params or None)
        return {"ok": True, "result": resp}

    if a.verb == "search":
        body: dict[str, Any] = {
            "filterGroups": [
                {
                    "filters": [
                        {
                            "propertyName": a.property,
                            "operator": a.operator,
                            "value": a.value,
                        }
                    ]
                }
            ],
            "limit": a.limit,
        }
        if props := _properties_arg(a.properties):
            body["properties"] = props
        resp = _req("POST", f"{base}/search", body=body)
        return {
            "ok": True,
            "items": resp.get("results") or [],
            "count": resp.get("total", len(resp.get("results") or [])),
            "paging": resp.get("paging"),
        }

    if a.verb == "create":
        resp = _req("POST", base, body={"properties": _kv_to_props(a.props)})
        return {"ok": True, "result": resp}

    if a.verb == "update":
        resp = _req(
            "PATCH",
            f"{base}/{_seg(a.id)}",
            body={"properties": _kv_to_props(a.props)},
        )
        return {"ok": True, "result": resp}

    return {"ok": False, "error": f"unknown_verb:{a.verb}"}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except ValueError as e:
        print(f"invalid argument: {e}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as e:
        print(f"invalid json_body: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling HubSpot: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling HubSpot: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
