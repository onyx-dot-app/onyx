"""Capture private guest process facts before Craft HTTP timeout teardown."""

from __future__ import annotations

import json
import os
import re
import selectors
import shutil
import subprocess
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

import httpx

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.server.features.build.configs import CRAFT_SANDBOX_RUNTIME, SANDBOX_NAMESPACE
from onyx.server.features.build.db.sandbox import get_sandbox_by_user_id
from onyx.server.features.build.sandbox.labels import (
    LABEL_K8S_COMPONENT,
    LABEL_K8S_COMPONENT_SANDBOX,
    LABEL_K8S_MANAGED_BY,
    LABEL_K8S_MANAGED_BY_ONYX,
    LABEL_SANDBOX_ID,
    LABEL_SANDBOX_PROTOCOL,
    LABEL_TENANT_ID,
    SANDBOX_PROTOCOL_VERSION,
)
from shared_configs.contextvars import get_current_tenant_id
from tests.integration.common_utils.craft_shim_diagnostics import (
    _fixed_facts,
    _unavailable,
)
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_CI_KUBE_CONTEXT = "kind-onyx-craft-ci"
_CI_NODE = "onyx-craft-ci-control-plane"
_MANAGED_PUSH_PROBE = """
import os
import signal
import stat
import sys
from contextlib import suppress
from pathlib import Path

sys.excepthook = lambda *_: None
signal.alarm(5)
rows = []
fd_types = {
    stat.S_IFIFO: 'fifo', stat.S_IFSOCK: 'socket', stat.S_IFCHR: 'char',
    stat.S_IFBLK: 'block', stat.S_IFDIR: 'directory', stat.S_IFREG: 'regular',
    stat.S_IFLNK: 'symlink',
}
wait_categories = {
    'pipe_read': {'pipe_read', 'anon_pipe_read', 'fifo_pipe_read',
                  'pipe_wait_readable'},
    'futex_wait': {'futex_wait_queue', 'futex_wait_queue_me', 'futex_wait',
                   'futex_wait_multiple', 'futex_do_wait', 'futex_sleep_multiple'},
    'child_wait': {'do_wait', 'kernel_wait4', 'kernel_waitid'},
    'flock_wait': {'flock_lock_inode_wait', 'locks_lock_inode_wait',
                   'posix_lock_inode_wait'},
    'file_io': {'io_schedule', 'folio_wait_bit_common', 'wait_on_page_bit_common',
                'filemap_get_pages', '__wait_on_buffer', 'jbd2_log_wait_commit'},
}
x86_64_syscalls = {
    0: 'read', 1: 'write', 17: 'read', 18: 'write', 19: 'read', 20: 'write',
    61: 'child_wait', 202: 'futex_wait', 247: 'child_wait',
    295: 'read', 296: 'write', 327: 'read', 328: 'write',
    449: 'futex_wait', 455: 'futex_wait',
}
native_x86_64 = os.uname().machine == 'x86_64'
for process in Path('/proc').iterdir():
    if not process.name.isascii() or not process.name.isdecimal():
        continue
    with suppress(OSError, ValueError, IndexError):
        with (process / 'cmdline').open('rb') as source:
            raw_argv = source.read(4096)
        argv = raw_argv.split(b'\\0')
        if len(raw_argv) == 4096 or not any(
            argv[index:index + 3] == [b'-m', b'onyx_guest', b'push-managed']
            for index in range(len(argv) - 2)
        ):
            continue
        with (process / 'stat').open() as source:
            fields = source.read(4096).rsplit(')', 1)[1].split()
        row = [f'pid={int(process.name)}', f'state={fields[0]}',
               f'utime_ticks={int(fields[11])}', f'stime_ticks={int(fields[12])}']
        wait = 'other'
        with suppress(OSError):
            with (process / 'wchan').open() as source:
                wchan = source.read(128).strip()
            wait = next((category for category, names in wait_categories.items()
                         if wchan in names), 'other')
        row.append(f'wait={wait}')
        syscall = 'unavailable'
        syscall_fd = None
        if native_x86_64:
            with suppress(OSError, ValueError, IndexError):
                with (process / 'syscall').open() as source:
                    fields = source.read(256).split()
                if len(fields) == 9 and fields[0].isascii() and fields[0].isdecimal():
                    syscall = x86_64_syscalls.get(int(fields[0]), 'other')
                    if syscall in {'read', 'write'}:
                        fd = int(fields[1], 16)
                        if 0 <= fd <= 2**31 - 1:
                            syscall_fd = fd
        row.append(f'syscall={syscall}')
        if syscall_fd is not None:
            row.append(f'syscall_fd={syscall_fd}')
        for fd in range(3):
            with suppress(OSError):
                kind = stat.S_IFMT((process / 'fd' / str(fd)).stat().st_mode)
                row.append(f'fd{fd}={fd_types.get(kind, "other")}')
        with suppress(OSError, ValueError, IndexError):
            with (process / 'status').open() as source:
                for line in source.read(4096).splitlines():
                    if line.startswith('VmRSS:'):
                        row.append(f'rss_kib={int(line.split()[1])}')
                        break
        rows.append('helper ' + ' '.join(row))
        if len(rows) == 16:
            break
summary = [f'helper_count={len(rows)}']
with suppress(OSError, ValueError, IndexError):
    with Path('/proc/meminfo').open() as source:
        for line in source.read(4096).splitlines():
            key = {'MemTotal:': 'total_kib', 'MemAvailable:': 'available_kib'}.get(
                line.split()[0]
            )
            if key:
                summary.append(f'{key}={int(line.split()[1])}')
print('summary ' + ' '.join(summary))
for row in rows:
    print(row)
with suppress(OSError, ValueError, IndexError):
    lock = Path('/run/onyx/managed.lock').stat()
    owners = set()
    waiters = set()
    with Path('/proc/locks').open() as source:
        for line in source.read(65536).splitlines():
            fields = line.split()
            waiting = fields[1] == '->'
            if waiting:
                fields.pop(1)
            if fields[1] != 'FLOCK':
                continue
            major, minor, inode = fields[5].split(':')
            if (int(major, 16), int(minor, 16), int(inode)) != (
                os.major(lock.st_dev), os.minor(lock.st_dev), lock.st_ino
            ):
                continue
            pids = waiters if waiting else owners
            if len(pids) < 16:
                pids.add(int(fields[4]))
    for key, pids in (('owner_pid', owners), ('waiter_pid', waiters)):
        for pid in sorted(pids):
            print(f'lock {key}={pid}')
"""


