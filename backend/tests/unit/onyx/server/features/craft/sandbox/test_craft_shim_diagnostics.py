"""Fixed projection and bounded Unix HTTP controls for the private shim reader."""

from __future__ import annotations

import json
import os
import signal
import socket
import stat
import struct
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.integration.common_utils import craft_guest_diagnostics as guest
from tests.integration.common_utils import craft_shim_diagnostics as subject

_CANARY = "secret-label-argument-address-header-error"
_ZERO = "availability=observed fifo_read=0 rpc_send=0 rpc_response_wait=0 rpc_other=0 forwarder_other=0"


def _stack(frames: list[tuple[str, str]], state: str = "IO wait") -> bytes:
    return (
        "goroutine 27 ["
        + state
        + "]:\n"
        + "\n".join(f"{name}({_CANARY})\n\t{source} +0x123" for name, source in frames)
        + "\n"
    ).encode()


def _copy_frames() -> list[tuple[str, str]]:
    return [
        ("io.copyBuffer", "/go/src/io/io.go:429"),
        (subject._COPY, "/kata/stream.go:112"),
    ]


def _rpc_frames() -> list[tuple[str, str]]:
    return [
        (subject._RPC, "/kata/agent_ttrpc.pb.go:474"),
        (subject._WRITE, "/kata/iostream.go:63"),
        *_copy_frames(),
    ]


@pytest.mark.parametrize(
    ("frames", "state", "expected"),
    [
        (
            [
                ("internal/poll.(*FD).Read", "/go/src/internal/poll/fd_unix.go:165"),
                ("os.(*File).Read", "/go/src/os/file.go:144"),
                ("github.com/containerd/fifo.(*fifo).Read", "/fifo@v1.1.0/fifo.go:178"),
                *_copy_frames(),
            ],
            "IO wait, 2 minutes",
            "fifo_read=1 rpc_send=0 rpc_response_wait=0 rpc_other=0 forwarder_other=0",
        ),
        (
            [
                (
                    "github.com/containerd/ttrpc.(*channel).send",
                    "/ttrpc@v1.2.7/channel.go:144",
                ),
                (subject._TTRPC + "createStream", "/ttrpc@v1.2.7/client.go:431"),
                *_rpc_frames(),
            ],
            "IO wait",
            "fifo_read=0 rpc_send=1 rpc_response_wait=0 rpc_other=0 forwarder_other=0",
        ),
        (
            [
                (
                    "internal/sync.(*Mutex).lockSlow",
                    "/go/src/internal/sync/mutex.go:149",
                ),
                (subject._TTRPC + "createStream", "/ttrpc@v1.2.7/client.go:399"),
                *_rpc_frames(),
            ],
            "sync.Mutex.Lock",
            "fifo_read=0 rpc_send=1 rpc_response_wait=0 rpc_other=0 forwarder_other=0",
        ),
        (
            [
                (
                    subject._TTRPC + "dispatch",
                    "/go/pkg/mod/github.com/containerd/ttrpc@v1.2.7/client.go:545",
                ),
                *_rpc_frames(),
            ],
            "select",
            "fifo_read=0 rpc_send=0 rpc_response_wait=1 rpc_other=0 forwarder_other=0",
        ),
        (
            [
                (subject._TTRPC + "dispatch", "/ttrpc@v1.2.7/client.go:538"),
                *_rpc_frames(),
            ],
            "select",
            "fifo_read=0 rpc_send=0 rpc_response_wait=0 rpc_other=1 forwarder_other=0",
        ),
        (
            [
                (subject._TTRPC + "dispatch", "/ttrpc@v1.2.8/client.go:545"),
                *_rpc_frames(),
            ],
            "select",
            "fifo_read=0 rpc_send=0 rpc_response_wait=0 rpc_other=1 forwarder_other=0",
        ),
        (
            _copy_frames(),
            "runnable",
            "fifo_read=0 rpc_send=0 rpc_response_wait=0 rpc_other=0 forwarder_other=1",
        ),
    ],
)
def test_pinned_live_stack_categories_emit_only_fixed_counts(
    frames: list[tuple[str, str]],
    state: str,
    expected: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    facts = subject._classify_profile(_stack(frames, state))
    assert facts == "availability=observed " + expected
    assert _CANARY not in facts
    assert capsys.readouterr() == ("", "")


def test_stack_ancestry_must_be_in_the_same_goroutine() -> None:
    unrelated = _stack(_rpc_frames()[:-3], "select")
    assert subject._classify_profile(unrelated + b"\n" + _stack(_copy_frames())) == (
        "availability=observed fifo_read=0 rpc_send=0 rpc_response_wait=0 rpc_other=0 forwarder_other=1"
    )


@pytest.mark.parametrize(
    "profile",
    [
        b"",
        b"bad\n",
        b"goroutine 1 [select]:\ninvalid\n",
        b"\xff\n",
        b"goroutine 1 [select]:\n",
        b"x" * (1024 * 1024 + 1),
    ],
)
def test_invalid_or_oversized_profiles_cannot_emit_sensitive_content(
    profile: bytes,
) -> None:
    assert subject._classify_profile(profile) in {
        "availability=unavailable reason=unrecognized_profile",
        "availability=unavailable reason=oversized",
    }


@pytest.mark.parametrize(
    "output",
    [
        _ZERO + " " + _CANARY,
        _ZERO.replace("fifo_read=0", "fifo_read=65536"),
        _ZERO.replace("fifo_read=0", "fifo_read=00"),
        _ZERO.replace("fifo_read=0", "fifo_read=-1"),
        "availability=unavailable reason=" + _CANARY,
        _ZERO + "\n" + _CANARY,
        _CANARY * 100,
    ],
)
def test_parent_rejects_non_schema_child_output(output: str) -> None:
    assert subject._fixed_facts(output).startswith("availability=unavailable reason=")
    assert _CANARY not in subject._fixed_facts(output)


@contextmanager
def _unix_peer(
    _tmp_path: Path, response: bytes, delay: float = 0
) -> Iterator[tuple[socket.socket, list[bytes]]]:
    requests: list[bytes] = []
    with (
        tempfile.TemporaryDirectory(prefix="shim-", dir="/tmp") as directory,
        socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server,
    ):
        path = Path(directory) / "http.sock"
        server.bind(str(path))
        server.listen(1)
        server.settimeout(2)

        def serve() -> None:
            with server.accept()[0] as connection:
                requests.append(connection.recv(1024))
                if delay:
                    time.sleep(delay)
                with suppress(BrokenPipeError):
                    connection.sendall(response)

        thread = threading.Thread(target=serve)
        thread.start()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(path))
                yield client, requests
        finally:
            thread.join(timeout=3)
            assert not thread.is_alive()


