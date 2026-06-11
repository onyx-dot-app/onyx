#!/usr/bin/env python3
"""HubSpot CRM wrapper for the Onyx Craft sandbox.

Common CRM operations exposed as subcommands. Output is JSON on stdout. No auth
is handled here: the sandbox egress proxy injects the connected user's bearer
token on the wire. Writes (create/update/archive) may pause for user approval at
the proxy.

User input is passed as query params or JSON request bodies (never
string-formatted into a query language), so there is no injection risk.
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

# The core CRM object types Craft works with by default. HubSpot also accepts
# any custom object type here; these are just the well-known, validated names.
_KNOWN_OBJECT_TYPES = ("contacts", "companies", "deals", "tickets")

# Sensible default properties to pull back per object type, so list/search
# output identifies a record without HubSpot's full property blob.
_DEFAULT_PROPERTIES: dict[str, list[str]] = {
    "contacts": ["firstname", "lastname", "email", "company", "phone"],
    "companies": ["name", "domain", "industry", "city", "country"],
    "deals": ["dealname", "amount", "dealstage", "pipeline", "closedate"],
    "tickets": ["subject", "content", "hs_pipeline_stage", "hs_ticket_priority"],
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
    """URL-encode a single path segment (ids may contain special chars)."""
    return urllib.parse.quote(value, safe="")


def _url(path: str, params: dict[str, Any] | None = None) -> str:
    url = _BASE + path
    if params:
        pairs: list[tuple[str, str]] = []
        for key, val in params.items():
            if val is None:
                continue
            # Repeat the key for list-valued params (HubSpot wants
            # `?properties=a&properties=b`).
            if isinstance(val, (list, tuple)):
                pairs.extend((key, str(v)) for v in val)
            else:
                pairs.append((key, str(val)))
        if pairs:
            url += "?" + urllib.parse.urlencode(pairs)
    return url


def _request(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    """Make an HTTP request and return parsed JSON (or {} for an empty body).
    Raises urllib errors, handled by the caller."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(  # noqa: S310 — fixed https host (api.hubapi.com)
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(
        req, timeout=_HTTP_TIMEOUT_SECONDS
    ) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _properties_for(object_type: str, override: str | None) -> list[str] | None:
    if override:
        return [p.strip() for p in override.split(",") if p.strip()]
    return _DEFAULT_PROPERTIES.get(object_type)


def _cmd_list(a: argparse.Namespace) -> dict[str, Any]:
    """Page through an object type up to --limit records."""
    results: list[Any] = []
    after: str | None = None
    props = _properties_for(a.object_type, a.properties)
    while True:
        params: dict[str, Any] = {
            "limit": min(_PAGE_SIZE, a.limit - len(results)),
            "properties": props,
            "archived": "true" if a.archived else None,
        }
        if after:
            params["after"] = after
        resp = _request("GET", _url(f"/crm/v3/objects/{_seg(a.object_type)}", params))
        results.extend(resp.get("results") or [])
        after = (((resp.get("paging") or {}).get("next")) or {}).get("after")
        if len(results) >= a.limit or not after:
            break
    truncated = bool(after) and len(results) >= a.limit
    return {
        "ok": True,
        "results": results[: a.limit],
        "count": min(len(results), a.limit),
        "truncated": truncated,
    }


def _cmd_get(a: argparse.Namespace) -> dict[str, Any]:
    props = _properties_for(a.object_type, a.properties)
    url = _url(
        f"/crm/v3/objects/{_seg(a.object_type)}/{_seg(a.id)}",
        {"properties": props, "associations": a.associations},
    )
    return {"ok": True, "result": _request("GET", url)}


def _cmd_search(a: argparse.Namespace) -> dict[str, Any]:
    props = _properties_for(a.object_type, a.properties)
    body: dict[str, Any] = {"limit": min(a.limit, _PAGE_SIZE)}
    if props:
        body["properties"] = props
    if a.query:
        body["query"] = a.query
    if a.filter:
        # One simple `property OP value` filter, e.g. `email EQ a@b.com`.
        prop, op, value = a.filter.split(" ", 2)
        body["filterGroups"] = [
            {"filters": [{"propertyName": prop, "operator": op, "value": value}]}
        ]
    resp = _request("POST", _url(f"/crm/v3/objects/{_seg(a.object_type)}/search"), body)
    results = resp.get("results") or []
    return {
        "ok": True,
        "results": results,
        "count": len(results),
        "total": resp.get("total"),
    }


