"""mitmproxy entrypoint for the sandbox egress proxy."""

import asyncio
import os
import signal
import sys
import threading
import uuid
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from onyx.cache.factory import get_cache_backend
from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import SqlEngine
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.backend import build_ca_store
from onyx.sandbox_proxy.backend import build_ip_lookup
from onyx.sandbox_proxy.ca import CABootstrap
from onyx.sandbox_proxy.ca import MaterializedCA
from onyx.sandbox_proxy.credential_injection import CredentialInjectionDispatcher
from onyx.sandbox_proxy.credential_injection import CredentialResolver
from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.sandbox_proxy.request_evaluator import ExternalAppRequestEvaluator
from onyx.sandbox_proxy.resolvers.external_app import ExternalAppResolver
from onyx.sandbox_proxy.resolvers.llm_provider_key import LLMProviderKeyResolver
from onyx.sandbox_proxy.resolvers.onyx_pat import OnyxPatResolver
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_HEALTHZ_PORT
from onyx.server.features.build.configs import SANDBOX_PROXY_LISTEN_PORT
from onyx.utils.logger import setup_logger
from onyx.utils.variable_functionality import set_is_ee_based_on_env_variable

_DB_POOL_SIZE = 4
_DB_MAX_OVERFLOW = 4
_DB_APP_NAME = "sandbox_proxy"

# Cap on the SIGTERM drain; only fires if `GateAddon.drain_inflight` hangs.
_DRAIN_TIMEOUT_S = 10.0

# Startup sync deadline; past it the proxy exits rather than serve traffic with
# unbacked identity.
_LOOKUP_INITIAL_SYNC_TIMEOUT_S = 60.0

# Default suits prod (root in /var/run/ tmpfs, K8s-standard); env-tunable so
# local-dev runs without root can point at /tmp.
_MITM_CONFDIR = os.environ.get(
    "SANDBOX_PROXY_MITM_CONFDIR",
    "/var/run/sandbox-proxy/mitmproxy-confdir",
)

logger = setup_logger()


class _Readiness:
    def __init__(self) -> None:
        self.ca_ready = False
        self.lookup_ready = False
        self.shutting_down = False


def _build_healthz_handler(
    readiness: _Readiness,
    lookup: SandboxIPLookup,
) -> type[BaseHTTPRequestHandler]:
    class _HealthzHandler(BaseHTTPRequestHandler):
        def log_message(
            self,
            format: str,  # noqa: ARG002 — stdlib API contract
            *args: object,  # noqa: ARG002
        ) -> None:
            return

        def do_GET(self) -> None:
            if self.path == "/healthz":
                # is_synced() flips false on watch loss, so a reconnecting
                # informer reports not-ready even after initial sync.
                healthy = (
                    readiness.ca_ready
                    and lookup.is_synced()
                    and not readiness.shutting_down
                )
                if healthy:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"ok\n")
                else:
                    self.send_response(503)
                    self.send_header("Content-Type", "text/plain")
                    self.end_headers()
                    self.wfile.write(b"not ready\n")
                return

            self.send_response(404)
            self.end_headers()

    return _HealthzHandler


def _start_healthz_server(readiness: _Readiness, lookup: SandboxIPLookup) -> HTTPServer:
    handler = _build_healthz_handler(readiness, lookup)
    server = HTTPServer(
        ("0.0.0.0", SANDBOX_PROXY_HEALTHZ_PORT),  # noqa: S104 — container scope
        handler,
    )
    thread = threading.Thread(
        target=server.serve_forever,
        name="sandbox-proxy-healthz",
        daemon=True,
    )
    thread.start()
    logger.info("healthz listening on 0.0.0.0:%d", SANDBOX_PROXY_HEALTHZ_PORT)
    return server


def _bootstrap_ca() -> MaterializedCA:
    # Pass pem_path explicitly so it tracks _MITM_CONFDIR. ca.py's default
    # points at /var/run/...; we cannot let the two drift, since mitmproxy
    # auto-loads $confdir/mitmproxy-ca.pem and would otherwise never see what
    # CABootstrap wrote.
    return CABootstrap(
        store=build_ca_store(),
        pem_path=f"{_MITM_CONFDIR}/mitmproxy-ca.pem",
    ).ensure_ca()


def _build_cache_factory() -> Callable[[str], CacheBackend]:
    """
    tenant_id -> CacheBackend; Must match the API side's namespace to share
    keys.
    """

    def _factory(tenant_id: str) -> CacheBackend:
        return get_cache_backend(tenant_id=tenant_id)

    return _factory


