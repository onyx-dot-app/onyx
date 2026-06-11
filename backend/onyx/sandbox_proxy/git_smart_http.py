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

import os
import re
from dataclasses import dataclass

from mitmproxy import http

GIT_HOST = "github.com"

# Push packfiles legitimately exceed the gate's generic 1 MiB body cap (a pack
# carries full blobs), so recognized git requests are exempted up to this size
# and skip action-matching (git endpoints are in no action catalog).
GIT_SMART_HTTP_MAX_BODY_BYTES = int(
    os.environ.get("GIT_SMART_HTTP_MAX_BODY_BYTES", str(128 * 1024 * 1024))
)

# Branch namespace Craft sessions are allowed to push to. Mirrors
# onyx.server.features.build.sandbox.util.git_scripts.CRAFT_BRANCH_PATTERN.
ALLOWED_PUSH_REF_PATTERN = re.compile(
    r"^refs/heads/craft/[A-Za-z0-9][A-Za-z0-9._/-]{0,120}$"
)

_GIT_PATH_PATTERN = re.compile(
    r"^/(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/(?P<name>[A-Za-z0-9._-]{1,100}?)"
    r"(?:\.git)?"
    r"(?P<endpoint>/info/refs|/git-upload-pack|/git-receive-pack)$"
)

_FLUSH_PKT = b"0000"
_ZERO_SHA = "0" * 40


class GitProtocolError(ValueError):
    """The request claims to be git smart-HTTP but the body doesn't parse."""


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


@dataclass(frozen=True)
class RefUpdate:
    old_sha: str
    new_sha: str
    ref_name: str

    @property
    def is_delete(self) -> bool:
        return self.new_sha == _ZERO_SHA


def parse_receive_pack_commands(body: bytes) -> list[RefUpdate]:
    """Parse the pkt-line command section of a git-receive-pack request body.

    Each pkt-line: 4 hex length chars (including themselves), then
    ``<old-sha> <new-sha> <ref-name>``; the first line also carries a
    NUL-separated capability list. A flush-pkt (``0000``) ends the section;
    the packfile follows. Raises GitProtocolError on anything malformed — the
    caller fails closed (no credential, request blocked).
    """
    updates: list[RefUpdate] = []
    offset = 0
    while True:
        if offset + 4 > len(body):
            raise GitProtocolError("truncated pkt-line stream")
        length_hex = body[offset : offset + 4]
        if length_hex == _FLUSH_PKT:
            break
        try:
            length = int(length_hex, 16)
        except ValueError as e:
            raise GitProtocolError(f"bad pkt-line length {length_hex!r}") from e
        if length < 4 or offset + length > len(body):
            raise GitProtocolError("pkt-line length out of bounds")

        line = body[offset + 4 : offset + length]
        offset += length

        line = line.split(b"\0", 1)[0].rstrip(b"\n")
        try:
            decoded = line.decode("utf-8")
        except UnicodeDecodeError as e:
            raise GitProtocolError("non-utf8 ref command") from e

        parts = decoded.split(" ", 2)
        if len(parts) != 3 or len(parts[0]) != 40 or len(parts[1]) != 40:
            raise GitProtocolError(f"malformed ref command: {decoded!r}")
        updates.append(RefUpdate(old_sha=parts[0], new_sha=parts[1], ref_name=parts[2]))

        if len(updates) > 100:
            raise GitProtocolError("too many ref updates in one push")

    if not updates:
        raise GitProtocolError("push contains no ref updates")
    return updates


def disallowed_push_refs(body: bytes) -> list[str]:
    """Ref names in a receive-pack body outside the craft/ namespace.

    Empty list ⇒ the push only touches ``refs/heads/craft/*``. Raises
    GitProtocolError when the body doesn't parse.
    """
    return [
        update.ref_name
        for update in parse_receive_pack_commands(body)
        if not ALLOWED_PUSH_REF_PATTERN.match(update.ref_name)
    ]
