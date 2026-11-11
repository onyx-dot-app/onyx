"""Minimal in-guest agent over vsock (port 52): kit agent + work-net networking + kernel618 probes.

Protocol on vsock port 52: one line per connection.
  ping             -> pong
  ocready          -> waits until opencode serve answers, replies "ready"
  run <b64 bash>   -> runs script as the sandbox user, streams output, then "EXIT <code>"
  root <b64 bash>  -> same, as root
  netsetup <b64>   -> (root) installs the egress-proxy CA and turns on the proxy env for later scripts
  setenv <b64>     -> extra KEY=VAL lines for scripts + opencode
  startoc          -> starts `opencode serve` (with the proxy env once netsetup ran)
  clock            -> "<CLOCK_REALTIME ns> <CLOCK_MONOTONIC ns> <CLOCK_BOOTTIME ns>"
  settime <ns>     -> (root) clock_settime(CLOCK_REALTIME, ns); replies the new realtime ns
  pyrand           -> 8 bytes from this long-lived process's Python `random` state + 8 bytes of os.urandom
  tarout <b64 sh>  -> (root, prebuild) runs the tar pipeline and streams its raw stdout, then closes
  tarin <b64 sh>   -> (root, prebuild) feeds the rest of the connection (until host EOF) to the script's stdin; "EXIT <rc>"
  netreset [rst]   -> (prebuild) closes every live relay connection (both sides); rst = TCP reset to the client
  netstat          -> number of live relay connections
At boot, starts `opencode serve` when the kernel cmdline contains fcmode=template.

Networking (the VM has no NIC):
  outbound: TCP 127.0.0.1:3128 -> vsock CID 2 port 3128 (host agent -> egress proxy).
  inbound:  vsock port P -> TCP 127.0.0.1:P for P in INBOUND_PORTS.
"""

import asyncio
import base64
import os
import random
import socket
import subprocess
import threading
import time
import urllib.request

PORT = 52
PROXY_PORT = 3128
HOST_CID = 2
INBOUND_PORTS = (3010, 4096)
CA_BUNDLE = "/etc/ssl/sandbox/ca-bundle.crt"
PROXY_URL = f"http://127.0.0.1:{PROXY_PORT}"
NO_PROXY = "127.0.0.1,localhost"
BUF = 256 * 1024
NET_ON_FILE = "/run/fc-net-on"
EXTRA_ENV_FILE = "/run/fc-extra-env"

