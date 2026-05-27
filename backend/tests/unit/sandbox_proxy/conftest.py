"""Shared `StaticLookup` stub for sandbox_proxy tests.

Two shapes: `StaticLookup({ip: identity, ...})` keys by source IP;
`StaticLookup.single(identity_or_none)` returns the same identity for any IP.
"""

from __future__ import annotations

from onyx.sandbox_proxy.identity import SandboxIdentity
from onyx.sandbox_proxy.identity import SandboxIPLookup


class StaticLookup(SandboxIPLookup):
    """`SandboxIPLookup` Protocol stub with a fixed in-memory map."""

    def __init__(
        self,
        cache: dict[str, SandboxIdentity] | None = None,
        *,
        single: SandboxIdentity | None = None,
        single_mode: bool = False,
    ) -> None:
        self._cache: dict[str, SandboxIdentity] = cache or {}
        self._single = single
        self._single_mode = single_mode

    @classmethod
    def single(cls, identity: SandboxIdentity | None) -> "StaticLookup":
        """Return `identity` for any source IP (or `None` for none)."""
        return cls(single=identity, single_mode=True)

    def start(self) -> None:
        return None

    def lookup(self, src_ip: str) -> SandboxIdentity | None:
        if self._single_mode:
            return self._single
        return self._cache.get(src_ip)

    def wait_for_initial_sync(
        self,
        timeout_seconds: float,  # noqa: ARG002
    ) -> bool:
        return True

    def is_synced(self) -> bool:
        return True

    def stop(self) -> None:
        return None
