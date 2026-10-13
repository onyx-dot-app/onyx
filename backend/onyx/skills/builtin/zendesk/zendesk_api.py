#!/usr/bin/env python3
"""Zendesk Support (REST API v2) wrapper for the Onyx Craft sandbox.

Common ticket operations as subcommands. Authentication is handled by the
egress proxy, which injects the connected user's bearer token on the wire —
this script sends no credentials itself. User input rides as query params or
JSON request bodies (ids are percent-encoded into the path, nothing else is),
so there is no injection risk. Output is JSON on stdout; HTTP failures are
surfaced as ``{"ok": false, "status": ..., "error": ...}``.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

_HTTP_TIMEOUT_SECONDS = 180
_DEFAULT_LIMIT = 100
_PAGE_SIZE = 100
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")

# Zendesk's own limit: a search returns at most 1000 results over 10 pages.
_SEARCH_RESULT_CAP = 1000
# Field definitions are a small fixed set; fetch them all rather than page.
_FIELDS_LIMIT = 200
# A hard stop on any paged walk. Zendesk can serve an empty page that still
# carries a next link, which would otherwise loop forever on a `--limit` the
# results never reach.
_MAX_PAGES = 50

# A DNS label, matched with `fullmatch`. This script runs inside the sandbox
# with no Onyx imports, so it repeats the provider's check rather than
# sharing it (`external_apps/providers/zendesk.py:normalise_subdomain`).
_SUBDOMAIN_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?")

# Fields worth keeping off a ticket payload; Zendesk returns ~40 per ticket and
# the rest are nulls and internal ids.
_TICKET_FIELDS = (
    "id",
    "subject",
    "description",
    "status",
    "priority",
    "type",
    "tags",
    "created_at",
    "updated_at",
    "requester_id",
    "assignee_id",
    "organization_id",
    "group_id",
    "via",
    "satisfaction_rating",
    "custom_fields",
    "url",
)


class ZendeskError(Exception):
    """A request this script refuses to make (bad arguments, unusable site)."""


def _epoch_seconds(value: str) -> int:
    """``--since`` as the unix timestamp the incremental export requires. Takes
    an epoch value already, or an ISO-8601 instant (which the agent is far more
    likely to have to hand). A naive instant is read as UTC."""
    text = value.strip()
    if text.isdigit():
        return int(text)
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        raise ZendeskError(
            f"--since must be a unix timestamp or an ISO-8601 instant, got {value!r}"
        ) from None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return int(moment.timestamp())


def _site_base_url(value: str) -> str:
    """The API base URL for ``--site``, which accepts either a bare subdomain
    (``acme``) or the account URL (``https://acme.zendesk.com``). Anything that
    is not a single Zendesk subdomain is rejected: the proxy only injects this
    account's token for this account's host."""
    host = re.sub(r"^https?://", "", value.strip().lower())
    host = re.split(r"[/?#]", host, maxsplit=1)[0]
    subdomain = host.partition(":")[0].removesuffix(".zendesk.com")
    if not _SUBDOMAIN_RE.fullmatch(subdomain):
        raise argparse.ArgumentTypeError(
            f"--site must be a Zendesk subdomain or account URL, got {value!r}"
        )
    return f"https://{subdomain}.zendesk.com"


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays small.
    Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _slim(ticket: Any, full: bool) -> Any:
    """A ticket cut down to the fields worth reading, unless ``--full``."""
    if full or not isinstance(ticket, dict):
        return ticket
    return {key: ticket[key] for key in _TICKET_FIELDS if key in ticket}


def _slim_result(result: Any, full: bool) -> Any:
    """One search hit. Search spans tickets, users and organizations, so only a
    ticket may be cut down to the ticket field list — slimming a user would
    drop the very `name` and `email` the agent searched for. `result_type` is
    kept either way: it is what tells a mixed result set apart."""
    if not isinstance(result, dict):
        return result
    result_type = result.get("result_type")
    if result_type not in (None, "ticket"):
        return result
    slimmed = _slim(result, full)
    if result_type is not None and isinstance(slimmed, dict):
        slimmed["result_type"] = result_type
    return slimmed


def _request(
    base_url: str, method: str, path: str, body: dict[str, Any] | None = None
) -> Any:
    """Make one Zendesk API request and return the parsed JSON body. Transport
    and HTTP errors propagate to ``main``."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(  # noqa: S310 — https base URL validated above
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw else {}


def _path(template: str, *ids: str) -> str:
    """A path with each id percent-encoded into one segment."""
    return template.format(*(urllib.parse.quote(str(i), safe="") for i in ids))


def _query(params: dict[str, Any]) -> str:
    usable = {k: v for k, v in params.items() if v is not None}
    return f"?{urllib.parse.urlencode(usable)}" if usable else ""


def _paginate(
    base_url: str, path: str, key: str, limit: int, params: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Walk a Zendesk collection up to ``limit`` records, following whichever
    paging shape the endpoint uses (see ``_next_page_url``). ``per_page`` is the
    one size parameter all of them honour.

    Truncates mid-page at ``limit``, which suits a browsing read. The
    incremental export cannot work that way — it has ``_incremental_tickets``,
    which stops on a page boundary so its cursor stays safe to resume from."""
    if limit <= 0:
        raise ZendeskError("limit must be a positive integer")
    results: list[Any] = []
    page_params = dict(params or {})
    page_params["per_page"] = min(_PAGE_SIZE, limit)
    url: str | None = f"{base_url}{path}{_query(page_params)}"
    for _ in range(_MAX_PAGES):
        if url is None or len(results) >= limit:
            break
        page = _request(base_url, "GET", url[len(base_url) :])
        records = page.get(key) or []
        if not isinstance(records, list):
            raise ZendeskError(f"expected a list under {key!r} in the response")
        results.extend(records)
        url = _next_page_url(page, base_url)
    return {
        "ok": True,
        key: results[:limit],
        "count": min(len(results), limit),
        "truncated": bool(url) or len(results) > limit,
    }


def _next_page_url(page: dict[str, Any], base_url: str) -> str | None:
    """The next page's URL, or ``None`` at the end of the collection. A link
    pointing anywhere but this account is not ours to follow."""
    if page.get("end_of_stream") is True:
        return None
    if (page.get("meta") or {}).get("has_more") is False:
        return None
    candidate = (
        page.get("next_page")
        or page.get("after_url")
        or (page.get("links") or {}).get("next")
    )
    if not isinstance(candidate, str) or not candidate.startswith(f"{base_url}/"):
        return None
    return candidate


def _incremental_tickets(base_url: str, a: argparse.Namespace) -> dict[str, Any]:
    """The cursor incremental export: the one endpoint built for "what moved
    since last run", which is how a scheduled task should poll.

    Stops only on a page boundary, so the ``cursor`` it returns is always a
    safe place to resume from: every ticket before it is in this result and
    none after it is. ``--limit`` is therefore a floor rounded up to the next
    page, not a hard cap."""
    if a.limit <= 0:
        raise ZendeskError("limit must be a positive integer")
    if (a.since is None) == (a.cursor is None):
        raise ZendeskError("pass exactly one of --since or --cursor")

    params: dict[str, Any] = (
        {"cursor": a.cursor} if a.cursor else {"start_time": _epoch_seconds(a.since)}
    )
    params["per_page"] = min(_PAGE_SIZE, a.limit)
    url: str | None = (
        f"{base_url}/api/v2/incremental/tickets/cursor.json{_query(params)}"
    )

    tickets: list[Any] = []
    cursor: str | None = a.cursor
    end_of_stream = False
    for _ in range(_MAX_PAGES):
        if url is None:
            break
        page = _request(base_url, "GET", url[len(base_url) :])
        tickets.extend(page.get("tickets") or [])
        after_cursor = page.get("after_cursor")
        if isinstance(after_cursor, str):
            cursor = after_cursor
        end_of_stream = page.get("end_of_stream") is True
        # Stop only after consuming a page, never mid-page: the cursor has
        # already moved past every ticket this page carried.
        url = None if len(tickets) >= a.limit else _next_page_url(page, base_url)

    return {
        "ok": True,
        "tickets": [_slim(ticket, a.full) for ticket in tickets],
        "count": len(tickets),
        "cursor": cursor,
        "end_of_stream": end_of_stream,
    }


def _pairs(pairs: list[str]) -> dict[str, Any]:
    """Parse repeated ``--set key=value`` flags into a field dict. Values that
    parse as JSON (numbers, booleans, arrays) keep that type."""
    fields: dict[str, Any] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ZendeskError(f"expected key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        try:
            fields[key.strip()] = json.loads(value)
        except ValueError:
            fields[key.strip()] = value
    return fields


def _tags(value: str | None) -> list[str]:
    return [tag.strip() for tag in (value or "").split(",") if tag.strip()]


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="zendesk_api.py", description="Zendesk Support.")
    p.add_argument(
        "--site",
        required=True,
        type=_site_base_url,
        help="Zendesk subdomain or account URL, e.g. acme",
    )
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    p.add_argument(
        "--full",
        action="store_true",
        help="keep every ticket field instead of the readable subset",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("search", help="search with Zendesk query syntax")
    sp.add_argument("query", help='e.g. "type:ticket status:open tags:billing"')
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--sort-by", dest="sort_by", help="e.g. created_at, updated_at")
    sp.add_argument("--sort-order", dest="sort_order", choices=("asc", "desc"))

    sp = sub.add_parser("ticket", help="fetch one ticket")
    sp.add_argument("id")

    sp = sub.add_parser("comments", help="list a ticket's comments")
    sp.add_argument("id")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("metrics", help="reply/resolution times for one ticket")
    sp.add_argument("id")

    sp = sub.add_parser(
        "changed", help="tickets changed since a time (incremental export)"
    )
    sp.add_argument(
        "--since",
        help="unix timestamp or ISO-8601 instant, e.g. 2026-10-01T00:00:00Z",
    )
    sp.add_argument(
        "--cursor",
        help="resume from the `cursor` a previous run returned",
    )
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("views", help="list views")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("view-tickets", help="tickets in a view")
    sp.add_argument("id")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("satisfaction", help="list satisfaction (CSAT) ratings")
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)
    sp.add_argument("--score", help="e.g. good, bad, received")

    sp = sub.add_parser("user", help="fetch one user ('me' for the connected user)")
    sp.add_argument("id")

    sp = sub.add_parser("organization", help="fetch one organization")
    sp.add_argument("id")

    sub.add_parser("fields", help="list ticket field definitions")

    sp = sub.add_parser("create", help="open a ticket (write)")
    sp.add_argument("--subject", required=True)
    sp.add_argument("--body", required=True, help="the first comment")
    sp.add_argument("--requester-email", dest="requester_email")
    sp.add_argument("--tags", help="comma-separated")
    sp.add_argument("--set", action="append", default=[], metavar="key=value")

    sp = sub.add_parser("update", help="change a ticket's fields (write)")
    sp.add_argument("id")
    sp.add_argument("--set", action="append", default=[], metavar="key=value")

    sp = sub.add_parser("comment", help="add a comment to a ticket (write)")
    sp.add_argument("id")
    sp.add_argument("--body", required=True)
    sp.add_argument(
        "--public",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="public reply to the requester; default is an internal note",
    )

    sp = sub.add_parser("tag", help="add or replace a ticket's tags (write)")
    sp.add_argument("id")
    sp.add_argument("--tags", required=True, help="comma-separated")
    sp.add_argument(
        "--replace", action="store_true", help="replace the tags instead of adding"
    )

    sp = sub.add_parser("call", help="raw request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="path starting with /api/v2/")
    sp.add_argument("body", nargs="?", help="optional JSON request body")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    """Run the chosen subcommand. Reads and writes are split so each half stays
    a flat lookup; an unknown command cannot reach here (argparse rejects it)."""
    result = _dispatch_read(a)
    return result if result is not None else _dispatch_write(a)


def _dispatch_read(a: argparse.Namespace) -> dict[str, Any] | None:
    """The read subcommands, or ``None`` when ``a.cmd`` is not one of them."""
    site: str = a.site

    if a.cmd == "search":
        if a.limit <= 0:
            raise ZendeskError("limit must be a positive integer")
        limit = min(a.limit, _SEARCH_RESULT_CAP)
        params = {
            "query": a.query,
            "sort_by": a.sort_by,
            "sort_order": a.sort_order,
        }
        result = _paginate(site, "/api/v2/search.json", "results", limit, params)
        result["results"] = [_slim_result(r, a.full) for r in result["results"]]
        return result

    if a.cmd == "ticket":
        path = _path("/api/v2/tickets/{0}.json", a.id)
        ticket = _request(site, "GET", path).get("ticket")
        return {"ok": True, "ticket": _slim(ticket, a.full)}

    if a.cmd == "comments":
        path = _path("/api/v2/tickets/{0}/comments.json", a.id)
        return _paginate(site, path, "comments", a.limit)

    if a.cmd == "metrics":
        path = _path("/api/v2/tickets/{0}/metrics.json", a.id)
        metric = _request(site, "GET", path).get("ticket_metric")
        return {"ok": True, "ticket_metric": metric}

    if a.cmd == "changed":
        return _incremental_tickets(site, a)

    if a.cmd == "views":
        return _paginate(site, "/api/v2/views.json", "views", a.limit)

    if a.cmd == "view-tickets":
        path = _path("/api/v2/views/{0}/tickets.json", a.id)
        result = _paginate(site, path, "tickets", a.limit)
        result["tickets"] = [_slim(t, a.full) for t in result["tickets"]]
        return result

    if a.cmd == "satisfaction":
        params = {"score": a.score}
        return _paginate(
            site,
            "/api/v2/satisfaction_ratings.json",
            "satisfaction_ratings",
            a.limit,
            params,
        )

    if a.cmd == "user":
        path = _path("/api/v2/users/{0}.json", a.id)
        return {"ok": True, "user": _request(site, "GET", path).get("user")}

    if a.cmd == "organization":
        path = _path("/api/v2/organizations/{0}.json", a.id)
        return {
            "ok": True,
            "organization": _request(site, "GET", path).get("organization"),
        }

    if a.cmd == "fields":
        return _paginate(
            site, "/api/v2/ticket_fields.json", "ticket_fields", _FIELDS_LIMIT
        )

    return None


def _dispatch_write(a: argparse.Namespace) -> dict[str, Any]:
    """The write subcommands plus the `call` escape hatch."""
    site: str = a.site

    if a.cmd == "create":
        ticket: dict[str, Any] = {
            "subject": a.subject,
            "comment": {"body": a.body},
            **_pairs(a.set),
        }
        if a.requester_email:
            ticket["requester"] = {"email": a.requester_email}
        if a.tags:
            ticket["tags"] = _tags(a.tags)
        created = _request(site, "POST", "/api/v2/tickets.json", {"ticket": ticket})
        return {"ok": True, "ticket": _slim(created.get("ticket"), a.full)}

    if a.cmd == "tag":
        tags = _tags(a.tags)
        if not tags:
            raise ZendeskError("--tags must name at least one tag")
        # The dedicated tags endpoint, not a ticket update: it is what the
        # "Change a ticket's tags" action governs, so tagging follows that
        # setting rather than the one for ticket updates. PUT sets the whole
        # tag list, POST adds to it.
        path = _path("/api/v2/tickets/{0}/tags.json", a.id)
        updated = _request(site, "PUT" if a.replace else "POST", path, {"tags": tags})
        return {"ok": True, "tags": updated.get("tags")}

    if a.cmd in ("update", "comment"):
        if a.cmd == "update":
            ticket = _pairs(a.set)
            if not ticket:
                raise ZendeskError("no fields given; pass at least one --set key=value")
        else:
            ticket = {"comment": {"body": a.body, "public": a.public}}
        path = _path("/api/v2/tickets/{0}.json", a.id)
        updated = _request(site, "PUT", path, {"ticket": ticket})
        return {"ok": True, "ticket": _slim(updated.get("ticket"), a.full)}

    if a.cmd != "call":
        raise ZendeskError(f"unknown command {a.cmd!r}")

    # `call` raw escape hatch.
    body = None
    if a.body:
        parsed = json.loads(a.body)
        if not isinstance(parsed, dict):
            raise ZendeskError("body must be a JSON object")
        body = parsed
    if not a.path.startswith("/api/v2/") or ".." in a.path:
        raise ZendeskError("path must start with /api/v2/ and contain no '..'")
    return {"ok": True, "data": _request(site, a.method, a.path, body)}


def _error_message(detail: str) -> str:
    """The most specific message Zendesk gave. Its error bodies are either
    ``{"error": "...", "description": "..."}`` or ``{"details": {...}}``."""
    try:
        parsed = json.loads(detail)
    except ValueError:
        return detail
    if not isinstance(parsed, dict):
        return detail
    for key in ("description", "error", "details"):
        value = parsed.get(key)
        if value:
            return value if isinstance(value, str) else json.dumps(value)
    return detail


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except (ZendeskError, json.JSONDecodeError) as e:
        print(f"invalid input: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        failure: dict[str, Any] = {
            "ok": False,
            "status": e.code,
            "error": _error_message(detail),
        }
        if e.code == 429:
            # Zendesk throttles per account per minute; tell the agent to wait
            # rather than hammer the endpoint.
            failure["retry_after_seconds"] = e.headers.get("Retry-After")
        print(json.dumps(failure))
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Zendesk: {e.reason}", file=sys.stderr)
        return 1
    print(json.dumps(result if a.raw else _prune(result)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
