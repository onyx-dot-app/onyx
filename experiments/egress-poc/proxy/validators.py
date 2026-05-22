"""Defensive canonicalization at the trust boundary.

The Anthropic SOCKS5 CVE was a parser differential: JS `endsWith` saw one
host, libc `getaddrinfo` saw another after C-string truncation on `\\x00`.
We bounce anything weird before policy evaluation so the broker and the
upstream resolver agree on what we asked about.
"""

from __future__ import annotations

import re
import unicodedata

_CONTROL_OR_DEL = re.compile(r"[\x00-\x1f\x7f]")


class InvalidHost(ValueError):
    pass


def canonicalize_host(host: str | None) -> str:
    if not host:
        raise InvalidHost("empty host")
    if _CONTROL_OR_DEL.search(host):
        raise InvalidHost("control character in host")
    if "%" in host:
        raise InvalidHost("percent-encoding in host")
    if "\x00" in host:
        raise InvalidHost("null byte in host")
    # Strip any port; Host header may include :port and we key on hostname only.
    bare = host.rsplit(":", 1)[0] if host.count(":") == 1 else host
    try:
        normalized = unicodedata.normalize("NFKC", bare).lower().strip()
    except (TypeError, ValueError):
        raise InvalidHost("could not normalize host")
    if not normalized:
        raise InvalidHost("empty after normalization")
    try:
        normalized.encode("ascii")
    except UnicodeEncodeError:
        raise InvalidHost("non-ASCII host (IDN not supported in v0)")
    return normalized
