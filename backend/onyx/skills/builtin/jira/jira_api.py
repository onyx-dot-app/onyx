#!/usr/bin/env python3
"""Jira Cloud REST API wrapper for the Onyx Craft sandbox.

Common Jira operations exposed as subcommands. The connected user's token is
injected by the egress gateway, so this script sends no credentials itself.

Every call other than site discovery is scoped to an Atlassian site by its cloud
id and rooted at the v3 Jira Cloud base ``/ex/jira/{cloud_id}/rest/api/3``. The
cloud id is resolved automatically from ``/oauth/token/accessible-resources``
(first site, or the one selected by ``--cloud-id`` / ``--site``) and cached for
the process.

Output is JSON on stdout; Jira signals failure with a non-2xx status and a JSON
body, surfaced here as ``{"ok": false, ...}``.
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
_DEFAULT_FIELDS = "summary,description,status,assignee,priority,issuetype,labels"
_HEADERS = {
    "Accept": "application/json",
}


class _CloudIdError(Exception):
    """No usable cloud id could be resolved (surfaced as a JSON error)."""


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
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
        return json.loads(raw) if raw else {}


def _resolve_cloud_id(cloud_id: str | None, site: str | None) -> str:
    """Resolve the Atlassian cloud id to scope Jira calls.

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


def _jira(cloud_id: str, path: str) -> str:
    """Build a v3 Jira Cloud REST path under a site's cloud id."""
    return f"/ex/jira/{cloud_id}/rest/api/3{path}"


def _query(path: str, params: dict[str, Any]) -> str:
    clean = {k: v for k, v in params.items() if v is not None}
    if not clean:
        return path
    sep = "&" if "?" in path else "?"
    return f"{path}{sep}{urllib.parse.urlencode(clean)}"


def _one(path: str, key: str) -> dict[str, Any]:
    return {"ok": True, key: _request("GET", path)}


