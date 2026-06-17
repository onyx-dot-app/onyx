#!/usr/bin/env python3
"""Linear (GraphQL) wrapper for the Onyx Craft sandbox.

Common operations exposed as subcommands. User input is passed as
GraphQL *variables* (never string-formatted into the query), so there
is no injection risk. Output is JSON on stdout.
"""

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from typing import Any

_ENDPOINT = "https://api.linear.app/graphql"
_PAGE_SIZE = 100
_DEFAULT_LIMIT = 100
_IDENT_RE = re.compile(r"^[A-Za-z][A-Za-z0-9]*-\d+$")
_HTTP_TIMEOUT_SECONDS = 180

_ISSUE_FIELDS = """
  id identifier title url priority
  state { name type }
  assignee { name email }
  team { key name }
  updatedAt
"""


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} so LLM-facing output stays
    small. Booleans and 0 are kept — they carry signal."""
    if isinstance(value, dict):
        out = {k: _prune(v) for k, v in value.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _gql(query: str, variables: dict[str, Any]) -> dict[str, Any]:
    """POST a GraphQL request; return the parsed JSON. Raises on
    transport failure (handled by the caller)."""
    req = urllib.request.Request(  # noqa: S310 — fixed https endpoint
        _ENDPOINT,
        data=json.dumps({"query": query, "variables": variables}).encode("utf-8"),
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def _unwrap(resp: dict[str, Any], key: str) -> dict[str, Any]:
    """GraphQL error → uniform error envelope; else lift data[key]."""
    if resp.get("errors"):
        return {"ok": False, "errors": resp["errors"]}
    return {"ok": True, key: (resp.get("data") or {}).get(key)}


def _paginate(
    query: str, variables: dict[str, Any], conn_key: str, limit: int
) -> dict[str, Any]:
    """Walk a GraphQL connection (`nodes` + `pageInfo`) up to `limit`."""
    nodes: list[Any] = []
    after: str | None = None
    while True:
        v = dict(variables, first=min(_PAGE_SIZE, limit - len(nodes)))
        if after:
            v["after"] = after
        resp = _gql(query, v)
        if resp.get("errors"):
            return {"ok": False, "errors": resp["errors"]}
        conn = ((resp.get("data") or {}).get(conn_key)) or {}
        nodes.extend(conn.get("nodes") or [])
        page = conn.get("pageInfo") or {}
        after = page.get("endCursor")
        if len(nodes) >= limit:
            return {
                "ok": True,
                conn_key: nodes[:limit],
                "count": limit,
                "truncated": bool(page.get("hasNextPage")),
            }
        if not page.get("hasNextPage"):
            break
    return {"ok": True, conn_key: nodes, "count": len(nodes), "truncated": False}


def _issue_filter(a: argparse.Namespace) -> dict[str, Any]:
    f: dict[str, Any] = {}
    if getattr(a, "team", None):
        f["team"] = {"key": {"eq": a.team}}
    if getattr(a, "assignee", None) == "me":
        f["assignee"] = {"isMe": {"eq": True}}
    elif getattr(a, "assignee", None):
        f["assignee"] = {"id": {"eq": a.assignee}}
    if getattr(a, "state", None):
        f["state"] = {"name": {"eq": a.state}}
    return f


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="linear_api.py", description="Linear GraphQL.")
    p.add_argument("--raw", action="store_true", help="don't prune empty fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sub.add_parser("me", help="the connected user (viewer)")

    with_limit(sub.add_parser("teams", help="list teams"))

    sp = sub.add_parser("issues", help="list issues (filtered)")
    sp.add_argument("--team", help="team key, e.g. ENG")
    sp.add_argument("--assignee", help="'me' or a user id")
    sp.add_argument("--state", help="workflow state name")
    with_limit(sp)

    sp = sub.add_parser("issue", help="one issue by id or IDENT-123")
    sp.add_argument("ref")

    sp = sub.add_parser("search", help="full-text issue search")
    sp.add_argument("query")
    with_limit(sp)

    with_limit(sub.add_parser("projects", help="list projects"))

    sp = sub.add_parser("create-issue", help="create an issue (write)")
    sp.add_argument("team_id")
    sp.add_argument("title")
    sp.add_argument("--description")
    sp.add_argument("--assignee", help="user id")

    sp = sub.add_parser("comment", help="comment on an issue (write)")
    sp.add_argument("issue_id")
    sp.add_argument("body")

    sp = sub.add_parser("call", help="raw GraphQL")
    sp.add_argument("query")
    sp.add_argument("variables", nargs="?")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "me":
        return _unwrap(_gql("query { viewer { id name email } }", {}), "viewer")

    if a.cmd == "teams":
        q = (
            "query($first:Int,$after:String){ teams(first:$first,after:$after)"
            "{ nodes { id key name } pageInfo { hasNextPage endCursor } } }"
        )
        return _paginate(q, {}, "teams", a.limit)

    if a.cmd == "issues":
        q = (
            "query($first:Int,$after:String,$filter:IssueFilter){"
            " issues(first:$first,after:$after,filter:$filter)"
            f"{{ nodes {{ {_ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }} }}"
        )
        return _paginate(q, {"filter": _issue_filter(a)}, "issues", a.limit)

    if a.cmd == "issue":
        if _IDENT_RE.match(a.ref):
            team, number = a.ref.split("-")
            q = (
                "query($k:String!,$n:Float!){ issues(first:1,filter:"
                "{team:{key:{eq:$k}},number:{eq:$n}})"
                f"{{ nodes {{ {_ISSUE_FIELDS} description }} }} }}"
            )
            resp = _gql(q, {"k": team.upper(), "n": float(number)})
            if resp.get("errors"):
                return {"ok": False, "errors": resp["errors"]}
            nodes = ((resp.get("data") or {}).get("issues") or {}).get("nodes") or []
            return {"ok": True, "issue": nodes[0] if nodes else None}
        q = f"query($id:String!){{ issue(id:$id){{ {_ISSUE_FIELDS} description }} }}"
        return _unwrap(_gql(q, {"id": a.ref}), "issue")

    if a.cmd == "search":
        q = (
            "query($q:String!,$first:Int,$after:String){"
            " issueSearch(query:$q,first:$first,after:$after)"
            f"{{ nodes {{ {_ISSUE_FIELDS} }} pageInfo {{ hasNextPage endCursor }} }} }}"
        )
        return _paginate(q, {"q": a.query}, "issueSearch", a.limit)

    if a.cmd == "projects":
        q = (
            "query($first:Int,$after:String){ projects(first:$first,after:$after)"
            "{ nodes { id name state url } pageInfo { hasNextPage endCursor } } }"
        )
        return _paginate(q, {}, "projects", a.limit)

    if a.cmd == "create-issue":
        inp: dict[str, Any] = {"teamId": a.team_id, "title": a.title}
        if a.description:
            inp["description"] = a.description
        if a.assignee:
            inp["assigneeId"] = a.assignee
        q = (
            "mutation($input:IssueCreateInput!){ issueCreate(input:$input)"
            "{ success issue { id identifier url } } }"
        )
        return _unwrap(_gql(q, {"input": inp}), "issueCreate")

    if a.cmd == "comment":
        q = (
            "mutation($input:CommentCreateInput!){ commentCreate(input:$input)"
            "{ success comment { id url } } }"
        )
        return _unwrap(
            _gql(q, {"input": {"issueId": a.issue_id, "body": a.body}}),
            "commentCreate",
        )

    # `call` raw escape hatch
    variables: dict[str, Any] = {}
    if a.variables:
        parsed = json.loads(a.variables)
        if not isinstance(parsed, dict):
            return {"ok": False, "error": "variables_not_object"}
        variables = parsed
    resp = _gql(a.query, variables)
    if resp.get("errors"):
        return {"ok": False, "errors": resp["errors"]}
    return {"ok": True, "data": resp.get("data")}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    try:
        result = _dispatch(a)
    except json.JSONDecodeError as e:
        print(f"invalid variables: {e}", file=sys.stderr)
        return 2
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        print(f"HTTP {e.code} calling Linear: {detail}", file=sys.stderr)
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling Linear: {e.reason}", file=sys.stderr)
        return 1
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
