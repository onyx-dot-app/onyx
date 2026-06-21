#!/usr/bin/env python3
"""HubSpot (CRM v3) wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. Output is JSON on stdout. No auth is
handled here: the sandbox egress proxy injects the connected user's bearer
token on the wire. Writes (create/update) may pause for user approval at the
proxy.
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
        clean = {k: v for k, v in params.items() if v is not None}
        url += "?" + urllib.parse.urlencode(clean, doseq=True)
    return url


def _req_json(
    path: str,
    params: dict[str, Any] | None = None,
    method: str = "GET",
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a HubSpot JSON endpoint; return parsed JSON ({} on empty/204)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        _url(path, params), data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _paginate(
    path: str, params: dict[str, Any], limit: int
) -> dict[str, Any]:
    """Walk a HubSpot list endpoint (`results` + `paging.next.after`) up to
    `limit`."""
    items: list[Any] = []
    after: str | None = None
    while True:
        q = dict(params, limit=min(_PAGE_SIZE, limit - len(items)))
        if after:
            q["after"] = after
        resp = _req_json(path, params=q)
        items.extend(resp.get("results") or [])
        after = ((resp.get("paging") or {}).get("next") or {}).get("after")
        if len(items) >= limit:
            return {
                "ok": True,
                "results": items[:limit],
                "count": limit,
                "truncated": bool(after),
            }
        if not after:
            break
    return {"ok": True, "results": items, "count": len(items), "truncated": False}


def _properties(pairs: list[str] | None) -> dict[str, str]:
    """Parse repeated ``key=value`` flags into a HubSpot properties dict."""
    props: dict[str, str] = {}
    for pair in pairs or []:
        key, sep, val = pair.partition("=")
        if not sep:
            raise ValueError(f"property must be key=value, got {pair!r}")
        props[key] = val
    return props


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="hubspot_api.py", description="HubSpot CRM.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
        sp.add_argument(
            "--properties",
            help="comma-separated property names to return",
        )

    sub.add_parser("me", help="the connected HubSpot account")

    with_limit(sub.add_parser("contacts", help="list contacts"))

    sp = sub.add_parser("contact", help="one contact by id")
    sp.add_argument("contact_id")
    sp.add_argument("--properties", help="comma-separated property names to return")

    with_limit(sub.add_parser("companies", help="list companies"))

    sp = sub.add_parser("company", help="one company by id")
    sp.add_argument("company_id")
    sp.add_argument("--properties", help="comma-separated property names to return")

    with_limit(sub.add_parser("deals", help="list deals"))

    sp = sub.add_parser("deal", help="one deal by id")
    sp.add_argument("deal_id")
    sp.add_argument("--properties", help="comma-separated property names to return")

    sp = sub.add_parser("search-contacts", help="full-text contact search")
    sp.add_argument("query")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    # --- writes (may prompt for approval) ---
    sp = sub.add_parser("create-contact", help="create a contact (write)")
    sp.add_argument(
        "--property",
        dest="props",
        action="append",
        metavar="KEY=VALUE",
        help="contact property (repeatable), e.g. --property email=a@b.com",
    )

    sp = sub.add_parser("update-contact", help="update a contact (write)")
    sp.add_argument("contact_id")
    sp.add_argument(
        "--property",
        dest="props",
        action="append",
        metavar="KEY=VALUE",
        help="contact property to set (repeatable)",
    )

    sp = sub.add_parser("call", help="raw HubSpot request")
    sp.add_argument("method", choices=("GET", "POST", "PATCH", "PUT", "DELETE"))
    sp.add_argument("path", help="appended to https://api.hubapi.com")
    sp.add_argument("json_body", nargs="?", help="JSON object for the request body")
    return p


def _list_params(a: argparse.Namespace) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if getattr(a, "properties", None):
        params["properties"] = a.properties
    return params


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "me":
        return {"ok": True, "account": _req_json("/account-info/v3/details")}

    if a.cmd == "contacts":
        return _paginate("/crm/v3/objects/contacts", _list_params(a), a.limit)

    if a.cmd == "contact":
        obj = _req_json(
            f"/crm/v3/objects/contacts/{_seg(a.contact_id)}", _list_params(a)
        )
        return {"ok": True, "contact": obj}

    if a.cmd == "companies":
        return _paginate("/crm/v3/objects/companies", _list_params(a), a.limit)

    if a.cmd == "company":
        obj = _req_json(
            f"/crm/v3/objects/companies/{_seg(a.company_id)}", _list_params(a)
        )
        return {"ok": True, "company": obj}

    if a.cmd == "deals":
        return _paginate("/crm/v3/objects/deals", _list_params(a), a.limit)

    if a.cmd == "deal":
        obj = _req_json(f"/crm/v3/objects/deals/{_seg(a.deal_id)}", _list_params(a))
        return {"ok": True, "deal": obj}

    if a.cmd == "search-contacts":
        body = {"query": a.query, "limit": min(_PAGE_SIZE, a.limit)}
        resp = _req_json(
            "/crm/v3/objects/contacts/search", method="POST", body=body
        )
        results = resp.get("results") or []
        return {
            "ok": True,
            "results": results[: a.limit],
            "count": min(len(results), a.limit),
            "total": resp.get("total"),
        }

    if a.cmd == "create-contact":
        contact = _req_json(
            "/crm/v3/objects/contacts",
            method="POST",
            body={"properties": _properties(a.props)},
        )
        return {"ok": True, "contact": contact}

    if a.cmd == "update-contact":
        contact = _req_json(
            f"/crm/v3/objects/contacts/{_seg(a.contact_id)}",
            method="PATCH",
            body={"properties": _properties(a.props)},
        )
        return {"ok": True, "contact": contact}

    # `call` raw escape hatch
    parsed_body = None
    if a.json_body:
        parsed_body = json.loads(a.json_body)
        if not isinstance(parsed_body, dict):
            return {"ok": False, "error": "json_body_not_object"}
    resp = _req_json("/" + a.path.lstrip("/"), method=a.method, body=parsed_body)
    return {"ok": True, "data": resp}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
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
