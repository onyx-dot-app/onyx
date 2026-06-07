#!/usr/bin/env python3
"""GitHub REST API wrapper for the Onyx Craft sandbox.

Common GitHub operations exposed as subcommands. The connected user's token is
injected by the egress gateway, so this script sends no credentials itself.
Output is JSON on stdout; GitHub signals failure with a non-2xx status and a
``{"message": ...}`` body, surfaced here as ``{"ok": false, ...}``.
"""

import argparse
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

_BASE = "https://api.github.com"
_PER_PAGE = 100
_DEFAULT_LIMIT = 100
_HTTP_TIMEOUT_SECONDS = 180
# GitHub requires a User-Agent and recommends pinning the API version.
_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "onyx-craft",
    "X-GitHub-Api-Version": "2022-11-28",
}
# GitHub objects carry dozens of `*_url` fields that are pure noise for an LLM.
_KEEP_URLS = frozenset({"html_url"})


def _prune(value: Any) -> Any:
    """Recursively drop None / "" / [] / {} and GitHub's noisy `*_url` keys
    (keeping `html_url`) so LLM-facing output stays small. Booleans and 0 are
    kept — they carry signal."""
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k not in _KEEP_URLS and (k == "url" or k.endswith("_url")):
                continue
            pv = _prune(v)
            if pv not in (None, "", [], {}):
                out[k] = pv
        return out
    if isinstance(value, list):
        return [_prune(v) for v in value]
    return value


def _request(
    method: str, path: str, body: dict[str, Any] | None = None
) -> tuple[Any, dict[str, str]]:
    """Issue a request to the GitHub REST API; return (parsed_json, headers).
    Raises urllib errors on transport / non-2xx failure (handled by caller)."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(  # noqa: S310 — fixed https base url
        _BASE + path,
        data=data,
        method=method,
        headers=dict(
            _HEADERS, **({"Content-Type": "application/json"} if data else {})
        ),
    )
    with urllib.request.urlopen(req, timeout=_HTTP_TIMEOUT_SECONDS) as resp:  # noqa: S310
        raw = resp.read().decode("utf-8")
        parsed = json.loads(raw) if raw else None
        return parsed, {k.lower(): v for k, v in resp.headers.items()}


def _next_path(link_header: str | None) -> str | None:
    """Pull the `rel="next"` path out of GitHub's Link header, or None."""
    if not link_header:
        return None
    for part in link_header.split(","):
        section = part.split(";")
        if len(section) < 2 or 'rel="next"' not in section[1]:
            continue
        url = section[0].strip().strip("<>")
        split = urllib.parse.urlsplit(url)
        return f"{split.path}?{split.query}" if split.query else split.path
    return None


def _paginate(
    path: str, params: dict[str, Any], list_key: str, limit: int
) -> dict[str, Any]:
    """Page through a GitHub list endpoint up to `limit`. `list_key` selects the
    array out of search responses (`items`) vs. bare-array endpoints (whole body)."""
    query = dict(params, per_page=min(_PER_PAGE, limit))
    next_path: str | None = f"{path}?{urllib.parse.urlencode(query)}"
    items: list[Any] = []
    while next_path and len(items) < limit:
        parsed, headers = _request("GET", next_path)
        batch = parsed.get(list_key, []) if isinstance(parsed, dict) else (parsed or [])
        items.extend(batch)
        next_path = _next_path(headers.get("link"))
    truncated = bool(next_path) or len(items) > limit
    return {
        "ok": True,
        list_key: items[:limit],
        "count": min(len(items), limit),
        "truncated": truncated,
    }


def _one(path: str, key: str) -> dict[str, Any]:
    parsed, _ = _request("GET", path)
    return {"ok": True, key: parsed}


