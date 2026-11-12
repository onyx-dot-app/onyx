"""Prototype guest agent of the host agent KVM tests (vsock port 52).

The kit root drive runs it as PID 1's last step (fc-init). The real guest
daemon replaces it in production.

Protocol on vsock port 52: one line per connection.
  ping             -> pong
  run <b64 bash>   -> runs script as the sandbox user, streams output, then "EXIT <code>"
  root <b64 bash>  -> same, as root
  netsetup <b64>   -> (root) installs the egress-proxy CA and turns on the proxy env for later scripts
  settime <ns>     -> (root) clock_settime(CLOCK_REALTIME, ns); replies the new realtime ns

Networking (the VM has no NIC):
  outbound: TCP 127.0.0.1:3128 -> vsock CID 2 port 3128 (host agent -> egress proxy).
  inbound:  vsock port P -> TCP 127.0.0.1:P for P in INBOUND_PORTS.
"""

import asyncio
import base64
import io
import os
import socket
import subprocess
import threading
import time
from collections.abc import Awaitable, Callable

PORT = 52
PROXY_PORT = 3128
HOST_CID = 2
INBOUND_PORTS = (3010, 4096)
CA_BUNDLE = "/etc/ssl/sandbox/ca-bundle.crt"
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"
NO_PROXY = "127.0.0.1,localhost"
BUF = 256 * 1024
NET_ON_FILE = "/run/fc-net-on"

ENV = dict(
    os.environ,
    HOME="/home/sandbox",
    PATH="/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin",
)
NET_ENV = {
    "HTTP_PROXY": PROXY_URL,
    "HTTPS_PROXY": PROXY_URL,
    "http_proxy": PROXY_URL,
    "https_proxy": PROXY_URL,
    "NO_PROXY": NO_PROXY,
    "no_proxy": NO_PROXY,
    "NODE_USE_ENV_PROXY": "1",
    "NODE_EXTRA_CA_CERTS": CA_BUNDLE,
    "REQUESTS_CA_BUNDLE": CA_BUNDLE,
    "SSL_CERT_FILE": CA_BUNDLE,
    "CURL_CA_BUNDLE": CA_BUNDLE,
    "GIT_SSL_CAINFO": CA_BUNDLE,
    "PIP_CERT": CA_BUNDLE,
}


def env() -> dict[str, str]:
    e = dict(ENV)
    if os.path.exists(NET_ON_FILE):
        e.update(NET_ENV)
    return e


NETSETUP = r"""
set -e
mkdir -p /run/ovl
for d in /etc/ssl /usr/local/share/ca-certificates /etc/ca-certificates; do
  [ -d "$d" ] || continue
  n=$(echo "$d" | tr / _); mkdir -p /run/ovl/$n/u /run/ovl/$n/w
  mount -t overlay overlay -o lowerdir=$d,upperdir=/run/ovl/$n/u,workdir=/run/ovl/$n/w $d
done
install -m 0644 /run/proxy-ca.crt /usr/local/share/ca-certificates/sandbox-proxy.crt
update-ca-certificates >/dev/null 2>&1
install -d -m 0755 /etc/ssl/sandbox
install -m 0644 /etc/ssl/certs/ca-certificates.crt /etc/ssl/sandbox/ca-bundle.crt
if command -v certutil >/dev/null; then
  su -s /bin/bash sandbox -c 'd=$HOME/.pki/nssdb; mkdir -p $d; [ -f $d/cert9.db ] || certutil -d sql:$d -N --empty-password; certutil -d sql:$d -A -t "C,," -n sandbox-proxy -i /run/proxy-ca.crt' && echo NSS_OK
fi
touch /run/fc-net-on
echo NETSETUP_OK
"""


def run_script(f: io.BufferedIOBase, script: str, as_root: bool) -> None:
    who = None if as_root else "sandbox"
    p = subprocess.Popen(
        ["bash", "-c", script],
        env=env(),
        cwd="/workspace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        user=who,
        group=who,
    )
    assert p.stdout is not None
    for out in p.stdout:
        f.write(out)
        f.flush()
    f.write(b"EXIT %d\n" % p.wait())


