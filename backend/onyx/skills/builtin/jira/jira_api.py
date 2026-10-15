#!/usr/bin/env python3
"""Jira (Atlassian Cloud) REST API wrapper for the Onyx Craft sandbox.

Common Jira operations exposed as subcommands. The connected user's token is
injected by the egress gateway, so this script sends no credentials itself.
API calls route through Atlassian's gateway to a specific site as
``/ex/jira/{cloud_id}/rest/api/3/...``; the cloud id is resolved automatically
from ``/oauth/token/accessible-resources`` (the first site, or a
``--cloud-id`` / ``--site`` override). Output is JSON on stdout; Jira signals
failure with a non-2xx status and an ``{"errorMessages": [...], ...}`` body,
surfaced here as ``{"ok": false, ...}``.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.atlassian.com"
_API_VERSION = "3"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 180
_HEADERS = {
    "Accept": "application/json",
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
    method: str, path: str, body: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Issue a request to the Atlassian REST API; return the parsed JSON. Raises
    urllib errors on transport / non-2xx failure (handled by the caller)."""
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


def _accessible_resources() -> list[dict[str, Any]]:
    """The Atlassian sites this authorization can reach (each carries an `id`
    used as the cloud id, plus `name` and `url`)."""
    resources = _request("GET", "/oauth/token/accessible-resources")
    return resources if isinstance(resources, list) else []


def _resolve_cloud_id(cloud_id: str | None, site: str | None) -> str:
    """Pick the cloud id: an explicit `--cloud-id`, or the site whose name/url
    matches `--site`, or the first accessible site. Raises ValueError when no
    site can be resolved."""
    if cloud_id:
        return cloud_id
    resources = _accessible_resources()
    if not resources:
        raise ValueError(
            "No accessible Atlassian sites for this authorization; "
            "reconnect the Jira app or check its scopes."
        )
    if site:
        needle = site.lower()
        for res in resources:
            name = str(res.get("name", "")).lower()
            url = str(res.get("url", "")).lower()
            if needle in name or needle in url:
                return str(res["id"])
        raise ValueError(f"No accessible site matched --site {site!r}.")
    return str(resources[0]["id"])


def _api(cloud_id: str, suffix: str) -> str:
    """Build a `/ex/jira/{cloud_id}/rest/api/3/...` path from a version-relative
    suffix (which must start with `/`)."""
    return f"/ex/jira/{cloud_id}/rest/api/{_API_VERSION}{suffix}"


def _adf(text: str) -> dict[str, Any]:
    """A minimal Atlassian Document Format doc wrapping a single text paragraph
    (Jira v3 issue descriptions and comment bodies are ADF, not plain text)."""
    return {
        "type": "doc",
        "version": 1,
        "content": [
            {
                "type": "paragraph",
                "content": [{"type": "text", "text": text}],
            }
        ],
    }


def _paginate_search(cloud_id: str, jql: str, limit: int) -> dict[str, Any]:
    """Page through JQL issue search (GET with `jql`, `startAt`, `maxResults`
    query params; the body carries `issues` and `total`)."""
    results: list[Any] = []
    start_at = 0
    while len(results) < limit:
        max_results = min(_PAGE_SIZE, limit - len(results))
        query = urllib.parse.urlencode(
            {"jql": jql, "startAt": start_at, "maxResults": max_results}
        )
        parsed = _request("GET", _api(cloud_id, f"/search?{query}"))
        issues = parsed.get("issues") or []
        results.extend(issues)
        total = parsed.get("total")
        start_at += len(issues)
        if not issues or (total is not None and start_at >= total):
            return {
                "ok": True,
                "issues": results[:limit],
                "count": len(results[:limit]),
                "truncated": False,
            }
    return {"ok": True, "issues": results[:limit], "count": limit, "truncated": True}