def _paginate(
    path: str,
    list_key: str,
    results_key: str,
    limit: int,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Page through a Jira list endpoint (offset/limit pagination via ``startAt``
    and ``maxResults`` query params).

    ``results_key`` names the array in the body: Jira's v3 endpoints diverge here
    — ``/search`` returns ``issues``, ``/project/search`` returns ``values``, and
    ``/issue/{key}/comment`` returns ``comments`` — so each caller names its own
    rather than assuming one shape.
    """
    results: list[Any] = []
    start = 0
    base_params = dict(params or {})
    while len(results) < limit:
        page_limit = min(_PAGE_SIZE, limit - len(results))
        url = _query(path, dict(base_params, startAt=start, maxResults=page_limit))
        parsed = _request("GET", url)
        batch = parsed.get(results_key) or []
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


def _adf_paragraph(text: str) -> dict[str, Any]:
    """Wrap plain text in a minimal Atlassian Document Format (ADF) doc.

    Jira Cloud's v3 API expects rich text (descriptions, comment bodies) as ADF;
    this wraps the input as a single paragraph document.
    """
    return {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}],
    }


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jira_api.py", description="Jira Cloud REST API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    p.add_argument("--cloud-id", help="Atlassian cloud id to target (skips lookup)")
    p.add_argument("--site", help="pick a site by name/url substring (else the first)")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sub.add_parser("sites", help="list accessible Atlassian sites + cloud ids")

    sub.add_parser("me", help="the connected user's Jira profile")

    sp = sub.add_parser("projects", help="list projects")
    with_limit(sp)

    sp = sub.add_parser("search", help="search issues with JQL")
    sp.add_argument("jql", help="a JQL query, e.g. 'project = ENG AND status != Done'")
    with_limit(sp)

    sp = sub.add_parser("issue", help="fetch an issue by id or key")
    sp.add_argument("issue_id_or_key")
    sp.add_argument("--fields", default=_DEFAULT_FIELDS, help="comma-separated fields")

    sp = sub.add_parser("comments", help="list an issue's comments")
    sp.add_argument("issue_id_or_key")
    with_limit(sp)

    sp = sub.add_parser("create-issue", help="create an issue (write)")
    sp.add_argument("--project", required=True, help="project key")
    sp.add_argument(
        "--summary", "--title", dest="summary", required=True, help="summary"
    )
    sp.add_argument("--description", required=True, help="description (plain text)")
    sp.add_argument("--type", default="Task", help="issue type name (default: Task)")

    sp = sub.add_parser("update-issue", help="update an issue (write)")
    sp.add_argument("issue_id_or_key")
    sp.add_argument("--summary", help="new summary")
    sp.add_argument("--description", help="new description (plain text)")
    sp.add_argument("--labels", help="comma-separated labels")

    sp = sub.add_parser("comment", help="add a comment to an issue (write)")
    sp.add_argument("issue_id_or_key", help="the issue the comment is attached to")
    sp.add_argument("body", help="comment text")

    sp = sub.add_parser("transitions", help="list an issue's available transitions")
    sp.add_argument("issue_id_or_key")

    sp = sub.add_parser("transition", help="apply a transition to an issue (write)")
    sp.add_argument("issue_id_or_key")
    sp.add_argument("transition_id", help="transition id (from `transitions`)")

    sp = sub.add_parser("delete-issue", help="delete an issue (write)")
    sp.add_argument("issue_id_or_key")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    # `sites` is the one command that needs no cloud id — resolve lazily for the
    # rest so a bad/unauthorized grant surfaces one clean error.
    if a.cmd == "sites":
        return {"ok": True, "sites": _request("GET", _ACCESSIBLE_RESOURCES)}

    cloud_id = _resolve_cloud_id(a.cloud_id, a.site)

    if a.cmd == "me":
        return _one(_jira(cloud_id, "/myself"), "user")

    if a.cmd == "projects":
        return _paginate(
            _jira(cloud_id, "/project/search"), "projects", "values", a.limit
        )

    if a.cmd == "search":
        return _paginate(
            _jira(cloud_id, "/search"),
            "issues",
            "issues",
            a.limit,
            params={"jql": a.jql},
        )

    if a.cmd == "issue":
        path = _query(
            _jira(cloud_id, f"/issue/{a.issue_id_or_key}"), {"fields": a.fields}
        )
        return {"ok": True, "issue": _request("GET", path)}

    if a.cmd == "comments":
        return _paginate(
            _jira(cloud_id, f"/issue/{a.issue_id_or_key}/comment"),
            "comments",
            "comments",
            a.limit,
        )

    if a.cmd == "create-issue":
        payload: dict[str, Any] = {
            "fields": {
                "project": {"key": a.project},
                "summary": a.summary,
                "issuetype": {"name": a.type},
                "description": _adf_paragraph(a.description),
            }
        }
        return {
            "ok": True,
            "issue": _request("POST", _jira(cloud_id, "/issue"), payload),
        }

    if a.cmd == "update-issue":
        fields: dict[str, Any] = {}
        if a.summary is not None:
            fields["summary"] = a.summary
        if a.description is not None:
            fields["description"] = _adf_paragraph(a.description)
        if a.labels is not None:
            fields["labels"] = [label for label in a.labels.split(",") if label]
        if not fields:
            return _bad_request(
                "update-issue requires --summary, --description, or --labels"
            )
        return {
            "ok": True,
            "issue": _request(
                "PUT",
                _jira(cloud_id, f"/issue/{a.issue_id_or_key}"),
                {"fields": fields},
            ),
        }

    if a.cmd == "comment":
        payload = {"body": _adf_paragraph(a.body)}
        return {
            "ok": True,
            "comment": _request(
                "POST", _jira(cloud_id, f"/issue/{a.issue_id_or_key}/comment"), payload
            ),
        }

    if a.cmd == "transitions":
        path = _jira(cloud_id, f"/issue/{a.issue_id_or_key}/transitions")
        return {"ok": True, "transitions": _request("GET", path)}

    if a.cmd == "transition":
        payload = {"transition": {"id": a.transition_id}}
        _request(
            "POST", _jira(cloud_id, f"/issue/{a.issue_id_or_key}/transitions"), payload
        )
        return {
            "ok": True,
            "transitioned": a.issue_id_or_key,
            "transition_id": a.transition_id,
        }

    if a.cmd == "delete-issue":
        _request("DELETE", _jira(cloud_id, f"/issue/{a.issue_id_or_key}"))
        return {"ok": True, "deleted": a.issue_id_or_key}

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
                    "error": f"network error calling Jira: {e.reason}",
                }
            )
        )
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
