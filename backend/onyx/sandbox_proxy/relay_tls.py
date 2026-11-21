"""mTLS listener for the Firecracker host agent relays.

The relays send signed egress tokens. This listener keeps them off the pod
network in clear text: it requires a client certificate from the relay CA,
optionally pins its SAN, and then pipes the connection to the plain proxy
listener on loopback. The gate checks the signed token there, as for any
other connection.
"""

import asyncio
import os
import ssl
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, ConfigDict

from onyx.utils.logger import setup_logger

logger = setup_logger()

_CHUNK = 64 * 1024
_HANDSHAKE_TIMEOUT_S = 10.0


class RelayTLSConfig(BaseModel):
    model_config = ConfigDict(frozen=True, strict=True)

    port: int
    cert_path: str
    key_path: str
    client_ca_path: str
    # DNS or URI SANs; the client leaf must have one. Empty: any certificate
    # that the client CA signed.
    allowed_sans: frozenset[str]


def build_relay_tls_context(config: RelayTLSConfig) -> ssl.SSLContext:
    """Raises if a file does not load, so a bad setup stops the proxy."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.minimum_version = ssl.TLSVersion.TLSv1_3
    context.verify_mode = ssl.CERT_REQUIRED
    context.load_cert_chain(config.cert_path, config.key_path)
    context.load_verify_locations(cafile=config.client_ca_path)
    return context


def peer_sans(peercert: dict[str, Any] | None) -> list[str]:
    if not peercert:
        return []
    return [
        value
        for kind, value in peercert.get("subjectAltName", ())
        if kind in ("DNS", "URI")
    ]


def loopback_for(listen_host: str) -> str:
    """The address that reaches a listener bound to listen_host."""
    if listen_host in ("", "0.0.0.0"):  # noqa: S104 — wildcard bind
        return "127.0.0.1"
    if listen_host == "::":
        return "::1"
    return listen_host


class _ContextFiles:
    """The TLS context for the files on disk. It rebuilds the context on the
    next connection after a file changes (a rotated Secret), and keeps the
    last good context if the new files do not load."""

    def __init__(self, config: RelayTLSConfig) -> None:
        self._config = config
        self._stamp = self._read_stamp()
        self._context = build_relay_tls_context(config)

    def _read_stamp(self) -> tuple[tuple[int, int], ...]:
        paths = (
            self._config.cert_path,
            self._config.key_path,
            self._config.client_ca_path,
        )
        stats = [os.stat(path) for path in paths]
        return tuple((st.st_mtime_ns, st.st_size) for st in stats)

    def current(self) -> ssl.SSLContext:
        try:
            stamp = self._read_stamp()
            if stamp != self._stamp:
                self._context = build_relay_tls_context(self._config)
                self._stamp = stamp
                logger.info("relay mTLS certificate files reloaded")
        except (OSError, ValueError):
            logger.exception("relay mTLS reload failed; keeping the last good files")
        return self._context


class RelayTLSListener:
    def __init__(
        self,
        config: RelayTLSConfig,
        listen_host: str,
        upstream_host: str,
        upstream_port: int,
    ) -> None:
        self._config = config
        self._listen_host = listen_host
        self._upstream = (upstream_host, upstream_port)
        # Raises if a file does not load, so a bad setup stops the proxy.
        self._files = _ContextFiles(config)
        self._server: asyncio.Server | None = None

    async def start(self) -> None:
        # TLS starts per connection (start_tls), so each handshake uses the
        # current files and a failed handshake is logged.
        self._server = await asyncio.start_server(
            self._handle,
            host=self._listen_host,
            port=self._config.port,
        )
        logger.info(
            "relay mTLS listening on [%s]:%d (pinned SANs: %s)",
            self._listen_host,
            self._config.port,
            sorted(self._config.allowed_sans) or "any from the client CA",
        )

    @property
    def port(self) -> int:
        """The bound port (useful when config.port is 0)."""
        if self._server is None:
            raise RuntimeError("relay mTLS listener is not started")
        return self._server.sockets[0].getsockname()[1]

    async def close(self) -> None:
        if self._server is None:
            return
        self._server.close()
        self._server.close_clients()
        await self._server.wait_closed()

    def _allowed(self, sans: Iterable[str]) -> bool:
        allowed = self._config.allowed_sans
        return not allowed or any(san in allowed for san in sans)

    async def _handle(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        try:
            await writer.start_tls(
                self._files.current(), ssl_handshake_timeout=_HANDSHAKE_TIMEOUT_S
            )
        except (OSError, TimeoutError) as e:
            logger.warning(
                "relay_tls_rejected reason=handshake peer=%s error=%r", peer, e
            )
            writer.transport.abort()
            return
        sans = peer_sans(writer.get_extra_info("peercert"))
        if not self._allowed(sans):
            logger.warning("relay_tls_rejected reason=san peer=%s sans=%s", peer, sans)
            await _close(writer)
            return
        logger.debug("relay_tls_accepted peer=%s sans=%s", peer, sans)
        try:
            up_reader, up_writer = await asyncio.open_connection(*self._upstream)
        except OSError:
            logger.exception("relay_tls_upstream_failed peer=%s", peer)
            await _close(writer)
            return
        # Close both sides when either one ends, like the relay: the guest
        # vsock carries no half-close.
        tasks = [
            asyncio.create_task(_pipe(reader, up_writer)),
            asyncio.create_task(_pipe(up_reader, writer)),
        ]
        try:
            await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await _close(up_writer)
            await _close(writer)


async def _pipe(src: asyncio.StreamReader, dst: asyncio.StreamWriter) -> None:
    try:
        while data := await src.read(_CHUNK):
            dst.write(data)
            await dst.drain()
    except OSError:
        return


async def _close(writer: asyncio.StreamWriter) -> None:
    writer.close()
    try:
        await writer.wait_closed()
    except OSError:
        pass
