"""Git Smart HTTP request recognition for the sandbox proxy.

Lets the proxy recognize git-over-HTTPS traffic to github.com so a resolver
can inject the user's GitHub credential. A clone/fetch is two requests:

    GET  https://github.com/<owner>/<repo>.git/info/refs?service=git-upload-pack
    POST https://github.com/<owner>/<repo>.git/git-upload-pack

`git-upload-pack` is the read service (clone/fetch); `git-receive-pack` is the
write counterpart used by `git push`. GitHub canonicalizes the path with a
`.git` suffix. This module only *recognizes* requests and extracts owner/repo
+ read-vs-write — it carries no policy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from mitmproxy import http

GIT_HOST = "github.com"

_GIT_PATH_PATTERN = re.compile(
    r"^/(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<name>[A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?"
    r"(?P<endpoint>/info/refs|/git-upload-pack|/git-receive-pack)$"
)


@dataclass(frozen=True)
class GitRequestInfo:
    owner: str
    name: str
    is_push: bool  # receive-pack (push) vs upload-pack (fetch/clone)


def parse_git_request(request: http.Request) -> GitRequestInfo | None:
    """Recognize a git smart-HTTP request to github.com, or return None."""
    if request.host.lower() != GIT_HOST:
        return None

    match = _GIT_PATH_PATTERN.match(request.path.split("?", 1)[0])
    if match is None:
        return None
    endpoint = match.group("endpoint")

    if endpoint == "/info/refs":
        if request.method != "GET":
            return None
        service = request.query.get("service", "")
        if service not in ("git-upload-pack", "git-receive-pack"):
            return None
        is_push = service == "git-receive-pack"
    else:
        if request.method != "POST":
            return None
        is_push = endpoint == "/git-receive-pack"

    return GitRequestInfo(
        owner=match.group("owner"), name=match.group("name"), is_push=is_push
    )