@pytest.mark.parametrize("chunked", [False, True])
def test_real_unix_http_accepts_standard_framing_privately(
    tmp_path: Path, chunked: bool, capsys: pytest.CaptureFixture[str]
) -> None:
    body = _stack([("runtime.gopark", "/go/src/runtime/proc.go:460")], "select")
    if chunked:
        headers = b"Transfer-Encoding: chunked\r\n"
        wire = (
            f"{len(body):x}\r\n".encode()
            + body
            + b"\r\n0\r\nPrivate-Trailer: "
            + _CANARY.encode()
            + b"\r\n\r\n"
        )
    else:
        headers = f"Content-Length: {len(body)}\r\n".encode()
        wire = body
    response = (
        b"HTTP/1.1 200 OK\r\nPrivate-Header: "
        + _CANARY.encode()
        + b"\r\n"
        + headers
        + b"\r\n"
        + wire
    )
    with _unix_peer(tmp_path, response) as (client, requests):
        assert subject._read_profile(client, time.monotonic() + 1) == _ZERO
    assert requests == [
        b"GET /debug/pprof/goroutine?debug=2 HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n"
    ]
    assert capsys.readouterr() == ("", "")


@pytest.mark.parametrize(
    ("response", "expected"),
    [
        (b"HTTP/1.1 403 secret\r\n\r\nsecret", "unsupported"),
        (b"HTTP/1.1 200 OK\r\nContent-Encoding: gzip\r\n\r\nsecret", "unsupported"),
        (b"HTTP/1.1 200 OK\r\nTransfer-Encoding: secret\r\n\r\nsecret", "unsupported"),
        (b"HTTP/1.1 200 OK\r\nContent-Length: 1048577\r\n\r\n", "oversized"),
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 10\r\nContent-Length: 10\r\n\r\n",
            "unrecognized_profile",
        ),
        (
            b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\nshort",
            "unrecognized_profile",
        ),
    ],
)
def test_real_unix_http_rejects_unsupported_or_partial_responses(
    tmp_path: Path, response: bytes, expected: str
) -> None:
    with _unix_peer(tmp_path, response) as (client, _):
        assert (
            subject._read_profile(client, time.monotonic() + 1)
            == "availability=unavailable reason=" + expected
        )


