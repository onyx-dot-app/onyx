#!/usr/bin/env python3
"""Google Calendar wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. Output is JSON on stdout.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://www.googleapis.com/calendar/v3/"
_PAGE_SIZE = 250
_DEFAULT_LIMIT = 250
_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE")
_HTTP_TIMEOUT_SECONDS = 180


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays
    small. Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _seg(value: str) -> str:
    """URL-encode a single path segment (ids may contain @ or /)."""
    return urllib.parse.quote(value, safe="")


def _req(
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Call a Calendar endpoint; return parsed JSON ({} on empty/204).
    Raises on transport failure (handled by the caller)."""
    url = _BASE + path
    if params:
        clean = {k: v for k, v in params.items() if v is not None}
        url += "?" + urllib.parse.urlencode(clean)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    headers = {"Content-Type": "application/json; charset=utf-8"} if data else {}
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        url, data=data, method=method, headers=headers
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
    return json.loads(raw) if raw.strip() else {}


def _paginate(path: str, params: dict[str, Any], limit: int) -> dict[str, Any]:
    """Walk a list endpoint (`items` + `nextPageToken`) up to `limit`."""
    items: list[Any] = []
    token: str | None = None
    while True:
        q = dict(params, maxResults=min(_PAGE_SIZE, limit - len(items)))
        if token:
            q["pageToken"] = token
        resp = _req("GET", path, params=q)
        items.extend(resp.get("items") or [])
        token = resp.get("nextPageToken")
        if len(items) >= limit:
            return {
                "ok": True,
                "items": items[:limit],
                "count": limit,
                "truncated": bool(token),
            }
        if not token:
            break
    return {"ok": True, "items": items, "count": len(items), "truncated": False}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="gcal_api.py", description="Google Calendar.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    with_limit(sub.add_parser("calendars", help="list the user's calendars"))

    sp = sub.add_parser("events", help="list events in a calendar")
    sp.add_argument("calendar_id")
    sp.add_argument("--from", dest="time_min", help="RFC3339 lower bound")
    sp.add_argument("--to", dest="time_max", help="RFC3339 upper bound")
    sp.add_argument("--q", help="free-text query")
    with_limit(sp)

    sp = sub.add_parser("event", help="one event")
    sp.add_argument("calendar_id")
    sp.add_argument("event_id")

    sp = sub.add_parser("create-event", help="create an event (write)")
    sp.add_argument("calendar_id")
    sp.add_argument("summary")
    sp.add_argument("start_iso")
    sp.add_argument("end_iso")
    sp.add_argument("--description")
    sp.add_argument("--attendees", help="comma-separated emails")

    sp = sub.add_parser("delete-event", help="delete an event (write)")
    sp.add_argument("calendar_id")
    sp.add_argument("event_id")

    sp = sub.add_parser("freebusy", help="busy intervals for calendars")
    sp.add_argument("from_iso")
    sp.add_argument("to_iso")
    sp.add_argument("calendar_ids", nargs="+")

    sp = sub.add_parser("call", help="raw Calendar request")
    sp.add_argument("method", choices=_METHODS)
    sp.add_argument("path", help="appended to calendar/v3/")
    sp.add_argument("json_body", nargs="?")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "calendars":
        return _paginate("users/me/calendarList", {}, a.limit)

    if a.cmd == "events":
        return _paginate(
            f"calendars/{_seg(a.calendar_id)}/events",
            {
                "singleEvents": "true",
                "orderBy": "startTime",
                "timeMin": a.time_min,
                "timeMax": a.time_max,
                "q": a.q,
            },
            a.limit,
        )

    if a.cmd == "event":
        ev = _req(
            "GET",
            f"calendars/{_seg(a.calendar_id)}/events/{_seg(a.event_id)}",
        )
        return {"ok": True, "event": ev}

    if a.cmd == "create-event":
        body: dict[str, Any] = {
            "summary": a.summary,
            "start": {"dateTime": a.start_iso},
            "end": {"dateTime": a.end_iso},
        }
        if a.description:
            body["description"] = a.description
        if a.attendees:
            body["attendees"] = [
                {"email": e.strip()} for e in a.attendees.split(",") if e.strip()
            ]
        ev = _req("POST", f"calendars/{_seg(a.calendar_id)}/events", body=body)
        return {"ok": True, "event": ev}

    if a.cmd == "delete-event":
        _req(
            "DELETE",
            f"calendars/{_seg(a.calendar_id)}/events/{_seg(a.event_id)}",
        )
        return {"ok": True, "deleted": True}

    if a.cmd == "freebusy":
        resp = _req(
            "POST",
            "freeBusy",
            body={
                "timeMin": a.from_iso,
                "timeMax": a.to_iso,
                "items": [{"id": c} for c in a.calendar_ids],
            },
        )
        return {"ok": True, "calendars": resp.get("calendars")}

    # `call` raw escape hatch
    body = None
    if a.json_body:
        body = json.loads(a.json_body)
        if not isinstance(body, dict):
            return {"ok": False, "error": "json_body_not_object"}
    resp = _req(a.method, a.path.lstrip("/"), body=body)
    return {"ok": True, "data": resp}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except json.JSONDecodeError as e:
        print(f"invalid json_body: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling Google Calendar: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Google Calendar: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