def _bad_request(message: str) -> dict[str, Any]:
    """A client-side validation failure, in the same JSON shape as API errors."""
    return {"ok": False, "status": None, "error": message}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="jira_api.py", description="Jira REST API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    p.add_argument(
        "--cloud-id",
        help="explicit Atlassian cloud id (skips accessible-resources lookup)",
    )
    p.add_argument(
        "--site",
        help="pick the accessible site by name or url (else the first is used)",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("sites", help="list the accessible Atlassian sites")
    sub.add_parser("myself", help="the connected Jira user")
    sub.add_parser("projects", help="list projects")

    sp = sub.add_parser("search", help="search issues with JQL")
    sp.add_argument("jql", help='a JQL query, e.g. "project = ENG ORDER BY created"')
    sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sp = sub.add_parser("issue", help="fetch a single issue")
    sp.add_argument("issue_key", help="issue id or key, e.g. ENG-4287")

    sp = sub.add_parser("create-issue", help="create an issue (write)")
    sp.add_argument("--project", required=True, help="project key, e.g. ENG")
    sp.add_argument("--type", default="Task", help="issue type name (default: Task)")
    sp.add_argument("--summary", required=True, help="issue summary")
    sp.add_argument("--description", help="optional issue description")

    sp = sub.add_parser("comment", help="add a comment to an issue (write)")
    sp.add_argument("issue_key", help="issue id or key, e.g. ENG-4287")
    sp.add_argument("body", help="comment text")

    sp = sub.add_parser("transitions", help="list an issue's available transitions")
    sp.add_argument("issue_key", help="issue id or key, e.g. ENG-4287")

    sp = sub.add_parser("transition", help="transition an issue (write)")
    sp.add_argument("issue_key", help="issue id or key, e.g. ENG-4287")
    sp.add_argument("transition_id", help="a transition id from `transitions`")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    # `sites` never needs a resolved cloud id — it's how you discover them.
    if a.cmd == "sites":
        return {"ok": True, "sites": _accessible_resources()}

    cloud_id = _resolve_cloud_id(a.cloud_id, a.site)

    if a.cmd == "myself":
        return {"ok": True, "user": _request("GET", _api(cloud_id, "/myself"))}

    if a.cmd == "projects":
        return {
            "ok": True,
            "projects": _request("GET", _api(cloud_id, "/project")),
        }

    if a.cmd == "search":
        return _paginate_search(cloud_id, a.jql, a.limit)

    if a.cmd == "issue":
        return {
            "ok": True,
            "issue": _request("GET", _api(cloud_id, f"/issue/{a.issue_key}")),
        }

    if a.cmd == "create-issue":
        fields: dict[str, Any] = {
            "project": {"key": a.project},
            "issuetype": {"name": a.type},
            "summary": a.summary,
        }
        if a.description:
            fields["description"] = _adf(a.description)
        payload = {"fields": fields}
        return {
            "ok": True,
            "issue": _request("POST", _api(cloud_id, "/issue"), payload),
        }

    if a.cmd == "comment":
        payload = {"body": _adf(a.body)}
        return {
            "ok": True,
            "comment": _request(
                "POST", _api(cloud_id, f"/issue/{a.issue_key}/comment"), payload
            ),
        }

    if a.cmd == "transitions":
        return {
            "ok": True,
            "transitions": _request(
                "GET", _api(cloud_id, f"/issue/{a.issue_key}/transitions")
            ),
        }

    if a.cmd == "transition":
        payload = {"transition": {"id": a.transition_id}}
        # A successful transition returns 204 with an empty body.
        _request("POST", _api(cloud_id, f"/issue/{a.issue_key}/transitions"), payload)
        return {"ok": True, "transitioned": a.issue_key, "transition": a.transition_id}

    raise AssertionError(f"unhandled command: {a.cmd!r}")


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except ValueError as e:
        # Client-side resolution failure (no site / bad --site), same JSON shape.
        print(json.dumps(_bad_request(str(e))))
        return 1
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            parsed = json.loads(detail)
            messages = parsed.get("errorMessages") or []
            errors = parsed.get("errors") or {}
            message = "; ".join(messages) or json.dumps(errors) or detail
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