@contextmanager
def capture_guest_facts_on_read_timeout(user: DATestUser) -> Iterator[None]:
    try:
        yield
    except httpx.ReadTimeout:
        try:
            context = os.environ.get("SANDBOX_TEST_KUBE_CONTEXT")
            if (
                os.environ.get("GITHUB_ACTIONS") == "true"
                and context == _CI_KUBE_CONTEXT
                and os.environ.get("SANDBOX_TEST_FIRECRACKER") == "true"
                and os.environ.get("SANDBOX_TEST_FRONTEND_URL")
                and CRAFT_SANDBOX_RUNTIME == "kubernetes_firecracker"
                and client.base_url == httpx.URL("")
            ):
                target = _owned_target(user, context)
                if (
                    target is not None
                    and os.environ.get("SANDBOX_TEST_SHIM_PPROF") == "true"
                ):
                    try:
                        shim_facts = _owned_shim_facts(target)
                    except Exception:
                        shim_facts = _unavailable("capture_failed")
                    with suppress(Exception):
                        print(
                            f"Craft shim timeout facts; target_sandbox_id={target.sandbox_id} "
                            f"shim_forwarder_facts={shim_facts}",
                            flush=True,
                        )
                facts = _owned_guest_facts(target)
                print(
                    f"Craft HTTP read timeout; managed_push_facts={facts}", flush=True
                )
        except Exception as error:
            error_class = type(error).__name__
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", error_class) is None:
                error_class = "Exception"
            with suppress(Exception):
                print(
                    f"Craft timeout sample failed; exception={error_class}", flush=True
                )
        raise


@dataclass(frozen=True)
class _OwnedTarget:
    sandbox_id: UUID
    pod_uid: str
    node_name: str
    container_id: str
    command: tuple[str, ...]


