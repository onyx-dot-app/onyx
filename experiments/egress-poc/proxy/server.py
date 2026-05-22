"""Proxy entrypoint. Boots mitmproxy as a library with three listeners:

  - 8444  regular HTTP-proxy mode (explicit-mode sandbox)
  - 8443  transparent TLS mode    (transparent-mode sandbox, HTTPS)
  - 8081  transparent HTTP mode   (transparent-mode sandbox, plain HTTP)

The Onyx CA is decrypted at boot and placed in mitmproxy's confdir as the
combined-PEM file mitmproxy expects for on-the-fly leaf-cert signing.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from addon import EgressAddon
from ca_loader import prepare_ca_file

# mitmproxy is installed in the proxy container's venv only.
from mitmproxy import options  # ty: ignore[unresolved-import]
from mitmproxy.tools.dump import DumpMaster  # ty: ignore[unresolved-import]

# /tmp is the conventional confdir location inside the proxy container; this
# path is never reachable from the host.
CONFDIR = "/tmp/onyx-mitm"  # noqa: S108


def _configure_logging() -> None:
    level = os.getenv("LOG_LEVEL", "INFO").upper()
    # We emit our own JSON audit lines via print(); mitmproxy's own logger
    # uses logging at INFO and noisier, so squash it unless explicitly asked.
    logging.basicConfig(level=level, format="%(message)s", stream=sys.stderr)
    logging.getLogger("mitmproxy").setLevel(
        logging.INFO if level == "DEBUG" else logging.WARNING
    )


async def main() -> None:
    _configure_logging()
    prepare_ca_file(CONFDIR)

    opts = options.Options(
        confdir=CONFDIR,
        mode=[
            "regular@0.0.0.0:8444",
            "transparent@0.0.0.0:8443",
            "transparent@0.0.0.0:8081",
        ],
        ssl_insecure=False,
        showhost=True,
        # Do NOT contact the real upstream during TLS handshake to sniff its
        # cert. Leaf certs are generated purely from SNI; our addon overrides
        # the destination in the request hook before any upstream connection
        # is attempted.
        upstream_cert=False,
    )
    master = DumpMaster(opts, with_termlog=False, with_dumper=False)
    # connection_strategy is registered by the proxyserver addon (added by
    # DumpMaster); set it AFTER master construction. "lazy" defers upstream
    # connection until our request hook has had a chance to rewrite the
    # destination via the broker-supplied upstream_url.
    master.options.update(connection_strategy="lazy")
    master.addons.add(EgressAddon())

    logging.getLogger("egress-poc.proxy").info(
        "egress-poc proxy listening: regular=8444 transparent_https=8443 transparent_http=8081"
    )
    await master.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