def test_real_unix_http_header_and_decoded_body_caps(tmp_path: Path) -> None:
    with _unix_peer(
        tmp_path, b"HTTP/1.1 200 OK\r\nPrivate: " + b"a" * 16384 + b"\r\n\r\n"
    ) as (client, _):
        with pytest.raises(OverflowError):
            subject._read_profile(client, time.monotonic() + 1)
    response = (
        b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n100001\r\n"
        + b"x" * 1048577
        + b"\r\n0\r\n\r\n"
    )
    with _unix_peer(tmp_path, response) as (client, _):
        assert (
            subject._read_profile(client, time.monotonic() + 1)
            == "availability=unavailable reason=oversized"
        )


def test_real_unix_http_slow_response_obeys_deadline(tmp_path: Path) -> None:
    with _unix_peer(tmp_path, b"HTTP/1.1 200 OK\r\n\r\n", 0.15) as (client, _):
        with pytest.raises(TimeoutError):
            subject._read_profile(client, time.monotonic() + 0.04)


@pytest.mark.parametrize(
    "field,value",
    [
        ("node_pid", 0),
        ("container_id", "../private"),
        ("pod_uid", _CANARY),
        ("namespace", "../private"),
    ],
)
def test_bad_owned_target_is_refused_before_filesystem_or_http(
    field: str, value: object
) -> None:
    target: dict[str, object] = {
        "node_pid": 22,
        "container_id": "a" * 64,
        "pod_uid": "38e643c8-20d0-4b5e-8d90-3fa39b05e479",
        "namespace": "onyx-sandboxes",
    }
    target[field] = value
    with (
        patch.object(subject, "_annotations") as annotations,
        patch.object(subject, "_read_profile") as read,
    ):
        assert (
            subject._capture(target, time.monotonic() + 1)
            == "availability=unavailable reason=missing_target"
        )
    annotations.assert_not_called()
    read.assert_not_called()


def test_privileged_cli_emits_fixed_failure_without_arguments_or_tracebacks() -> None:
    result = subprocess.run(
        [sys.executable, "-I", subject.__file__],
        input=_CANARY.encode(),
        capture_output=True,
        check=True,
        timeout=2,
    )
    assert result.stdout in {
        b"availability=unavailable reason=unsupported\n",
        b"availability=unavailable reason=capture_failed\n",
    }
    assert result.stderr == b""


def test_bounded_child_output_closes_and_reaps_without_retaining_canary() -> None:
    processes: list[subprocess.Popen[bytes]] = []
    popen = subprocess.Popen

    def start(command: list[str], **kwargs: object) -> subprocess.Popen[bytes]:
        process = popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        assert kwargs == {
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.DEVNULL,
        }
        processes.append(process)
        return process

    command = [
        sys.executable,
        "-I",
        "-c",
        "import sys;sys.stdout.write('x'*4096);sys.stdout.flush()",
    ]
    with (
        patch.object(guest.subprocess, "Popen", side_effect=start),
        pytest.raises(OverflowError),
    ):
        guest._bounded_command(command, b"", time.monotonic() + 1, 256)
    command = [sys.executable, "-I", "-c", "import time;time.sleep(2)"]
    with (
        patch.object(guest.subprocess, "Popen", side_effect=start),
        pytest.raises(TimeoutError),
    ):
        guest._bounded_command(command, b"", time.monotonic() + 0.04, 256)
    assert len(processes) == 2
    for process in processes:
        assert process.poll() is not None
        assert process.stdin is not None and process.stdin.closed
        assert process.stdout is not None and process.stdout.closed


def test_reader_owns_an_alarm_even_if_parent_stays_alive() -> None:
    source = (
        "import importlib.util,os,signal,time\n"
        f"spec=importlib.util.spec_from_file_location('reader',{subject.__file__!r})\n"
        "reader=importlib.util.module_from_spec(spec);spec.loader.exec_module(reader)\n"
        "reader.sys.platform='linux';reader.os.geteuid=lambda:0;reader._SO_PEERCRED=17\n"
        "reader._read=lambda *args:('NSpid: '+str(os.getpid())+'\\n').encode()\n"
        "reader._capture=lambda *args:time.sleep(2)\n"
        "alarm=signal.alarm;reader.signal.alarm=lambda seconds:alarm(1) if seconds==5 else None\n"
        "reader._main()\n"
    )
    result = subprocess.run(
        [sys.executable, "-I", "-c", source],
        input=b"{}",
        capture_output=True,
        timeout=3,
    )
    assert result.returncode == -signal.SIGALRM
    assert result.stdout == result.stderr == b""