def _parse_properties_kv(pairs: list[str]) -> dict[str, str]:
    """Turn `name=value` CLI args into a HubSpot properties dict."""
    out: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"property must be name=value: {pair!r}")
        key, value = pair.split("=", 1)
        out[key] = value
    return out


def _cmd_create(a: argparse.Namespace) -> dict[str, Any]:
    body = {"properties": _parse_properties_kv(a.set)}
    resp = _request("POST", _url(f"/crm/v3/objects/{_seg(a.object_type)}"), body)
    return {"ok": True, "result": resp}


def _cmd_update(a: argparse.Namespace) -> dict[str, Any]:
    body = {"properties": _parse_properties_kv(a.set)}
    resp = _request(
        "PATCH",
        _url(f"/crm/v3/objects/{_seg(a.object_type)}/{_seg(a.id)}"),
        body,
    )
    return {"ok": True, "result": resp}


def _cmd_archive(a: argparse.Namespace) -> dict[str, Any]:
    _request("DELETE", _url(f"/crm/v3/objects/{_seg(a.object_type)}/{_seg(a.id)}"))
    return {"ok": True, "archived": {"object_type": a.object_type, "id": a.id}}


def _cmd_properties(a: argparse.Namespace) -> dict[str, Any]:
    resp = _request("GET", _url(f"/crm/v3/properties/{_seg(a.object_type)}"))
    results = resp.get("results") or []
    # Trim to the fields an agent needs to choose/inspect a property.
    slim = [
        {
            "name": p.get("name"),
            "label": p.get("label"),
            "type": p.get("type"),
            "fieldType": p.get("fieldType"),
        }
        for p in results
    ]
    return {"ok": True, "results": slim, "count": len(slim)}


def _cmd_owners(a: argparse.Namespace) -> dict[str, Any]:
    resp = _request("GET", _url("/crm/v3/owners", {"limit": a.limit}))
    results = resp.get("results") or []
    return {"ok": True, "results": results, "count": len(results)}


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hubspot_api.py", description="HubSpot CRM.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def obj(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "object_type",
            help="CRM object type, e.g. " + ", ".join(_KNOWN_OBJECT_TYPES),
        )

    def props(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--properties",
            help="comma-separated property names (defaults are object-aware)",
        )

    sp = sub.add_parser("list", help="list records of an object type")
    obj(sp)
    props(sp)
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--archived", action="store_true", help="list archived records")

    sp = sub.add_parser("get", help="fetch one record by id")
    obj(sp)
    sp.add_argument("id")
    props(sp)
    sp.add_argument(
        "--associations", help="comma-separated assoc. object types to include"
    )

    sp = sub.add_parser("search", help="search/filter records")
    obj(sp)
    props(sp)
    sp.add_argument("--query", help="full-text query string")
    sp.add_argument(
        "--filter",
        help="single filter: 'property OPERATOR value', e.g. 'email EQ a@b.com'",
    )
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("create", help="create a record (write)")
    obj(sp)
    sp.add_argument("set", nargs="+", help="property assignments: name=value ...")

    sp = sub.add_parser("update", help="update a record (write)")
    obj(sp)
    sp.add_argument("id")
    sp.add_argument("set", nargs="+", help="property assignments: name=value ...")

    sp = sub.add_parser("archive", help="archive (soft-delete) a record (write)")
    obj(sp)
    sp.add_argument("id")

    sp = sub.add_parser("properties", help="list an object type's properties")
    obj(sp)

    sp = sub.add_parser("owners", help="list account owners (users)")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    return p


_DISPATCH = {
    "list": _cmd_list,
    "get": _cmd_get,
    "search": _cmd_search,
    "create": _cmd_create,
    "update": _cmd_update,
    "archive": _cmd_archive,
    "properties": _cmd_properties,
    "owners": _cmd_owners,
}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _DISPATCH[a.cmd](a)
    except ValueError as e:
        print(f"invalid input: {e}", file=sys.stderr)
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
