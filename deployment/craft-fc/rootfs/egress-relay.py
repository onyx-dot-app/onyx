#!/usr/local/bin/python3 -IS
"""In-guest egress relay. Installed as /craft-fc/bin/egress-relay.

The VM has no network card. Programs use HTTP(S)_PROXY=http://127.0.0.1:3128.
Each TCP connection to 127.0.0.1:3128 is spliced to a vsock connection to the
host (CID 2, port 3128). Firecracker maps that to the host UDS
<vsock uds>_3128, where the node agent relays it to the egress proxy.

When one side closes or fails, both sides are closed. Firecracker does not pass
a guest half-close (SHUT_WR) to the host, so a half-close would leave the host
relay and the proxy connection open, and leak guest file descriptors.

SIGHUP resets every live connection (TCP RST to the client, buffered data is
dropped) and keeps listening. Send it after a snapshot restore: clients with
pooled connections or open streams then get an error at once, instead of a
hang.

craft-init runs it as uid 65534. `-IS`: standard library only, no site packages
and no PYTHON* variables.
"""

import asyncio
import os
import resource
import signal
import socket
import struct
import sys

LISTEN_HOST = "127.0.0.1"
LISTEN_PORT = int(os.environ.get("CRAFT_EGRESS_LISTEN_PORT", "3128"))
HOST_CID = 2
HOST_PORT = int(os.environ.get("CRAFT_EGRESS_VSOCK_PORT", "3128"))
BUF = 256 * 1024

_live: set[tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = set()


def _log(msg: str) -> None:
    print(f"egress-relay: {msg}", file=sys.stderr, flush=True)


async def _pump(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(BUF):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass


async def _handle(
    client_reader: asyncio.StreamReader, client_writer: asyncio.StreamWriter
) -> None:
    sock: socket.socket | None = None
    try:
        sock = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        sock.setblocking(False)
        await asyncio.get_running_loop().sock_connect(sock, (HOST_CID, HOST_PORT))
        host_reader, host_writer = await asyncio.open_connection(sock=sock, limit=BUF)
    except OSError as e:
        if sock is not None:
            sock.close()
        client_writer.close()
        _log(f"vsock connect failed: {e}")
        return
    pair = (client_writer, host_writer)
    _live.add(pair)
    pumps = [
        asyncio.ensure_future(_pump(client_reader, host_writer)),
        asyncio.ensure_future(_pump(host_reader, client_writer)),
    ]
    try:
        await asyncio.wait(pumps, return_when=asyncio.FIRST_COMPLETED)
    finally:
        for task in pumps:
            task.cancel()
        _close(pair)


def _close(pair: tuple[asyncio.StreamWriter, asyncio.StreamWriter]) -> None:
    _live.discard(pair)
    for writer in pair:
        writer.close()


def _reset() -> None:
    count = len(_live)
    for pair in list(_live):
        _live.discard(pair)
        client_sock = pair[0].get_extra_info("socket")
        if client_sock is not None:
            # Linger 0: close() sends RST, not FIN after the buffered data.
            client_sock.setsockopt(
                socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
            )
        for writer in pair:
            writer.transport.abort()
    _log(f"SIGHUP: reset {count} connections")


async def _main() -> None:
    loop = asyncio.get_running_loop()
    loop.add_signal_handler(signal.SIGHUP, _reset)
    server = await asyncio.start_server(
        _handle, LISTEN_HOST, LISTEN_PORT, limit=BUF, backlog=512
    )
    _log(f"listening on {LISTEN_HOST}:{LISTEN_PORT} -> vsock {HOST_CID}:{HOST_PORT}")
    async with server:
        await server.serve_forever()


def main() -> None:
    _, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    resource.setrlimit(resource.RLIMIT_NOFILE, (hard, hard))
    asyncio.run(_main())


if __name__ == "__main__":
    main()