def _emit(result: dict[str, Any], raw: bool) -> int:
    print(json.dumps(result if raw else _prune(result)))
    return 0 if result.get("ok") else 1


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="github_api.py", description="GitHub REST API.")
    p.add_argument("--raw", action="store_true", help="don't prune empty / url fields")
    sub = p.add_subparsers(dest="cmd", required=True)

    def with_limit(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--limit", type=int, default=_DEFAULT_LIMIT)

    sub.add_parser("me", help="the connected user")

    with_limit(sub.add_parser("repos", help="the user's repositories"))

    sp = sub.add_parser("repo", help="one repository")
    sp.add_argument("owner")
    sp.add_argument("repo")

    sp = sub.add_parser("issues", help="a repo's issues")
    sp.add_argument("owner")
    sp.add_argument("repo")
    sp.add_argument("--state", default="open", choices=["open", "closed", "all"])
    with_limit(sp)

    sp = sub.add_parser("issue", help="one issue")
    sp.add_argument("owner")
    sp.add_argument("repo")
    sp.add_argument("number")

    sp = sub.add_parser("pulls", help="a repo's pull requests")
    sp.add_argument("owner")
    sp.add_argument("repo")
    sp.add_argument("--state", default="open", choices=["open", "closed", "all"])
    with_limit(sp)

    sp = sub.add_parser("pull", help="one pull request")
    sp.add_argument("owner")
    sp.add_argument("repo")
    sp.add_argument("number")

    sp = sub.add_parser("search-repos", help="search repositories")
    sp.add_argument("query")
    with_limit(sp)

    sp = sub.add_parser("search-issues", help="search issues and pull requests")
    sp.add_argument("query")
    with_limit(sp)

    sp = sub.add_parser("create-issue", help="open an issue (write)")
    sp.add_argument("owner")
    sp.add_argument("repo")
    sp.add_argument("title")
    sp.add_argument("--body")

    sp = sub.add_parser("comment", help="comment on an issue or PR (write)")
    sp.add_argument("owner")
    sp.add_argument("repo")
    sp.add_argument("number")
    sp.add_argument("body")
    return p


def _dispatch(a: argparse.Namespace) -> dict[str, Any]:
    if a.cmd == "me":
        return _one("/user", "user")

    if a.cmd == "repos":
        return _paginate("/user/repos", {"sort": "updated"}, "__list__", a.limit)

    if a.cmd == "repo":
        return _one(f"/repos/{a.owner}/{a.repo}", "repo")

    if a.cmd == "issues":
        return _paginate(
            f"/repos/{a.owner}/{a.repo}/issues", {"state": a.state}, "__list__", a.limit
        )

    if a.cmd == "issue":
        return _one(f"/repos/{a.owner}/{a.repo}/issues/{a.number}", "issue")

    if a.cmd == "pulls":
        return _paginate(
            f"/repos/{a.owner}/{a.repo}/pulls", {"state": a.state}, "__list__", a.limit
        )

    if a.cmd == "pull":
        return _one(f"/repos/{a.owner}/{a.repo}/pulls/{a.number}", "pull")

    if a.cmd == "search-repos":
        return _paginate("/search/repositories", {"q": a.query}, "items", a.limit)

    if a.cmd == "search-issues":
        return _paginate("/search/issues", {"q": a.query}, "items", a.limit)

    if a.cmd == "create-issue":
        body: dict[str, Any] = {"title": a.title}
        if a.body:
            body["body"] = a.body
        parsed, _ = _request("POST", f"/repos/{a.owner}/{a.repo}/issues", body)
        return {"ok": True, "issue": parsed}

    # comment
    parsed, _ = _request(
        "POST",
        f"/repos/{a.owner}/{a.repo}/issues/{a.number}/comments",
        {"body": a.body},
    )
    return {"ok": True, "comment": parsed}


def main(argv: list[str]) -> int:
    a = _build_parser().parse_args(argv[1:])
    # The bare-array list endpoints return their items under a sentinel key;
    # rename it to a friendly name before emitting.
    try:
        result = _dispatch(a)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(detail).get("message", detail)
        except ValueError:
            message = detail
        print(json.dumps({"ok": False, "status": e.code, "error": message}))
        return 1
    except urllib.error.URLError as e:
        print(f"network error calling GitHub: {e.reason}", file=sys.stderr)
        return 1
    if "__list__" in result:
        result[a.cmd] = result.pop("__list__")
    return _emit(result, a.raw)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
