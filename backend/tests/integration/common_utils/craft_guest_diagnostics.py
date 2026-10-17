"""Capture private guest process facts before Craft HTTP timeout teardown."""

from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager, suppress
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
from tests.integration.common_utils.http_client import client
from tests.integration.common_utils.test_models import DATestUser

_CI_KUBE_CONTEXT = "kind-onyx-craft-ci"
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
                facts = _owned_guest_facts(user, context)
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


def _owned_guest_facts(user: DATestUser, context: str) -> str:
    user_id = UUID(user.id)
    tenant_id = get_current_tenant_id()
    with get_session_with_current_tenant() as db_session:
        sandbox = get_sandbox_by_user_id(db_session, user_id)
        if sandbox is None:
            return "unavailable"
        if sandbox.user_id != user_id:
            raise ValueError("Sandbox ownership mismatch")
        sandbox_id = UUID(str(sandbox.id))
    pod_name = f"sandbox-{sandbox_id.hex}"
    command = ["kubectl", "--context", context, "--namespace", SANDBOX_NAMESPACE]
    metadata = subprocess.run(
        [*command, "get", "pod", pod_name, "-o", "json"],
        capture_output=True,
        text=True,
        timeout=5.0,
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
    output = subprocess.run(
        [
            *command,
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
    return f"target_sandbox_id={sandbox_id} | {_managed_push_facts(output.stdout)}"


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
