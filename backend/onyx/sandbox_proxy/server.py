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

from onyx.cache.interface import CacheBackend
from onyx.db.engine.sql_engine import get_session_with_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.sandbox_proxy.action_matcher import SlackSendMessageMatcher
from onyx.sandbox_proxy.addons.gate import GateAddon
from onyx.sandbox_proxy.addons.passthrough import PassthroughAddon
from onyx.sandbox_proxy.ca import CABootstrap
from onyx.sandbox_proxy.ca import MaterializedCA
from onyx.sandbox_proxy.ca_k8s import K8sSecretCAStore
from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity import SandboxIPLookup
from onyx.sandbox_proxy.identity_k8s import K8sInformerLookup
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_HEALTHZ_PORT
from onyx.server.features.build.configs import SANDBOX_PROXY_LISTEN_PORT
from onyx.utils.logger import setup_logger

_DB_POOL_SIZE = 4
_DB_MAX_OVERFLOW = 4
_DB_APP_NAME = "sandbox_proxy"

# Outer cap on the SIGTERM drain. ``GateAddon.drain_inflight`` writes
# terminal decisions, wakes parked coroutines, and then awaits the
# tracked request() tasks so the connections close cleanly. This bound
# only fires if something hangs (a stuck DB / Redis call or a
# coroutine that can't make progress); the K8s
# ``terminationGracePeriodSeconds`` is the outer envelope.
_DRAIN_TIMEOUT_SECONDS = 10.0

# If the watch isn't reachable in this window on startup, the proxy
# exits non-zero rather than serve traffic with unbacked identity.
_LOOKUP_INITIAL_SYNC_TIMEOUT_SECONDS = 60.0

# Must be the parent of ca._DEFAULT_CA_PEM_PATH.
_MITM_CONFDIR = "/var/run/sandbox-proxy/mitmproxy-confdir"

logger = setup_logger()


class _Readiness:
    def __init__(self) -> None:
        self.ca_ready = False
        self.lookup_ready = False
        self.draining = False


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
                # is_synced() flips on watch reconnects, so we report
                # not-ready if the informer has lost its watch even
                # after initial sync.
                healthy = (
                    readiness.ca_ready and lookup.is_synced() and not readiness.draining
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
    return CABootstrap(store=K8sSecretCAStore()).ensure_ca()


def _build_lookup() -> K8sInformerLookup:
    lookup = K8sInformerLookup()
    lookup.start()
    synced = lookup.wait_for_initial_sync(
        timeout_seconds=_LOOKUP_INITIAL_SYNC_TIMEOUT_SECONDS
    )
    if not synced:
        raise RuntimeError(
            "Sandbox IP lookup did not complete initial sync within "
            f"{_LOOKUP_INITIAL_SYNC_TIMEOUT_SECONDS:.1f}s; refusing to "
            "serve traffic with unbacked identity"
        )
    return lookup


def _build_cache_factory() -> "Callable[[str], CacheBackend]":
    """Return a tenant_id → CacheBackend factory for the gate addon.

    The API side uses ``get_cache_backend(tenant_id=...)`` so the
    gate must do the same to share the same Redis key prefix.
    """
    from onyx.cache.factory import get_cache_backend

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


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    master: DumpMaster,
    readiness: _Readiness,
    lookup: SandboxIPLookup,
    gate: GateAddon,
) -> None:
    async def _drain_and_shutdown() -> None:
        try:
            await asyncio.wait_for(
                gate.drain_inflight(), timeout=_DRAIN_TIMEOUT_SECONDS
            )
        except asyncio.TimeoutError:
            logger.warning(
                "gate drain exceeded %.1fs; exiting anyway",
                _DRAIN_TIMEOUT_SECONDS,
            )
        except Exception:
            logger.exception("gate drain raised; exiting anyway")
        master.shutdown()

    def _on_signal() -> None:
        if readiness.draining:
            return
        logger.info("SIGTERM received; flipping readiness and draining")
        readiness.draining = True
        lookup.stop()
        # Schedule the drain on the event loop; mitmproxy will exit
        # once master.shutdown() runs from inside _drain_and_shutdown.
        loop.create_task(_drain_and_shutdown())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, _on_signal)


def main() -> int:
    logger.info(
        "starting sandbox proxy listen=%d healthz=%d namespace=%s",
        SANDBOX_PROXY_LISTEN_PORT,
        SANDBOX_PROXY_HEALTHZ_PORT,
        SANDBOX_NAMESPACE,
    )

    readiness = _Readiness()

    SqlEngine.set_app_name(_DB_APP_NAME)
    SqlEngine.init_engine(pool_size=_DB_POOL_SIZE, max_overflow=_DB_MAX_OVERFLOW)

    materialized_ca = _bootstrap_ca()
    readiness.ca_ready = True
    logger.info("CA bootstrapped at %s", materialized_ca.pem_path)

    lookup = _build_lookup()
    healthz_server: HTTPServer | None = None
    try:
        readiness.lookup_ready = True
        logger.info("informer initial sync complete")

        healthz_server = _start_healthz_server(readiness, lookup)

        identity = IdentityResolver(ip_lookup=lookup)
        passthrough = PassthroughAddon(identity=identity)
        proxy_instance_id = os.environ.get("HOSTNAME") or str(uuid.uuid4())
        gate = GateAddon(
            identity=identity,
            action_matcher=SlackSendMessageMatcher(),
            db_session_factory=lambda tenant_id: get_session_with_tenant(
                tenant_id=tenant_id
            ),
            cache_factory=_build_cache_factory(),
            proxy_instance_id=proxy_instance_id,
        )

        # DumpMaster's constructor binds to the running event loop.
        async def _async_main() -> None:
            options = _build_mitm_options()
            master = DumpMaster(options=options, with_termlog=True, with_dumper=False)
            master.addons.add(passthrough)
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

    logger.info("sandbox proxy exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
