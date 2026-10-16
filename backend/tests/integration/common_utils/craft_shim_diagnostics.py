"""Private stdlib-only reader for one CI-owned Kata shim."""

from __future__ import annotations

import http.client
import io
import json
import os
import re
import signal
import socket
import stat
import struct
import sys
import time
from pathlib import Path

_CATEGORIES = (
    "fifo_read",
    "rpc_send",
    "rpc_response_wait",
    "rpc_other",
    "forwarder_other",
)
_REASONS = frozenset(
    {
        "disabled",
        "missing_target",
        "target_changed",
        "ambiguous_target",
        "unsupported",
        "denied",
        "deadline",
        "oversized",
        "unrecognized_profile",
        "capture_failed",
    }
)
_MAX_PROFILE = 1024 * 1024
_COPY = "github.com/kata-containers/kata-containers/src/runtime/pkg/containerd-shim-v2.ioCopy.func1"
_WRITE = "github.com/kata-containers/kata-containers/src/runtime/virtcontainers.(*stdinStream).Write"
_RPC = "github.com/kata-containers/kata-containers/src/runtime/virtcontainers/pkg/agent/protocols/grpc.(*agentserviceClient).WriteStdin"
_TTRPC = "github.com/containerd/ttrpc.(*Client)."
_HEX = re.compile(r"[0-9a-f]{64}")
if sys.platform == "linux":
    _SO_PEERCRED = socket.SO_PEERCRED
else:
    _SO_PEERCRED = 0


def _unavailable(reason: str) -> str:
    return f"availability=unavailable reason={reason if reason in _REASONS else 'capture_failed'}"


def _fixed_facts(output: str) -> str:
    if len(output) > 256:
        return _unavailable("oversized")
    text = output.removesuffix("\n")
    if text in {_unavailable(reason) for reason in _REASONS}:
        return text
    parts = text.split(" ")
    if len(parts) != 6 or parts[0] != "availability=observed":
        return _unavailable("capture_failed")
    for category, part in zip(_CATEGORIES, parts[1:], strict=True):
        key, _, value = part.partition("=")
        if (
            key != category
            or re.fullmatch(r"0|[1-9][0-9]{0,4}", value) is None
            or int(value) > 65535
        ):
            return _unavailable("capture_failed")
    return text


def _classify_profile(profile: bytes) -> str:
    if len(profile) > _MAX_PROFILE:
        return _unavailable("oversized")
    try:
        text = profile.decode("utf-8", errors="strict")
    except UnicodeError:
        return _unavailable("unrecognized_profile")
    if not text.endswith("\n"):
        return _unavailable("unrecognized_profile")
    counts = dict.fromkeys(_CATEGORIES, 0)
    blocks = text.strip().split("\n\n")
    if not blocks:
        return _unavailable("unrecognized_profile")
    for block in blocks:
        lines = block.splitlines()
        if (
            not lines
            or re.fullmatch(r"goroutine [0-9]+ \[[^\]\n]+\]:", lines[0]) is None
        ):
            return _unavailable("unrecognized_profile")
        frames: list[tuple[str, str]] = []
        for index, line in enumerate(lines[1:], 1):
            if (
                line.startswith(("\t", "created by "))
                or line == "...additional frames elided..."
            ):
                continue
            match = re.fullmatch(r"(.+)\([^\n]*\)", line)
            if (
                match is None
                or index + 1 >= len(lines)
                or not lines[index + 1].startswith("\t")
            ):
                return _unavailable("unrecognized_profile")
            frames.append((match[1], lines[index + 1]))
        names = [name for name, _ in frames]
        if not names:
            return _unavailable("unrecognized_profile")
        state = lines[0].split("[", 1)[1].split(",", 1)[0].removesuffix("]:")
        if _COPY not in names:
            continue
        category = "forwarder_other"
        if _WRITE in names and _RPC in names:
            category = "rpc_other"
            # ttrpc v1.2.7 dispatch selects for the response at client.go:545.
            if state == "select" and any(
                name == _TTRPC + "dispatch"
                and re.search(r"/ttrpc@v1\.2\.7/client\.go:545(?: |$)", source)
                for name, source in frames
            ):
                category = "rpc_response_wait"
            elif (
                _TTRPC + "createStream" in names
                and (state in {"IO wait", "sync.Mutex.Lock", "semacquire"})
                and any(
                    name in names
                    for name in (
                        "github.com/containerd/ttrpc.(*channel).send",
                        "sync.(*Mutex).Lock",
                        "internal/sync.(*Mutex).lockSlow",
                    )
                )
            ):
                category = "rpc_send"
        elif (
            "github.com/containerd/fifo.(*fifo).Read" in names
            and (state in {"IO wait", "syscall"})
            and "os.(*File).Read" in names
            and any(
                name in names
                for name in (
                    "internal/poll.(*FD).Read",
                    "syscall.Read",
                    "syscall.Syscall",
                )
            )
        ):
            category = "fifo_read"
        counts[category] += 1
        if counts[category] > 65535:
            return _unavailable("oversized")
    return "availability=observed " + " ".join(
        f"{key}={counts[key]}" for key in _CATEGORIES
    )