def _build_mitm_options() -> Options:
    return Options(
        listen_host="0.0.0.0",  # noqa: S104 — container scope; pod network only
        listen_port=SANDBOX_PROXY_LISTEN_PORT,
        confdir=_MITM_CONFDIR,
        mode=["regular"],
        ssl_insecure=False,
    )


async def _run_master(master: DumpMaster) -> None:
    await master.run()


def build_resolvers() -> list[CredentialResolver]:
    """Builds the registered credential resolvers, in first-claim-wins order.

    Host-claim sets are designed to be disjoint (external-app requests are
    attributed by the matcher; host-only resolvers added later claim their own
    canonical hosts). Order is a safety net against accidental overlap, not a
    designed-in priority.
    """
    return [OnyxPatResolver(), LLMProviderKeyResolver(), ExternalAppResolver()]


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    master: DumpMaster,
    readiness: _Readiness,
    lookup: SandboxIPLookup,
    gate: GateAddon,
) -> None:
    async def _drain_and_shutdown() -> None:
        try:
            await asyncio.wait_for(gate.drain_inflight(), timeout=_DRAIN_TIMEOUT_S)
        except asyncio.TimeoutError:
            logger.warning(
                "Gate drain exceeded %.1fs; Exiting anyway.",
                _DRAIN_TIMEOUT_S,
            )
        except Exception:
            logger.exception("Gate drain raised; Exiting anyway.")
        master.shutdown()

    def _on_signal() -> None:
        if readiness.shutting_down:
            return
        logger.info("SIGTERM received; Flipping readiness and draining.")
        readiness.shutting_down = True
        lookup.stop()
        loop.create_task(_drain_and_shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_signal)


def main() -> int:
    set_is_ee_based_on_env_variable()

    logger.info(
        "Starting sandbox proxy listen=%d healthz=%d namespace=%s",
        SANDBOX_PROXY_LISTEN_PORT,
        SANDBOX_PROXY_HEALTHZ_PORT,
        SANDBOX_NAMESPACE,
    )

    readiness = _Readiness()

    SqlEngine.set_app_name(_DB_APP_NAME)
    SqlEngine.init_engine(pool_size=_DB_POOL_SIZE, max_overflow=_DB_MAX_OVERFLOW)

    # Bind healthz before the blocking CA bootstrap and informer sync below, so
    # the probe endpoint answers from t=0 — reporting 503 (not connection-refused)
    # until startup finishes. Otherwise a slow startup k8s call leaves the port
    # unbound and the liveness probe SIGKILLs the pod mid-boot. ca_ready and
    # is_synced() are false pre-startup, so /healthz stays not-ready until
    # genuinely ready.
    lookup = build_ip_lookup()
    healthz_server: HTTPServer | None = None
    try:
        healthz_server = _start_healthz_server(readiness, lookup)

        materialized_ca = _bootstrap_ca()
        readiness.ca_ready = True
        logger.info("CA bootstrapped at %s", materialized_ca.pem_path)

        lookup.start()
        if not lookup.wait_for_initial_sync(
            timeout_seconds=_LOOKUP_INITIAL_SYNC_TIMEOUT_S
        ):
            raise RuntimeError(
                "Sandbox IP lookup did not complete initial sync within "
                f"{_LOOKUP_INITIAL_SYNC_TIMEOUT_S:.1f}s; refusing to serve traffic "
                "with unbacked identity."
            )
        readiness.lookup_ready = True
        logger.info("Informer initial sync complete.")

        identity = IdentityResolver(ip_lookup=lookup)
        proxy_instance_id = os.environ.get("HOSTNAME") or str(uuid.uuid4())
        resolvers = build_resolvers()
        logger.info(
            "Credential resolvers registered: %s",
            [type(r).__name__ for r in resolvers],
        )
        gate = GateAddon(
            identity=identity,
            request_evaluator=ExternalAppRequestEvaluator(),
            cache_factory=_build_cache_factory(),
            proxy_instance_id=proxy_instance_id,
            credential_dispatcher=CredentialInjectionDispatcher(resolvers),
        )

        # DumpMaster binds to the running event loop in its constructor.
        async def _async_main() -> None:
            options = _build_mitm_options()
            master = DumpMaster(options=options, with_termlog=False, with_dumper=False)
            master.addons.add(gate)
            _install_signal_handlers(
                asyncio.get_running_loop(),
                master,
                readiness,
                lookup,
                gate,
            )
            await _run_master(master)

        asyncio.run(_async_main())
    finally:
        lookup.stop()
        if healthz_server is not None:
            healthz_server.shutdown()
            healthz_server.server_close()

    logger.info("Sandbox proxy exiting cleanly.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
