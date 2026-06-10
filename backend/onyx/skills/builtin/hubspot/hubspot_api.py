#!/usr/bin/env python3
"""HubSpot CRM API wrapper for the Onyx Craft sandbox.

Common HubSpot CRM operations exposed as subcommands. The connected user's token
is injected by the egress gateway, so this script sends no credentials itself.
Output is JSON on stdout; HubSpot signals failure with a non-2xx status and a
``{"message": ..., "category": ...}`` body, surfaced here as ``{"ok": false, ...}``.
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

# Default properties to request per object type so list/get output is useful
# without the caller naming columns (HubSpot otherwise returns only a few).
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


def _request(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Issue a request to the HubSpot CRM API; return parsed JSON ({} on 204).
    Raises urllib errors on transport / non-2xx failure (handled by caller)."""
    url = _BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        if clean:
            url += "?" + urllib.parse.urlencode(clean, doseq=True)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json"} if data is not None else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _paginate_list(path: str, params: dict[str, Any], limit: int) -> dict[str, Any]:
    """Page through a CRM list endpoint (`results` + `paging.next.after`) up to
    `limit`."""
    results: list[Any] = []
    after: str | None = None
    while len(results) < limit:
        q = dict(params, limit=min(_PAGE_SIZE, limit - len(results)))
        if after:
            q["after"] = after
        parsed = _request("GET", path, params=q)
        results.extend(parsed.get("results") or [])
        after = ((parsed.get("paging") or {}).get("next") or {}).get("after")
        if not after:
            break
    return {
        "ok": True,
        "results": results[:limit],
        "count": min(len(results), limit),
        "truncated": bool(after),
    }


def _object_properties(object_type: str, override: str | None) -> list[str]:
    if override:
        return [p.strip() for p in override.split(",") if p.strip()]
    return _DEFAULT_PROPERTIES.get(object_type, [])


def _properties_from_pairs(pairs: list[str]) -> dict[str, str]:
    """Parse repeated `key=value` flags into a HubSpot properties dict."""
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
    p = argparse.ArgumentParser(prog="hubspot_api.py", description="HubSpot CRM API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def list_parser(name: str, help_text: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
        sp.add_argument("--properties", help="comma-separated property names")
        return sp

    def get_parser(name: str, help_text: str, id_name: str) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text)
        sp.add_argument(id_name)
        sp.add_argument("--properties", help="comma-separated property names")
        return sp

    list_parser("contacts", "list contacts")
    get_parser("contact", "one contact by id", "contact_id")
    list_parser("companies", "list companies")
    get_parser("company", "one company by id", "company_id")
    list_parser("deals", "list deals")
    get_parser("deal", "one deal by id", "deal_id")

    sp = sub.add_parser("owners", help="list CRM owners (users)")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("search", help="search an object by free-text query or filters")
    sp.add_argument("object", choices=["contacts", "companies", "deals"])
    sp.add_argument("query", help="free-text search query")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--properties", help="comma-separated property names")

    sp = sub.add_parser("create-contact", help="create a contact (write)")
    sp.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="key=value",
        help="a property to set (repeatable), e.g. --set email=a@b.com",
    )

    sp = sub.add_parser("update-contact", help="edit a contact (write)")
    sp.add_argument("contact_id")
    sp.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="key=value",
        help="a property to set (repeatable)",
    )

    sp = sub.add_parser("create-company", help="create a company (write)")
    sp.add_argument(
        "--set", action="append", default=[], metavar="key=value", help="a property"
    )

    sp = sub.add_parser("create-deal", help="create a deal (write)")
    sp.add_argument(
        "--set", action="append", default=[], metavar="key=value", help="a property"
    )

    sp = sub.add_parser("call", help="raw HubSpot request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="path under https://api.hubapi.com, e.g. /crm/v3/...")
    sp.add_argument("json_body", nargs="?")
    return p


def _list(object_type: str, a: argparse.Namespace) -> dict[str, Any]:
    props = _object_properties(object_type, a.properties)
    return _paginate_list(
        f"/crm/v3/objects/{object_type}",
        {"properties": props or None},
        a.limit,
    )


def _get(object_type: str, obj_id: str, a: argparse.Namespace) -> dict[str, Any]:
    props = _object_properties(object_type, a.properties)
    parsed = _request(
        "GET",
        f"/crm/v3/objects/{object_type}/{urllib.parse.quote(obj_id, safe='')}",
        params={"properties": props or None},
    )
    return {"ok": True, object_type[:-1]: parsed}


def _create(object_type: str, pairs: list[str], key: str) -> dict[str, Any]:
    props = _properties_from_pairs(pairs)
    if not props:
        return {"ok": False, "error": "no_properties_given"}
    parsed = _request(
        "POST", f"/crm/v3/objects/{object_type}", body={"properties": props}
    )
    return {"ok": True, key: parsed}


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "contacts":
        return _list("contacts", a)
    if a.cmd == "contact":
        return _get("contacts", a.contact_id, a)
    if a.cmd == "companies":
        return _list("companies", a)
    if a.cmd == "company":
        return _get("companies", a.company_id, a)
    if a.cmd == "deals":
        return _list("deals", a)
    if a.cmd == "deal":
        return _get("deals", a.deal_id, a)

    if a.cmd == "owners":
        return _paginate_list("/crm/v3/owners", {}, a.limit)

    if a.cmd == "search":
        props = _object_properties(a.object, a.properties)
        body: dict[str, Any] = {"query": a.query, "limit": min(_PAGE_SIZE, a.limit)}
        if props:
            body["properties"] = props
        parsed = _request("POST", f"/crm/v3/objects/{a.object}/search", body=body)
        results = parsed.get("results") or []
        return {
            "ok": True,
            "results": results[: a.limit],
            "count": min(len(results), a.limit),
            "total": parsed.get("total"),
        }

    if a.cmd == "create-contact":
        return _create("contacts", a.set, "contact")
    if a.cmd == "update-contact":
        props = _properties_from_pairs(a.set)
        if not props:
            return {"ok": False, "error": "no_properties_given"}
        cid = urllib.parse.quote(a.contact_id, safe="")
        parsed = _request(
            "PATCH", f"/crm/v3/objects/contacts/{cid}", body={"properties": props}
        )
        return {"ok": True, "contact": parsed}
    if a.cmd == "create-company":
        return _create("companies", a.set, "company")
    if a.cmd == "create-deal":
        return _create("deals", a.set, "deal")

    # `call` raw escape hatch
    body = None
    if a.json_body:
        body = json.loads(a.json_body)
        if not isinstance(body, dict):
            return {"ok": False, "error": "json_body_not_object"}
    parsed = _request(a.method, "/" + a.path.lstrip("/"), body=body)
    return {"ok": True, "data": parsed}


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