def _owned_target(user: DATestUser, context: str) -> _OwnedTarget | None:
    user_id = UUID(user.id)
    tenant_id = get_current_tenant_id()
    with get_session_with_current_tenant() as db_session:
        sandbox = get_sandbox_by_user_id(db_session, user_id)
        if sandbox is None:
            return None
        if sandbox.user_id != user_id:
            raise ValueError("Sandbox ownership mismatch")
        sandbox_id = UUID(str(sandbox.id))
    command = ["kubectl", "--context", context, "--namespace", SANDBOX_NAMESPACE]
    return _read_owned_pod(sandbox_id, tenant_id, tuple(command))


def _read_owned_pod(
    sandbox_id: UUID, tenant_id: str, command: tuple[str, ...], timeout: float = 5.0
) -> _OwnedTarget:
    pod_name = f"sandbox-{sandbox_id.hex}"
    metadata = subprocess.run(
        [*command, "get", "pod", pod_name, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=True,
    )
    pod = json.loads(metadata.stdout)
    labels = pod["metadata"]["labels"]
    if (
        pod["metadata"]["name"] != pod_name
        or pod["metadata"]["namespace"] != SANDBOX_NAMESPACE
        or not isinstance(pod["metadata"]["uid"], str)
        or not pod["metadata"]["uid"]
        or pod["metadata"].get("deletionTimestamp")
        or labels.get(LABEL_SANDBOX_ID) != str(sandbox_id)
        or labels.get(LABEL_TENANT_ID) != tenant_id
        or labels.get(LABEL_SANDBOX_PROTOCOL) != SANDBOX_PROTOCOL_VERSION
        or labels.get(LABEL_K8S_MANAGED_BY) != LABEL_K8S_MANAGED_BY_ONYX
        or labels.get(LABEL_K8S_COMPONENT) != LABEL_K8S_COMPONENT_SANDBOX
        or pod["spec"]["runtimeClassName"] != "kata-fc"
        or [container["name"] for container in pod["spec"]["containers"]] != ["sandbox"]
        or [container["name"] for container in pod["spec"]["initContainers"]]
        != ["sandbox-firewall"]
    ):
        raise ValueError("Sandbox pod shape mismatch")
    statuses = pod.get("status", {}).get("containerStatuses", [])
    container_id = ""
    if (
        len(statuses) == 1
        and statuses[0].get("name") == "sandbox"
        and "running" in statuses[0].get("state", {})
    ):
        container_id = statuses[0].get("containerID", "")
    return _OwnedTarget(
        sandbox_id,
        pod["metadata"]["uid"],
        pod["spec"].get("nodeName", ""),
        container_id,
        command,
    )


def _owned_guest_facts(target: _OwnedTarget | None) -> str:
    if target is None:
        return "unavailable"
    pod_name = f"sandbox-{target.sandbox_id.hex}"
    output = subprocess.run(
        [
            *target.command,
            "exec",
            pod_name,
            "-c",
            "sandbox",
            "--",
            "python3",
            "-c",
            _MANAGED_PUSH_PROBE,
        ],
        capture_output=True,
        text=True,
        timeout=20.0,
        check=True,
    )
    return (
        f"target_sandbox_id={target.sandbox_id} | {_managed_push_facts(output.stdout)}"
    )


def _bounded_command(
    command: list[str], payload: bytes, deadline: float, maximum: int
) -> tuple[int, bytes]:
    with subprocess.Popen(
        command,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    ) as process:
        if process.stdin is None or process.stdout is None:
            raise RuntimeError("Missing diagnostic pipe")
        try:
            process.stdin.write(payload)
            process.stdin.close()
            output = bytearray()
            with selectors.DefaultSelector() as selector:
                selector.register(process.stdout, selectors.EVENT_READ)
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError
                    chunk = os.read(
                        process.stdout.fileno(), min(4096, maximum + 1 - len(output))
                    )
                    if not chunk:
                        break
                    output.extend(chunk)
                    if len(output) > maximum:
                        raise OverflowError
            return process.wait(timeout=max(0.001, deadline - time.monotonic())), bytes(
                output
            )
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=0.5)


