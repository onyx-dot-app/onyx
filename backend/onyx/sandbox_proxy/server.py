"""mitmproxy entrypoint for the sandbox egress proxy."""

import asyncio
import signal
import sys
import threading
from http.server import BaseHTTPRequestHandler
from http.server import HTTPServer

from mitmproxy.options import Options
from mitmproxy.tools.dump import DumpMaster

from onyx.sandbox_proxy.addons.passthrough import PassthroughAddon
from onyx.sandbox_proxy.ca import CABootstrap
from onyx.sandbox_proxy.ca import MaterializedCA
from onyx.sandbox_proxy.ca_k8s import K8sSecretCAStore
from onyx.sandbox_proxy.identity import IdentityResolver
from onyx.sandbox_proxy.identity_k8s import K8sInformerLookup
from onyx.server.features.build.configs import SANDBOX_NAMESPACE
from onyx.server.features.build.configs import SANDBOX_PROXY_HEALTHZ_PORT
from onyx.server.features.build.configs import SANDBOX_PROXY_LISTEN_PORT
from onyx.utils.logger import setup_logger

# If the watch isn't reachable in this window on startup, the proxy
# exits non-zero rather than serve traffic with unbacked identity.
_LOOKUP_INITIAL_SYNC_TIMEOUT_SECONDS = 60.0

_MITM_CONFDIR = "/var/run/sandbox-proxy/mitmproxy-confdir"

logger = setup_logger()


class _Readiness:
    def __init__(self) -> None:
        self.ca_ready = False
        self.lookup_ready = False
        self.draining = False

    def is_ready(self) -> bool:
        return self.ca_ready and self.lookup_ready and not self.draining


def _build_healthz_handler(
    readiness: _Readiness,
    lookup: K8sInformerLookup,
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


def _start_healthz_server(
    readiness: _Readiness, lookup: K8sInformerLookup
) -> HTTPServer:
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


def _build_mitm_options(ca_pem_path: str) -> Options:
    return Options(
        listen_host="0.0.0.0",  # noqa: S104 — container scope; pod network only
        listen_port=SANDBOX_PROXY_LISTEN_PORT,
        confdir=_MITM_CONFDIR,
        certs=[f"*={ca_pem_path}"],
        mode=["regular"],
        ssl_insecure=False,
        flow_detail=0,
    )


async def _run_master(master: DumpMaster) -> None:
    await master.run()


def _install_signal_handlers(
    loop: asyncio.AbstractEventLoop,
    master: DumpMaster,
    readiness: _Readiness,
    lookup: K8sInformerLookup,
) -> None:
    def _on_signal() -> None:
        if readiness.draining:
            return
        logger.info("SIGTERM received; flipping readiness and draining")
        readiness.draining = True
        lookup.stop()
        master.shutdown()

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

    materialized_ca = _bootstrap_ca()
    readiness.ca_ready = True
    logger.info("CA bootstrapped at %s", materialized_ca.pem_path)

    lookup = _build_lookup()
    readiness.lookup_ready = True
    logger.info("informer initial sync complete")

    _start_healthz_server(readiness, lookup)

    identity = IdentityResolver(ip_lookup=lookup)
    addon = PassthroughAddon(identity=identity)

    options = _build_mitm_options(str(materialized_ca.pem_path))
    master = DumpMaster(options=options, with_termlog=True, with_dumper=False)
    master.addons.add(addon)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _install_signal_handlers(loop, master, readiness, lookup)
    try:
        loop.run_until_complete(_run_master(master))
    finally:
        loop.close()

    logger.info("sandbox proxy exiting cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