def _read(path: Path, maximum: int = 65536) -> bytes:
    with path.open("rb") as source:
        value = source.read(maximum + 1)
    if len(value) > maximum:
        raise OverflowError
    return value


def _annotations(path: Path, pod_uid: str, namespace: str, kind: str) -> dict[str, str]:
    value = json.loads(_read(path))
    annotations = value["annotations"]
    if not isinstance(annotations, dict) or any(
        not isinstance(key, str) or not isinstance(item, str)
        for key, item in annotations.items()
    ):
        raise ValueError
    if (
        annotations.get("io.kubernetes.cri.container-type") != kind
        or annotations.get("io.kubernetes.cri.sandbox-uid") != pod_uid
        or annotations.get("io.kubernetes.cri.sandbox-namespace") != namespace
    ):
        raise ValueError
    return annotations


def _process_identity(
    pid: int, node_pid: int, shim_pid: int, sandbox: str
) -> tuple[int, int, int, int]:
    process = Path(f"/proc/{pid}")
    namespace = (process / "ns/pid").stat().st_ino
    if namespace != Path(f"/proc/{node_pid}/ns/pid").stat().st_ino:
        raise ValueError
    status = _read(process / "status", 8192).decode("ascii")
    mappings = [
        line.split()[1:] for line in status.splitlines() if line.startswith("NSpid:")
    ]
    if (
        len(mappings) != 1
        or len(mappings[0]) != 2
        or [int(value) for value in mappings[0]] != [pid, shim_pid]
    ):
        raise ValueError
    executable = os.readlink(process / "exe")
    if executable != "/opt/kata/bin/containerd-shim-kata-v2":
        raise ValueError
    argv = _read(process / "cmdline", 8192).split(b"\0")
    if [argv[index + 1] for index in range(len(argv) - 1) if argv[index] == b"-id"] != [
        sandbox.encode("ascii")
    ]:
        raise ValueError
    if [
        argv[index + 1]
        for index in range(len(argv) - 1)
        if argv[index] == b"-namespace"
    ] != [b"k8s.io"]:
        raise ValueError
    executable_stat = (process / "exe").stat()
    return (
        _start_time(process),
        namespace,
        executable_stat.st_dev,
        executable_stat.st_ino,
    )


def _start_time(process: Path) -> int:
    return int(_read(process / "stat", 8192).rsplit(b")", 1)[1].split()[19])


class _HeaderReader(io.BufferedReader):
    remaining = 16384

    def readline(self, size: int | None = -1, /) -> bytes:
        value = super().readline(
            min(self.remaining + 1, size)
            if size is not None and size >= 0
            else self.remaining + 1
        )
        self.remaining -= len(value)
        if self.remaining < 0:
            raise OverflowError
        return value