ENV = dict(
    os.environ,
    HOME="/home/sandbox",
    PATH="/home/sandbox/.opencode/bin:/workspace/.venv/bin:/usr/local/bin:/usr/bin:/bin",
    OPENCODE_DISABLE_MODELS_FETCH="1",
    XDG_DATA_HOME="/workspace/sessions/.opencode-data",
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


def opencode_up() -> bool:
    try:
        urllib.request.build_opener(urllib.request.ProxyHandler({})).open(
            "http://127.0.0.1:4096/doc", timeout=1
        )
        return True
    except Exception:
        return False


def env() -> dict[str, str]:
    e = dict(ENV)
    if os.path.exists(NET_ON_FILE):
        e.update(NET_ENV)
    if os.path.exists(EXTRA_ENV_FILE):
        for line in open(EXTRA_ENV_FILE):
            if "=" in line:
                k, v = line.rstrip("\n").split("=", 1)
                e[k] = v
    return e


def start_opencode() -> None:
    subprocess.Popen(
        [
            "opencode",
            "serve",
            "--hostname",
            "0.0.0.0",  # noqa: S104 - inside the guest VM
            "--port",
            "4096",
            "--print-logs",
        ],
        env=env(),
        user="sandbox",
        group="sandbox",
        cwd="/workspace",
        stdout=open("/tmp/opencode.log", "wb"),  # noqa: S108 - inside the guest VM
        stderr=subprocess.STDOUT,
    )


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


def run_script(f, script: str, as_root: bool) -> None:  # noqa: ANN001
    who = {} if as_root else {"user": "sandbox", "group": "sandbox"}
    p = subprocess.Popen(
        ["bash", "-c", script],
        env=env(),
        cwd="/workspace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        **who,
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
        elif line == "clock":
            f.write(
                b"%d %d %d\n"
                % (
                    time.clock_gettime_ns(time.CLOCK_REALTIME),
                    time.clock_gettime_ns(time.CLOCK_MONOTONIC),
                    time.clock_gettime_ns(time.CLOCK_BOOTTIME),
                )
            )
        elif line.startswith("settime "):
            time.clock_settime_ns(time.CLOCK_REALTIME, int(line.split()[1]))
            f.write(b"%d\n" % time.clock_gettime_ns(time.CLOCK_REALTIME))
        elif line == "pyrand":
            f.write(
                b"%016x %s\n" % (random.getrandbits(64), os.urandom(8).hex().encode())
            )
        elif line == "ocready":
            deadline = time.time() + 120
            while time.time() < deadline and not opencode_up():
                time.sleep(0.02)
            f.write(b"ready\n" if opencode_up() else b"timeout\n")
        elif line == "startoc":
            start_opencode()
            f.write(b"started\n")
        elif line.startswith("netsetup "):
            with open("/run/proxy-ca.crt", "wb") as ca:
                ca.write(base64.b64decode(line[9:]))
            p = subprocess.run(["bash", "-c", NETSETUP], capture_output=True)
            f.write(p.stdout + p.stderr + b"EXIT %d\n" % p.returncode)
        elif line.startswith("setenv "):
            with open(EXTRA_ENV_FILE, "wb") as ef:
                ef.write(base64.b64decode(line[7:]))
            f.write(b"ok\n")
        elif line.startswith("tarout "):
            p = subprocess.Popen(
                ["bash", "-c", base64.b64decode(line[7:]).decode()],
                stdout=subprocess.PIPE,
                stderr=open("/run/tarout.err", "wb"),
                cwd="/",
            )
            assert p.stdout is not None
            while True:
                b = p.stdout.read(BUF)
                if not b:
                    break
                f.write(b)
            f.flush()
            open("/run/tarout.rc", "w").write(str(p.wait()))
        elif line.startswith("tarin "):
            p = subprocess.Popen(
                ["bash", "-c", base64.b64decode(line[6:]).decode()],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd="/",
            )
            assert p.stdin is not None and p.stdout is not None
            n = 0
            while True:
                b = f.read1(BUF)
                if not b:
                    break
                n += len(b)
                p.stdin.write(b)
            p.stdin.close()
            out = p.stdout.read()
            rc = p.wait()
            # FC turns the host SHUT_WR into a full close, so this reply is usually lost: also leave a file
            open("/run/tarin.rc", "w").write(
                "EXIT %d BYTES %d %s\n"
                % (rc, n, out.decode(errors="replace").strip()[-200:])
            )
            f.write(out + b"BYTES %d\nEXIT %d\n" % (n, rc))
        elif line.startswith("netreset"):
            n = net_reset("rst" in line)
            f.write(b"closed %d\n" % n)
        elif line == "netstat":
            f.write(b"live %d\n" % len(LIVE))
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


LIVE: set = set()  # (vsock writer, local writer) of live relay connections
LOOP: list = []


def net_reset(rst: bool) -> int:
    """Init fix for stale pooled connections after restore: drop every relay connection, so client pools see a dead socket."""
    import struct

    done = threading.Event()
    count = [0]

    def _do() -> None:
        for pair in list(LIVE):
            for w in pair:
                if rst and w is pair[1]:
                    try:
                        w.get_extra_info("socket").setsockopt(
                            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                        )
                    except OSError:
                        pass
                w.close()
            LIVE.discard(pair)
            count[0] += 1
        done.set()

    LOOP[0].call_soon_threadsafe(_do)
    done.wait(5)
    return count[0]


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


def inbound_handler(port: int):  # noqa: ANN201
    async def h(r: asyncio.StreamReader, w: asyncio.StreamWriter) -> None:
        try:
            r2, w2 = await asyncio.open_connection("127.0.0.1", port, limit=BUF)
        except OSError:
            w.close()
            return
        await splice(r, w, r2, w2, close_w1_on_eof=True)

    return h


async def net_main() -> None:
    LOOP.append(asyncio.get_running_loop())
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
    if "fcmode=template" in open("/proc/cmdline").read():
        start_opencode()
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


main()