def _owned_shim_facts(target: _OwnedTarget | None) -> str:
    if target is None:
        return _unavailable("missing_target")
    if (
        target.node_name != _CI_NODE
        or re.fullmatch(r"containerd://[0-9a-f]{64}", target.container_id) is None
    ):
        return _unavailable("missing_target")
    if (
        not os.path.isfile("/usr/bin/python3")
        or os.uname().sysname != "Linux"
        or shutil.which("sudo") is None
        or shutil.which("timeout") is None
    ):
        return _unavailable("unsupported")
    deadline = time.monotonic() + 8
    try:
        code, output = _bounded_command(
            [
                "docker",
                "inspect",
                "--type",
                "container",
                "--format",
                '{{.State.Pid}} {{index .Config.Labels "io.x-k8s.kind.cluster"}}',
                _CI_NODE,
            ],
            b"",
            min(deadline, time.monotonic() + 1),
            128,
        )
        match = re.fullmatch(rb"([1-9][0-9]{0,9}) onyx-craft-ci\n", output)
        if code or match is None:
            return _unavailable("missing_target")
        payload = json.dumps(
            {
                "node_pid": int(match[1]),
                "container_id": target.container_id.removeprefix("containerd://"),
                "pod_uid": target.pod_uid,
                "namespace": SANDBOX_NAMESPACE,
            }
        ).encode("ascii")
        helper = Path(__file__).with_name("craft_shim_diagnostics.py")
        code, output = _bounded_command(
            [
                "sudo",
                "-n",
                "timeout",
                "--signal=KILL",
                "6s",
                "/usr/bin/python3",
                "-I",
                str(helper),
            ],
            payload,
            min(deadline, time.monotonic() + 6.5),
            256,
        )
        if code:
            return _unavailable(
                "deadline" if code in {124, 137, 142, -9, -14} else "denied"
            )
        facts = _fixed_facts(output.decode("ascii"))
        if time.monotonic() >= deadline:
            return _unavailable("deadline")
        try:
            current = _read_owned_pod(
                target.sandbox_id,
                get_current_tenant_id(),
                target.command,
                deadline - time.monotonic(),
            )
        except (KeyError, TypeError, ValueError, subprocess.CalledProcessError):
            return _unavailable("target_changed")
        if current != target:
            return _unavailable("target_changed")
        return facts
    except (TimeoutError, subprocess.TimeoutExpired):
        return _unavailable("deadline")
    except OverflowError:
        return _unavailable("oversized")
    except Exception:
        return _unavailable("capture_failed")


def _managed_push_facts(output: str) -> str:
    numeric_fields = {
        "summary": {
            "helper_count": 16,
            "total_kib": 2**63 - 1,
            "available_kib": 2**63 - 1,
        },
        "helper": {
            "pid": 2**31 - 1,
            "syscall_fd": 2**31 - 1,
            "utime_ticks": 2**63 - 1,
            "stime_ticks": 2**63 - 1,
            "rss_kib": 2**63 - 1,
        },
        "lock": {"owner_pid": 2**31 - 1, "waiter_pid": 2**31 - 1},
    }
    categories = {
        "state": set("RSDZTtXxIPW"),
        "wait": {
            "pipe_read",
            "futex_wait",
            "child_wait",
            "flock_wait",
            "file_io",
            "other",
        },
        "syscall": {
            "read",
            "write",
            "futex_wait",
            "child_wait",
            "other",
            "unavailable",
        },
        **{
            f"fd{fd}": {
                "fifo",
                "socket",
                "char",
                "block",
                "directory",
                "regular",
                "symlink",
                "other",
            }
            for fd in range(3)
        },
    }
    remaining_rows = {"summary": 1, "helper": 16, "lock": 32}
    rows = []
    for line in output[:4096].splitlines():
        kind, _, raw_fields = line.partition(" ")
        if kind not in remaining_rows or not remaining_rows[kind]:
            continue
        facts: dict[str, str] = {}
        for field in raw_fields.split():
            key, _, value = field.partition("=")
            maximum = numeric_fields[kind].get(key)
            if (
                maximum is not None
                and value.isascii()
                and value.isdecimal()
                and len(value) <= 20
                and int(value) <= maximum
                and (int(value) > 0 or not key.endswith("pid"))
            ):
                facts[key] = str(int(value))
            elif kind == "helper" and value in categories.get(key, set()):
                facts[key] = value
        if facts.get("syscall") not in {"read", "write"}:
            facts.pop("syscall_fd", None)
        if facts and (kind != "helper" or "pid" in facts):
            rows.append(
                kind + " " + " ".join(f"{key}={value}" for key, value in facts.items())
            )
            remaining_rows[kind] -= 1
    return " | ".join(rows) or "unavailable"