def _read_profile(peer: socket.socket, deadline: float) -> str:
    peer.settimeout(max(0.001, deadline - time.monotonic()))
    peer.sendall(
        b"GET /debug/pprof/goroutine?debug=2 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    )
    with http.client.HTTPResponse(peer) as response:
        response.fp = _HeaderReader(response.fp.detach())
        response.begin()
        if response.status != 200:
            return _unavailable("unsupported")
        if response.getheader("Content-Encoding") is not None or response.getheader(
            "Transfer-Encoding", ""
        ).lower() not in {"", "chunked"}:
            return _unavailable("unsupported")
        lengths = response.headers.get_all("Content-Length", [])
        if len(lengths) > 1 or (lengths and response.chunked):
            return _unavailable("unrecognized_profile")
        if lengths and (not lengths[0].isascii() or not lengths[0].isdecimal()):
            return _unavailable("unrecognized_profile")
        if lengths and int(lengths[0]) > _MAX_PROFILE:
            return _unavailable("oversized")
        body = bytearray()
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError
            peer.settimeout(remaining)
            chunk = response.read1(min(16384, _MAX_PROFILE + 1 - len(body)))
            if not chunk:
                break
            body.extend(chunk)
            if len(body) > _MAX_PROFILE:
                return _unavailable("oversized")
        if response.length not in {None, 0}:
            return _unavailable("unrecognized_profile")
        return _classify_profile(bytes(body))


def _capture(target: dict[str, object], deadline: float) -> str:
    node_pid, container = target["node_pid"], target["container_id"]
    pod_uid, namespace = target["pod_uid"], target["namespace"]
    if (
        type(node_pid) is not int
        or node_pid <= 1
        or not isinstance(container, str)
        or _HEX.fullmatch(container) is None
        or not isinstance(pod_uid, str)
        or re.fullmatch(r"[0-9a-f-]{36}", pod_uid) is None
        or not isinstance(namespace, str)
        or re.fullmatch(r"[a-z0-9][a-z0-9-]{0,62}", namespace) is None
    ):
        return _unavailable("missing_target")
    root = Path(f"/proc/{node_pid}/root")
    node_identity = (
        Path(f"/proc/{node_pid}/ns/pid").stat().st_ino,
        _start_time(Path(f"/proc/{node_pid}")),
    )
    bundles = root / "run/containerd/io.containerd.runtime.v2.task/k8s.io"
    workload = bundles / container / "config.json"
    annotations = _annotations(workload, pod_uid, namespace, "container")
    sandbox = annotations.get("io.kubernetes.cri.sandbox-id", "")
    if _HEX.fullmatch(sandbox) is None:
        return _unavailable("missing_target")
    bundle = bundles / sandbox
    sandbox_config = bundle / "config.json"
    sandbox_annotations = _annotations(sandbox_config, pod_uid, namespace, "sandbox")
    if sandbox_annotations.get("io.kubernetes.cri.sandbox-id") != sandbox:
        return _unavailable("missing_target")
    pid_file = bundle / "shim.pid"
    shim_pid = int(_read(pid_file, 32))
    if shim_pid <= 1:
        return _unavailable("missing_target")
    monitor = root / "run/vc/sbs" / sandbox / "shim-monitor.sock"
    before = monitor.stat()
    if (
        not stat.S_ISSOCK(before.st_mode)
        or before.st_uid != 0
        or stat.S_IMODE(before.st_mode) != 0o600
    ):
        return _unavailable("denied")
    directory_fd = os.open(monitor.parent, os.O_RDONLY | os.O_DIRECTORY)
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as peer:
            peer.settimeout(max(0.001, deadline - time.monotonic()))
            peer.connect(f"/proc/self/fd/{directory_fd}/shim-monitor.sock")
            pid, uid, gid = struct.unpack(
                "3i", peer.getsockopt(socket.SOL_SOCKET, _SO_PEERCRED, 12)
            )
            if uid != 0 or gid != 0:
                return _unavailable("denied")
            identity = _process_identity(pid, node_pid, shim_pid, sandbox)
            connected = monitor.stat()
            if (connected.st_dev, connected.st_ino) != (before.st_dev, before.st_ino):
                return _unavailable("target_changed")
            facts = _read_profile(peer, deadline)
            try:
                after = monitor.stat()
                changed = (
                    (after.st_dev, after.st_ino, after.st_mode, after.st_uid)
                    != (before.st_dev, before.st_ino, before.st_mode, before.st_uid)
                    or identity != _process_identity(pid, node_pid, shim_pid, sandbox)
                    or int(_read(pid_file, 32)) != shim_pid
                    or annotations
                    != _annotations(workload, pod_uid, namespace, "container")
                    or sandbox_annotations
                    != _annotations(sandbox_config, pod_uid, namespace, "sandbox")
                    or node_identity
                    != (
                        Path(f"/proc/{node_pid}/ns/pid").stat().st_ino,
                        _start_time(Path(f"/proc/{node_pid}")),
                    )
                )
            except (OSError, ValueError, KeyError):
                changed = True
            if changed:
                return _unavailable("target_changed")
            return facts
    finally:
        os.close(directory_fd)


def _main() -> None:
    sys.excepthook = lambda *_: None
    signal.alarm(5)
    deadline = time.monotonic() + 5
    facts = _unavailable("capture_failed")
    try:
        if sys.platform != "linux" or os.geteuid() != 0 or not _SO_PEERCRED:
            facts = _unavailable("unsupported")
        else:
            caller_mappings = [
                line.split()[1:]
                for line in _read(Path("/proc/self/status"), 8192).splitlines()
                if line.startswith(b"NSpid:")
            ]
            if len(caller_mappings) != 1 or caller_mappings[0] != [
                str(os.getpid()).encode("ascii")
            ]:
                print(_unavailable("unsupported"), flush=True)
                return
            target = json.loads(sys.stdin.buffer.read(1025))
            if isinstance(target, dict):
                facts = _capture(target, deadline)
    except PermissionError:
        facts = _unavailable("denied")
    except FileNotFoundError:
        facts = _unavailable("missing_target")
    except (TimeoutError, socket.timeout):
        facts = _unavailable("deadline")
    except OverflowError:
        facts = _unavailable("oversized")
    except Exception:
        pass
    print(_fixed_facts(facts), flush=True)


if __name__ == "__main__":
    _main()
