"""KVM test proxy: the sandbox proxy GateAddon in mitmproxy, off-cluster.

Real: GateAddon, SignedIdentityVerifier, CachedNodeSigningKeyLookup and
CacheReplayGuard over Redis, the placement record check, the destination
policy and the upstream event loop.
Stubbed (no Postgres or Kubernetes on the test host): the sandbox owner (a
fixed user id once the placement record matches), the pod-IP lookup, the
credential evaluators and resolvers.

Env: the usual Onyx env (SANDBOX_RUNTIME=firecracker, CACHE_BACKEND=redis,
REDIS_HOST, MULTI_TENANT=false), HARNESS_PROXY_PORT, HARNESS_CONFDIR.
"""

import asyncio
import logging
import os
from uuid import UUID

from mitmproxy import http
from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from onyx.cache.factory import get_cache_backend, get_shared_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.microvm.registry import (
    get_sandbox_placement,
)
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.destination_policy import (
    UpstreamEventLoop,
    parse_destination_policy,
)
from onyx.sandbox_proxy.request_evaluator import RequestEvaluator
from onyx.sandbox_proxy.sandbox_identity.models import ResolvedSandbox
from onyx.sandbox_proxy.sandbox_identity.resolution import SandboxIdentityResolver
from onyx.sandbox_proxy.sandbox_identity.signed import (
    SandboxClaims,
    SignedIdentityVerifier,
)
from onyx.sandbox_proxy.sandbox_identity.signed_lookups import (
    CachedNodeSigningKeyLookup,
    CacheReplayGuard,
    CacheSandboxPlacementLookup,
)

OWNER = UUID("7c9e6679-7425-40de-944b-e07fc1f90ae7")
log = logging.getLogger("harness")


class PlacementNoDB(CacheSandboxPlacementLookup):
    """The real placement record check; a fixed owner instead of Postgres."""

    def owner_if_placed(self, claims: SandboxClaims) -> UUID | None:
        p = get_sandbox_placement(
            self._cache_factory(claims.tenant_id), claims.sandbox_id
        )
        ok = (
            p is not None
            and p.node_id == claims.node_id
            and p.generation == claims.generation
        )
        log.warning(
            "harness_placement sandbox=%s node=%s gen=%s placed=%s",
            claims.sandbox_id,
            claims.node_id,
            claims.generation,
            ok,
        )
        return OWNER if ok else None


class NoPodIdentity(SandboxIdentityResolver):
    def resolve_sandbox(self, src_ip: str) -> ResolvedSandbox | None:  # noqa: ARG002
        return None

    def resolve_session_by_id(
        self,
        session_id: UUID,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
    ) -> UUID | None:
        return None


class NoMatch(RequestEvaluator):
    def evaluate(
        self,
        request: http.Request,  # noqa: ARG002
        tenant_id: str,  # noqa: ARG002
        user_id: UUID,  # noqa: ARG002
    ) -> None:
        return None


def main() -> None:
    logging.basicConfig(
        level=logging.DEBUG, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    for noisy in ("hpack", "asyncio", "urllib3", "mitmproxy"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    def cache_factory(tenant_id: str) -> CacheBackend:
        return get_cache_backend(tenant_id=tenant_id)

    verifier = SignedIdentityVerifier(
        signing_keys=CachedNodeSigningKeyLookup(get_shared_cache_backend),
        placement=PlacementNoDB(cache_factory),
        replay_guard=CacheReplayGuard(cache_factory),
    )
    gate = GateAddon(
        identity=NoPodIdentity(),
        request_evaluator=NoMatch(),
        destination_policy=parse_destination_policy(""),
        cache_factory=cache_factory,
        proxy_instance_id="kvmtest",
        credential_dispatcher=CredentialInjectionDispatcher([]),
        signed_identity=verifier,
    )

    async def run() -> None:
        master = DumpMaster(
            options=Options(
                listen_host="127.0.0.1",
                listen_port=int(os.environ.get("HARNESS_PROXY_PORT", "8099")),
                confdir=os.environ.get("HARNESS_CONFDIR", "/opt/proxy/confdir"),
                mode=["regular"],
                ssl_insecure=False,
                rawtcp=False,
            ),
            with_termlog=False,
            with_dumper=False,
        )
        master.addons.add(gate)
        await master.run()

    asyncio.run(run(), loop_factory=UpstreamEventLoop)


if __name__ == "__main__":
    main()