def handle(conn: socket.socket) -> None:
    f = conn.makefile("rwb")
    try:
        line = f.readline().decode().strip()
        if line == "ping":
            f.write(b"pong\n")
        elif line.startswith("settime "):
            time.clock_settime_ns(time.CLOCK_REALTIME, int(line.split()[1]))
            f.write(b"%d\n" % time.clock_gettime_ns(time.CLOCK_REALTIME))
        elif line.startswith("netsetup "):
            with open("/run/proxy-ca.crt", "wb") as ca:
                ca.write(base64.b64decode(line[9:]))
            p = subprocess.run(["bash", "-c", NETSETUP], capture_output=True)
            f.write(p.stdout + p.stderr + b"EXIT %d\n" % p.returncode)
        elif line.startswith(("run ", "root ")):
            verb, _, payload = line.partition(" ")
            run_script(f, base64.b64decode(payload).decode(), as_root=verb == "root")
        f.flush()
    finally:
        conn.close()


# ---------------------------------------------------------------- networking


async def pump(
    r: asyncio.StreamReader, w: asyncio.StreamWriter, full_close: bool = False
) -> None:
    try:
        while True:
            data = await r.read(BUF)
            if not data:
                break
            w.write(data)
            await w.drain()
        if full_close:
            w.close()  # Firecracker vsock does not pass a guest half-close (SHUT_WR) to the host UDS
        elif w.can_write_eof():
            w.write_eof()
    except (ConnectionError, OSError):
        pass


# (vsock writer, local writer) of live relay connections.
LIVE: set[tuple[asyncio.StreamWriter, asyncio.StreamWriter]] = set()


async def splice(
    r1: asyncio.StreamReader,
    w1: asyncio.StreamWriter,
    r2: asyncio.StreamReader,
    w2: asyncio.StreamWriter,
    close_w1_on_eof: bool = False,
) -> None:
    """r1/w1 = vsock side, r2/w2 = local TCP side."""
    pair = (w1, w2)
    LIVE.add(pair)
    try:
        await asyncio.gather(pump(r1, w2), pump(r2, w1, full_close=close_w1_on_eof))
    finally:
        LIVE.discard(pair)
    for w in (w1, w2):
        w.close()


async def outbound(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    s.setblocking(False)
    try:
        await asyncio.get_running_loop().sock_connect(s, (HOST_CID, PROXY_PORT))
    except OSError:
        s.close()
        w.close()
        return
    r2, w2 = await asyncio.open_connection(sock=s, limit=BUF)
    # prebuild fix: full close of the vsock side on client EOF. FC drops a guest SHUT_WR, so a half-close
    # leaves host relay + proxy connection open forever and leaks 2 guest fds per closed client connection.
    await splice(r2, w2, r, w, close_w1_on_eof=True)


def inbound_handler(
    port: int,
) -> Callable[[asyncio.StreamReader, asyncio.StreamWriter], Awaitable[None]]:
    async def h(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            r2, w2 = await asyncio.open_connection("127.0.0.1", port, limit=BUF)
        except OSError:
            w.close()
            return
        await splice(r, w, r2, w2, close_w1_on_eof=True)

    return h


async def net_main() -> None:
    await asyncio.start_server(
        outbound, "127.0.0.1", PROXY_PORT, limit=BUF, backlog=512
    )
    for port in INBOUND_PORTS:
        s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
        s.bind((socket.VMADDR_CID_ANY, port))
        s.listen(512)
        s.setblocking(False)
        await asyncio.start_server(inbound_handler(port), sock=s, limit=BUF)
    await asyncio.Event().wait()


def main() -> None:
    import resource

    resource.setrlimit(
        resource.RLIMIT_NOFILE, (65536, 65536)
    )  # prebuild fix: the default 1024 is far too low for a relay
    threading.Thread(target=lambda: asyncio.run(net_main()), daemon=True).start()
    s = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
    s.bind((socket.VMADDR_CID_ANY, PORT))
    s.listen(64)
    while True:
        try:
            conn, _ = s.accept()
        except OSError:  # prebuild fix: never let PID 1 die on accept errors (EMFILE -> guest kernel panic)
            time.sleep(0.05)
            continue
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