def test_oci_annotations_bind_uid_namespace_and_type(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    data = {
        "annotations": {
            "io.kubernetes.cri.container-type": "container",
            "io.kubernetes.cri.sandbox-uid": "owned",
            "io.kubernetes.cri.sandbox-namespace": "sandbox",
        }
    }
    path.write_text(json.dumps(data))
    assert (
        subject._annotations(path, "owned", "sandbox", "container")
        == data["annotations"]
    )
    for expected in [
        ("other", "sandbox", "container"),
        ("owned", "other", "container"),
        ("owned", "sandbox", "sandbox"),
    ]:
        with pytest.raises(ValueError):
            subject._annotations(path, *expected)


@pytest.mark.parametrize(
    "mutation",
    ["none", "namespace", "mapping", "executable", "sandboxarg", "duplicatearg"],
)
def test_peer_identity_uses_kernel_proc_paths_and_exact_sandbox(mutation: str) -> None:
    sandbox = "b" * 64
    namespace = os.stat_result((stat.S_IFREG, 7, 2, 1, 0, 0, 0, 0, 0, 0))
    wrong_namespace = os.stat_result((stat.S_IFREG, 8, 2, 1, 0, 0, 0, 0, 0, 0))
    arguments = [b"shim", b"-namespace", b"k8s.io", b"-id", sandbox.encode()]
    if mutation == "sandboxarg":
        arguments[-1] = b"other"
    if mutation == "duplicatearg":
        arguments.extend([b"-id", b"other"])

    def read(path: Path, _maximum: int = 65536) -> bytes:
        if path.name == "status":
            return b"NSpid:\t99\t" + (b"19" if mutation == "mapping" else b"18") + b"\n"
        if path.name == "cmdline":
            return b"\0".join(arguments) + b"\0"
        if path.name == "stat":
            return b"99 (shim) " + b" ".join([b"S", *([b"0"] * 18), b"555"])
        raise AssertionError(path)

    def process_stat(path: Path) -> os.stat_result:
        if mutation == "namespace" and str(path) == "/proc/99/ns/pid":
            return wrong_namespace
        return namespace

    with (
        patch.object(subject, "_read", side_effect=read),
        patch.object(Path, "stat", autospec=True, side_effect=process_stat),
        patch.object(
            subject.os,
            "readlink",
            return_value="/wrong/executable"
            if mutation == "executable"
            else "/opt/kata/bin/containerd-shim-kata-v2",
        ),
        patch.object(
            Path,
            "resolve",
            side_effect=AssertionError("Must use kernel proc magic links"),
        ),
    ):
        if mutation == "none":
            assert subject._process_identity(99, 22, 18, sandbox) == (555, 7, 2, 7)
        else:
            with pytest.raises(ValueError):
                subject._process_identity(99, 22, 18, sandbox)


@pytest.mark.parametrize(
    "race",
    [
        "none",
        "peer",
        "socket_before",
        "socket_after",
        "start_time",
        "pid_file",
        "oci",
        "node_start",
    ],
)
def test_capture_refuses_wrong_peer_and_discards_raced_identity(race: str) -> None:
    target: dict[str, object] = {
        "node_pid": 22,
        "container_id": "a" * 64,
        "pod_uid": "38e643c8-20d0-4b5e-8d90-3fa39b05e479",
        "namespace": "onyx-sandboxes",
    }
    monitor = os.stat_result((stat.S_IFSOCK | 0o600, 7, 2, 1, 0, 0, 0, 0, 0, 0))
    replaced = os.stat_result((stat.S_IFSOCK | 0o600, 8, 2, 1, 0, 0, 0, 0, 0, 0))
    monitor_checks = 0
    annotations = {"io.kubernetes.cri.sandbox-id": "b" * 64}
    annotation_checks = 0

    def checked_annotations(
        _path: Path, _uid: str, _namespace: str, _kind: str
    ) -> dict[str, str]:
        nonlocal annotation_checks
        annotation_checks += 1
        if race == "oci" and annotation_checks > 2:
            raise ValueError
        return annotations

    def checked_stat(path: Path) -> os.stat_result:
        nonlocal monitor_checks
        if path.name == "shim-monitor.sock":
            monitor_checks += 1
            if (race == "socket_before" and monitor_checks == 2) or (
                race == "socket_after" and monitor_checks == 3
            ):
                return replaced
        return monitor

    identities: list[tuple[int, int, int, int] | Exception] = [
        (555, 7, 2, 7),
        (556 if race == "start_time" else 555, 7, 2, 7),
    ]
    if race == "peer":
        identities[0] = ValueError("private-peer-error")
    with (
        patch.object(subject, "_annotations", side_effect=checked_annotations),
        patch.object(
            subject,
            "_read",
            side_effect=[b"18", b"19" if race == "pid_file" else b"18"],
        ),
        patch.object(
            subject,
            "_start_time",
            side_effect=[101, 102 if race == "node_start" else 101],
        ),
        patch.object(subject, "_process_identity", side_effect=identities),
        patch.object(subject, "_read_profile", return_value=_ZERO) as read,
        patch.object(Path, "stat", autospec=True, side_effect=checked_stat),
        patch.object(
            Path, "resolve", side_effect=AssertionError("No userspace resolution")
        ),
        patch.object(subject.os, "open", return_value=6),
        patch.object(subject.os, "close") as close,
        patch.object(subject.socket, "socket") as factory,
    ):
        peer = factory.return_value.__enter__.return_value
        peer.getsockopt.return_value = struct.pack("3i", 99, 0, 0)
        if race == "peer":
            with pytest.raises(ValueError):
                subject._capture(target, time.monotonic() + 1)
        else:
            assert subject._capture(target, time.monotonic() + 1) == (
                _ZERO
                if race == "none"
                else "availability=unavailable reason=target_changed"
            )
        if race in {"peer", "socket_before"}:
            read.assert_not_called()
        else:
            read.assert_called_once()
        factory.return_value.__exit__.assert_called_once()
        close.assert_called_once_with(6)


def test_parent_uses_exact_node_and_privileged_fixed_reader_then_revalidates() -> None:
    from uuid import UUID

    target = guest._OwnedTarget(
        UUID("3e65cb5e-c1dd-4315-b640-e89c05845218"),
        "38e643c8-20d0-4b5e-8d90-3fa39b05e479",
        guest._CI_NODE,
        "containerd://" + "a" * 64,
        ("kubectl", "--context", "kind-onyx-craft-ci"),
    )
    with (
        patch.object(guest.os.path, "isfile", return_value=True),
        patch.object(guest.os, "uname") as uname,
        patch.object(guest.shutil, "which", return_value="/usr/bin/tool"),
        patch.object(
            guest,
            "_bounded_command",
            side_effect=[(0, b"22 onyx-craft-ci\n"), (0, _ZERO.encode())],
        ) as command,
        patch.object(guest, "_read_owned_pod", return_value=target) as revalidate,
    ):
        uname.return_value.sysname = "Linux"
        assert guest._owned_shim_facts(target) == _ZERO
    assert command.call_count == 2
    assert command.call_args_list[0].args[0] == [
        "docker",
        "inspect",
        "--type",
        "container",
        "--format",
        '{{.State.Pid}} {{index .Config.Labels "io.x-k8s.kind.cluster"}}',
        "onyx-craft-ci-control-plane",
    ]
    assert command.call_args_list[1].args[0] == [
        "sudo",
        "-n",
        "timeout",
        "--signal=KILL",
        "6s",
        "/usr/bin/python3",
        "-I",
        str(Path(guest.__file__).with_name("craft_shim_diagnostics.py")),
    ]
    assert json.loads(command.call_args_list[1].args[1]) == {
        "node_pid": 22,
        "container_id": "a" * 64,
        "pod_uid": target.pod_uid,
        "namespace": guest.SANDBOX_NAMESPACE,
    }
    revalidate.assert_called_once()


@pytest.mark.parametrize(
    "node,container",
    [("other", "containerd://" + "a" * 64), (guest._CI_NODE, "containerd://../other")],
)
def test_parent_rejects_non_owned_node_and_container_before_commands(
    node: str, container: str
) -> None:
    from uuid import UUID

    target = guest._OwnedTarget(
        UUID("3e65cb5e-c1dd-4315-b640-e89c05845218"), "owned", node, container, ()
    )
    with patch.object(guest, "_bounded_command") as command:
        assert (
            guest._owned_shim_facts(target)
            == "availability=unavailable reason=missing_target"
        )
    command.assert_not_called()
