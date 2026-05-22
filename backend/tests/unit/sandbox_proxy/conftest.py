"""Shared helpers for sandbox_proxy unit tests.

The `StaticLookup` stub lives here so both `test_identity.py` (unit
tests with stubbed sessions) and `test_identity_resolver.py`
(external-dependency tests against real Postgres) can import a single
`SandboxIPLookup` Protocol implementation.

Two construction shapes:

* `StaticLookup({"10.0.0.1": identity, ...})` — dict-keyed by source
  IP. Used by tests that distinguish between several pods.
* `StaticLookup.single(identity_or_none)` — returns the same
  identity (or `None`) regardless of source IP. Used by tests that
  exercise only one pod.
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
